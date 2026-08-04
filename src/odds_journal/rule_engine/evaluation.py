from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
import yaml

from ..calibration import CalibrationConfig
from ..models import (
    AnalysisDimension,
    AnalysisOutlook,
    BaselineGate,
    CandidateDisposition,
    CalibrationEvent,
    MultiMarketScoreMatrix,
    SCORE_MARKETS,
    synthesize_baseline,
)
from .audit import stable_sha256
from .candidates import apply_rankings
from .config import require_contract4
from .features import feature_snapshot
from .profiles import resolve_profile
from .evaluators import evaluate


class BaselineOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asian_line_display: str
    asian_home_line: float
    total_goals_minimum: int = Field(ge=0)
    total_goals_maximum: int = Field(ge=0)
    score_candidates: list[str] = Field(min_length=2, max_length=2)
    fixed_handicap_home_line: int
    fixed_handicap_source_type: str

    @model_validator(mode="after")
    def valid_range(self) -> "BaselineOutput":
        if self.total_goals_minimum > self.total_goals_maximum:
            raise ValueError("总进球范围无效")
        if len(set(self.score_candidates)) != 2:
            raise ValueError("基础比分必须恰好两个且不重复")
        return self


class AnalysisDraftInput(BaseModel):
    """Human/AI supplied baseline evidence. Contract 4 code only aggregates it."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    analysis_input_mode: Literal["market_only", "full_context"]
    baseline_gate: BaselineGate
    score_matrix: MultiMarketScoreMatrix
    baseline_output: BaselineOutput
    fact_refs: list[str] = Field(min_length=1)
    hypothesis_a: str = Field(min_length=1)
    hypothesis_b: str = Field(min_length=1)


class MachineRuleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    triggered: bool
    not_triggered_reason: str | None = None
    applicability: Literal["applicable", "not_applicable"]
    effect: Literal["ranking", "handicap_signal", "total_goals_pool", "score_pool", "outcome_risk_pool", "control"]
    target_market: str
    target_selection: str
    source_snapshot_ids: list[str] = Field(default_factory=list)
    source_provider_ids: list[str] = Field(default_factory=list)
    correlation_keys: list[str] = Field(default_factory=list)
    threshold_observations: dict[str, Any] = Field(default_factory=dict)
    supporting_evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)


class EvaluationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
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
    events: list[MachineRuleEvent]
    bundle_sha256: str


class ReasoningDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    disposition: CandidateDisposition
    hypothesis_a: str = Field(min_length=1)
    hypothesis_b: str = Field(min_length=1)
    supporting_evidence: list[str] = Field(min_length=1)
    counter_evidence: list[str] = Field(min_length=1)
    invalidation_condition: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    total_goals_range: tuple[int, int] | None = None
    score_candidates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_candidates(self) -> "ReasoningDisposition":
        if self.total_goals_range and self.total_goals_range[0] > self.total_goals_range[1]:
            raise ValueError("总进球候选下限不能大于上限")
        if len(self.score_candidates) != len(set(self.score_candidates)):
            raise ValueError("规则比分候选不得重复")
        if any(not __import__("re").fullmatch(r"\d+-\d+", score) for score in self.score_candidates):
            raise ValueError("规则比分候选必须使用 H-A 格式")
        return self


def _source_ids(features: dict[str, Any], rule_id: str) -> list[str]:
    if rule_id in {"total-goals-cross-market-v1", "korea-goal-drop-v1"}:
        return list(features["total_nodes"])
    if "kelly" in rule_id:
        return [*features["euro_nodes"], *features["kelly_nodes"]]
    if rule_id == "hidden-draw-away-cut-v1":
        return [*features["euro_nodes"], *features["kelly_nodes"]]
    if rule_id == "quarter-low-water-inducement-v1":
        return [*features["asian_nodes"], *features["euro_nodes"], *features["kelly_nodes"]]
    if rule_id == "korea-deep-line-loss-tolerance-v1":
        return [*features["asian_nodes"], *features["euro_nodes"], *features["kelly_nodes"]]
    if rule_id == "score-baseline-v1":
        return [*features["asian_nodes"], *features["euro_nodes"]]
    return list(features["asian_nodes"])


def evaluate_draft(
    *,
    match_id: str,
    metadata: Any,
    cutoff: datetime,
    config: CalibrationConfig,
    calibration_config_sha256: str,
    market_snapshot_sha256: str,
    draft: AnalysisDraftInput,
) -> EvaluationBundle:
    require_contract4(config)
    profile, chain, applicable = resolve_profile(config, metadata.competition_code)
    features = feature_snapshot(metadata, cutoff)
    baseline = synthesize_baseline(draft.score_matrix)
    events: list[MachineRuleEvent] = []
    for rule in config.rules:
        target_market = rule.target_market or "handicap"
        target_selection = rule.target_selection or "pass"
        if rule.rule_id not in applicable:
            events.append(MachineRuleEvent(
                rule_id=rule.rule_id, triggered=False, not_triggered_reason="not_applicable",
                applicability="not_applicable", effect=rule.effect, target_market=target_market,
                target_selection=target_selection,
            ))
            continue
        triggered, reason, observations = evaluate(rule.rule_id, features, rule.thresholds)
        ids = _source_ids(features, rule.rule_id)
        events.append(MachineRuleEvent(
            rule_id=rule.rule_id,
            triggered=triggered,
            not_triggered_reason=None if triggered else reason,
            applicability="applicable",
            effect=rule.effect,
            target_market=target_market,
            target_selection=target_selection,
            source_snapshot_ids=ids if triggered else [],
            source_provider_ids=["macau"] if triggered and ids else [],
            correlation_keys=["macau:odds-kelly"] if rule.rule_id in {"draw-kelly-parity-v1", "hidden-draw-away-cut-v1"} and triggered else [],
            threshold_observations=observations,
            supporting_evidence=[f"feature:{name}" for name in rule.feature_ids] if triggered else [],
            counter_evidence=["需要 AI 处置并保留反证"] if triggered else [],
        ))
    draft_hash = stable_sha256(draft.model_dump(mode="json"))
    feature_hash = stable_sha256(features)
    raw = {
        "match_id": match_id, "cutoff_at": cutoff.isoformat(), "ruleset_version": "1.5.0",
        "calibration_config_sha256": calibration_config_sha256, "draft_input_sha256": draft_hash,
        "market_snapshot_sha256": market_snapshot_sha256, "feature_snapshot_sha256": feature_hash,
        "profile_chain": chain, "competition_profile": profile,
        "baseline_summary": baseline.model_dump(mode="json"), "features": features,
        "events": [event.model_dump(mode="json") for event in events],
    }
    return EvaluationBundle.model_validate({**raw, "bundle_sha256": stable_sha256(raw)})


def build_outlook(
    draft: AnalysisDraftInput,
    bundle: EvaluationBundle,
    dispositions: list[ReasoningDisposition],
) -> AnalysisOutlook:
    disposition_by_id = {item.rule_id: item for item in dispositions}
    if len(disposition_by_id) != len(dispositions):
        raise ValueError("同一规则不得有重复处置")
    triggered_ids = {event.rule_id for event in bundle.events if event.triggered}
    unknown_ids = set(disposition_by_id) - triggered_ids
    if unknown_ids:
        raise ValueError("只能处置已触发规则：" + ", ".join(sorted(unknown_ids)))
    baseline = bundle.baseline_summary["markets"]
    baseline_rankings = {market: value["ranking"] for market, value in baseline.items()}
    events: list[CalibrationEvent] = []
    ranking_events: list[dict[str, Any]] = []
    for event in bundle.events:
        decision = disposition_by_id.get(event.rule_id)
        if event.triggered and decision is None:
            raise ValueError(f"触发规则缺少 AI 处置：{event.rule_id}")
        ranking = list(baseline_rankings.get(event.target_market, []))
        payload: dict[str, Any] = {
            "rule_id": event.rule_id, "contract_version": 4, "triggered": event.triggered,
            "not_triggered_reason": event.not_triggered_reason, "applicability": event.applicability,
            "effect": event.effect, "target_market": event.target_market,
            "target_selection": event.target_selection,
            "source_dimensions": [
                AnalysisDimension.TOTAL_GOALS_MARKET.value if event.target_market == "total_goals"
                else AnalysisDimension.EUROPEAN_ODDS.value if event.target_market == "one_x_two"
                else AnalysisDimension.ASIAN_HANDICAP_MARKET.value
            ] if event.triggered else [], "source_provider_ids": event.source_provider_ids,
            "source_snapshot_ids": event.source_snapshot_ids, "correlation_keys": event.correlation_keys,
            "threshold_observations": event.threshold_observations,
            "before_ranking": ranking, "proposed_ranking": ranking, "final_ranking": ranking,
            "adjustment_level": 0, "supporting_evidence": event.supporting_evidence,
            "counter_evidence": event.counter_evidence,
        }
        if event.triggered:
            payload["decision"] = decision.disposition.model_dump(mode="json")
            if event.effect == "ranking":
                payload["adjustment_level"] = 1
                proposed = list(ranking)
                if event.target_selection in proposed and proposed.index(event.target_selection) > 0:
                    index = proposed.index(event.target_selection)
                    proposed[index - 1], proposed[index] = proposed[index], proposed[index - 1]
                payload["proposed_ranking"] = proposed
                ranking_events.append({**event.model_dump(mode="json"), "disposition": decision.disposition.disposition})
        events.append(CalibrationEvent.model_validate(payload))
    experimental = apply_rankings(baseline_rankings, [item.model_dump(mode="json") | {"disposition": "adopted"} for item in events], adopted_only=False)
    final = apply_rankings(baseline_rankings, ranking_events, adopted_only=True)
    output = draft.baseline_output
    baseline_total_decision: dict[str, Any] = {"disposition": "adopted"}
    baseline_score_decision: dict[str, Any] = {"disposition": "adopted"}
    total_candidates: list[dict[str, Any]] = []
    score_candidates: list[dict[str, Any]] = []
    outcome_risks: list[dict[str, Any]] = []

    def excluded_baseline(rule_ids: list[str]) -> dict[str, Any]:
        return {
            "disposition": "excluded",
            "exclusion_reason": "已采用实验规则候选",
            "counter_evidence_refs": [f"rule:{rule_id}" for rule_id in rule_ids],
        }

    triggered_total = [event for event in bundle.events if event.triggered and event.effect == "total_goals_pool"]
    total_adopted = [event for event in triggered_total if disposition_by_id[event.rule_id].disposition.disposition == "adopted"]
    if total_adopted:
        baseline_total_decision = excluded_baseline([event.rule_id for event in total_adopted])
    for event in triggered_total:
        decision = disposition_by_id[event.rule_id]
        if decision.total_goals_range is None:
            raise ValueError(f"总进球规则缺少候选区间：{event.rule_id}")
        total_candidates.append({
            "minimum": decision.total_goals_range[0], "maximum": decision.total_goals_range[1],
            "rule_id": event.rule_id, "decision": decision.disposition.model_dump(mode="json"),
        })

    triggered_scores = [event for event in bundle.events if event.triggered and event.effect == "score_pool"]
    korea_risk = next((event for event in bundle.events if event.triggered and event.rule_id == "korea-deep-line-loss-tolerance-v1"), None)
    score_events = [*triggered_scores, *([korea_risk] if korea_risk else [])]
    score_adopted = [event for event in score_events if disposition_by_id[event.rule_id].disposition.disposition == "adopted"]
    if score_adopted:
        baseline_score_decision = excluded_baseline([event.rule_id for event in score_adopted])
    for event in score_events:
        decision = disposition_by_id[event.rule_id]
        if not decision.score_candidates:
            raise ValueError(f"比分规则缺少候选：{event.rule_id}")
        if event.rule_id == "korea-deep-line-loss-tolerance-v1" and "0-1" not in decision.score_candidates:
            raise ValueError("韩国深盘输球风险必须登记 0-1 比分候选")
        score_candidates.extend({
            "score": score, "rule_id": event.rule_id,
            "decision": decision.disposition.model_dump(mode="json"),
        } for score in decision.score_candidates)

    for event in bundle.events:
        if not event.triggered or event.effect != "outcome_risk_pool":
            continue
        decision = disposition_by_id[event.rule_id]
        outcome_risks.append({
            "market": event.target_market, "selection": event.target_selection,
            "rule_id": event.rule_id, "decision": decision.disposition.model_dump(mode="json"),
        })

    pools = {
        "total_goals_candidate_pool": [
            {"minimum": output.total_goals_minimum, "maximum": output.total_goals_maximum, "rule_id": "baseline", "decision": baseline_total_decision},
            *total_candidates,
        ],
        "score_candidate_pool": [
            {"score": score, "rule_id": "baseline", "decision": baseline_score_decision}
            for score in output.score_candidates
        ] + score_candidates,
        "outcome_risk_pool": outcome_risks,
    }
    adopted_total = [item for item in pools["total_goals_candidate_pool"] if item["decision"]["disposition"] == "adopted"]
    adopted_scores = [item["score"] for item in pools["score_candidate_pool"] if item["decision"]["disposition"] == "adopted"]
    if len(adopted_total) != 1:
        raise ValueError("最终总进球必须有且仅有一个已采纳候选")
    if len(adopted_scores) != 2 or len(set(adopted_scores)) != 2:
        raise ValueError("最终比分必须有且仅有两个不同的已采纳候选")
    final_total = adopted_total[0]
    return AnalysisOutlook.model_validate({
        "schema_version": 4,
        "data_mode": "degraded" if draft.baseline_gate.decision == "degraded" else "complete",
        "missing_reasons": list(draft.baseline_gate.reasons) if draft.baseline_gate.decision == "degraded" else [],
        "weight_model": {"model_id": "asian-core-v1"}, "competition_profile": bundle.competition_profile,
        "calibration_contract_version": 4, "analysis_input_mode": draft.analysis_input_mode,
        "profile_chain": bundle.profile_chain, "evaluation_bundle_sha256": bundle.bundle_sha256,
        "baseline_gate": draft.baseline_gate.model_dump(mode="json"), "score_matrix": draft.score_matrix.model_dump(mode="json"),
        "baseline_summary_v3": bundle.baseline_summary, "experimental_rankings": experimental, "final_rankings": final,
        "one_x_two": {"choices": final["one_x_two"][:2]},
        "asian_handicap": {"line_display": output.asian_line_display, "home_line": output.asian_home_line, "ranking": {"choices": final["asian_handicap"]}},
        "fixed_handicap_1x2": {"home_line": output.fixed_handicap_home_line, "source_type": output.fixed_handicap_source_type, "ranking": {"choices": final["fixed_handicap_1x2"][:2]}},
        "total_goals": {"minimum": final_total["minimum"], "maximum": final_total["maximum"]},
        "score_candidates": adopted_scores, "calibration_events": [item.model_dump(mode="json") for item in events],
        **pools,
    })


def validate_outlook_bundle(
    *,
    root: Any,
    metadata: Any,
    receipt: Any,
    config: CalibrationConfig,
    outlook: AnalysisOutlook,
) -> list[str]:
    """Recompute the content-addressed bundle referenced by an Outlook V4."""
    errors: list[str] = []
    base = root / "raw" / "matches" / metadata.match_id
    draft_path = base / "analysis-draft-input.yml"
    bundle_path = base / f"rule-evaluation-{outlook.evaluation_bundle_sha256}.yml"
    if not draft_path.is_file():
        return ["Contract 4 缺少 analysis-draft-input.yml"]
    if not bundle_path.is_file():
        return ["Contract 4 缺少 Outlook 引用的评估 bundle"]
    try:
        draft = AnalysisDraftInput.model_validate(yaml.safe_load(draft_path.read_text(encoding="utf-8")) or {})
        actual = EvaluationBundle.model_validate(yaml.safe_load(bundle_path.read_text(encoding="utf-8")) or {})
        expected = evaluate_draft(
            match_id=metadata.match_id,
            metadata=metadata,
            cutoff=receipt.as_of,
            config=config,
            calibration_config_sha256=receipt.calibration_config_sha256,
            market_snapshot_sha256=receipt.market_snapshots_sha256,
            draft=draft,
        )
        if actual.model_dump(mode="json") != expected.model_dump(mode="json"):
            errors.append("Contract 4 评估 bundle 与当前快照、配置或 Draft Input 不一致")
        if outlook.evaluation_bundle_sha256 != expected.bundle_sha256:
            errors.append("AnalysisOutlook 未绑定当前评估 bundle")
    except Exception as exc:
        errors.append(str(exc))
    return errors
