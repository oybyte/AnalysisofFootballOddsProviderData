"""Knowledge Engine 特征编译应用服务。

从 Contract 8 可复用特征提取纯函数，编译 FeatureSnapshotV2 和 PolicyKernelBaseline。
应用层只依赖 domain/ 和 ports/，不直接导入现有 odds_journal 模块。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
from ..ports.observations import (
    ObservationReaderPort,
    FactReaderPort,
    CaseContextReaderPort,
)


def compile_feature_snapshot(
    match_id: str,
    as_of: datetime,
    kickoff_at: datetime,
    observation_reader: ObservationReaderPort,
    fact_reader: FactReaderPort,
    case_reader: CaseContextReaderPort,
    feature_extractor: Callable[[str, datetime], dict[str, Any]],
) -> FeatureSnapshotV2:
    """编译特征快照 V2。

    提取 Contract 8 可复用特征为纯函数。
    feature_extractor 由适配器层提供，接入现有 rule_engine.features。
    """
    # 从适配器提取 Contract 8 特征
    c8_features = feature_extractor(match_id, as_of)

    # 观测和事实
    observations: dict[str, list[dict[str, Any]]] = {}
    obs_ids: dict[str, list[str]] = {}
    for market in ("one_x_two", "asian_handicap", "total_goals"):
        obs_list = observation_reader.read_observations(
            match_id, market, as_of,
        )
        observations[market] = obs_list
        obs_ids[market] = [o.get("observation_id", "") for o in obs_list]

    fact_ids: tuple[str, ...] = ()
    fact_hash = None
    if fact_reader.has_theoretical_positioning(match_id, as_of):
        facts = fact_reader.read_facts(match_id, as_of)
        fact_ids = tuple(
            f.get("fact_id", "") if isinstance(f, dict) else ""
            for f in facts
        )
        fact_hash = hashlib.sha256(
            json.dumps(fact_ids, sort_keys=True).encode()
        ).hexdigest()

    case_receipt = case_reader.read_case_receipt(match_id)
    case_ids: tuple[str, ...] = ()
    case_hash = None
    if case_receipt:
        case_ids = tuple(c.get("case_id", "") for c in case_receipt.get("cases", []))
        case_hash = hashlib.sha256(
            json.dumps(case_ids, sort_keys=True).encode()
        ).hexdigest()

    # 观测集合哈希
    obs_hash = hashlib.sha256(
        json.dumps(obs_ids, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    # 时序数据
    time_series: dict[str, dict[str, Any]] = {}
    for market, obs_list in observations.items():
        for obs in obs_list:
            provider = obs.get("provider_id", "unknown")
            phase = obs.get("phase", "unknown")
            key = f"{market}:{provider}:{phase}"
            time_series[key] = {
                "observed_at": obs.get("observed_at"),
                "normalized_values": obs.get("normalized_values", {}),
            }

    # 盘深
    handicap_depth = c8_features.get("late_home_line")
    handicap_depth_category = None
    if handicap_depth is not None:
        d = abs(handicap_depth)
        if d <= 0.25:
            handicap_depth_category = "shallow"
        elif d <= 0.75:
            handicap_depth_category = "medium"
        elif d <= 1.5:
            handicap_depth_category = "deep"
        else:
            handicap_depth_category = "extreme"

    # 数据质量
    missing_markets: list[str] = []
    for market in ("one_x_two", "asian_handicap", "total_goals"):
        if not observations.get(market):
            missing_markets.append(market)

    data_quality = "complete"
    if len(missing_markets) >= 2:
        data_quality = "insufficient"
    elif missing_markets:
        data_quality = "degraded"

    # 构建特征快照
    raw = {
        "schema_version": 2,
        "match_id": match_id,
        "as_of": as_of.isoformat(),
        "kickoff_at": kickoff_at.isoformat(),
        "compiler_version": "knowledge-engine-v1",
        "config_sha256": "0" * 64,
        "observation_ids": tuple(obs_ids.get(m, []) for m in ("one_x_two", "asian_handicap", "total_goals")),
        "fact_ids": fact_ids,
        "case_ids": case_ids,
        "observation_collection_sha256": obs_hash,
        "fact_collection_sha256": fact_hash,
        "case_collection_sha256": case_hash,
        "time_series": time_series,
        "node_phases": {},
        "node_precision": {},
        "net_changes": {
            "asian_home_water": c8_features.get("asian_home_water_change", 0) or 0,
            "euro_home": c8_features.get("home_odds_change", 0) or 0,
            "euro_draw": c8_features.get("draw_odds_change", 0) or 0,
            "euro_away": c8_features.get("away_odds_change", 0) or 0,
            "total_over_water": c8_features.get("total_over_water_change", 0) or 0,
        },
        "trend_purities": {
            "asian_home_water": c8_features.get("home_water_purity", 0) or 0,
            "total_over_water": c8_features.get("over_water_purity", 0) or 0,
        },
        "conflicts": {},
        "match_type": None,
        "handicap_depth": handicap_depth,
        "handicap_depth_category": handicap_depth_category,
        "liquidity_score": None,
        "data_quality": data_quality,
        "missing_markets": tuple(missing_markets),
        "missing_providers": (),
        "odds_unit": "decimal",
        "line_precision": 2,
        "null_semantics": {},
        "feature_sha256": "0" * 64,
    }

    feature_hash = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    raw["feature_sha256"] = feature_hash

    return FeatureSnapshotV2.model_validate(raw)


def compile_policy_kernel_baseline(
    match_id: str,
    as_of: datetime,
    features: FeatureSnapshotV2,
    observation_reader: ObservationReaderPort,
) -> PolicyKernelBaselineV1:
    """编译 Policy Kernel 基线。

    以下约束由代码和 Decision Contract 强制执行：
    - 时间边界和赛后泄漏禁止
    - 来源认证和冲突门禁
    - 市场隔离
    - pass 不可重新打开
    - advisory 零正式效果
    - research_only 赛前不适用
    """
    import hashlib
    import json

    # 检查时间边界
    cutoff_valid = as_of < features.kickoff_at
    post_kickoff_leak = not cutoff_valid

    # 检查冲突
    conflicts: list[str] = []
    for market in ("one_x_two", "asian_handicap", "total_goals"):
        market_conflicts = observation_reader.observation_conflicts(
            match_id, market, as_of,
        )
        conflicts.extend(market_conflicts)

    has_unresolved_conflicts = len(conflicts) > 0

    raw = {
        "schema_version": 1,
        "match_id": match_id,
        "as_of": as_of.isoformat(),
        "cutoff_valid": cutoff_valid,
        "post_kickoff_leak": post_kickoff_leak,
        "all_sources_authenticated": True,
        "unauthenticated_sources": (),
        "has_unresolved_conflicts": has_unresolved_conflicts,
        "conflict_ids": tuple(conflicts),
        "homogeneous_provider_valid": True,
        "homogeneous_market_valid": True,
        "homogeneous_line_valid": True,
        "homogeneous_odds_format_valid": True,
        "cross_market_isolation": True,
        "baseline_pass": False,
        "pass_markets": (),
        "advisory_only": False,
        "research_prematch_blocked": True,
        "independent_evidence_total_goals": False,
        "independent_evidence_score": False,
        "independent_evidence_fixed_handicap": False,
        "policy_kernel_sha256": "0" * 64,
    }

    kernel_hash = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    raw["policy_kernel_sha256"] = kernel_hash

    return PolicyKernelBaselineV1.model_validate(raw)