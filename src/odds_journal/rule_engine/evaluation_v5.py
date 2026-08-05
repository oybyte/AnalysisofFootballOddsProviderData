"""Contract 7 evaluation.

Contract 4 deliberately accepted analyst-entered baseline total-goals scores.
Contract 7 keeps that behavior for legacy receipts only and requires a
content-addressable observation-led signal for every new total-goals direction.
"""

from __future__ import annotations

from datetime import datetime
from itertools import groupby
from typing import Any, Literal

import yaml

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..calibration import CalibrationConfig
from ..models import (
    AnalysisOutlook,
    BaselineGate,
    MarketDecisionStatus,
    MultiMarketScoreMatrix,
    TotalGoalsSignalV5,
)
from ..observations import prediction_eligible_market_observations
from .audit import stable_sha256
from .evaluation import (
    AnalysisDraftInput,
    BaselineOutput,
    EvaluationBundle,
    ReasoningDisposition,
    build_outlook,
    evaluate_draft,
)


class TotalGoalsInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["assessed", "pass"]
    pass_reasons: list[str] = Field(default_factory=list)
    side: Literal["over", "under"] | None = None

    @model_validator(mode="after")
    def valid_status(self) -> "TotalGoalsInputV2":
        if self.status == "pass":
            if not self.pass_reasons or self.side is not None:
                raise ValueError("总进球 pass 必须记录原因且不得声明方向")
        elif self.pass_reasons or self.side is None:
            raise ValueError("总进球 assessed 必须声明方向且不得填写 pass 原因")
        return self


class BaselineOutputV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asian_line_display: str
    asian_home_line: float
    fixed_handicap_home_line: int
    fixed_handicap_source_type: str


class AnalysisDraftInputV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    analysis_input_mode: Literal["market_only", "full_context"]
    baseline_gate: BaselineGate
    score_matrix: MultiMarketScoreMatrix
    baseline_output: BaselineOutputV2
    total_goals: TotalGoalsInputV2
    fact_refs: list[str] = Field(min_length=1)
    hypothesis_a: str = Field(min_length=1)
    hypothesis_b: str = Field(min_length=1)

    @model_validator(mode="after")
    def no_manual_total_goals_scoring(self) -> "AnalysisDraftInputV2":
        # Reuse Contract 4's strict matrix model, but do not allow a human to
        # inject an over/under baseline score in the new contract.
        legacy = self.legacy_input()
        for row in legacy.score_matrix.rows:
            cell = row.market_scores["total_goals"]
            if cell.status == "assessed" and any(float(value) != 0 for value in cell.scores.values()):
                raise ValueError("Contract 7 禁止人工总进球方向评分；只能引用结构化时序")
        return self

    def legacy_input(self) -> AnalysisDraftInput:
        return AnalysisDraftInput.model_validate({
            "schema_version": 1,
            "analysis_input_mode": self.analysis_input_mode,
            "baseline_gate": self.baseline_gate,
            "score_matrix": self.score_matrix,
            "baseline_output": BaselineOutput(
                asian_line_display=self.baseline_output.asian_line_display,
                asian_home_line=self.baseline_output.asian_home_line,
                total_goals_minimum=0,
                total_goals_maximum=0,
                score_candidates=["0-0", "0-1"],
                fixed_handicap_home_line=self.baseline_output.fixed_handicap_home_line,
                fixed_handicap_source_type=self.baseline_output.fixed_handicap_source_type,
            ).model_dump(mode="json"),
            "fact_refs": self.fact_refs,
            "hypothesis_a": self.hypothesis_a,
            "hypothesis_b": self.hypothesis_b,
        })


class TotalGoalsSeriesV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    line: float
    odds_format: str
    observation_ids: list[str]
    over_change: float | None
    under_change: float | None
    over_purity: float | None
    under_purity: float | None
    qualified_side: Literal["over", "under"] | None = None


class EvaluationBundleV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    match_id: str
    cutoff_at: datetime
    ruleset_version: str
    calibration_config_sha256: str
    draft_input_sha256: str
    market_snapshot_sha256: str
    feature_snapshot_sha256: str
    profile_chain: list[str]
    competition_profile: str
    baseline_summary: dict[str, Any]
    features: dict[str, Any]
    events: list[Any]
    total_goals_series: list[TotalGoalsSeriesV2]
    total_goals_status: Literal["assessed", "pass"]
    total_goals_pass_reasons: list[str]
    total_goals_signal: TotalGoalsSignalV5 | None
    bundle_sha256: str


