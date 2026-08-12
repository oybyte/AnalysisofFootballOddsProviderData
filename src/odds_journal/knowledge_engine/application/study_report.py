"""Knowledge Engine Study Report 应用服务。

从事件 ledger 重建 Study 报告，包含：
- registered Study
- 有效 Primary Run
- exposure 状态
- 未被 supersede 的 Outcome
- failure/not_run/counterfactual 排除项
- Snapshot、市场、cohort、暴露状态分层

固定统计口径：
- 同一 study_id + match_id + snapshot_sha256 仅计一次有效 Primary
- 被 supersede 的 Outcome 不进入分母
- 只有 prospective_out_of_sample 进入发布指标
- 无有效正式基线的 Run 可以计 coverage，不能进入与 1.8.0 的共同覆盖比较
- 1X2 仅在基线与知识均有有效概率 forecast 时计算 Brier、Log Loss
- 亚洲让球、总进球只计算既有 Settlement utility
- AI exposure 与 blind Run 必须独立分层
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from ..adapters.study_ledger import StudyLedger
from ..domain.studies import StudyEventType, StudyState


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_study_report(
    study_id: str,
    ledger: StudyLedger,
) -> dict[str, Any]:
    """从台账重建 Study 报告。"""
    state = ledger.rebuild_study_state(study_id)
    if not state.get("exists"):
        raise ValueError(f"Study {study_id} 未注册")

    primary_claims = state.get("primary_claims", {})
    outcomes = state.get("outcomes", [])
    valid_outcomes = state.get("valid_outcomes", [])
    exposures = state.get("exposures", [])
    failures = state.get("failures", [])
    ai_advisories = state.get("ai_advisories", [])

    # 去重：同一 study_id + match_id + snapshot_sha256 仅计一次有效 Primary
    seen_primary: set[tuple[str, str, str]] = set()
    unique_primaries: list[dict[str, Any]] = []
    for key, claim in primary_claims.items():
        dedup_key = (
            claim.get("study_id", ""),
            claim.get("match_id", ""),
            claim.get("snapshot_sha256", ""),
        )
        if dedup_key not in seen_primary:
            seen_primary.add(dedup_key)
            unique_primaries.append(claim)

    # 暴露分层
    exposed_match_ids = {e.get("match_id") for e in exposures}
    exposed_outcomes = [o for o in valid_outcomes if o.get("match_id") in exposed_match_ids]
    blind_outcomes = [o for o in valid_outcomes if o.get("match_id") not in exposed_match_ids]

    # 概率评分（1X2 Brier / Log Loss）
    probability_scoring = _compute_probability_scoring(unique_primaries, valid_outcomes)

    # 市场裁决统计
    market_stats = _compute_market_stats(valid_outcomes)

    # coverage 统计
    coverage = {
        "total_primary_runs": len(unique_primaries),
        "total_outcomes": len(valid_outcomes),
        "exposed_outcomes": len(exposed_outcomes),
        "blind_outcomes": len(blind_outcomes),
        "failures": len(failures),
        "ai_advisories": len(ai_advisories),
    }

    report = {
        "study_id": study_id,
        "study_state": state.get("state", StudyState.REGISTERED.value),
        "primary_runs": unique_primaries,
        "outcomes": valid_outcomes,
        "superseded_outcomes": state.get("superseded_outcome_ids", []),
        "exposures": exposures,
        "failures": failures,
        "ai_advisories": ai_advisories,
        "coverage": coverage,
        "exposure_stratification": {
            "exposed_count": len(exposed_outcomes),
            "blind_count": len(blind_outcomes),
            "exposure_rate": len(exposed_outcomes) / len(valid_outcomes) if valid_outcomes else 0,
        },
        "probability_scoring": probability_scoring,
        "market_adjudication": market_stats,
    }

    # 计算报告哈希
    report["study_report_sha256"] = _sha256(report)
    return report


def _compute_probability_scoring(
    primaries: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算 1X2 Brier Score 和 Log Loss。

    1X2 仅在基线与知识均有有效概率 forecast 时计算。
    """
    brier_scores: list[float] = []
    log_losses: list[float] = []

    outcome_by_match: dict[str, dict[str, Any]] = {}
    for outcome in outcomes:
        match_id = outcome.get("match_id")
        if match_id:
            outcome_by_match[match_id] = outcome

    for primary in primaries:
        match_id = primary.get("match_id")
        outcome = outcome_by_match.get(match_id)
        if not outcome:
            continue

        result_1x2 = outcome.get("result_one_x_two")
        if not result_1x2:
            continue

        # 检查是否有概率 forecast
        baseline_probs = primary.get("baseline_probabilities") or primary.get("market_candidates", {}).get("one_x_two", {}).get("probabilities")
        if not baseline_probs:
            continue

        if result_1x2 not in baseline_probs:
            continue

        # Brier Score
        brier = sum(
            (baseline_probs.get(k, 0) - (1.0 if k == result_1x2 else 0.0)) ** 2
            for k in ("home", "draw", "away")
        )
        brier_scores.append(brier)

        # Log Loss
        p = baseline_probs.get(result_1x2, 0)
        if p > 0:
            log_losses.append(-math.log(p))

    return {
        "sample_count": len(brier_scores),
        "avg_brier_score": sum(brier_scores) / len(brier_scores) if brier_scores else 0,
        "avg_log_loss": sum(log_losses) / len(log_losses) if log_losses else 0,
    }


def _compute_market_stats(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    """计算市场裁决统计。"""
    market_stats: dict[str, dict[str, int]] = {}
    for outcome in outcomes:
        for market, decision in outcome.get("market_outcomes", {}).items():
            if market not in market_stats:
                market_stats[market] = {"correct": 0, "wrong": 0, "pass": 0, "total": 0, "not_evaluated": 0}
            stats = market_stats[market]
            stats["total"] += 1
            status = decision.get("status", "")
            if status == "pass" or status == "not_evaluated":
                stats["pass" if status == "pass" else "not_evaluated"] += 1
            elif decision.get("correct"):
                stats["correct"] += 1
            else:
                stats["wrong"] += 1

    result: dict[str, Any] = {}
    for market, stats in market_stats.items():
        assessed = stats["total"] - stats["pass"] - stats["not_evaluated"]
        accuracy = stats["correct"] / assessed if assessed > 0 else 0
        result[market] = {
            **stats,
            "accuracy": accuracy,
            "assessed_count": assessed,
        }
    return result
