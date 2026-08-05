from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .analysis_context import market_snapshots_sha256, parse_receipt
from .ledger import append_payloads, atomic_write_text, read_ledger, sha256_json
from .markdown import MatchDocument
from .models import AnalysisOutlook, MatchStatus, MarketSnapshot
from .observations import effective_market_snapshots, market_feature_snapshot
from .rules import sha256_file
from .rules_release import validate_ruleset_proposal
from .transaction import RepositoryTransaction


EXPERIMENT_ROOT = Path("knowledge/rule-experiments/football-analysis")
EXPERIMENT_LEDGER = Path("knowledge/evidence/rule-experiment-events.jsonl")
ACTIVE_EXPERIMENT = EXPERIMENT_ROOT / "active.yml"
EXPERIMENT_RULE_IDS = (
    "tg-same-line-water-defense-v1",
    "tg-line-drop-over-price-divergence-v1",
    "tg-late-shock-guard-v1",
    "tg-two-dimension-confirmation-v1",
    "tg-dual-line-bracket-v1",
    "tg-handicap-ceiling-risk-v1",
    "tg-head-provider-divergence-nordic-v1",
    "tg-floor-anchor-upper-tail-v1",
    "tg-draw-compression-hypothesis-v1",
    "tg-one-sided-overrun-risk-v1",
    "tg-away-collapse-prior-v1",
    "tg-extreme-under-context-v1",
)