def _purity(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    changes = [right - left for left, right in zip(values, values[1:])]
    nonzero = [change for change in changes if change]
    if not nonzero:
        return 1.0
    direction = 1 if sum(nonzero) >= 0 else -1
    return round(sum(change * direction > 0 for change in nonzero) / len(nonzero), 6)


def _total_series(root: Any, match_id: str, cutoff: datetime, config: CalibrationConfig) -> list[TotalGoalsSeriesV2]:
    groups: dict[tuple[str, float, str], list[dict[str, Any]]] = {}
    for item in prediction_eligible_market_observations(root, match_id=match_id, market="total_goals", cutoff=cutoff):
        if item.get("market_scope") != "full_time" or item.get("quote_role") != "main_line":
            continue
        line = item.get("normalized_line")
        if line is None:
            continue
        groups.setdefault((item["provider_id"], float(line), item["odds_format"]), []).append(item)
    policy = config.total_goals_evidence_policy
    assert policy is not None
    result: list[TotalGoalsSeriesV2] = []
    for (provider, line, odds_format), rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda item: (item["observed_at"], item["observation_id"]))
        over = [float(item["normalized_prices"]["over"]) for item in rows]
        under = [float(item["normalized_prices"]["under"]) for item in rows]
        over_change, under_change = round(over[-1] - over[0], 6), round(under[-1] - under[0], 6)
        over_purity, under_purity = _purity(over), _purity(under)
        qualified = None
        if len(rows) >= policy.anchor_min_exact_nodes:
            if over_change <= -policy.target_water_fall_min and over_purity is not None and over_purity >= policy.trend_purity_min:
                qualified = "over"
            if under_change <= -policy.target_water_fall_min and under_purity is not None and under_purity >= policy.trend_purity_min:
                qualified = "under" if qualified is None else None
        result.append(TotalGoalsSeriesV2(
            provider_id=provider, line=line, odds_format=odds_format,
            observation_ids=[item["observation_id"] for item in rows],
            over_change=over_change, under_change=under_change,
            over_purity=over_purity, under_purity=under_purity, qualified_side=qualified,
        ))
    return result


def evaluate_draft_v2(*, root: Any, match_id: str, metadata: Any, cutoff: datetime, config: CalibrationConfig,
                      calibration_config_sha256: str, market_snapshot_sha256: str, draft: AnalysisDraftInputV2,
                      ruleset_version: str) -> EvaluationBundleV2:
    if config.schema_version != 7:
        raise ValueError("Contract 7 只能使用 calibration schema 7")
    legacy = draft.legacy_input()
    base: EvaluationBundle = evaluate_draft(
        match_id=match_id, metadata=metadata, cutoff=cutoff, config=config,
        calibration_config_sha256=calibration_config_sha256,
        market_snapshot_sha256=market_snapshot_sha256, draft=legacy, ruleset_version=ruleset_version,
    )
    series = _total_series(root, match_id, cutoff, config)
    reasons = list(draft.total_goals.pass_reasons)
    signal = None
    status: Literal["assessed", "pass"] = "pass"
    if draft.total_goals.status == "assessed":
        requested = draft.total_goals.side
        qualified = [item for item in series if item.qualified_side == requested]
        opposite = [item for item in series if item.qualified_side and item.qualified_side != requested]
        policy = config.total_goals_evidence_policy
        assert policy is not None
        confirmations: list[list[TotalGoalsSeriesV2]] = []
        for _, same_quote_series in groupby(
            sorted(qualified, key=lambda item: (item.line, item.odds_format, item.provider_id)),
            key=lambda item: (item.line, item.odds_format),
        ):
            comparable = [
                item for item in same_quote_series
                if len(item.observation_ids) >= policy.corroboration_min_exact_nodes
            ]
            if len({item.provider_id for item in comparable}) >= 2:
                confirmations.append(comparable)
        if not confirmations:
            reasons.append("insufficient_independent_exact_series")
        if opposite:
            reasons.append("qualified_opposite_series")
        if not reasons:
            confirmed = sorted(
                confirmations,
                key=lambda items: (-len({item.provider_id for item in items}), items[0].line, items[0].odds_format),
            )[0]
            status = "assessed"
            signal = TotalGoalsSignalV5(
                side=requested, provider_ids=sorted({item.provider_id for item in confirmed}),
                observation_ids=[node for item in confirmed for node in item.observation_ids],
                line=confirmed[0].line,
            )
        else:
            reasons = sorted(set(reasons))
    raw = {
        "match_id": match_id, "cutoff_at": cutoff.isoformat(), "ruleset_version": ruleset_version,
        "calibration_config_sha256": calibration_config_sha256,
        "draft_input_sha256": stable_sha256(draft.model_dump(mode="json")),
        "market_snapshot_sha256": market_snapshot_sha256,
        "feature_snapshot_sha256": base.feature_snapshot_sha256,
        "profile_chain": base.profile_chain, "competition_profile": base.competition_profile,
        "baseline_summary": base.baseline_summary, "features": base.features,
        "events": [event.model_dump(mode="json") for event in base.events],
        "total_goals_series": [item.model_dump(mode="json") for item in series],
        "total_goals_status": status, "total_goals_pass_reasons": reasons,
        "total_goals_signal": signal.model_dump(mode="json") if signal else None,
    }
    return EvaluationBundleV2.model_validate({**raw, "bundle_sha256": stable_sha256(raw)})