ADVISORY_RULE_IDS = (
    "advisory-initial-water-guard-v1",
    "advisory-home-favorite-goals-transmission-v1",
    "advisory-away-brand-trap-v1",
    "advisory-total-water-tier-v1",
    "advisory-bracket-boundary-v1",
    "advisory-draw-goals-link-v1",
    "advisory-environment-goals-v1",
    "advisory-deep-line-over-trap-v1",
    "advisory-draw-double-check-v1",
    "advisory-head-provider-line-drop-v1",
)
REQUIRED_THRESHOLDS = {
    "tg-same-line-water-defense-v1": {"water_fall_min"},
    "tg-line-drop-over-price-divergence-v1": {"line_drop_min", "over_micro_fall_max"},
    "tg-late-shock-guard-v1": {"late_window_minutes", "water_move_min"},
    "tg-two-dimension-confirmation-v1": {"independent_dimensions_min"},
    "tg-dual-line-bracket-v1": {"low_line", "high_line", "low_over_water_max"},
    "tg-handicap-ceiling-risk-v1": {"line_drop_min"},
    "tg-head-provider-divergence-nordic-v1": {"ordinary_provider_min"},
    "tg-floor-anchor-upper-tail-v1": {"low_line", "high_line", "low_over_water_max"},
    "tg-draw-compression-hypothesis-v1": {"draw_stability_max"},
    "tg-one-sided-overrun-risk-v1": {"total_line", "over_water_max", "deep_line_min", "high_water_min"},
    "tg-away-collapse-prior-v1": set(),
    "tg-extreme-under-context-v1": {"total_line", "under_water_max"},
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _directory_hash(directory: Path) -> str:
    rows = [
        f"{path.relative_to(directory).as_posix()}|{sha256_file(path)}"
        for path in sorted(directory.glob("**/*"))
        if path.is_file() and path.name not in {"APPROVAL.yml", "EXPERIMENT-ACTIVATION.yml"}
    ]
    return hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


class ExperimentRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    reliability: Literal["experimental"] = "experimental"
    effect: Literal["total_goals_pool", "outcome_risk_pool", "control"]
    determinism: Literal["deterministic", "hybrid"]
    applies_to_profiles: list[str] = Field(min_length=1)
    thresholds: dict[str, float] = Field(default_factory=dict)
    target_selection: Literal["over", "under", "dynamic", "pass"] = "dynamic"
    introduced_in: Literal["1.6.0"] = "1.6.0"
    revision: int = Field(default=1, ge=1)
    supersedes_rule_ids: list[str] = Field(default_factory=list)
    override_mode: Literal["none", "replace", "when_triggered"] = "none"
    override_scope: Literal["total_goals", "none"] = "none"

    @model_validator(mode="after")
    def validate_override(self) -> "ExperimentRuleConfig":
        if self.override_mode == "none" and self.supersedes_rule_ids:
            raise ValueError(f"{self.rule_id} 未启用覆盖模式却声明 supersedes")
        if self.override_mode != "none" and (not self.supersedes_rule_ids or self.override_scope == "none"):
            raise ValueError(f"{self.rule_id} 覆盖配置不完整")
        if self.rule_id in self.supersedes_rule_ids:
            raise ValueError("规则不能覆盖自身")
        missing = REQUIRED_THRESHOLDS.get(self.rule_id, set()) - set(self.thresholds)
        if missing:
            raise ValueError(f"{self.rule_id} 缺少阈值：{', '.join(sorted(missing))}")
        return self


class ExperimentAdvisoryConfig(BaseModel):
    """An experimental warning that is structurally unable to affect a prediction."""

    model_config = ConfigDict(extra="forbid")

    advisory_id: str
    pack_id: Literal[
        "initial-water-guard",
        "away-brand-trap",
        "total-water-boundaries",
        "deep-line-goal-trap",
    ]
    effect: Literal["advisory"] = "advisory"
    official_effect: Literal["none"] = "none"
    severity: Literal["info", "warning"]
    determinism: Literal["deterministic", "hybrid"]
    applies_to_profiles: list[str] = Field(min_length=1)
    required_inputs: list[str] = Field(min_length=1)
    thresholds: dict[str, float] = Field(default_factory=dict)
    evidence_provenance: Literal["gap"] = "gap"
    source_intake_path: str = Field(min_length=1)
    introduced_in: Literal["1.6.0"] = "1.6.0"
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_advisory(self) -> "ExperimentAdvisoryConfig":
        if self.advisory_id not in ADVISORY_RULE_IDS:
            raise ValueError(f"未知提示规则：{self.advisory_id}")
        return self


class ExperimentCalibrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[5] = 5
    profile_id: Literal["football-analysis-v5"] = "football-analysis-v5"
    source_intake_paths: list[str] = Field(min_length=1)
    recognized_providers: list[str] = Field(min_length=1)
    head_providers: dict[str, list[str]]
    competition_profiles: dict[str, list[str]]
    profile_chains: dict[str, list[str]]
    rules: list[ExperimentRuleConfig]
    advisories: list[ExperimentAdvisoryConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_contract(self) -> "ExperimentCalibrationConfig":
        ids = [item.rule_id for item in self.rules]
        if len(ids) != len(set(ids)) or set(ids) != set(EXPERIMENT_RULE_IDS):
            raise ValueError("Contract 5 必须且只能定义12条总进球实验规则")
        advisory_ids = [item.advisory_id for item in self.advisories]
        if len(advisory_ids) != len(set(advisory_ids)):
            raise ValueError("实验提示规则 ID 不可重复")
        for profile, chain in self.profile_chains.items():
            if not chain or chain[0] != "global" or chain[-1] != profile or len(chain) != len(set(chain)):
                raise ValueError(f"profile 链无效：{profile}")
        graph = {item.rule_id: [target for target in item.supersedes_rule_ids if target in ids] for item in self.rules}
        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(node: str) -> None:
            if node in visiting:
                raise ValueError("实验规则覆盖关系存在循环")
            if node in visited:
                return
            visiting.add(node)
            for target in graph[node]:
                walk(target)
            visiting.remove(node)
            visited.add(node)

        for identity in ids:
            walk(identity)
        return self

    def profile_chain_for(self, competition_code: str) -> list[str]:
        matched = [name for name, codes in self.competition_profiles.items() if competition_code in codes]
        if not matched:
            return ["global"]
        if competition_code == "competition-u-388f03e8f4":
            return ["global", "low-goal", "nordic-low-heat"]
        profile = matched[-1]
        return list(self.profile_chains.get(profile, ["global", profile]))

    def applicable_rules(self, competition_code: str) -> list[ExperimentRuleConfig]:
        chain = set(self.profile_chain_for(competition_code))
        return [item for item in self.rules if chain & set(item.applies_to_profiles)]

    def applicable_advisories(self, competition_code: str) -> list[ExperimentAdvisoryConfig]:
        chain = set(self.profile_chain_for(competition_code))
        return [item for item in self.advisories if chain & set(item.applies_to_profiles)]


class ActiveExperiment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["active", "inactive"]
    ruleset_id: Literal["football-analysis"] = "football-analysis"
    ruleset_version: str
    experiment_revision: int = Field(ge=1)
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str
    calibration_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    precedence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_mapping_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    approved_by: str
    activated_at: datetime
    deactivation_reason: str | None = None


class ExperimentAnalysisReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2, 3] = 1
    receipt_id: str
    match_id: str
    prepared_at: datetime
    as_of: datetime
    kickoff_at: datetime
    official_ruleset_version: str
    official_analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_snapshots_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_ruleset_version: str
    experiment_revision: int
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str
    calibration_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    precedence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_chain: list[str]
    applicable_rule_ids: list[str]
    applicable_advisory_ids: list[str] = Field(default_factory=list)
    observation_set_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    market_feature_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def observation_freeze_contract(self) -> "ExperimentAnalysisReceipt":
        if self.schema_version == 2 and not (
            self.observation_set_sha256 and self.market_feature_snapshot_sha256
        ):
            raise ValueError("实验回执 V2 必须冻结观测集合和趋势特征哈希")
        return self


class ExperimentRuleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    status: Literal["triggered", "not_triggered", "not_applicable", "suppressed", "insufficient_data"]
    original_status: str | None = None
    suppressed_by_rule_id: str | None = None
    suppressed_external_rule_ids: list[str] = Field(default_factory=list)
    suppression_reason: str | None = None
    effect: Literal["total_goals_pool", "outcome_risk_pool", "control"]
    target_selection: Literal["over", "under", "pass"]
    signal_direction: Literal["over", "under", "neutral"]
    signal_tier: Literal["consensus", "disputed", "anomalous"]
    requires_ai_confirmation: bool
    source_snapshot_ids: list[str] = Field(default_factory=list)
    source_provider_ids: list[str] = Field(default_factory=list)
    independence_keys: list[str] = Field(default_factory=list)
    deterministic_observations: dict[str, Any] = Field(default_factory=dict)
    reason: str

    @property
    def triggered(self) -> bool:
        return self.status == "triggered"


class ExperimentAdvisoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisory_id: str
    pack_id: str
    status: Literal["triggered", "not_triggered", "not_applicable", "insufficient_data"]
    severity: Literal["info", "warning"]
    requires_ai_confirmation: bool
    source_snapshot_ids: list[str] = Field(default_factory=list)
    source_provider_ids: list[str] = Field(default_factory=list)
    observations: dict[str, Any] = Field(default_factory=dict)
    missing_inputs: list[str] = Field(default_factory=list)
    reason: str


class ExperimentAdvisoryBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    competition_code: str
    experiment_ruleset_version: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cutoff_at: datetime
    experiment_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_outlook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_chain: list[str]
    fund_flow_status: Literal["unknown"] = "unknown"
    causal_attribution: Literal["unverified"] = "unverified"
    events: list[ExperimentAdvisoryEvent]
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentAdvisoryDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    advisory_id: str
    disposition: Literal["acknowledged", "dismissed", "insufficient_data"]
    reason: str = Field(min_length=1)
    counter_evidence: list[str] = Field(default_factory=list)
    invalidation_condition: str = Field(min_length=1)
    actor: str = Field(min_length=1)


class ExperimentAdvisoryReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str
    match_id: str
    status: Literal["complete", "insufficient_data", "failed"]
    prepared_at: datetime
    data_cutoff_at: datetime
    kickoff_at: datetime
    official_lock_candidate_id: str
    official_lock_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    advisory_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    advisory_dispositions_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    advisory_bundle_path: str | None = None
    reasons: list[str] = Field(default_factory=list)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentAdvisoryOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    outcome_id: str
    match_id: str
    advisory_receipt_id: str
    advisory_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_at: datetime
    final_score: str
    rule_results: dict[str, Literal["support", "counterexample", "ambiguous", "not_applicable"]]
    key_events: str | None = None
    random_event_status: Literal["unreviewed"] = "unreviewed"
    outcome_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentEvaluationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    competition_code: str
    experiment_ruleset_version: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cutoff_at: datetime
    experiment_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_outlook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_chain: list[str]
    fund_flow_status: Literal["unknown"] = "unknown"
    causal_attribution: Literal["unverified"] = "unverified"
    features: dict[str, Any]
    events: list[ExperimentRuleEvent]
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    disposition: Literal["adopted", "excluded"]
    hypothesis_a: str = Field(min_length=1)
    hypothesis_b: str = Field(min_length=1)
    supporting_evidence: list[str] = Field(min_length=1)
    counter_evidence: list[str] = Field(min_length=1)
    invalidation_condition: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    primary_range: tuple[int, int] | None = None
    modal_goals: list[int] = Field(default_factory=list, max_length=2)
    tail_ranges: list[tuple[int, int]] = Field(default_factory=list)
    excluded_ranges: list[tuple[int, int]] = Field(default_factory=list)
    score_candidates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_candidates(self) -> "ExperimentDisposition":
        ranges = ([self.primary_range] if self.primary_range else []) + self.tail_ranges + self.excluded_ranges
        if any(left > right or left < 0 for left, right in ranges):
            raise ValueError("实验总进球区间无效")
        if self.primary_range and any(value < self.primary_range[0] or value > self.primary_range[1] for value in self.modal_goals):
            raise ValueError("众数进球必须位于主区间内")
        if self.score_candidates and (len(self.score_candidates) != 2 or len(set(self.score_candidates)) != 2):
            raise ValueError("实验比分必须恰好两个且不同")
        if any(not re.fullmatch(r"\d+-\d+", value) for value in self.score_candidates):
            raise ValueError("实验比分必须使用 H-A 格式")
        return self


class ExperimentTotalGoalsCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_range: tuple[int, int]
    modal_goals: list[int] = Field(default_factory=list, max_length=2)
    tail_ranges: list[tuple[int, int]] = Field(default_factory=list)
    excluded_ranges: list[tuple[int, int]] = Field(default_factory=list)
    signal_tier: Literal["consensus", "disputed", "anomalous"]
    rule_ids: list[str] = Field(min_length=1)
    disposition: Literal["adopted", "excluded"]


class ExperimentOutlook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    official_outlook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ai_dispositions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_ruleset_version: str
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_chain: list[str]
    experiment_status: Literal["complete", "insufficient_data"]
    official_rankings: dict[str, list[str]]
    experimental_rankings: dict[str, list[str]]
    ranking_deltas: dict[str, dict[str, list[str]]]
    total_goals_candidates: list[ExperimentTotalGoalsCandidate]
    final_primary_range: tuple[int, int]
    modal_goals: list[int] = Field(default_factory=list, max_length=2)
    tail_ranges: list[tuple[int, int]] = Field(default_factory=list)
    excluded_ranges: list[tuple[int, int]] = Field(default_factory=list)
    score_candidates: list[str] = Field(min_length=2, max_length=2)
    dispositions: list[ExperimentDisposition]
    event_statuses: dict[str, str]
    outlook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_output(self) -> "ExperimentOutlook":
        if len(set(self.score_candidates)) != 2:
            raise ValueError("实验最终比分必须恰好两个且不同")
        if self.final_primary_range[0] > self.final_primary_range[1]:
            raise ValueError("实验最终总进球区间无效")
        return self


class ExperimentPredictionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str
    match_id: str
    status: Literal["complete", "insufficient_data", "failed"]
    prepared_at: datetime
    data_cutoff_at: datetime
    kickoff_at: datetime
    official_lock_candidate_id: str
    official_lock_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_outlook_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    ai_dispositions_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    experiment_outlook_path: str | None = None
    reasons: list[str] = Field(default_factory=list)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExperimentOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    outcome_id: str
    match_id: str
    experiment_prediction_receipt_id: str
    experiment_prediction_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_at: datetime
    final_score: str
    total_goals: int
    primary_range_hit: bool
    modal_goal_hit: bool
    tail_range_hit: bool
    score_hit: bool
    official_primary_range_hit: bool | None
    comparison: Literal["experiment_better", "official_better", "same"]
    rule_results: dict[str, Literal["support", "counterexample", "ambiguous", "not_applicable"]]
    key_events: str | None = None
    random_event_status: Literal["unreviewed"] = "unreviewed"
    outcome_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LiveExperimentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    observed_at: datetime
    minute: int = Field(ge=0, le=130)
    score: str = Field(pattern=r"^\d+-\d+$")
    event_type: Literal["goal", "state_update"]
    weaker_side_counterattack_status: Literal["capable", "limited", "unknown"] = "unknown"
    source_ref: str = Field(min_length=1)


class LiveExperimentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str
    match_id: str
    observed_at: datetime
    minute: int
    score: str
    source_ref: str
    base_primary_range: tuple[int, int]
    candidate_primary_range: tuple[int, int]
    triggered_rule: Literal["early-goal-upshift", "two-goal-control", "none"]
    reason: str
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _read_config(snapshot: Path) -> tuple[ExperimentCalibrationConfig, Path]:
    manifest = yaml.safe_load((snapshot / "manifest.yml").read_text(encoding="utf-8")) or {}
    config_path = snapshot / str(manifest.get("calibration_config_path"))
    config = ExperimentCalibrationConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    expected = str(manifest.get("calibration_config_sha256") or "")
    if sha256_file(config_path) != expected:
        raise ValueError("实验校准配置哈希不一致")
    return config, config_path


def active_experiment(root: Path) -> ActiveExperiment | None:
    path = root / ACTIVE_EXPERIMENT
    if not path.is_file():
        return None
    active = ActiveExperiment.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if active.status != "active":
        return None
    snapshot = root / active.snapshot_path
    if not snapshot.is_dir():
        raise ValueError("活动实验快照不存在")
    config, config_path = _read_config(snapshot)
    if sha256_file(config_path) != active.calibration_config_sha256:
        raise ValueError("活动实验配置哈希不一致")
    precedence = snapshot / "precedence.yml"
    if not precedence.is_file() or sha256_file(precedence) != active.precedence_sha256:
        raise ValueError("活动实验覆盖图哈希不一致")
    source_map = snapshot / "source-map.yml"
    if active.source_mapping_sha256:
        if not source_map.is_file() or sha256_file(source_map) != active.source_mapping_sha256:
            raise ValueError("活动实验来源与冲突映射缺失或哈希不一致")
    if config.profile_id != "football-analysis-v5":
        raise ValueError("活动实验不是 Contract 5")
    if _directory_hash(snapshot) != active.proposal_sha256:
        raise ValueError("活动实验快照内容哈希不一致")
    return active


def _next_experiment_revision(root: Path, version: str) -> int:
    ledger = root / EXPERIMENT_LEDGER
    revisions = [
        int(event.payload.get("experiment_revision", 0))
        for event in read_ledger(ledger)
        if event.payload.get("event_type") == "experiment_activated"
        and event.payload.get("ruleset_version") == version
    ]
    return max(revisions, default=0) + 1


def activate_experiment(root: Path, version: str, *, approved_by: str, activated_at: datetime) -> ActiveExperiment:
    if approved_by.strip() != "lcz":
        raise ValueError("实验规则必须由 lcz 批准")
    proposal = root / "knowledge/rule-proposals/football-analysis" / version
    validation = validate_ruleset_proposal(root, version)
    failures = [f"{path}: {'; '.join(errors)}" for path, errors in validation.items() if errors]
    if failures:
        raise ValueError("规则提案校验失败：" + "；".join(failures))
    manifest = yaml.safe_load((proposal / "manifest.yml").read_text(encoding="utf-8")) or {}
    if manifest.get("calibration_contract_version") != 5:
        raise ValueError("活动实验必须使用 Calibration Contract 5")
    config_path = proposal / str(manifest.get("calibration_config_path"))
    config = ExperimentCalibrationConfig.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    for relative in config.source_intake_paths:
        if not (root / relative).is_file():
            raise ValueError(f"实验规则来源 intake 不存在：{relative}")
    precedence = proposal / "precedence.yml"
    if not precedence.is_file():
        raise ValueError("实验提案缺少 precedence.yml")
    source_map = proposal / "source-map.yml"
    if not source_map.is_file():
        raise ValueError("实验提案缺少 source-map.yml")
    mapping = yaml.safe_load(source_map.read_text(encoding="utf-8")) or {}
    for source in mapping.get("sources", []):
        source_path = root / str(source.get("path") or "")
        if not source_path.is_file() or sha256_file(source_path) != source.get("sha256"):
            raise ValueError(f"实验来源映射缺失或哈希不一致：{source.get('path')}")
    proposal_hash = _directory_hash(proposal)
    target = root / EXPERIMENT_ROOT / version / proposal_hash
    existing = active_experiment(root)
    if existing and existing.proposal_sha256 == proposal_hash:
        return existing
    revision = _next_experiment_revision(root, version)
    raw = {
        "schema_version": 1,
        "status": "active",
        "ruleset_id": "football-analysis",
        "ruleset_version": version,
        "experiment_revision": revision,
        "proposal_sha256": proposal_hash,
        "snapshot_path": target.relative_to(root).as_posix(),
        "calibration_config_sha256": sha256_file(config_path),
        "precedence_sha256": sha256_file(precedence),
        "source_mapping_sha256": sha256_file(source_map),
        "approved_by": approved_by.strip(),
        "activated_at": activated_at,
    }
    active = ActiveExperiment.model_validate(raw)
    active_path = root / ACTIVE_EXPERIMENT
    ledger = root / EXPERIMENT_LEDGER
    with RepositoryTransaction(root, files=[active_path, ledger], directories=[target], operation="activate-rule-experiment") as transaction:
        if target.exists():
            if _directory_hash(target) != proposal_hash:
                raise ValueError("已存在实验快照与当前提案哈希不一致")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(proposal, target)
            atomic_write_text(
                target / "EXPERIMENT-ACTIVATION.yml",
                yaml.safe_dump(active.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            )
        atomic_write_text(active_path, yaml.safe_dump(active.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        append_payloads(
            ledger,
            [{"event_type": "experiment_activated", **active.model_dump(mode="json")}],
            recorded_at=activated_at,
            actor=approved_by,
            event_id_factory=lambda item, _: f"experiment:activate:{proposal_hash}:{revision}",
        )
        transaction.commit()
    return active


def deactivate_experiment(root: Path, *, approved_by: str, reason: str, deactivated_at: datetime) -> ActiveExperiment:
    if approved_by.strip() != "lcz" or not reason.strip():
        raise ValueError("停用实验必须由 lcz 提供明确原因")
    current = active_experiment(root)
    if current is None:
        raise ValueError("当前没有活动实验")
    inactive = current.model_copy(update={"status": "inactive", "deactivation_reason": reason.strip()})
    active_path = root / ACTIVE_EXPERIMENT
    ledger = root / EXPERIMENT_LEDGER
    with RepositoryTransaction(root, files=[active_path, ledger], directories=[], operation="deactivate-rule-experiment") as transaction:
        atomic_write_text(active_path, yaml.safe_dump(inactive.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        append_payloads(
            ledger,
            [{"event_type": "experiment_deactivated", "proposal_sha256": current.proposal_sha256, "reason": reason.strip()}],
            recorded_at=deactivated_at,
            actor=approved_by,
            event_id_factory=lambda item, _: f"experiment:deactivate:{current.proposal_sha256}:{current.experiment_revision}",
        )
        transaction.commit()
    return inactive


def experiment_status(root: Path) -> dict[str, Any]:
    path = root / ACTIVE_EXPERIMENT
    if not path.is_file():
        return {"active": False, "reason": "not_configured"}
    stored = ActiveExperiment.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return {"active": stored.status == "active", **stored.model_dump(mode="json")}


def _receipt_data(model: BaseModel) -> dict[str, Any]:
    raw = model.model_dump(mode="json")
    if isinstance(model, ExperimentAnalysisReceipt):
        # Preserve hashes of immutable V1/V2 receipts after adding later
        # optional context fields.
        if model.schema_version == 1:
            raw.pop("observation_set_sha256", None)
            raw.pop("market_feature_snapshot_sha256", None)
        if model.schema_version in {1, 2}:
            raw.pop("applicable_advisory_ids", None)
    for field in ("receipt_sha256", "outlook_sha256", "outcome_sha256", "bundle_sha256"):
        if field in raw:
            raw[field] = "0" * 64
    return raw


def _finalize(model_class: type[BaseModel], raw: dict[str, Any], hash_field: str) -> BaseModel:
    provisional = model_class.model_validate({**raw, hash_field: "0" * 64})
    payload = provisional.model_dump(mode="json")
    payload[hash_field] = _hash(_receipt_data(provisional))
    return model_class.model_validate(payload)


def prepare_experiment_context(root: Path, path: Path, official_receipt: Any) -> tuple[Path, ExperimentAnalysisReceipt] | None:
    active = active_experiment(root)
    if active is None:
        return None
    document = MatchDocument.load(path)
    base = root / "raw/matches" / document.metadata.match_id
    target = base / "experiment-analysis-receipt.yml"
    if target.is_file():
        existing = ExperimentAnalysisReceipt.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
        if existing.receipt_sha256 != _hash(_receipt_data(existing)):
            raise ValueError("实验分析回执哈希无效")
        if existing.proposal_sha256 == active.proposal_sha256:
            return target, existing
        raise ValueError("该比赛已冻结其他实验快照，禁止中途切换")
    snapshot = root / active.snapshot_path
    config, _ = _read_config(snapshot)
    profile_chain = config.profile_chain_for(document.metadata.competition_code)
    official_hash = sha256_json(official_receipt.model_dump(mode="json"))
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    observation_features = market_feature_snapshot(
        root, document.metadata.match_id, official_receipt.as_of
    )
    has_observation_input = bool(
        observation_features["observation_ids"]
        or observation_features["phase_only_observation_ids"]
    )
    has_advisories = bool(config.applicable_advisories(document.metadata.competition_code))
    raw = {
        "schema_version": 3 if has_advisories else 2 if has_observation_input else 1,
        "receipt_id": f"experiment-context-{document.metadata.match_id}-{active.proposal_sha256[:12]}",
        "match_id": document.metadata.match_id,
        "prepared_at": now,
        "as_of": official_receipt.as_of,
        "kickoff_at": document.metadata.kickoff_at,
        "official_ruleset_version": official_receipt.ruleset_version,
        "official_analysis_receipt_sha256": official_hash,
        "market_snapshots_sha256": market_snapshots_sha256(document),
        "experiment_ruleset_version": active.ruleset_version,
        "experiment_revision": active.experiment_revision,
        "proposal_sha256": active.proposal_sha256,
        "snapshot_path": active.snapshot_path,
        "calibration_config_sha256": active.calibration_config_sha256,
        "precedence_sha256": active.precedence_sha256,
        "profile_chain": profile_chain,
        "applicable_rule_ids": [item.rule_id for item in config.applicable_rules(document.metadata.competition_code)],
        "applicable_advisory_ids": [item.advisory_id for item in config.applicable_advisories(document.metadata.competition_code)],
    }
    if has_observation_input:
        raw.update({
            "observation_set_sha256": observation_features["observation_set_sha256"],
            "market_feature_snapshot_sha256": observation_features["feature_snapshot_sha256"],
        })
    receipt = _finalize(ExperimentAnalysisReceipt, raw, "receipt_sha256")
    assert isinstance(receipt, ExperimentAnalysisReceipt)
    atomic_write_text(target, yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    return target, receipt


def _number(snapshot: MarketSnapshot, key: str) -> float | None:
    value = snapshot.normalized_values.get(key)
    return float(value) if value is not None else None


def _series(nodes: list[MarketSnapshot], keys: tuple[str, ...]) -> dict[str, Any]:
    ordered = sorted(nodes, key=lambda item: (item.captured_at, item.snapshot_id))
    values: dict[str, list[float]] = {}
    for key in keys:
        present = [_number(item, key) for item in ordered]
        values[key] = [float(item) for item in present if item is not None]
    changes = {key: round(items[-1] - items[0], 6) if len(items) >= 2 else None for key, items in values.items()}
    return {
        "snapshot_ids": [item.snapshot_id for item in ordered],
        "provider": ordered[0].provider_id,
        "market": str(ordered[0].market),
        "odds_format": str(ordered[0].odds_format),
        "phases": sorted({str(item.phase) for item in ordered}),
        "captured_at": [item.captured_at.isoformat() for item in ordered],
        "values": values,
        "changes": changes,
        "three_nodes": len(ordered) >= 3 and {"opening", "mid", "late"}.issubset({str(item.phase) for item in ordered}),
        "time_precision": "exact",
    }


def _phase_only_experiment_series(features: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {
        "total_series": [], "asian_series": [], "euro_series": [], "kelly_series": []
    }
    for item in features.get("phase_only_series", []):
        prices = item.get("normalized_price_endpoints", [{}, {}])
        if len(prices) != 2:
            continue
        common = {
            "snapshot_ids": item["observation_ids"],
            "provider": item["provider_id"],
            "market": item["market"],
            "odds_format": (
                "hong_kong" if item["market"] in {"asian_handicap", "total_goals"}
                else "kelly" if item["market"] == "kelly_index" else "decimal"
            ),
            "phases": item.get("phases", []),
            "captured_at": [f"phase:{phase}" for phase in item.get("phases", [])],
            "three_nodes": False,
            "time_precision": "phase_only",
        }
        lines = item.get("line_endpoints", [None, None])
        if item["market"] == "total_goals":
            if lines[0] == lines[1] and lines[0] is not None:
                values = {
                    "over_water": [prices[0].get("over"), prices[1].get("over")],
                    "under_water": [prices[0].get("under"), prices[1].get("under")],
                }
                values = {key: [float(value) for value in row if value is not None] for key, row in values.items()}
                output["total_series"].append({
                    **common, "line": float(lines[0]), "values": values,
                    "changes": {key: round(row[-1] - row[0], 6) if len(row) == 2 else None for key, row in values.items()},
                })
            else:
                for index, line in enumerate(lines):
                    if line is None:
                        continue
                    output["total_series"].append({
                        **common, "line": float(line),
                        "captured_at": [f"phase:{item.get('phases', [index])[index]}"],
                        "values": {
                            "over_water": [float(prices[index]["over"])] if "over" in prices[index] else [],
                            "under_water": [float(prices[index]["under"])] if "under" in prices[index] else [],
                        },
                        "changes": {"over_water": None, "under_water": None},
                    })
        elif item["market"] == "asian_handicap":
            output["asian_series"].append({
                **common,
                "values": {
                    "home_line": [float(value) for value in lines if value is not None],
                    "home_water": [float(value["home"]) for value in prices if "home" in value],
                    "away_water": [float(value["away"]) for value in prices if "away" in value],
                },
                "changes": item.get("price_changes", {}),
            })
        else:
            target = "euro_series" if item["market"] == "european_odds" else "kelly_series"
            values = {
                key: [float(value[key]) for value in prices if key in value]
                for key in ("home", "draw", "away")
            }
            output[target].append({
                **common,
                "values": values,
                "changes": {key: round(row[-1] - row[0], 6) if len(row) == 2 else None for key, row in values.items()},
            })
    return output


def experiment_feature_snapshot(
    metadata: Any,
    cutoff: datetime,
    *,
    snapshots: list[MarketSnapshot] | None = None,
    observation_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_snapshots = metadata.market_snapshots if snapshots is None else snapshots
    eligible = [item for item in source_snapshots if item.captured_at <= cutoff and item.captured_at < metadata.kickoff_at]
    total_groups: dict[tuple[str, float], list[MarketSnapshot]] = defaultdict(list)
    asian_groups: dict[str, list[MarketSnapshot]] = defaultdict(list)
    euro_groups: dict[str, list[MarketSnapshot]] = defaultdict(list)
    kelly_groups: dict[str, list[MarketSnapshot]] = defaultdict(list)
    for item in eligible:
        market = str(item.market)
        if market == "total_goals" and _number(item, "line") is not None:
            total_groups[(item.provider_id, float(_number(item, "line")))].append(item)
        elif market == "asian_handicap":
            asian_groups[item.provider_id].append(item)
        elif market == "european_odds":
            euro_groups[item.provider_id].append(item)
        elif market == "kelly_index":
            kelly_groups[item.provider_id].append(item)
    totals = []
    for (provider, line), nodes in sorted(total_groups.items()):
        totals.append({"line": line, **_series(nodes, ("over_water", "under_water"))})
    asians = [{"provider": provider, **_series(nodes, ("home_line", "home_water", "away_water"))} for provider, nodes in sorted(asian_groups.items())]
    euros = [{"provider": provider, **_series(nodes, ("home", "draw", "away"))} for provider, nodes in sorted(euro_groups.items())]
    kellies = [{"provider": provider, **_series(nodes, ("home", "draw", "away"))} for provider, nodes in sorted(kelly_groups.items())]
    if observation_features is not None:
        phase = _phase_only_experiment_series(observation_features)
        totals.extend(phase["total_series"])
        asians.extend(phase["asian_series"])
        euros.extend(phase["euro_series"])
        kellies.extend(phase["kelly_series"])
    return {
        "total_series": totals,
        "asian_series": asians,
        "euro_series": euros,
        "kelly_series": kellies,
        "tags": list(metadata.tags),
        "kickoff_at": metadata.kickoff_at.isoformat(),
        "cutoff": cutoff.isoformat(),
        "fund_flow_status": "unknown",
        "causal_attribution": "unverified",
    }


def _event(
    rule: ExperimentRuleConfig,
    status: str,
    reason: str,
    *,
    direction: str = "neutral",
    tier: str = "disputed",
    observations: dict[str, Any] | None = None,
    series: list[dict[str, Any]] | None = None,
) -> ExperimentRuleEvent:
    selected = series or []
    return ExperimentRuleEvent(
        rule_id=rule.rule_id,
        status=status,
        effect=rule.effect,
        target_selection=direction if direction in {"over", "under"} else "pass",
        signal_direction=direction,
        signal_tier=tier,
        requires_ai_confirmation=rule.determinism == "hybrid",
        source_snapshot_ids=sorted({identity for item in selected for identity in item.get("snapshot_ids", [])}),
        source_provider_ids=sorted({str(item.get("provider")) for item in selected if item.get("provider")}),
        independence_keys=sorted({
            f"{item.get('provider')}:{item.get('market', 'unknown')}:{item.get('line', 'na')}:{item.get('odds_format', 'unknown')}"
            for item in selected
        }),
        deterministic_observations=observations or {},
        reason=reason,
    )


def _provider_direction(features: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in features["total_series"]:
        grouped[item["provider"]].append(item)
    output: dict[str, tuple[str, dict[str, Any]]] = {}
    for provider, series in grouped.items():
        first = min(series, key=lambda item: min(item["captured_at"]))
        last = max(series, key=lambda item: max(item["captured_at"]))
        line_delta = last["line"] - first["line"] if first is not last else 0.0
        over_delta = last["changes"].get("over_water")
        direction = "over" if line_delta > 0 or (line_delta == 0 and over_delta is not None and over_delta < 0) else "under" if line_delta < 0 or (line_delta == 0 and over_delta is not None and over_delta > 0) else "neutral"
        output[provider] = (direction, last)
    return output


def evaluate_experiment_rules(config: ExperimentCalibrationConfig, competition_code: str, features: dict[str, Any]) -> list[ExperimentRuleEvent]:
    applicable = {item.rule_id for item in config.applicable_rules(competition_code)}
    by_id = {item.rule_id: item for item in config.rules}
    events: list[ExperimentRuleEvent] = []
    totals = features["total_series"]
    asians = features["asian_series"]
    kellies = features["kelly_series"]
    tags = set(features["tags"])

    for rule in config.rules:
        if rule.rule_id not in applicable:
            events.append(_event(rule, "not_applicable", "profile_not_applicable"))
            continue
        rid = rule.rule_id
        threshold = rule.thresholds
        if rid == "tg-same-line-water-defense-v1":
            matches = []
            direction = "neutral"
            for item in totals:
                if not item["three_nodes"]:
                    continue
                over = item["changes"].get("over_water")
                under = item["changes"].get("under_water")
                if over is not None and -over >= threshold["water_fall_min"]:
                    matches.append(item); direction = "over"
                elif under is not None and -under >= threshold["water_fall_min"]:
                    matches.append(item); direction = "under"
            events.append(_event(rule, "triggered" if matches else "not_triggered", "same_line_water_fall" if matches else "threshold_not_met", direction=direction, tier="consensus", observations={"water_fall_min": threshold["water_fall_min"]}, series=matches))
        elif rid == "tg-line-drop-over-price-divergence-v1":
            provider_series: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in totals: provider_series[item["provider"]].append(item)
            matches = []
            for provider, series in provider_series.items():
                chronological = sorted(series, key=lambda item: min(item["captured_at"]))
                opening, late = chronological[0], chronological[-1]
                line_drop = opening["line"] - late["line"]
                opening_values = opening["values"].get("over_water", [])
                late_values = late["values"].get("over_water", [])
                over_change = (
                    late_values[-1] - opening_values[0]
                    if opening_values and late_values else None
                )
                if line_drop >= threshold["line_drop_min"] and over_change is not None and over_change >= -threshold["over_micro_fall_max"]:
                    matches.extend([opening, late])
            events.append(_event(rule, "triggered" if matches else "not_triggered", "line_drop_without_over_tightening" if matches else "threshold_not_met", direction="under", tier="consensus", observations={"line_drop_min": threshold["line_drop_min"], "over_micro_fall_max": threshold["over_micro_fall_max"]}, series=matches))
        elif rid == "tg-late-shock-guard-v1":
            matches = []
            for item in totals:
                if item.get("time_precision") != "exact":
                    continue
                times = [datetime.fromisoformat(value) for value in item["captured_at"]]
                values = item["values"].get("over_water", [])
                if len(times) >= 2 and len(values) >= 2 and times[-1] >= datetime.fromisoformat(features["kickoff_at"]) - timedelta(minutes=int(threshold["late_window_minutes"])) and abs(values[-1] - values[-2]) >= threshold["water_move_min"]:
                    matches.append(item)
            events.append(_event(rule, "triggered" if matches else "not_triggered", "late_water_shock" if matches else "threshold_not_met", tier="anomalous", observations={"water_move_min": threshold["water_move_min"]}, series=matches))
        elif rid == "tg-dual-line-bracket-v1":
            by_provider = defaultdict(dict)
            for item in totals: by_provider[item["provider"]][item["line"]] = item
            matches = []
            for provider, lines in by_provider.items():
                low, high = lines.get(threshold["low_line"]), lines.get(threshold["high_line"])
                if not low or not high:
                    continue
                over_values = low["values"].get("over_water", [])
                under_change = high["changes"].get("under_water")
                if over_values and over_values[-1] <= threshold["low_over_water_max"] and under_change is not None and under_change < 0:
                    matches.extend([low, high])
            events.append(_event(rule, "triggered" if matches else "not_triggered", "dual_line_bracket_candidate" if matches else "threshold_not_met", direction="over", tier="disputed", series=matches))
        elif rid == "tg-handicap-ceiling-risk-v1":
            matches = []
            for item in asians:
                lines = item["values"].get("home_line", [])
                waters = item["values"].get("home_water", [])
                if len(lines) >= 2 and abs(lines[0]) - abs(lines[-1]) >= threshold["line_drop_min"] and len(waters) >= 2 and waters[-1] >= waters[0]:
                    matches.append(item)
            events.append(_event(rule, "triggered" if matches else "not_triggered", "handicap_ceiling_risk" if matches else "threshold_not_met", direction="under", tier="disputed", series=matches))
        elif rid == "tg-head-provider-divergence-nordic-v1":
            directions = _provider_direction(features)
            heads = config.head_providers.get("nordic-low-heat", [])
            ordinary = [value[0] for provider, value in directions.items() if provider not in heads and value[0] != "neutral"]
            majority = Counter(ordinary).most_common(1)[0] if ordinary else ("neutral", 0)
            head = next(((provider, directions[provider]) for provider in heads if provider in directions and directions[provider][0] != "neutral"), None)
            triggered = majority[1] >= int(threshold["ordinary_provider_min"]) and head is not None and head[1][0] != majority[0]
            selected = [value[1] for value in directions.values()] if triggered else []
            events.append(_event(rule, "triggered" if triggered else "not_triggered", "head_provider_divergence" if triggered else "threshold_not_met", direction=head[1][0] if triggered and head else "neutral", tier="disputed", observations={"ordinary_majority": majority[0], "ordinary_count": majority[1], "head_provider": head[0] if head else None}, series=selected))
        elif rid == "tg-floor-anchor-upper-tail-v1":
            by_provider = defaultdict(dict)
            for item in totals: by_provider[item["provider"]][item["line"]] = item
            matches = []
            for provider, lines in by_provider.items():
                low, high = lines.get(threshold["low_line"]), lines.get(threshold["high_line"])
                if not low or not high or not low["three_nodes"]:
                    continue
                low_values = low["values"].get("over_water", [])
                high_change = high["changes"].get("over_water")
                if low_values and all(value <= threshold["low_over_water_max"] for value in low_values) and high_change is not None and high_change < 0:
                    matches.extend([low, high])
            events.append(_event(rule, "triggered" if matches else "not_triggered", "floor_anchor_upper_tail" if matches else "threshold_not_met", direction="over", tier="disputed", series=matches))
        elif rid == "tg-draw-compression-hypothesis-v1":
            matches = []
            for item in kellies:
                values = item["values"]
                if min(map(len, (values.get("home", []), values.get("draw", []), values.get("away", [])))) < 2:
                    continue
                home, draw, away = values["home"], values["draw"], values["away"]
                if abs(home[-1] - away[-1]) < abs(home[0] - away[0]) and abs(draw[-1] - draw[0]) <= threshold["draw_stability_max"] and draw[-1] == min(home[-1], draw[-1], away[-1]):
                    matches.append(item)
            events.append(_event(rule, "triggered" if matches else "not_triggered", "draw_kelly_dual_hypothesis" if matches else "threshold_not_met", tier="disputed", series=matches))
        elif rid == "tg-one-sided-overrun-risk-v1":
            low = [item for item in totals if item["line"] == threshold["total_line"] and item["three_nodes"] and item["values"].get("over_water") and all(value <= threshold["over_water_max"] for value in item["values"]["over_water"])]
            deep = [item for item in asians if item["values"].get("home_line") and abs(item["values"]["home_line"][-1]) >= threshold["deep_line_min"] and (item["values"].get("home_water", [0])[-1] >= threshold["high_water_min"] or abs(item["values"]["home_line"][0]) > abs(item["values"]["home_line"][-1]))]
            draw_low = []
            for item in kellies:
                values = item["values"]
                if values.get("home") and values.get("draw") and values.get("away") and values["draw"][-1] == min(values["home"][-1], values["draw"][-1], values["away"][-1]): draw_low.append(item)
            selected = [*low, *deep, *draw_low]
            events.append(_event(rule, "triggered" if low and deep and draw_low else "not_triggered", "one_sided_overrun_candidate" if low and deep and draw_low else "threshold_not_met", direction="over", tier="anomalous", series=selected))
        elif rid == "tg-away-collapse-prior-v1":
            required = {"away-defense-bottom", "home-attack-top3"}
            status = "triggered" if required <= tags else "insufficient_data"
            events.append(_event(rule, status, "structured_team_profile" if status == "triggered" else "missing_structured_team_profile", direction="over", tier="anomalous", observations={"required_tags": sorted(required)}))
        elif rid == "tg-extreme-under-context-v1":
            under = [item for item in totals if item["line"] == threshold["total_line"] and item["three_nodes"] and item["values"].get("under_water") and all(value <= threshold["under_water_max"] for value in item["values"]["under_water"])]
            required = {"both-low-attack", "conservative-match"}
            status = "triggered" if under and required <= tags else "insufficient_data" if under else "not_triggered"
            events.append(_event(rule, status, "extreme_under_context" if status == "triggered" else "missing_context" if under else "threshold_not_met", direction="under", tier="anomalous", series=under))
        elif rid == "tg-two-dimension-confirmation-v1":
            events.append(_event(rule, "not_triggered", "evaluated_after_directional_rules"))

    directional = [item for item in events if item.status == "triggered" and item.signal_direction in {"over", "under"} and item.rule_id != "tg-two-dimension-confirmation-v1"]
    counts: dict[str, set[str]] = defaultdict(set)
    for item in directional:
        for key in item.independence_keys or [item.rule_id]:
            counts[item.signal_direction].add(key)
    control = next(item for item in events if item.rule_id == "tg-two-dimension-confirmation-v1")
    minimum = int(by_id[control.rule_id].thresholds["independent_dimensions_min"])
    winner = max(counts, key=lambda key: len(counts[key]), default="neutral")
    if winner != "neutral" and len(counts[winner]) >= minimum:
        index = events.index(control)
        events[index] = control.model_copy(update={"status": "triggered", "target_selection": winner, "signal_direction": winner, "signal_tier": "consensus", "reason": "independent_dimensions_confirmed", "deterministic_observations": {"independent_supports": len(counts[winner]), "threshold": minimum}})

    event_by_id = {item.rule_id: item for item in events}
    for rule in config.rules:
        source = event_by_id[rule.rule_id]
        should_override = rule.override_mode == "replace" or (rule.override_mode == "when_triggered" and source.status == "triggered")
        if not should_override:
            continue
        external = [target for target in rule.supersedes_rule_ids if target not in event_by_id]
        if external:
            event_by_id[rule.rule_id] = source.model_copy(update={"suppressed_external_rule_ids": external})
        for target in rule.supersedes_rule_ids:
            old = event_by_id.get(target)
            if old is None:
                continue
            event_by_id[target] = old.model_copy(update={"status": "suppressed", "original_status": old.status, "suppressed_by_rule_id": rule.rule_id, "suppression_reason": "最新规则在同市场同场景中显式覆盖", "reason": "superseded"})
    return [event_by_id[item.rule_id] for item in config.rules]


def _official_rankings(outlook: AnalysisOutlook) -> dict[str, list[str]]:
    if outlook.schema_version == 4 and outlook.final_rankings:
        return {key: list(value) for key, value in outlook.final_rankings.items()}
    return {
        "one_x_two": list(outlook.one_x_two.choices) if outlook.one_x_two else [],
        "asian_handicap": list(outlook.asian_handicap.ranking.choices) if outlook.asian_handicap else [],
        "fixed_handicap_1x2": list(outlook.fixed_handicap_1x2.ranking.choices) if outlook.fixed_handicap_1x2 else [],
        "total_goals": [],
    }


def evaluate_experiment(
    root: Path,
    path: Path,
    *,
    dispositions: list[ExperimentDisposition] | None,
) -> tuple[Path, ExperimentEvaluationBundle, Path | None, ExperimentOutlook | None]:
    document = MatchDocument.load(path)
    base = root / "raw/matches" / document.metadata.match_id
    receipt_path = base / "experiment-analysis-receipt.yml"
    if not receipt_path.is_file():
        raise ValueError("当前比赛没有实验分析回执；请重新运行 agent start")
    receipt = ExperimentAnalysisReceipt.model_validate(yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {})
    official_receipt = parse_receipt(document.sections["prematch-reasoning"])
    if official_receipt is None or sha256_json(official_receipt.model_dump(mode="json")) != receipt.official_analysis_receipt_sha256:
        raise ValueError("正式分析回执已变化，实验回执失效")
    if market_snapshots_sha256(document) != receipt.market_snapshots_sha256:
        raise ValueError("盘口快照已变化；请重启当前分析以冻结新截止时间")
    observation_snapshots: list[MarketSnapshot] | None = None
    if receipt.schema_version in {2, 3} and receipt.observation_set_sha256:
        current_features = market_feature_snapshot(root, document.metadata.match_id, receipt.as_of)
        if current_features["observation_set_sha256"] != receipt.observation_set_sha256:
            raise ValueError("规范化观测集合已变化；实验输入保持冻结，请重启分析")
        if current_features["feature_snapshot_sha256"] != receipt.market_feature_snapshot_sha256:
            raise ValueError("趋势特征已变化；实验输入保持冻结，请重启分析")
        observation_snapshots = effective_market_snapshots(
            root, document.metadata.match_id, receipt.as_of
        )
    official_path = base / "analysis-outlook.yml"
    draft_path = base / "analysis-draft-input.yml"
    if not official_path.is_file() or not draft_path.is_file():
        raise ValueError("实验评估必须在正式 Draft Input 和 Outlook 生成后执行")
    official = AnalysisOutlook.model_validate(yaml.safe_load(official_path.read_text(encoding="utf-8")) or {})
    official_hash = sha256_file(official_path)
    snapshot = root / receipt.snapshot_path
    config, _ = _read_config(snapshot)
    features = experiment_feature_snapshot(
        document.metadata,
        receipt.as_of,
        snapshots=observation_snapshots,
        observation_features=current_features if receipt.schema_version in {2, 3} and receipt.observation_set_sha256 else None,
    )
    events = evaluate_experiment_rules(config, document.metadata.competition_code, features)
    raw_bundle = {
        "schema_version": 1,
        "match_id": document.metadata.match_id,
        "competition_code": document.metadata.competition_code,
        "experiment_ruleset_version": receipt.experiment_ruleset_version,
        "proposal_sha256": receipt.proposal_sha256,
        "cutoff_at": receipt.as_of,
        "experiment_receipt_sha256": receipt.receipt_sha256,
        "official_outlook_sha256": official_hash,
        "draft_input_sha256": sha256_file(draft_path),
        "feature_snapshot_sha256": _hash(features),
        "profile_chain": receipt.profile_chain,
        "fund_flow_status": "unknown",
        "causal_attribution": "unverified",
        "features": features,
        "events": [item.model_dump(mode="json") for item in events],
    }
    bundle_hash = _hash(raw_bundle)
    bundle = ExperimentEvaluationBundle.model_validate({**raw_bundle, "bundle_sha256": bundle_hash})
    bundle_path = base / f"experiment-rule-evaluation-{bundle_hash}.yml"
    atomic_write_text(bundle_path, yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    if dispositions is None:
        return bundle_path, bundle, None, None
    by_rule = {item.rule_id: item for item in dispositions}
    if len(by_rule) != len(dispositions):
        raise ValueError("实验规则处置不得重复")
    triggered = {item.rule_id: item for item in events if item.status == "triggered"}
    if set(by_rule) != set(triggered):
        raise ValueError(f"实验处置必须覆盖全部触发规则；缺少={sorted(set(triggered)-set(by_rule))} 多出={sorted(set(by_rule)-set(triggered))}")
    adopted_candidates: list[ExperimentDisposition] = []
    for rule_id, event in triggered.items():
        decision = by_rule[rule_id]
        if decision.disposition == "adopted" and event.effect == "total_goals_pool":
            if decision.primary_range is None or len(decision.score_candidates) != 2:
                raise ValueError(f"采纳总进球规则必须填写主区间和两个比分：{rule_id}")
            adopted_candidates.append(decision)
    official_range = (official.total_goals.minimum, official.total_goals.maximum) if official.total_goals else (0, 0)
    official_scores = list(official.score_candidates)
    if adopted_candidates:
        signatures = {(item.primary_range, tuple(item.modal_goals), tuple(item.tail_ranges), tuple(item.excluded_ranges), tuple(item.score_candidates)) for item in adopted_candidates}
        if len(signatures) != 1:
            raise ValueError("多个已采纳实验规则必须收敛到同一总进球和比分候选")
        selected = adopted_candidates[0]
        final_range = selected.primary_range or official_range
        modal = selected.modal_goals
        tails = selected.tail_ranges
        excluded = selected.excluded_ranges
        scores = selected.score_candidates
        rule_ids = sorted(item.rule_id for item in adopted_candidates)
        tiers = {triggered[item].signal_tier for item in rule_ids}
        tier = "consensus" if "consensus" in tiers else "anomalous" if "anomalous" in tiers else "disputed"
    else:
        final_range, modal, tails, excluded, scores, rule_ids, tier = official_range, [], [], [], official_scores, ["official-baseline"], "disputed"
    candidate = ExperimentTotalGoalsCandidate(primary_range=final_range, modal_goals=modal, tail_ranges=tails, excluded_ranges=excluded, signal_tier=tier, rule_ids=rule_ids, disposition="adopted")
    rankings = _official_rankings(official)
    raw_outlook = {
        "schema_version": 1,
        "match_id": document.metadata.match_id,
        "official_outlook_sha256": official_hash,
        "experiment_receipt_sha256": receipt.receipt_sha256,
        "evaluation_bundle_sha256": bundle_hash,
        "ai_dispositions_sha256": _hash([item.model_dump(mode="json") for item in dispositions]),
        "experiment_ruleset_version": receipt.experiment_ruleset_version,
        "proposal_sha256": receipt.proposal_sha256,
        "profile_chain": receipt.profile_chain,
        "experiment_status": "complete",
        "official_rankings": rankings,
        "experimental_rankings": rankings,
        "ranking_deltas": {},
        "total_goals_candidates": [candidate.model_dump(mode="json")],
        "final_primary_range": final_range,
        "modal_goals": modal,
        "tail_ranges": tails,
        "excluded_ranges": excluded,
        "score_candidates": scores,
        "dispositions": [item.model_dump(mode="json") for item in dispositions],
        "event_statuses": {item.rule_id: item.status for item in events},
    }
    outlook = _finalize(ExperimentOutlook, raw_outlook, "outlook_sha256")
    assert isinstance(outlook, ExperimentOutlook)
    outlook_path = base / "experimental-analysis-outlook.yml"
    atomic_write_text(outlook_path, yaml.safe_dump(outlook.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    report = (
        f"# {document.metadata.home_team} VS {document.metadata.away_team} 实验轨分析\n\n"
        f"- 正式规则：football-analysis@{receipt.official_ruleset_version}\n"
        f"- 实验规则：football-analysis@{receipt.experiment_ruleset_version} / {receipt.proposal_sha256}\n"
        f"- 数据截止：{receipt.as_of.isoformat()}\n"
        f"- 正式总进球：{official_range[0]}-{official_range[1]}\n"
        f"- 实验总进球：{final_range[0]}-{final_range[1]}\n"
        f"- 众数候选：{', '.join(map(str, modal)) or '无'}\n"
        f"- 尾部风险：{tails or '无'}\n"
        f"- 实验比分：{', '.join(scores)}\n\n"
        "## 规则处置\n\n"
        + "\n".join(f"- {item.rule_id}: {item.status} / {item.reason}" for item in events)
        + "\n"
    )
    atomic_write_text(base / "experimental-analysis-report.md", report)
    return bundle_path, bundle, outlook_path, outlook


def _advisory_series(features: dict[str, Any], line: float) -> list[dict[str, Any]]:
    return [
        item for item in features.get("total_series", [])
        if item.get("line") is not None and abs(float(item["line"]) - line) < 1e-9
    ]


def _advisory_sources(items: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    return (
        sorted({identity for item in items for identity in item.get("snapshot_ids", [])}),
        sorted({str(item.get("provider")) for item in items if item.get("provider")}),
    )


def _advisory_event(
    rule: ExperimentAdvisoryConfig,
    *,
    status: Literal["triggered", "not_triggered", "not_applicable", "insufficient_data"],
    reason: str,
    sources: list[dict[str, Any]] | None = None,
    observations: dict[str, Any] | None = None,
    missing_inputs: list[str] | None = None,
) -> ExperimentAdvisoryEvent:
    snapshot_ids, provider_ids = _advisory_sources(sources or [])
    return ExperimentAdvisoryEvent(
        advisory_id=rule.advisory_id,
        pack_id=rule.pack_id,
        status=status,
        severity=rule.severity,
        requires_ai_confirmation=rule.determinism == "hybrid" or status == "triggered",
        source_snapshot_ids=snapshot_ids,
        source_provider_ids=provider_ids,
        observations=observations or {},
        missing_inputs=missing_inputs or [],
        reason=reason,
    )


def evaluate_experiment_advisories(
    root: Path,
    path: Path,
    *,
    dispositions: list[ExperimentAdvisoryDisposition] | None,
) -> tuple[Path, ExperimentAdvisoryBundle, Path]:
    """Evaluate warning-only rules without constructing an experimental prediction."""
    document = MatchDocument.load(path)
    base = root / "raw/matches" / document.metadata.match_id
    receipt_path = base / "experiment-analysis-receipt.yml"
    if not receipt_path.is_file():
        raise ValueError("当前比赛没有实验分析回执；请重新运行 agent start")
    receipt = ExperimentAnalysisReceipt.model_validate(yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {})
    official_path = base / "analysis-outlook.yml"
    if not official_path.is_file():
        raise ValueError("实验提示必须在正式 Outlook 生成后执行")
    official = AnalysisOutlook.model_validate(yaml.safe_load(official_path.read_text(encoding="utf-8")) or {})
    official_hash = sha256_file(official_path)
    official_receipt = parse_receipt(document.sections.get("prematch-reasoning", ""))
    if official_receipt is None or sha256_json(official_receipt.model_dump(mode="json")) != receipt.official_analysis_receipt_sha256:
        raise ValueError("正式分析回执已变化；实验提示输入保持冻结，请重新运行 agent start")
    if market_snapshots_sha256(document) != receipt.market_snapshots_sha256:
        raise ValueError("正式市场快照已变化；实验提示输入保持冻结，请重新运行 agent start")
    snapshot = root / receipt.snapshot_path
    config, _ = _read_config(snapshot)
    rules = config.applicable_advisories(document.metadata.competition_code)
    if not rules:
        raise ValueError("当前实验快照没有适用的提示规则")

    observation_snapshots: list[MarketSnapshot] | None = None
    current_features: dict[str, Any] | None = None
    if receipt.schema_version in {2, 3} and receipt.observation_set_sha256:
        current_features = market_feature_snapshot(root, document.metadata.match_id, receipt.as_of)
        if current_features["observation_set_sha256"] != receipt.observation_set_sha256:
            raise ValueError("规范化观测集合已变化；实验输入保持冻结，请重启分析")
        if current_features["feature_snapshot_sha256"] != receipt.market_feature_snapshot_sha256:
            raise ValueError("趋势特征已变化；实验输入保持冻结，请重启分析")
        observation_snapshots = effective_market_snapshots(root, document.metadata.match_id, receipt.as_of)
    features = experiment_feature_snapshot(
        document.metadata,
        receipt.as_of,
        snapshots=observation_snapshots,
        observation_features=current_features,
    )
    total_25 = [
        item for item in _advisory_series(features, 2.5)
        if item.get("provider") in config.recognized_providers
    ]
    total_30 = [
        item for item in _advisory_series(features, 3.0)
        if item.get("provider") in config.recognized_providers
    ]
    rankings = _official_rankings(official)
    events: list[ExperimentAdvisoryEvent] = []
    for rule in rules:
        if rule.advisory_id == "advisory-initial-water-guard-v1":
            if not total_25:
                event = _advisory_event(rule, status="insufficient_data", reason="缺少 2.5 球大小球水位", missing_inputs=["total_goals_2.5"])
            else:
                row = total_25[0]
                over = row.get("values", {}).get("over_water", [])
                under = row.get("values", {}).get("under_water", [])
                low = min(over[0], under[0]) if over and under else None
                if low is None:
                    event = _advisory_event(rule, status="insufficient_data", reason="2.5 球初始水位不完整", sources=total_25, missing_inputs=["opening_water"])
                elif low > rule.thresholds["initial_water_max"]:
                    event = _advisory_event(rule, status="not_triggered", reason="初始水位未处于守盘校验区间", sources=total_25, observations={"initial_min_water": low})
                elif not row.get("three_nodes"):
                    event = _advisory_event(rule, status="insufficient_data", reason="守盘提示需要同机构同档位三个精确节点", sources=total_25, observations={"initial_min_water": low}, missing_inputs=["three_exact_nodes"])
                else:
                    opposite_fall = min(row.get("changes", {}).get("over_water") or 0, row.get("changes", {}).get("under_water") or 0)
                    event = _advisory_event(rule, status="triggered" if opposite_fall <= -rule.thresholds["opposite_water_fall_min"] else "not_triggered", reason="初始低水与后续反向水位变化仅作为人工守盘校验提示", sources=total_25, observations={"initial_min_water": low, "minimum_water_change": opposite_fall})
        elif rule.advisory_id == "advisory-total-water-tier-v1":
            waters = {
                str(item["provider"]): float(item["values"]["over_water"][0])
                for item in total_25
                if item.get("values", {}).get("over_water")
            }
            if not waters:
                event = _advisory_event(rule, status="insufficient_data", reason="缺少 2.5 球大球水位", missing_inputs=["total_goals_2.5_over_water"])
            else:
                extreme = sorted(provider for provider, water in waters.items() if water <= rule.thresholds["extreme_over_water_max"])
                strong = sorted(provider for provider, water in waters.items() if water <= rule.thresholds["strong_over_water_max"])
                if extreme:
                    status, tier = "triggered", "extreme_control"
                elif strong:
                    status, tier = "triggered", "strong_control"
                else:
                    status, tier = "not_triggered", "balanced_or_higher"
                event = _advisory_event(rule, status=status, reason="2.5 球绝对水位分级提示，不生成进球区间或比分", sources=total_25, observations={"opening_over_water_by_provider": waters, "triggered_provider_ids": extreme or strong, "tier": tier})
        elif rule.advisory_id == "advisory-bracket-boundary-v1":
            by_key_25 = {(str(item.get("provider")), str(item.get("odds_format"))): item for item in total_25}
            by_key_30 = {(str(item.get("provider")), str(item.get("odds_format"))): item for item in total_30}
            pairs = [(key, by_key_25[key], by_key_30[key]) for key in sorted(set(by_key_25) & set(by_key_30))]
            if not pairs:
                event = _advisory_event(rule, status="insufficient_data", reason="夹击边界需要同时具备 2.5 与 3.0 球盘口", sources=[*total_25, *total_30], missing_inputs=["total_goals_2.5", "total_goals_3.0"])
            else:
                observations: dict[str, Any] = {}
                triggered_keys: list[str] = []
                for key, low_line, high_line in pairs:
                    low_values = low_line.get("values", {}).get("over_water", [])
                    high_values = high_line.get("values", {}).get("under_water", [])
                    if not low_values or not high_values:
                        continue
                    low_over, high_under = float(low_values[0]), float(high_values[0])
                    extreme = min(low_over, high_under) <= rule.thresholds["extreme_water_max"]
                    balanced = all(rule.thresholds["balanced_water_min"] <= value <= rule.thresholds["balanced_water_max"] for value in (low_over, high_under))
                    key_text = ":".join(key)
                    observations[key_text] = {"2.5_over": low_over, "3.0_under": high_under, "extreme_boundary": extreme, "balanced_boundary": balanced}
                    if extreme or balanced:
                        triggered_keys.append(key_text)
                if not observations:
                    event = _advisory_event(rule, status="insufficient_data", reason="夹击边界水位不完整", sources=[*total_25, *total_30], missing_inputs=["over_water", "under_water"])
                else:
                    observations["triggered_provider_formats"] = triggered_keys
                    event = _advisory_event(rule, status="triggered" if triggered_keys else "not_triggered", reason="夹击边界仅提示是否可人工使用夹击解释；不会收敛正式进球区间", sources=[*total_25, *total_30], observations=observations)
        elif rule.advisory_id == "advisory-draw-goals-link-v1":
            draw_primary = rankings.get("one_x_two", [None])[0] == "draw"
            event = _advisory_event(rule, status="triggered" if draw_primary else "not_triggered", reason="平局第一顺位仅要求人工复核大小球与比分关系，不新增或替换比分候选", observations={"official_draw_primary": draw_primary})
        elif rule.advisory_id == "advisory-environment-goals-v1":
            event = _advisory_event(rule, status="insufficient_data", reason="当前实验特征未冻结可追溯的天气与半中立场事实", missing_inputs=["weather_fact", "venue_context"])
        elif rule.advisory_id == "advisory-deep-line-over-trap-v1":
            event = _advisory_event(rule, status="insufficient_data", reason="深盘大球诱盘条件需要可追溯资金反向信号；当前资金归因固定为 unknown", sources=total_25, missing_inputs=["fund_flow"])
        elif rule.advisory_id == "advisory-head-provider-line-drop-v1":
            event = _advisory_event(rule, status="insufficient_data", reason="单头部机构降盘边界需要跨机构同档位精确让球与欧赔共识，当前提示输入未完整冻结", missing_inputs=["head_provider_cross_market_series"])
        else:
            required = ", ".join(rule.required_inputs)
            event = _advisory_event(rule, status="insufficient_data", reason="当前仓库未保存该提示所需的结构化外部事实", missing_inputs=rule.required_inputs, observations={"required_inputs": required})
        events.append(event)

    raw = {
        "schema_version": 1,
        "match_id": document.metadata.match_id,
        "competition_code": document.metadata.competition_code,
        "experiment_ruleset_version": receipt.experiment_ruleset_version,
        "proposal_sha256": receipt.proposal_sha256,
        "cutoff_at": receipt.as_of,
        "experiment_receipt_sha256": receipt.receipt_sha256,
        "official_outlook_sha256": official_hash,
        "feature_snapshot_sha256": _hash(features),
        "profile_chain": receipt.profile_chain,
        "events": [item.model_dump(mode="json") for item in events],
    }
    bundle = _finalize(ExperimentAdvisoryBundle, raw, "bundle_sha256")
    assert isinstance(bundle, ExperimentAdvisoryBundle)
    bundle_path = base / "experimental-advisories.yml"
    atomic_write_text(bundle_path, yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    triggered = {item.advisory_id for item in events if item.status == "triggered"}
    records = dispositions or []
    by_id = {item.advisory_id: item for item in records}
    if len(by_id) != len(records):
        raise ValueError("实验提示处置不得重复")
    if records and set(by_id) != triggered:
        raise ValueError(f"实验提示处置必须覆盖全部触发提示；缺少={sorted(triggered-set(by_id))} 多出={sorted(set(by_id)-triggered)}")
    disposition_path = base / "experimental-advisory-dispositions.yml"
    if records:
        atomic_write_text(disposition_path, yaml.safe_dump({"dispositions": [item.model_dump(mode="json") for item in records]}, allow_unicode=True, sort_keys=False))
    report = (
        f"# {document.metadata.home_team} VS {document.metadata.away_team} 实验提示\n\n"
        f"- 正式规则：football-analysis@{receipt.official_ruleset_version}\n"
        f"- 实验快照：football-analysis@{receipt.experiment_ruleset_version} / {receipt.proposal_sha256}\n"
        f"- 数据截止：{receipt.as_of.isoformat()}\n"
        f"- 正式结论不会受本报告影响。\n\n"
        "## 提示与警示\n\n"
        + "\n".join(f"- [{item.severity}] {item.advisory_id}: {item.status} / {item.reason}" for item in events)
        + "\n"
    )
    report_path = base / "experimental-advisories-report.md"
    atomic_write_text(report_path, report)
    return bundle_path, bundle, report_path


def freeze_experiment_prediction(root: Path, path: Path, official_candidate: Any) -> tuple[Path, ExperimentPredictionReceipt] | None:
    document = MatchDocument.load(path)
    base = root / "raw/matches" / document.metadata.match_id
    context_path = base / "experiment-analysis-receipt.yml"
    if not context_path.is_file():
        return None
    context = ExperimentAnalysisReceipt.model_validate(yaml.safe_load(context_path.read_text(encoding="utf-8")) or {})
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if now > document.metadata.kickoff_at:
        raise ValueError("比赛已开赛，禁止补建实验预测回执")
    outlook_path = base / "experimental-analysis-outlook.yml"
    reasons: list[str] = []
    status = "complete"
    outlook_hash = None
    dispositions_hash = None
    relative = None
    if not outlook_path.is_file():
        status = "insufficient_data"
        reasons.append("实验 Outlook 未生成或实验输入不足")
    else:
        outlook = ExperimentOutlook.model_validate(yaml.safe_load(outlook_path.read_text(encoding="utf-8")) or {})
        outlook_hash = outlook.outlook_sha256
        dispositions_hash = outlook.ai_dispositions_sha256
        relative = outlook_path.relative_to(root).as_posix()
    raw = {
        "schema_version": 1,
        "receipt_id": f"experiment-prediction-{official_candidate.receipt_id}",
        "match_id": document.metadata.match_id,
        "status": status,
        "prepared_at": now,
        "data_cutoff_at": official_candidate.data_cutoff_at,
        "kickoff_at": document.metadata.kickoff_at,
        "official_lock_candidate_id": official_candidate.receipt_id,
        "official_lock_candidate_sha256": official_candidate.receipt_sha256,
        "experiment_receipt_sha256": context.receipt_sha256,
        "experiment_outlook_sha256": outlook_hash,
        "ai_dispositions_sha256": dispositions_hash,
        "experiment_outlook_path": relative,
        "reasons": reasons,
    }
    receipt = _finalize(ExperimentPredictionReceipt, raw, "receipt_sha256")
    assert isinstance(receipt, ExperimentPredictionReceipt)
    target = base / "experiment-predictions" / f"{receipt.receipt_id}.yml"
    if target.is_file():
        existing = ExperimentPredictionReceipt.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
        if existing.receipt_sha256 != receipt.receipt_sha256:
            raise ValueError("同一正式候选已存在不同的实验预测回执")
        return target, existing
    ledger = root / EXPERIMENT_LEDGER
    with RepositoryTransaction(root, files=[target, ledger], directories=[], operation="freeze-experiment-prediction") as transaction:
        atomic_write_text(target, yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        append_payloads(
            ledger,
            [{"event_type": "experiment_prediction_frozen", "match_id": receipt.match_id, "receipt_id": receipt.receipt_id, "receipt_path": target.relative_to(root).as_posix(), "status": receipt.status}],
            recorded_at=now,
            actor="system",
            event_id_factory=lambda item, _: f"experiment:prediction:{receipt.receipt_id}",
        )
        transaction.commit()
    return target, receipt


def freeze_experiment_advisories(root: Path, path: Path, official_candidate: Any) -> tuple[Path, ExperimentAdvisoryReceipt] | None:
    document = MatchDocument.load(path)
    base = root / "raw/matches" / document.metadata.match_id
    context_path = base / "experiment-analysis-receipt.yml"
    if not context_path.is_file():
        return None
    context = ExperimentAnalysisReceipt.model_validate(yaml.safe_load(context_path.read_text(encoding="utf-8")) or {})
    if not context.applicable_advisory_ids:
        return None
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if now > document.metadata.kickoff_at:
        raise ValueError("比赛已开赛，禁止补建实验提示回执")
    bundle_path = base / "experimental-advisories.yml"
    status = "complete"
    reasons: list[str] = []
    bundle_hash = None
    dispositions_hash = None
    relative = None
    if not bundle_path.is_file():
        status = "insufficient_data"
        reasons.append("实验提示 Bundle 未生成")
    else:
        bundle = ExperimentAdvisoryBundle.model_validate(yaml.safe_load(bundle_path.read_text(encoding="utf-8")) or {})
        bundle_hash = bundle.bundle_sha256
        relative = bundle_path.relative_to(root).as_posix()
        triggered = {item.advisory_id for item in bundle.events if item.status == "triggered"}
        if any(item.status == "insufficient_data" for item in bundle.events):
            status = "insufficient_data"
            reasons.append("存在数据不足的实验提示")
        dispositions_path = base / "experimental-advisory-dispositions.yml"
        if triggered:
            if not dispositions_path.is_file():
                status = "insufficient_data"
                reasons.append("触发提示尚未完成人工处置")
            else:
                raw = yaml.safe_load(dispositions_path.read_text(encoding="utf-8")) or {}
                records = [ExperimentAdvisoryDisposition.model_validate(item) for item in raw.get("dispositions", [])]
                if {item.advisory_id for item in records} != triggered:
                    status = "insufficient_data"
                    reasons.append("提示人工处置不完整")
                else:
                    dispositions_hash = _hash([item.model_dump(mode="json") for item in records])
    raw = {
        "schema_version": 1,
        "receipt_id": f"experiment-advisory-{official_candidate.receipt_id}",
        "match_id": document.metadata.match_id,
        "status": status,
        "prepared_at": now,
        "data_cutoff_at": official_candidate.data_cutoff_at,
        "kickoff_at": document.metadata.kickoff_at,
        "official_lock_candidate_id": official_candidate.receipt_id,
        "official_lock_candidate_sha256": official_candidate.receipt_sha256,
        "experiment_receipt_sha256": context.receipt_sha256,
        "advisory_bundle_sha256": bundle_hash,
        "advisory_dispositions_sha256": dispositions_hash,
        "advisory_bundle_path": relative,
        "reasons": reasons,
    }
    receipt = _finalize(ExperimentAdvisoryReceipt, raw, "receipt_sha256")
    assert isinstance(receipt, ExperimentAdvisoryReceipt)
    target = base / "experiment-advisories" / f"{receipt.receipt_id}.yml"
    if target.is_file():
        existing = ExperimentAdvisoryReceipt.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
        if existing.receipt_sha256 != receipt.receipt_sha256:
            raise ValueError("同一正式候选已存在不同的实验提示回执")
        return target, existing
    ledger = root / EXPERIMENT_LEDGER
    with RepositoryTransaction(root, files=[target, ledger], directories=[], operation="freeze-experiment-advisory") as transaction:
        atomic_write_text(target, yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        append_payloads(
            ledger,
            [{"event_type": "experiment_advisory_frozen", "match_id": receipt.match_id, "receipt_id": receipt.receipt_id, "receipt_path": target.relative_to(root).as_posix(), "status": receipt.status}],
            recorded_at=now,
            actor="system",
            event_id_factory=lambda item, _: f"experiment:advisory:{receipt.receipt_id}",
        )
        transaction.commit()
    return target, receipt


def latest_experiment_advisory(root: Path, match_id: str) -> tuple[Path, ExperimentAdvisoryReceipt] | None:
    directory = root / "raw/matches" / match_id / "experiment-advisories"
    paths = sorted(directory.glob("*.yml")) if directory.is_dir() else []
    if not paths:
        return None
    loaded = [(path, ExperimentAdvisoryReceipt.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})) for path in paths]
    for _, receipt in loaded:
        if receipt.receipt_sha256 != _hash(_receipt_data(receipt)):
            raise ValueError("实验提示回执哈希无效")
    return max(loaded, key=lambda item: item[1].prepared_at)


def latest_experiment_prediction(root: Path, match_id: str) -> tuple[Path, ExperimentPredictionReceipt] | None:
    directory = root / "raw/matches" / match_id / "experiment-predictions"
    paths = sorted(directory.glob("*.yml")) if directory.is_dir() else []
    if not paths:
        return None
    loaded = [(path, ExperimentPredictionReceipt.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})) for path in paths]
    for _, receipt in loaded:
        if receipt.receipt_sha256 != _hash(_receipt_data(receipt)):
            raise ValueError("实验预测回执哈希无效")
    return max(loaded, key=lambda item: item[1].prepared_at)


def record_experiment_failure(
    root: Path,
    *,
    match_id: str,
    stage: str,
    reason: str,
    recorded_at: datetime,
) -> None:
    payload = {
        "event_type": "experiment_stage_failed",
        "match_id": match_id,
        "stage": stage,
        "reason": reason,
    }
    append_payloads(
        root / EXPERIMENT_LEDGER,
        [payload],
        recorded_at=recorded_at,
        actor="system",
        event_id_factory=lambda item, _: f"experiment:failure:{match_id}:{stage}:{_hash(item)[:16]}",
    )


def score_experiment_outcome(root: Path, path: Path) -> tuple[Path, ExperimentOutcome] | None:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.FINISHED, MatchStatus.REVIEWED} or not document.metadata.score:
        return None
    latest = latest_experiment_prediction(root, document.metadata.match_id)
    if latest is None or latest[1].status != "complete" or not latest[1].experiment_outlook_path:
        return None
    prediction_path, prediction = latest
    outlook = ExperimentOutlook.model_validate(yaml.safe_load((root / prediction.experiment_outlook_path).read_text(encoding="utf-8")) or {})
    total = int(document.metadata.total_goals or 0)
    score = str(document.metadata.score)
    primary_hit = outlook.final_primary_range[0] <= total <= outlook.final_primary_range[1]
    modal_hit = total in outlook.modal_goals
    tail_hit = any(left <= total <= right for left, right in outlook.tail_ranges)
    score_hit = score in outlook.score_candidates
    official_hit = document.metadata.settlement.total_goals_range_hit if document.metadata.settlement else None
    experiment_value = int(primary_hit) + int(score_hit)
    official_value = int(bool(official_hit)) + int(bool(document.metadata.settlement.score_candidate_hit if document.metadata.settlement else False))
    comparison = "experiment_better" if experiment_value > official_value else "official_better" if experiment_value < official_value else "same"
    adopted = {item.rule_id for item in outlook.dispositions if item.disposition == "adopted"}
    rule_results = {
        rule_id: "support" if primary_hit or tail_hit else "counterexample"
        for rule_id in adopted
    }
    for rule_id, status in outlook.event_statuses.items():
        rule_results.setdefault(rule_id, "not_applicable" if status == "not_applicable" else "ambiguous")
    now = document.metadata.result_recorded_at or datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    raw = {
        "schema_version": 1,
        "outcome_id": f"experiment-outcome-{prediction.receipt_id}",
        "match_id": document.metadata.match_id,
        "experiment_prediction_receipt_id": prediction.receipt_id,
        "experiment_prediction_receipt_sha256": prediction.receipt_sha256,
        "recorded_at": now,
        "final_score": score,
        "total_goals": total,
        "primary_range_hit": primary_hit,
        "modal_goal_hit": modal_hit,
        "tail_range_hit": tail_hit,
        "score_hit": score_hit,
        "official_primary_range_hit": official_hit,
        "comparison": comparison,
        "rule_results": rule_results,
        "key_events": document.metadata.key_events,
        "random_event_status": "unreviewed",
    }
    outcome = _finalize(ExperimentOutcome, raw, "outcome_sha256")
    assert isinstance(outcome, ExperimentOutcome)
    target = root / "raw/matches" / document.metadata.match_id / "experimental-outcome.yml"
    if target.is_file():
        existing = ExperimentOutcome.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
        if existing.outcome_sha256 == outcome.outcome_sha256:
            return target, existing
        raise ValueError("实验赛后评价已存在且内容不同，必须通过后续 supersedes 事件修正")
    atomic_write_text(target, yaml.safe_dump(outcome.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    append_payloads(
        root / EXPERIMENT_LEDGER,
        [{"event_type": "experiment_outcome_recorded", "match_id": outcome.match_id, "outcome_id": outcome.outcome_id, "outcome_path": target.relative_to(root).as_posix(), "comparison": outcome.comparison}],
        recorded_at=now,
        actor="system",
        event_id_factory=lambda item, _: f"experiment:outcome:{outcome.outcome_id}",
    )
    return target, outcome


def score_experiment_advisory_outcome(root: Path, path: Path) -> tuple[Path, ExperimentAdvisoryOutcome] | None:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.FINISHED, MatchStatus.REVIEWED} or not document.metadata.score:
        return None
    latest = latest_experiment_advisory(root, document.metadata.match_id)
    if latest is None or latest[1].status != "complete" or not latest[1].advisory_bundle_path:
        return None
    _, receipt = latest
    bundle = ExperimentAdvisoryBundle.model_validate(yaml.safe_load((root / receipt.advisory_bundle_path).read_text(encoding="utf-8")) or {})
    # Advisory events intentionally make no prediction. Their postmatch result
    # is therefore ambiguous until a later human research disposition exists.
    results = {
        item.advisory_id: "not_applicable" if item.status == "not_applicable" else "ambiguous"
        for item in bundle.events
    }
    now = document.metadata.result_recorded_at or datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    raw = {
        "schema_version": 1,
        "outcome_id": f"experiment-advisory-outcome-{receipt.receipt_id}",
        "match_id": document.metadata.match_id,
        "advisory_receipt_id": receipt.receipt_id,
        "advisory_receipt_sha256": receipt.receipt_sha256,
        "recorded_at": now,
        "final_score": str(document.metadata.score),
        "rule_results": results,
        "key_events": document.metadata.key_events,
        "random_event_status": "unreviewed",
    }
    outcome = _finalize(ExperimentAdvisoryOutcome, raw, "outcome_sha256")
    assert isinstance(outcome, ExperimentAdvisoryOutcome)
    target = root / "raw/matches" / document.metadata.match_id / "experimental-advisory-outcome.yml"
    if target.is_file():
        existing = ExperimentAdvisoryOutcome.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
        if existing.outcome_sha256 == outcome.outcome_sha256:
            return target, existing
        raise ValueError("实验提示赛后评价已存在且内容不同，必须通过后续 supersedes 事件修正")
    atomic_write_text(target, yaml.safe_dump(outcome.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    append_payloads(
        root / EXPERIMENT_LEDGER,
        [{"event_type": "experiment_advisory_outcome_recorded", "match_id": outcome.match_id, "outcome_id": outcome.outcome_id, "outcome_path": target.relative_to(root).as_posix()}],
        recorded_at=now,
        actor="system",
        event_id_factory=lambda item, _: f"experiment:advisory-outcome:{outcome.outcome_id}",
    )
    return target, outcome


def experiment_report(root: Path, version: str) -> dict[str, Any]:
    def belongs_to_version(path: Path) -> bool:
        receipt_path = path.parent / "experiment-analysis-receipt.yml"
        if not receipt_path.is_file():
            return False
        receipt = ExperimentAnalysisReceipt.model_validate(
            yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {}
        )
        return receipt.experiment_ruleset_version == version

    bundles = [
        path for path in (root / "raw/matches").glob("*/experiment-rule-evaluation-*.yml")
        if belongs_to_version(path)
    ]
    outcomes = [
        path for path in (root / "raw/matches").glob("*/experimental-outcome.yml")
        if belongs_to_version(path)
    ]
    advisory_bundles = [
        path for path in (root / "raw/matches").glob("*/experimental-advisories.yml")
        if belongs_to_version(path)
    ]
    advisory_outcomes = [
        path for path in (root / "raw/matches").glob("*/experimental-advisory-outcome.yml")
        if belongs_to_version(path)
    ]
    summary: dict[str, dict[str, int]] = {rule_id: defaultdict(int) for rule_id in EXPERIMENT_RULE_IDS}
    by_competition: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: {rule_id: defaultdict(int) for rule_id in EXPERIMENT_RULE_IDS}
    )
    provider_coverage: Counter[str] = Counter()
    profile_chains: Counter[str] = Counter()
    counterexamples: dict[str, list[str]] = defaultdict(list)
    for path in bundles:
        bundle = ExperimentEvaluationBundle.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        profile_chains[" -> ".join(bundle.profile_chain)] += 1
        for event in bundle.events:
            summary[event.rule_id][event.status] += 1
            by_competition[bundle.competition_code][event.rule_id][event.status] += 1
            for provider in event.source_provider_ids:
                provider_coverage[provider] += 1
        outlook_path = path.parent / "experimental-analysis-outlook.yml"
        if outlook_path.is_file():
            outlook = ExperimentOutlook.model_validate(yaml.safe_load(outlook_path.read_text(encoding="utf-8")) or {})
            for disposition in outlook.dispositions:
                summary[disposition.rule_id][disposition.disposition] += 1
                by_competition[bundle.competition_code][disposition.rule_id][disposition.disposition] += 1
    comparisons = Counter()
    for path in outcomes:
        outcome = ExperimentOutcome.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        comparisons[outcome.comparison] += 1
        for rule_id, result in outcome.rule_results.items():
            if rule_id in summary:
                summary[rule_id][result] += 1
                if result == "counterexample":
                    counterexamples[rule_id].append(outcome.match_id)
    advisory_summary: dict[str, dict[str, int]] = {rule_id: defaultdict(int) for rule_id in ADVISORY_RULE_IDS}
    for path in advisory_bundles:
        bundle = ExperimentAdvisoryBundle.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        disposition_path = path.parent / "experimental-advisory-dispositions.yml"
        disposition_data = yaml.safe_load(disposition_path.read_text(encoding="utf-8")) if disposition_path.is_file() else {}
        dispositions = {
            item.advisory_id: item.disposition
            for item in [
                ExperimentAdvisoryDisposition.model_validate(row)
                for row in (disposition_data or {}).get("dispositions", [])
            ]
        }
        for event in bundle.events:
            advisory_summary[event.advisory_id][event.status] += 1
            if event.advisory_id in dispositions:
                advisory_summary[event.advisory_id][f"disposition_{dispositions[event.advisory_id]}"] += 1
    for path in advisory_outcomes:
        outcome = ExperimentAdvisoryOutcome.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        for rule_id, result in outcome.rule_results.items():
            advisory_summary[rule_id][result] += 1
    return {
        "ruleset_version": version,
        "active": bool(active_experiment(root) and active_experiment(root).ruleset_version == version),
        "evaluated_matches": len({path.parent.name for path in bundles}),
        "scored_matches": len(outcomes),
        "comparisons": dict(comparisons),
        "rules": {rule_id: dict(values) for rule_id, values in summary.items()},
        "by_competition": {
            competition: {rule_id: dict(values) for rule_id, values in rules.items() if values}
            for competition, rules in by_competition.items()
        },
        "provider_coverage": dict(provider_coverage),
        "profile_chain_usage": dict(profile_chains),
        "counterexample_match_ids": dict(counterexamples),
        "advisories": {rule_id: dict(values) for rule_id, values in advisory_summary.items()},
        "automatic_promotion": False,
    }


def evaluate_live_experiment(root: Path, path: Path, event: LiveExperimentInput) -> tuple[Path, LiveExperimentReceipt]:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.LOCKED, MatchStatus.FINISHED, MatchStatus.REVIEWED}:
        raise ValueError("赛中实验要求比赛已有正式赛前锁定")
    if event.observed_at < document.metadata.kickoff_at:
        raise ValueError("赛中事件时间不能早于开赛")
    base = root / "raw/matches" / document.metadata.match_id
    experiment_path = base / "experimental-analysis-outlook.yml"
    if experiment_path.is_file():
        outlook = ExperimentOutlook.model_validate(yaml.safe_load(experiment_path.read_text(encoding="utf-8")) or {})
        primary = outlook.final_primary_range
    elif document.metadata.analysis_outlook and document.metadata.analysis_outlook.total_goals:
        primary = (document.metadata.analysis_outlook.total_goals.minimum, document.metadata.analysis_outlook.total_goals.maximum)
    else:
        raise ValueError("缺少可用的赛前总进球区间")
    home, away = map(int, event.score.split("-"))
    margin = abs(home - away)
    if event.event_type == "goal" and event.minute <= 20:
        candidate = (primary[0] + 1, primary[1] + 1)
        trigger, reason = "early-goal-upshift", "前20分钟进球，实验区间上调一级"
    elif margin >= 2 and event.weaker_side_counterattack_status == "limited":
        candidate = (max(0, primary[0] - 1), max(0, primary[1] - 1))
        trigger, reason = "two-goal-control", "两球领先且弱队反击受限，生成控节奏候选"
    else:
        candidate, trigger, reason = primary, "none", "未触发赛中实验规则"
    raw = {
        "schema_version": 1,
        "receipt_id": f"live-experiment-{document.metadata.match_id}-{event.observed_at:%Y%m%d%H%M%S}-{uuid4().hex[:8]}",
        "match_id": document.metadata.match_id,
        "observed_at": event.observed_at,
        "minute": event.minute,
        "score": event.score,
        "source_ref": event.source_ref,
        "base_primary_range": primary,
        "candidate_primary_range": candidate,
        "triggered_rule": trigger,
        "reason": reason,
    }
    receipt = _finalize(LiveExperimentReceipt, raw, "receipt_sha256")
    assert isinstance(receipt, LiveExperimentReceipt)
    target = base / "live-experiments" / f"{receipt.receipt_id}.yml"
    atomic_write_text(target, yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    return target, receipt