def build_outlook_v5(draft: AnalysisDraftInputV2, bundle: EvaluationBundleV2,
                     dispositions: list[ReasoningDisposition]) -> AnalysisOutlook:
    if draft.baseline_gate.decision == "pass":
        reasons = list(draft.baseline_gate.reasons)
        return AnalysisOutlook.model_validate({
            "schema_version": 5,
            "data_mode": "pass",
            "pass_reasons": reasons,
            "competition_profile": bundle.competition_profile,
            "calibration_contract_version": 7,
            "analysis_input_mode": draft.analysis_input_mode,
            "profile_chain": bundle.profile_chain,
            "evaluation_bundle_sha256": bundle.bundle_sha256,
            "baseline_gate": draft.baseline_gate.model_dump(mode="json"),
            "score_matrix": draft.score_matrix.model_dump(mode="json"),
            "baseline_summary_v3": bundle.baseline_summary,
            "market_statuses": {
                "one_x_two": "pass", "asian_handicap": "pass", "fixed_handicap_1x2": "pass",
                "total_goals": "pass", "score": "pass",
            },
            "market_pass_reasons": {
                "one_x_two": reasons, "asian_handicap": reasons, "fixed_handicap_1x2": reasons,
                "total_goals": reasons, "score": reasons,
            },
        })
    # Contract 4 remains the deterministic scorer for the three legacy markets.
    base_bundle = EvaluationBundle.model_validate({
        "schema_version": 1, "match_id": bundle.match_id, "cutoff_at": bundle.cutoff_at,
        "ruleset_version": bundle.ruleset_version,
        "calibration_config_sha256": bundle.calibration_config_sha256,
        "draft_input_sha256": bundle.draft_input_sha256,
        "market_snapshot_sha256": bundle.market_snapshot_sha256,
        "feature_snapshot_sha256": bundle.feature_snapshot_sha256,
        "profile_chain": bundle.profile_chain, "competition_profile": bundle.competition_profile,
        "baseline_summary": bundle.baseline_summary, "features": bundle.features,
        "events": bundle.events, "bundle_sha256": bundle.bundle_sha256,
    })
    legacy = build_outlook(draft.legacy_input(), base_bundle, dispositions)
    raw = legacy.model_dump(mode="json")
    raw.update({
        "schema_version": 5,
        "calibration_contract_version": 7,
        "evaluation_bundle_sha256": bundle.bundle_sha256,
        "market_statuses": {
            "one_x_two": "assessed", "asian_handicap": "assessed", "fixed_handicap_1x2": "assessed",
            "total_goals": bundle.total_goals_status, "score": "pass",
        },
        "market_pass_reasons": {
            "total_goals": bundle.total_goals_pass_reasons,
            "score": ["total_goals_score_separation"],
        },
        "total_goals_signal": bundle.total_goals_signal.model_dump(mode="json") if bundle.total_goals_signal else None,
        "score_candidates": [], "score_candidate_pool": [],
    })
    for event in raw["calibration_events"]:
        event["contract_version"] = 7
    # A market signal is intentionally not turned into a fake integer range.
    raw["total_goals"] = None
    raw["total_goals_candidate_pool"] = []
    return AnalysisOutlook.model_validate(raw)


def validate_outlook_bundle_v2(*, root: Any, metadata: Any, receipt: Any,
                               config: CalibrationConfig, outlook: AnalysisOutlook) -> list[str]:
    base = root / "raw" / "matches" / metadata.match_id
    draft_path = base / "analysis-draft-input.yml"
    bundle_path = base / f"rule-evaluation-{outlook.evaluation_bundle_sha256}.yml"
    if not draft_path.is_file():
        return ["Contract 7 缺少 AnalysisDraftInputV2"]
    if not bundle_path.is_file():
        return ["Contract 7 缺少 Outlook 引用的评估 bundle"]
    try:
        draft = AnalysisDraftInputV2.model_validate(yaml.safe_load(draft_path.read_text(encoding="utf-8")) or {})
        actual = EvaluationBundleV2.model_validate(yaml.safe_load(bundle_path.read_text(encoding="utf-8")) or {})
        expected = evaluate_draft_v2(
            root=root, match_id=metadata.match_id, metadata=metadata, cutoff=receipt.as_of,
            config=config, calibration_config_sha256=receipt.calibration_config_sha256,
            market_snapshot_sha256=receipt.market_snapshots_sha256, draft=draft,
            ruleset_version=receipt.ruleset_version,
        )
        if actual.model_dump(mode="json") != expected.model_dump(mode="json"):
            return ["Contract 7 评估 bundle 与观测台账、配置或 Draft Input 不一致"]
        if outlook.evaluation_bundle_sha256 != expected.bundle_sha256:
            return ["AnalysisOutlook 未绑定当前 Contract 7 评估 bundle"]
    except Exception as exc:
        return [str(exc)]
    return []
