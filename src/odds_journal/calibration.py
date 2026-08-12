from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    AnalysisDimension,
    AnalysisOutlook,
    CALIBRATION_RULE_IDS,
    CALIBRATION_RULE_IDS_V2,
    CALIBRATION_RULE_IDS_V3,
    CALIBRATION_RULE_IDS_V4,
    CandidateDisposition,
    CalibrationEvent,
    CalibrationMarketSummary,
    CalibrationSummary,
    FixedHandicapResult,
    MarketSnapshot,
    MatchMetadata,
    Selection,
)
from .rules import sha256_file


class CompetitionProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competition_codes: list[str] = Field(min_length=1)


class CalibrationRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    reliability: Literal["experimental"] = "experimental"
    thresholds: dict[str, float] = Field(default_factory=dict)
    allowed_values: dict[str, list[float]] = Field(default_factory=dict)
    scope: Literal["global", "low_stability", "korea"] = "global"
    effect: Literal[
        "ranking", "handicap_signal", "total_goals_pool", "score_pool", "outcome_risk_pool", "control"
    ] = "ranking"
    feature_ids: list[str] = Field(default_factory=list)
    evaluator_id: str | None = None
    target_market: str | None = None
    target_selection: str | None = None
    max_ranking_move: int = Field(default=0, ge=0, le=1)
    anchor_eligible: bool = False


class ComparisonPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_phases: list[Literal["opening", "mid", "late"]]
    late_window_minutes: int = Field(gt=0)
    asian_water_odds_format: Literal["hong_kong"]
    european_odds_format: Literal["decimal"]
    kelly_odds_format: Literal["kelly"]

    @model_validator(mode="after")
    def validate_phases(self) -> "ComparisonPolicyConfig":
        if self.required_phases != ["opening", "mid", "late"]:
            raise ValueError("校准比较阶段必须固定为 opening/mid/late")
        return self


class TotalGoalsEvidencePolicy(BaseModel):
    """Contract 7 guardrails for a directional total-goals conclusion."""

    model_config = ConfigDict(extra="forbid")

    anchor_min_exact_nodes: int = Field(default=3, ge=3)
    corroboration_min_exact_nodes: int = Field(default=3, ge=3)
    trend_purity_min: float = Field(default=0.67, ge=0, le=1)
    target_water_fall_min: float = Field(default=0.05, gt=0)


class FormalDraftPolicy(BaseModel):
    """Contract 8 thresholds for deterministic, market-scoped draft building."""

    model_config = ConfigDict(extra="forbid")

    eligible_provider_ids: list[str] = Field(min_length=2)
    one_x_two_min_providers: int = Field(default=3, ge=3)
    one_x_two_min_agreeing_providers: int = Field(default=2, ge=2)
    asian_min_providers: int = Field(default=2, ge=2)
    asian_min_agreeing_providers: int = Field(default=2, ge=2)
    asian_min_line_coverage: float = Field(default=0.5, ge=0.5, le=1)
    directional_probability_gap_min: float = Field(default=0.03, gt=0, le=1)

    @field_validator("eligible_provider_ids")
    @classmethod
    def unique_providers(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("正式草稿机构白名单不得重复")
        return value


class KnowledgeEnginePolicyV1(BaseModel):
    """Contract 9 知识引擎策略配置。

    匹配 calibration/football-analysis-v9.yml 的嵌套结构。
    各嵌套节为策略声明，用 dict 保持灵活性，model_validator 强制关键不变量。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[9] = 9
    profile_id: str = Field(min_length=1)
    ruleset_origin: Literal["proposal", "published"]
    formal_mode: Literal["disabled_until_release", "enabled"]

    knowledge_snapshot: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    reasoner: dict[str, Any] = Field(default_factory=dict)
    study: dict[str, Any] = Field(default_factory=dict)
    outbound: dict[str, Any] = Field(default_factory=dict)
    formal_isolation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_fixed_constraints(self) -> "KnowledgeEnginePolicyV1":
        if self.reasoner.get("ai_effect") != "advisory_only":
            raise ValueError("reasoner.ai_effect 必须为 advisory_only")
        if self.outbound.get("network") != "denied_by_default":
            raise ValueError("outbound.network 必须为 denied_by_default")
        if not self.formal_isolation.get("proposal_cannot_write_match"):
            raise ValueError("formal_isolation.proposal_cannot_write_match 必须为 true")
        if not self.formal_isolation.get("proposal_cannot_lock"):
            raise ValueError("formal_isolation.proposal_cannot_lock 必须为 true")
        if not self.formal_isolation.get("proposal_cannot_settle"):
            raise ValueError("formal_isolation.proposal_cannot_settle 必须为 true")
        if not self.formal_isolation.get("proposal_cannot_enter_official_statistics"):
            raise ValueError("formal_isolation.proposal_cannot_enter_official_statistics 必须为 true")
        return self


class CalibrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2, 3, 4, 7, 8]
    profile_id: Literal["low-stability-v1", "football-analysis-v2", "football-analysis-v3", "football-analysis-v4", "football-analysis-v7", "football-analysis-v8"]
    comparison_policy: ComparisonPolicyConfig
    competition_profiles: dict[str, CompetitionProfileConfig]
    recognized_providers: list[str]
    rules: list[CalibrationRuleConfig]
    profile_chains: dict[str, list[str]] = Field(default_factory=dict)
    total_goals_evidence_policy: TotalGoalsEvidencePolicy | None = None
    formal_draft_policy: FormalDraftPolicy | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "CalibrationConfig":
        ids = [item.rule_id for item in self.rules]
        expected = CALIBRATION_RULE_IDS_V4 if self.schema_version in {4, 7, 8} else CALIBRATION_RULE_IDS_V3 if self.schema_version in {2, 3} else CALIBRATION_RULE_IDS
        if len(ids) != len(set(ids)) or set(ids) != set(expected):
            raise ValueError(
                f"校准配置必须且只能定义 {len(expected)} 条契约 {self.schema_version} 规则"
            )
        codes = [
            code
            for profile in self.competition_profiles.values()
            for code in profile.competition_codes
        ]
        if len(codes) != len(set(codes)):
            raise ValueError("赛事代码不得同时属于多个校准 profile")
        if len(self.recognized_providers) != len(set(self.recognized_providers)):
            raise ValueError("认可机构列表不得重复")
        if self.schema_version == 3:
            by_id = {item.rule_id: item for item in self.rules}
            global_rules = {
                "draw-kelly-parity-v1", "deep-line-stable-cover-v1",
                "quarter-low-water-inducement-v1", "hidden-draw-away-cut-v1",
                "total-goals-cross-market-v1", "score-baseline-v1",
            }
            korea_rules = {"korea-goal-drop-v1", "korea-deep-line-loss-tolerance-v1"}
            if any(by_id[item].scope != "global" for item in global_rules):
                raise ValueError("六条通用规则必须使用 global scope")
            if any(by_id[item].scope != "korea" for item in korea_rules):
                raise ValueError("韩国规则必须使用 korea scope")
            if any(by_id[item].scope != "low_stability" for item in CALIBRATION_RULE_IDS):
                raise ValueError("lsl 规则必须使用 low_stability scope")
        if self.schema_version in {4, 7, 8}:
            by_id = {item.rule_id: item for item in self.rules}
            for item in CALIBRATION_RULE_IDS_V3:
                if not by_id[item].feature_ids or not by_id[item].evaluator_id:
                    raise ValueError(f"Contract 4 规则必须声明 feature_ids 和 evaluator_id：{item}")
            for item in (
                "trend-purity-v1", "provider-consensus-divergence-v1",
                "cross-dimension-netting-v1", "late-market-anomaly-v1", "single-kelly-value-guard-v1",
            ):
                if by_id[item].effect != "control" or not by_id[item].feature_ids:
                    raise ValueError(f"Contract 4 控制规则配置不完整：{item}")
            for profile, chain in self.profile_chains.items():
                if not chain or chain[-1] != profile or len(chain) != len(set(chain)):
                    raise ValueError("profile_chains 必须无环且以自身结束")
        if self.schema_version in {7, 8} and self.total_goals_evidence_policy is None:
            raise ValueError("Contract 7/8 必须声明 total_goals_evidence_policy")
        if self.schema_version not in {7, 8} and self.total_goals_evidence_policy is not None:
            raise ValueError("仅 Contract 7/8 支持 total_goals_evidence_policy")
        if self.schema_version == 8 and self.formal_draft_policy is None:
            raise ValueError("Contract 8 必须声明 formal_draft_policy")
        if self.schema_version != 8 and self.formal_draft_policy is not None:
            raise ValueError("仅 Contract 8 支持 formal_draft_policy")
        return self

    def profile_for(self, competition_code: str) -> str:
        for profile, config in self.competition_profiles.items():
            if competition_code in config.competition_codes:
                return profile
        return "global" if self.schema_version in {3, 4, 7, 8} else "not_applicable"

    def applicable_rule_ids(self, competition_code: str) -> list[str]:
        profile = self.profile_for(competition_code)
        applicable: list[str] = []
        for rule in self.rules:
            if rule.scope == "global" or (rule.scope == "low_stability" and profile in {"nor_eliteserien", "mls"}) or (rule.scope == "korea" and profile == "korea"):
                applicable.append(rule.rule_id)
        return applicable

    def profile_chain_for(self, competition_code: str) -> list[str]:
        profile = self.profile_for(competition_code)
        if self.schema_version not in {4, 7, 8}:
            return [profile]
        return list(self.profile_chains.get(profile, ["global", profile] if profile != "global" else ["global"]))

    def threshold(self, rule_id: str, name: str) -> float:
        rule = next(item for item in self.rules if item.rule_id == rule_id)
        try:
            return rule.thresholds[name]
        except KeyError as exc:
            raise ValueError(f"校准配置缺少阈值：{rule_id}.{name}") from exc

    def allowed(self, rule_id: str, name: str) -> list[float]:
        rule = next(item for item in self.rules if item.rule_id == rule_id)
        try:
            return rule.allowed_values[name]
        except KeyError as exc:
            raise ValueError(f"校准配置缺少允许值：{rule_id}.{name}") from exc


def load_calibration_config(path: Path, *, expected_sha256: str | None = None) -> CalibrationConfig | KnowledgeEnginePolicyV1:
    if expected_sha256 and sha256_file(path) != expected_sha256:
        raise ValueError("校准配置哈希不一致")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if data.get("calibration_contract_version") == 9 or data.get("schema_version") == 9:
        return KnowledgeEnginePolicyV1.model_validate(data)
    return CalibrationConfig.model_validate(data)


def _market(snapshot: MarketSnapshot) -> str:
    return str(snapshot.market)


def _phase(snapshot: MarketSnapshot) -> str:
    return str(snapshot.phase)


def _format(snapshot: MarketSnapshot) -> str:
    return str(snapshot.odds_format)


def _snapshots(
    metadata: MatchMetadata,
    market: str,
    provider: str,
    cutoff: datetime,
) -> list[MarketSnapshot]:
    return sorted(
        (
            item
            for item in metadata.market_snapshots
            if _market(item) == market
            and item.provider_id == provider
            and item.captured_at <= cutoff
            and item.captured_at <= metadata.kickoff_at
            and _phase(item) != "live"
        ),
        key=lambda item: (item.captured_at, item.snapshot_id),
    )


def _three_nodes(
    metadata: MatchMetadata,
    market: str,
    provider: str,
    odds_format: str,
    cutoff: datetime,
    late_window_minutes: int,
) -> tuple[list[MarketSnapshot] | None, str | None]:
    values = [
        item
        for item in _snapshots(metadata, market, provider, cutoff)
        if _format(item) == odds_format
    ]
    groups = {phase: [item for item in values if _phase(item) == phase] for phase in ("opening", "mid", "late")}
    if any(not groups[phase] for phase in groups):
        return None, "insufficient_data"
    selected = [groups["opening"][0], groups["mid"][-1], groups["late"][-1]]
    if selected[-1].captured_at < metadata.kickoff_at - timedelta(minutes=late_window_minutes):
        return None, "insufficient_data"
    if not (selected[0].captured_at < selected[1].captured_at < selected[2].captured_at):
        return None, "insufficient_data"
    return selected, None


def _number(snapshot: MarketSnapshot, key: str) -> float | None:
    value = snapshot.normalized_values.get(key)
    return float(value) if value is not None else None


def _delta(left: float, right: float) -> float:
    return round(left - right, 6)


def _identity(nodes: list[MarketSnapshot]) -> tuple[str | None, str | None]:
    opening = [_number(nodes[0], key) for key in ("home", "draw", "away")]
    late = [_number(nodes[-1], key) for key in ("home", "draw", "away")]
    if any(value is None for value in [*opening, *late]):
        return None, None
    labels = ("home", "draw", "away")
    opening_min = [index for index, value in enumerate(opening) if value == min(opening)]
    late_min = [index for index, value in enumerate(late) if value == min(late)]
    opening_max = [index for index, value in enumerate(opening) if value == max(opening)]
    late_max = [index for index, value in enumerate(late) if value == max(late)]
    favorite = labels[opening_min[0]] if len(opening_min) == len(late_min) == 1 and opening_min == late_min else None
    underdog = labels[opening_max[0]] if len(opening_max) == len(late_max) == 1 and opening_max == late_max else None
    return favorite, underdog


def _full_ranking(values: list[str], allowed: tuple[str, ...]) -> list[str]:
    return [*values, *(item for item in allowed if item not in values)]


def _promote_once(ranking: list[str], target: str) -> list[str]:
    result = list(ranking)
    index = result.index(target)
    if index > 1:
        result[index - 1], result[index] = result[index], result[index - 1]
    return result


def _same_line_run(
    snapshots: list[MarketSnapshot], depths: list[float], start: int
) -> list[MarketSnapshot]:
    target = depths[start]
    output: list[MarketSnapshot] = []
    for snapshot, depth in zip(snapshots[start:], depths[start:]):
        if depth != target:
            break
        output.append(snapshot)
    return output


def _base_event(
    rule_id: str,
    market: str,
    target: str,
    ranking: list[str],
    dimensions: list[str],
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "reliability": "experimental",
        "triggered": False,
        "not_triggered_reason": "threshold_not_met",
        "target_market": market,
        "target_selection": target,
        "source_dimensions": dimensions,
        "source_provider_ids": [],
        "source_snapshot_ids": [],
        "correlation_keys": [],
        "threshold_observations": {},
        "before_ranking": ranking,
        "proposed_ranking": ranking,
        "final_ranking": ranking,
        "adjustment_level": 0,
        "primary_changed": False,
        "supporting_evidence": [],
        "counter_evidence": [],
    }


def _trigger(
    raw: dict[str, Any],
    *,
    providers: list[str],
    snapshots: list[MarketSnapshot],
    observations: dict[str, Any],
    correlation_keys: list[str] | None = None,
) -> CalibrationEvent:
    observations = {
        **observations,
        "snapshots": [
            {
                "snapshot_id": item.snapshot_id,
                "raw_values": item.raw_values,
                "normalized_values": item.normalized_values,
            }
            for item in snapshots
        ],
    }
    raw.update(
        {
            "triggered": True,
            "not_triggered_reason": None,
            "source_provider_ids": list(dict.fromkeys(providers)),
            "source_snapshot_ids": list(dict.fromkeys(item.snapshot_id for item in snapshots)),
            "correlation_keys": correlation_keys or [],
            "threshold_observations": observations,
            "proposed_ranking": _promote_once(raw["before_ranking"], raw["target_selection"]),
            "final_ranking": raw["before_ranking"],
            "adjustment_level": 1,
            "supporting_evidence": [f"{raw['rule_id']} 刚性阈值已满足"],
            "counter_evidence": ["实验规则只校准权重，不单独构成第一顺位换位依据"],
        }
    )
    return CalibrationEvent.model_validate(raw)


def _not_triggered(raw: dict[str, Any], reason: str, **observations: Any) -> CalibrationEvent:
    raw["not_triggered_reason"] = reason
    raw["threshold_observations"] = observations
    return CalibrationEvent.model_validate(raw)


def _new_experimental_events(
    metadata: MatchMetadata,
    config: CalibrationConfig,
    profile: str,
    one_baseline: list[str],
    fixed_baseline: list[str],
    *,
    cutoff: datetime,
    favorite: str | None,
    fixed_favorite: str,
) -> list[CalibrationEvent]:
    """Evaluate the 1.3.0 additions conservatively.

    These rules are deliberately bounded: missing or ambiguous snapshots produce
    an explicit non-triggered event, and no rule can change the anchor alone.
    """
    events: list[CalibrationEvent] = []

    def add_not(rule_id: str, market: str, target: str, baseline: list[str], reason: str, **obs: Any) -> None:
        raw = _base_event(rule_id, market, target, baseline, [])
        events.append(_not_triggered(raw, reason, **obs))

    def add_trigger(
        rule_id: str,
        market: str,
        target: str,
        baseline: list[str],
        dimensions: list[str],
        providers: list[str],
        snapshots: list[MarketSnapshot],
        observations: dict[str, Any],
        correlation_keys: list[str] | None = None,
    ) -> None:
        raw = _base_event(rule_id, market, target, baseline, dimensions)
        events.append(_trigger(raw, providers=providers, snapshots=snapshots, observations=observations, correlation_keys=correlation_keys))

    kelly, kelly_error = _three_nodes(
        metadata, "kelly_index", "macau", config.comparison_policy.kelly_odds_format,
        cutoff, config.comparison_policy.late_window_minutes,
    )
    if kelly_error or kelly is None:
        add_not("draw-kelly-parity-v1", "one_x_two", Selection.DRAW.value, one_baseline, "insufficient_data")
    else:
        late = [_number(kelly[-1], key) for key in ("home", "draw", "away")]
        if any(value is None for value in late):
            add_not("draw-kelly-parity-v1", "one_x_two", Selection.DRAW.value, one_baseline, "insufficient_data")
        else:
            spread = max(late) - min(late)
            threshold = config.threshold("draw-kelly-parity-v1", "kelly_spread_parity")
            if spread <= threshold:
                add_trigger("draw-kelly-parity-v1", "one_x_two", Selection.DRAW.value, one_baseline,
                            [AnalysisDimension.KELLY_INDEX.value], ["macau"], kelly,
                            {"kelly_spread": spread, "threshold": threshold, "operator": "<="},
                            ["macau:kelly"])
            else:
                add_not("draw-kelly-parity-v1", "one_x_two", Selection.DRAW.value, one_baseline,
                        "threshold_not_met", kelly_spread=spread, threshold=threshold)

    asian, asian_error = _three_nodes(
        metadata, "asian_handicap", "macau", config.comparison_policy.asian_water_odds_format,
        cutoff, config.comparison_policy.late_window_minutes,
    )
    depth = [_number(item, "home_line") for item in asian] if asian else []
    water_key = f"{favorite}_water" if favorite in {"home", "away"} else None
    water = [_number(item, water_key) for item in asian] if asian and water_key else []
    stable_deep = bool(
        not asian_error and asian and depth and all(value is not None for value in depth)
        and min(abs(value) for value in depth) >= config.threshold("deep-line-stable-cover-v1", "minimum_line_depth")
        and len(set(depth)) == 1 and water and all(value is not None for value in water)
        and water[-1] <= config.threshold("deep-line-stable-cover-v1", "half_line_water_max")
    )
    if stable_deep:
        add_trigger("deep-line-stable-cover-v1", "fixed_handicap_1x2", fixed_favorite, fixed_baseline,
                    [AnalysisDimension.ASIAN_HANDICAP_MARKET.value], ["macau"], asian,
                    {"line_depth": abs(depth[-1]), "late_water": water[-1], "operator": "<="},
                    ["macau:asian-stable-line"])
    else:
        add_not("deep-line-stable-cover-v1", "fixed_handicap_1x2", fixed_favorite, fixed_baseline, "threshold_not_met")

    quarter = bool(asian and not asian_error and depth and abs(depth[-1] or 0) in {0.25, 0.5})
    if quarter and water and water[-1] is not None and water[-1] <= config.threshold("quarter-low-water-inducement-v1", "half_line_water_max"):
        add_trigger("quarter-low-water-inducement-v1", "fixed_handicap_1x2", FixedHandicapResult.HANDICAP_AWAY.value,
                    fixed_baseline, [AnalysisDimension.ASIAN_HANDICAP_MARKET.value, AnalysisDimension.EUROPEAN_ODDS.value],
                    ["macau"], asian, {"line_depth": abs(depth[-1]), "late_water": water[-1]}, ["macau:quarter-low-water"])
    else:
        add_not("quarter-low-water-inducement-v1", "fixed_handicap_1x2", FixedHandicapResult.HANDICAP_AWAY.value, fixed_baseline, "threshold_not_met")

    euro, euro_error = _three_nodes(
        metadata, "european_odds", "macau", config.comparison_policy.european_odds_format,
        cutoff, config.comparison_policy.late_window_minutes,
    )
    if euro_error or kelly_error or euro is None or kelly is None:
        add_not("hidden-draw-away-cut-v1", "one_x_two", Selection.DRAW.value, one_baseline, "insufficient_data")
    else:
        away_open, away_late = _number(euro[0], "away"), _number(euro[-1], "away")
        draw_values = [_number(item, "draw") for item in euro]
        away_kelly = _number(kelly[-1], "away")
        fall = (away_open - away_late) / away_open if away_open and away_late is not None else None
        draw_range = max(draw_values) - min(draw_values) if all(value is not None for value in draw_values) else None
        trigger = bool(
            fall is not None and fall >= config.threshold("hidden-draw-away-cut-v1", "away_odds_fall_min")
            and away_kelly is not None
            and config.threshold("hidden-draw-away-cut-v1", "kelly_min") <= away_kelly <= config.threshold("hidden-draw-away-cut-v1", "kelly_max")
            and draw_range is not None and draw_range <= config.threshold("hidden-draw-away-cut-v1", "draw_range_max")
        )
        if trigger:
            add_trigger("hidden-draw-away-cut-v1", "one_x_two", Selection.DRAW.value, one_baseline,
                        [AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.KELLY_INDEX.value], ["macau"], [*euro, *kelly],
                        {"away_odds_fall": fall, "draw_range": draw_range, "away_kelly": away_kelly}, ["macau:hidden-draw"])
        else:
            add_not("hidden-draw-away-cut-v1", "one_x_two", Selection.DRAW.value, one_baseline, "threshold_not_met", away_odds_fall=fall, draw_range=draw_range, away_kelly=away_kelly)

    total, total_error = _three_nodes(
        metadata, "total_goals", "macau", config.comparison_policy.asian_water_odds_format,
        cutoff, config.comparison_policy.late_window_minutes,
    )
    over_values = [_number(item, "over_water") for item in total] if total else []
    total_trigger = bool(
        not total_error and total and over_values and all(value is not None for value in over_values)
        and over_values[-1] <= config.threshold("total-goals-cross-market-v1", "over_water_max")
        and over_values[0] - over_values[-1] >= config.threshold("total-goals-cross-market-v1", "over_water_fall_min")
    )
    if total_trigger:
        add_trigger("total-goals-cross-market-v1", "fixed_handicap_1x2", fixed_favorite, fixed_baseline,
                    [AnalysisDimension.TOTAL_GOALS_MARKET.value], ["macau"], total,
                    {"over_water": over_values[-1], "water_fall": over_values[0] - over_values[-1]}, ["macau:total-goals"])
    else:
        add_not("total-goals-cross-market-v1", "fixed_handicap_1x2", fixed_favorite, fixed_baseline, "threshold_not_met")

    home_value = _number(euro[-1], "home") if euro else None
    if home_value is not None and home_value <= config.threshold("score-baseline-v1", "home_odds_max"):
        add_trigger("score-baseline-v1", "one_x_two", Selection.HOME.value, one_baseline,
                    [AnalysisDimension.EUROPEAN_ODDS.value], ["macau"], euro,
                    {"home_odds": home_value, "operator": "<="}, ["macau:score-baseline"])
    else:
        add_not("score-baseline-v1", "one_x_two", Selection.HOME.value, one_baseline, "threshold_not_met", home_odds=home_value)

    korea_rules = ("korea-goal-drop-v1", "korea-deep-line-loss-tolerance-v1")
    for rule_id in korea_rules:
        if profile != "korea":
            add_not(rule_id, "fixed_handicap_1x2", fixed_favorite, fixed_baseline, "not_applicable")
        elif rule_id == "korea-goal-drop-v1" and total_trigger:
            add_trigger(rule_id, "fixed_handicap_1x2", fixed_favorite, fixed_baseline,
                        [AnalysisDimension.TOTAL_GOALS_MARKET.value], ["macau"], total,
                        {"over_water_fall": over_values[0] - over_values[-1]}, ["macau:korea-goal-drop"])
        elif rule_id == "korea-deep-line-loss-tolerance-v1" and stable_deep:
            add_trigger(rule_id, "fixed_handicap_1x2", FixedHandicapResult.HANDICAP_AWAY.value, fixed_baseline,
                        [AnalysisDimension.ASIAN_HANDICAP_MARKET.value], ["macau"], asian,
                        {"line_depth": abs(depth[-1])}, ["macau:korea-deep-line"])
        else:
            add_not(rule_id, "fixed_handicap_1x2", fixed_favorite, fixed_baseline, "threshold_not_met")
    return events


def _v3_ranking(outlook: AnalysisOutlook, market: str) -> list[str]:
    assert outlook.baseline_summary_v3 is not None
    return list(outlook.baseline_summary_v3.markets[market].ranking)


def _v3_event(
    rule_id: str,
    *,
    applicable: bool,
    effect: str,
    target_market: str | None,
    target_selection: str,
    ranking: list[str] | None = None,
    triggered: bool = False,
    reason: str = "threshold_not_met",
    dimensions: list[str] | None = None,
    snapshots: list[MarketSnapshot] | None = None,
    observations: dict[str, Any] | None = None,
    correlation_keys: list[str] | None = None,
) -> CalibrationEvent:
    if not applicable:
        return CalibrationEvent(
            rule_id=rule_id,
            contract_version=3,
            triggered=False,
            not_triggered_reason="not_applicable",
            applicability="not_applicable",
            effect=effect,
            target_selection=target_selection,
            before_ranking=[],
            proposed_ranking=[],
            final_ranking=[],
            adjustment_level=0,
        )
    baseline = ranking or []
    proposed = _promote_once(baseline, target_selection) if triggered and effect == "ranking" else baseline
    values: dict[str, Any] = {
        "rule_id": rule_id,
        "contract_version": 3,
        "triggered": triggered,
        "not_triggered_reason": None if triggered else reason,
        "applicability": "applicable",
        "effect": effect,
        "target_market": target_market,
        "target_selection": target_selection,
        "source_dimensions": dimensions or [],
        "source_provider_ids": list(dict.fromkeys(item.provider_id for item in (snapshots or []))),
        "source_snapshot_ids": list(dict.fromkeys(item.snapshot_id for item in (snapshots or []))),
        "correlation_keys": correlation_keys or [],
        "threshold_observations": observations or {},
        "before_ranking": baseline,
        "proposed_ranking": proposed,
        "final_ranking": baseline,
        "adjustment_level": 1 if triggered and effect == "ranking" else 0,
        "supporting_evidence": [f"{rule_id} 刚性阈值已满足"] if triggered else [],
        "counter_evidence": ["实验规则不能单独推翻基础第一顺位"] if triggered else [],
        "decision": CandidateDisposition(disposition="adopted") if triggered else None,
    }
    return CalibrationEvent.model_validate(values)


def _v3_nodes(
    metadata: MatchMetadata, config: CalibrationConfig, market: str, provider: str, odds_format: str, cutoff: datetime
) -> list[MarketSnapshot] | None:
    nodes, _ = _three_nodes(metadata, market, provider, odds_format, cutoff, config.comparison_policy.late_window_minutes)
    return nodes


def _evaluate_calibration_v3(
    metadata: MatchMetadata,
    outlook: AnalysisOutlook,
    config: CalibrationConfig,
    *,
    cutoff: datetime,
) -> tuple[str, list[CalibrationEvent], None]:
    if outlook.schema_version != 3 or outlook.baseline_summary_v3 is None:
        raise ValueError("calibration contract 3 必须使用 AnalysisOutlook V3")
    profile = config.profile_for(metadata.competition_code)
    rules = {item.rule_id: item for item in config.rules}
    applicable = set(config.applicable_rule_ids(metadata.competition_code))
    euro = _v3_nodes(metadata, config, "european_odds", "macau", config.comparison_policy.european_odds_format, cutoff)
    kelly = _v3_nodes(metadata, config, "kelly_index", "macau", config.comparison_policy.kelly_odds_format, cutoff)
    asian = _v3_nodes(metadata, config, "asian_handicap", "macau", config.comparison_policy.asian_water_odds_format, cutoff)
    total = _v3_nodes(metadata, config, "total_goals", "macau", config.comparison_policy.asian_water_odds_format, cutoff)
    favorite, _ = _identity(euro) if euro else (None, None)
    one_rank = _v3_ranking(outlook, "one_x_two")
    fixed_rank = _v3_ranking(outlook, "fixed_handicap_1x2")
    asian_rank = _v3_ranking(outlook, "asian_handicap")
    total_rank = _v3_ranking(outlook, "total_goals")
    events: list[CalibrationEvent] = []

    def emit(rule_id: str, effect: str, market: str | None, selection: str, ranking: list[str], ok: bool, *, dimensions: list[str], snapshots: list[MarketSnapshot] | None, observations: dict[str, Any], reason: str = "threshold_not_met", correlation: list[str] | None = None) -> None:
        events.append(_v3_event(
            rule_id,
            applicable=rule_id in applicable,
            effect=effect,
            target_market=market,
            target_selection=selection,
            ranking=ranking,
            triggered=ok and rule_id in applicable,
            reason=reason if rule_id in applicable else "not_applicable",
            dimensions=dimensions if ok else [],
            snapshots=snapshots if ok else [],
            observations=observations,
            correlation_keys=correlation,
        ))

    # Global 1: three-way Kelly parity.
    values = [_number(kelly[-1], item) for item in ("home", "draw", "away")] if kelly else []
    spread = max(values) - min(values) if values and all(item is not None for item in values) else None
    threshold = config.threshold("draw-kelly-parity-v1", "kelly_spread_parity")
    emit("draw-kelly-parity-v1", "ranking", "one_x_two", Selection.DRAW.value, one_rank,
         spread is not None and spread <= threshold,
         dimensions=[AnalysisDimension.KELLY_INDEX.value], snapshots=kelly,
         observations={"kelly_spread": spread, "threshold": threshold, "operator": "<="},
         reason="insufficient_data" if spread is None else "threshold_not_met")

    # Global 2: stable deep-line branches.
    water_key = f"{favorite}_water" if favorite in {"home", "away"} else None
    depths = [_number(item, "home_line") for item in asian] if asian else []
    waters = [_number(item, water_key) for item in asian] if asian and water_key else []
    depths_ok = bool(depths and all(item is not None for item in depths) and len(set(depths)) == 1)
    waters_ok = bool(waters and all(item is not None for item in waters))
    depth = abs(float(depths[-1])) if depths_ok else None
    deep_band = bool(depths_ok and waters_ok and depth is not None and depth >= rules["deep-line-stable-cover-v1"].thresholds["minimum_line_depth"] and all(rules["deep-line-stable-cover-v1"].thresholds["deep_water_min"] <= item <= rules["deep-line-stable-cover-v1"].thresholds["deep_water_max"] for item in waters))
    half_one = bool(depths_ok and waters_ok and depth == rules["deep-line-stable-cover-v1"].thresholds["half_one_line"] and all(right <= left for left, right in zip(waters, waters[1:])) and any(right < left for left, right in zip(waters, waters[1:])) and waters[-1] <= rules["deep-line-stable-cover-v1"].thresholds["half_line_water_max"])
    favorite_handicap = Selection.HOME_HANDICAP.value if favorite == "home" else Selection.AWAY_HANDICAP.value
    emit("deep-line-stable-cover-v1", "handicap_signal", "asian_handicap", favorite_handicap, asian_rank,
         deep_band or half_one, dimensions=[AnalysisDimension.ASIAN_HANDICAP_MARKET.value], snapshots=asian,
         observations={"line_depth": depth, "waters": waters, "deep_band": deep_band, "half_one": half_one},
         reason="insufficient_data" if not (depths_ok and waters_ok) else "threshold_not_met")

    # Global 3: low-water needs both European divergence and Kelly non-advantage.
    euro_fav = [_number(item, favorite) for item in euro] if euro and favorite else []
    kelly_late = [_number(kelly[-1], item) for item in ("home", "draw", "away")] if kelly else []
    kelly_spread = max(kelly_late) - min(kelly_late) if kelly_late and all(item is not None for item in kelly_late) else None
    shallow = bool(depths_ok and depth in set(rules["quarter-low-water-inducement-v1"].allowed_values["line_depths"]))
    quarter_ok = bool(shallow and waters_ok and waters[-1] <= rules["quarter-low-water-inducement-v1"].thresholds["half_line_water_max"] and all(right <= left for left, right in zip(waters, waters[1:])) and euro_fav and all(item is not None for item in euro_fav) and euro_fav[-1] > euro_fav[0] and kelly_spread is not None and kelly_spread <= rules["quarter-low-water-inducement-v1"].thresholds["kelly_spread_max"])
    emit("quarter-low-water-inducement-v1", "outcome_risk_pool", "handicap", favorite_handicap, asian_rank,
         quarter_ok, dimensions=[AnalysisDimension.ASIAN_HANDICAP_MARKET.value, AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.KELLY_INDEX.value], snapshots=[*(asian or []), *(euro or []), *(kelly or [])],
         observations={"line_depth": depth, "late_water": waters[-1] if waters_ok else None, "euro_open": euro_fav[0] if euro_fav else None, "euro_late": euro_fav[-1] if euro_fav else None, "kelly_spread": kelly_spread},
         reason="insufficient_data" if not (asian and euro and kelly and favorite) else "threshold_not_met", correlation=["macau:odds-kelly"])

    # Global 4: away cut while draw remains stable.
    away_fall = draw_range = draw_kelly_range = away_kelly = None
    if euro and kelly:
        away_open, away_late = _number(euro[0], "away"), _number(euro[-1], "away")
        draw_values = [_number(item, "draw") for item in euro]
        draw_kelly = [_number(item, "draw") for item in kelly]
        away_kelly = _number(kelly[-1], "away")
        if away_open and away_late is not None and all(item is not None for item in draw_values) and all(item is not None for item in draw_kelly):
            away_fall = (away_open - away_late) / away_open
            draw_range = (max(draw_values) - min(draw_values)) / draw_values[0]
            draw_kelly_range = max(draw_kelly) - min(draw_kelly)
    hidden_ok = bool(away_fall is not None and away_fall >= rules["hidden-draw-away-cut-v1"].thresholds["away_odds_fall_min"] and away_kelly is not None and rules["hidden-draw-away-cut-v1"].thresholds["kelly_min"] <= away_kelly <= rules["hidden-draw-away-cut-v1"].thresholds["kelly_max"] and draw_range is not None and draw_range <= rules["hidden-draw-away-cut-v1"].thresholds["draw_range_max"] and draw_kelly_range is not None and draw_kelly_range <= rules["hidden-draw-away-cut-v1"].thresholds["draw_kelly_range_max"])
    emit("hidden-draw-away-cut-v1", "ranking", "one_x_two", Selection.DRAW.value, one_rank,
         hidden_ok, dimensions=[AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.KELLY_INDEX.value], snapshots=[*(euro or []), *(kelly or [])],
         observations={"away_fall": away_fall, "away_kelly": away_kelly, "draw_range": draw_range, "draw_kelly_range": draw_kelly_range},
         reason="insufficient_data" if not (euro and kelly) else "threshold_not_met", correlation=["macau:odds-kelly"])

    # Global 5: total-goals movement is confined to total-goals candidates.
    over = [_number(item, "over_water") for item in total] if total else []
    total_line = _number(total[-1], "line") if total else None
    monotonic_over = bool(over and all(item is not None for item in over) and all(right <= left for left, right in zip(over, over[1:])))
    over_fall = over[0] - over[-1] if monotonic_over else None
    favorite_odds = euro_fav[-1] if euro_fav else None
    deep_branch = bool(depth is not None and depth >= rules["total-goals-cross-market-v1"].thresholds["deep_line_min"] and favorite_odds is not None and favorite_odds <= rules["total-goals-cross-market-v1"].thresholds["deep_favorite_odds_max"])
    shallow_branch = bool(depth is not None and depth <= rules["total-goals-cross-market-v1"].thresholds["shallow_line_max"] and favorite_odds is not None and favorite_odds >= rules["total-goals-cross-market-v1"].thresholds["shallow_favorite_odds_min"])
    total_ok = bool(monotonic_over and total_line is not None and total_line <= rules["total-goals-cross-market-v1"].thresholds["total_line_max"] and over[-1] <= rules["total-goals-cross-market-v1"].thresholds["over_water_max"] and over_fall is not None and over_fall >= rules["total-goals-cross-market-v1"].thresholds["over_water_fall_min"] and (deep_branch or shallow_branch))
    emit("total-goals-cross-market-v1", "total_goals_pool", "total_goals", Selection.OVER.value if deep_branch else Selection.UNDER.value, total_rank,
         total_ok, dimensions=[AnalysisDimension.TOTAL_GOALS_MARKET.value, AnalysisDimension.ASIAN_HANDICAP_MARKET.value, AnalysisDimension.EUROPEAN_ODDS.value], snapshots=[*(total or []), *(asian or []), *(euro or [])],
         observations={"total_line": total_line, "over_water": over[-1] if over else None, "over_fall": over_fall, "deep_branch": deep_branch, "shallow_branch": shallow_branch},
         reason="insufficient_data" if not (total and asian and euro and favorite) else "threshold_not_met")

    # Global 6: score coverage never modifies a market ranking.
    home_odds = _number(euro[-1], "home") if euro else None
    shallow_score = bool(depth is not None and depth <= rules["score-baseline-v1"].thresholds["shallow_line_max"] and favorite_odds is not None and favorite_odds < rules["score-baseline-v1"].thresholds["shallow_favorite_odds_max"])
    score_ok = bool((home_odds is not None and home_odds <= rules["score-baseline-v1"].thresholds["home_odds_max"]) or shallow_score)
    emit("score-baseline-v1", "score_pool", "one_x_two", Selection.HOME.value if home_odds is not None and home_odds <= rules["score-baseline-v1"].thresholds["home_odds_max"] else favorite or Selection.HOME.value, one_rank,
         score_ok, dimensions=[AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.ASIAN_HANDICAP_MARKET.value], snapshots=[*(euro or []), *(asian or [])],
         observations={"home_odds": home_odds, "line_depth": depth, "shallow_score": shallow_score},
         reason="insufficient_data" if not euro else "threshold_not_met")

    # Korean overlays.
    korea_drop = bool(monotonic_over and over_fall is not None and over_fall >= rules["korea-goal-drop-v1"].thresholds["over_water_fall_min"])
    emit("korea-goal-drop-v1", "total_goals_pool", "total_goals", Selection.OVER.value, total_rank,
         korea_drop, dimensions=[AnalysisDimension.TOTAL_GOALS_MARKET.value], snapshots=total,
         observations={"over_fall": over_fall, "operator": ">=", "threshold": rules["korea-goal-drop-v1"].thresholds["over_water_fall_min"]},
         reason="insufficient_data" if not total else "threshold_not_met")
    home_water = [_number(item, "home_water") for item in asian] if asian else []
    home_euro = [_number(item, "home") for item in euro] if euro else []
    home_kelly = [_number(item, "home") for item in kelly] if kelly else []
    korea_loss = bool(depths_ok and depths[-1] <= -rules["korea-deep-line-loss-tolerance-v1"].thresholds["minimum_line_depth"] and home_water and all(item is not None for item in home_water) and home_water[-1] >= rules["korea-deep-line-loss-tolerance-v1"].thresholds["high_water_min"] and home_euro and home_kelly and all(item is not None for item in [*home_euro, *home_kelly]) and home_euro[0] - home_euro[-1] >= rules["korea-deep-line-loss-tolerance-v1"].thresholds["reverse_delta_min"] and home_kelly[-1] - home_kelly[0] >= rules["korea-deep-line-loss-tolerance-v1"].thresholds["reverse_delta_min"])
    emit("korea-deep-line-loss-tolerance-v1", "outcome_risk_pool", "one_x_two", Selection.AWAY.value, one_rank,
         korea_loss, dimensions=[AnalysisDimension.ASIAN_HANDICAP_MARKET.value, AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.KELLY_INDEX.value], snapshots=[*(asian or []), *(euro or []), *(kelly or [])],
         observations={"home_line": depths[-1] if depths_ok else None, "home_water": home_water[-1] if home_water else None, "euro_delta": home_euro[0] - home_euro[-1] if home_euro and all(item is not None for item in home_euro) else None, "kelly_delta": home_kelly[-1] - home_kelly[0] if home_kelly and all(item is not None for item in home_kelly) else None},
         reason="insufficient_data" if not (asian and euro and kelly) else "threshold_not_met", correlation=["macau:odds-kelly"])

    # Reuse the established V1/V2 calculation for LSL predicates, then convert
    # the events into contract 3 envelopes.  This keeps their threshold logic
    # stable while making the profile scope explicit.
    if profile in {"nor_eliteserien", "mls"}:
        legacy_data = config.model_dump(mode="python")
        legacy_data.update({"schema_version": 2, "profile_id": "football-analysis-v2"})
        legacy = CalibrationConfig.model_validate(legacy_data)
        _, legacy_events, _ = evaluate_calibration(metadata, outlook, legacy, cutoff=cutoff)
        for item in legacy_events:
            if item.rule_id not in CALIBRATION_RULE_IDS:
                continue
            events.append(CalibrationEvent.model_validate({
                **item.model_dump(mode="json"),
                "contract_version": 3,
                "applicability": "applicable",
                "effect": "ranking",
                "target_market": item.target_market,
                "decision": CandidateDisposition(disposition="adopted").model_dump(mode="json") if item.triggered else None,
            }))
    else:
        for rule_id in CALIBRATION_RULE_IDS:
            rule = rules[rule_id]
            events.append(_v3_event(rule_id, applicable=False, effect=rule.effect, target_market=None, target_selection="not_applicable"))
    return profile, events, None


def evaluate_calibration(
    metadata: MatchMetadata,
    outlook: AnalysisOutlook,
    config: CalibrationConfig,
    *,
    cutoff: datetime,
) -> tuple[str, list[CalibrationEvent], CalibrationSummary | None]:
    if config.schema_version == 3:
        return _evaluate_calibration_v3(metadata, outlook, config, cutoff=cutoff)
    profile = config.profile_for(metadata.competition_code)
    if outlook.schema_version == 2 and outlook.calibration_summary is not None:
        one_baseline = list(outlook.calibration_summary.one_x_two.baseline_ranking)
        fixed_baseline = list(outlook.calibration_summary.fixed_handicap_1x2.baseline_ranking)
    else:
        one_baseline = _full_ranking(
            outlook.one_x_two.choices if outlook.one_x_two else [Selection.HOME.value, Selection.DRAW.value],
            (Selection.HOME.value, Selection.DRAW.value, Selection.AWAY.value),
        )
        fixed_baseline = _full_ranking(
            outlook.fixed_handicap_1x2.ranking.choices if outlook.fixed_handicap_1x2 else [FixedHandicapResult.HANDICAP_HOME.value, FixedHandicapResult.HANDICAP_DRAW.value],
            tuple(item.value for item in FixedHandicapResult),
        )
    summary = CalibrationSummary(
        one_x_two=CalibrationMarketSummary(baseline_ranking=one_baseline, final_ranking=one_baseline),
        fixed_handicap_1x2=CalibrationMarketSummary(baseline_ranking=fixed_baseline, final_ranking=fixed_baseline),
        asian_handicap={"cover_signal": "neutral", "cover_signal_rule_ids": []},
    )
    if profile == "not_applicable":
        return profile, [], summary

    policy = config.comparison_policy
    euro, euro_error = _three_nodes(
        metadata,
        "european_odds",
        "macau",
        policy.european_odds_format,
        cutoff,
        policy.late_window_minutes,
    )
    favorite, underdog = _identity(euro) if euro else (None, None)
    fixed_favorite = (
        FixedHandicapResult.HANDICAP_HOME.value
        if favorite == Selection.HOME.value
        else FixedHandicapResult.HANDICAP_AWAY.value
    )
    events: list[CalibrationEvent] = []
    asian, asian_error = _three_nodes(
        metadata,
        "asian_handicap",
        "macau",
        policy.asian_water_odds_format,
        cutoff,
        policy.late_window_minutes,
    )

    # Rules 1-3: Macau Asian market, with all water comparisons constrained to one line.
    for rule_id, target in (
        ("lsl-asian-rise-water-rise", FixedHandicapResult.HANDICAP_DRAW.value),
        ("lsl-deep-line-falling-water", fixed_favorite),
        ("lsl-deep-line-drop-risk", FixedHandicapResult.HANDICAP_DRAW.value),
    ):
        raw = _base_event(rule_id, "fixed_handicap_1x2", target, fixed_baseline, [AnalysisDimension.ASIAN_HANDICAP_MARKET.value])
        if asian_error or euro_error or favorite not in {"home", "away"}:
            events.append(_not_triggered(raw, "insufficient_data"))
            continue
        all_asian = [
            item
            for item in _snapshots(metadata, "asian_handicap", "macau", cutoff)
            if _format(item) == "hong_kong"
        ]
        line_key = "home_line"
        water_key = f"{favorite}_water"
        if any(_number(item, line_key) is None or _number(item, water_key) is None for item in all_asian):
            events.append(_not_triggered(raw, "insufficient_data"))
            continue
        sign = -1.0 if favorite == "home" else 1.0
        depths = [sign * float(_number(item, line_key)) for item in all_asian]
        if rule_id == "lsl-asian-rise-water-rise":
            allowed_steps = set(config.allowed(rule_id, "line_rise_steps"))
            rises = [index for index in range(1, len(depths)) if round(depths[index] - depths[index - 1], 2) in allowed_steps]
            if not rises:
                events.append(_not_triggered(raw, "threshold_not_met", line_rise=0))
                continue
            index = rises[-1]
            new_depth = depths[index]
            same_line = _same_line_run(all_asian, depths, index)
            threshold = config.threshold(rule_id, "water_rise_min")
            delta = _delta(float(_number(same_line[-1], water_key)), float(_number(same_line[0], water_key))) if len(same_line) >= 2 else None
            if len(same_line) < 2 or same_line[-1].snapshot_id != all_asian[-1].snapshot_id:
                events.append(_not_triggered(raw, "insufficient_data", same_line_nodes=len(same_line)))
            elif delta is not None and delta >= threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=same_line, observations={"line_depth": new_depth, "water_delta": delta, "operator": ">=", "threshold": threshold}))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", water_delta=delta, threshold=threshold))
        elif rule_id == "lsl-deep-line-falling-water":
            minimum = config.threshold(rule_id, "minimum_line_depth")
            threshold = config.threshold(rule_id, "water_fall_min")
            same_line = [item for item, depth in zip(all_asian, depths) if depth == depths[-1]]
            delta = _delta(float(_number(same_line[0], water_key)), float(_number(same_line[-1], water_key))) if len(same_line) >= 2 else None
            no_drop = all(right >= left for left, right in zip(depths, depths[1:]))
            if depths[0] >= minimum and no_drop and delta is not None and delta >= threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=same_line, observations={"minimum_depth": min(depths), "water_fall": delta, "operator": ">=", "threshold": threshold}))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", minimum_depth=min(depths), water_fall=delta, no_drop=no_drop))
        else:
            minimum = config.threshold(rule_id, "minimum_line_depth")
            threshold = config.threshold(rule_id, "post_drop_water_rise_strict")
            drops = [index for index in range(1, len(depths)) if depths[index - 1] >= minimum and depths[index] < depths[index - 1] and all_asian[index].captured_at >= metadata.kickoff_at - timedelta(minutes=policy.late_window_minutes)]
            if not drops:
                events.append(_not_triggered(raw, "threshold_not_met", late_drop=False))
                continue
            index = drops[-1]
            new_depth = depths[index]
            same_line = _same_line_run(all_asian, depths, index)
            delta = _delta(float(_number(same_line[-1], water_key)), float(_number(same_line[0], water_key))) if len(same_line) >= 2 else None
            if len(same_line) < 2:
                events.append(_not_triggered(raw, "insufficient_data", same_line_nodes=len(same_line)))
            elif delta is not None and delta > threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=same_line, observations={"line_depth": new_depth, "water_delta": delta, "operator": ">", "threshold": threshold}))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", water_delta=delta, threshold=threshold))

    # Rule 4.
    raw = _base_event("lsl-favorite-kelly-draw-resonance", "one_x_two", Selection.DRAW.value, one_baseline, [AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.KELLY_INDEX.value])
    kelly, kelly_error = _three_nodes(
        metadata,
        "kelly_index",
        "macau",
        policy.kelly_odds_format,
        cutoff,
        policy.late_window_minutes,
    )
    if euro_error or kelly_error or favorite not in {"home", "away"}:
        events.append(_not_triggered(raw, "insufficient_data"))
    else:
        required_values = (
            _number(euro[0], favorite),
            _number(euro[-1], favorite),
            _number(kelly[0], favorite),
            _number(kelly[-1], favorite),
            _number(kelly[-1], "draw"),
        )
        if any(value is None for value in required_values):
            events.append(_not_triggered(raw, "insufficient_data"))
            odds_fall = kelly_fall = late_favorite = late_draw = None
        else:
            odds_fall = _delta(required_values[0], required_values[1])
            kelly_fall = _delta(required_values[2], required_values[3])
            late_favorite = required_values[3]
            late_draw = required_values[4]
            threshold = config.threshold(raw["rule_id"], "minimum_fall")
            if late_favorite >= late_draw and odds_fall >= threshold and kelly_fall >= threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=[*euro, *kelly], observations={"odds_fall": odds_fall, "kelly_fall": kelly_fall, "late_favorite_kelly": late_favorite, "late_draw_kelly": late_draw}, correlation_keys=["macau:odds-kelly"]))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", odds_fall=odds_fall, kelly_fall=kelly_fall, late_favorite_kelly=late_favorite, late_draw_kelly=late_draw))

    # Rule 5.
    raw = _base_event("lsl-single-side-draw-protection", "one_x_two", Selection.DRAW.value, one_baseline, [AnalysisDimension.EUROPEAN_ODDS.value])
    qualifying: dict[tuple[str, int], list[tuple[str, list[MarketSnapshot]]]] = {}
    for provider in ("macau", "william-hill", "ladbrokes"):
        nodes, error = _three_nodes(
            metadata,
            "european_odds",
            provider,
            policy.european_odds_format,
            cutoff,
            policy.late_window_minutes,
        )
        if error or nodes is None:
            continue
        draw_values = [_number(item, "draw") for item in nodes]
        if any(value is None for value in draw_values):
            continue
        for endpoint in ("home", "away"):
            values = [_number(item, endpoint) for item in nodes]
            if any(value is None for value in values):
                continue
            direction = 1 if values[-1] > values[0] else -1
            monotonic = all((right - left) * direction >= 0 for left, right in zip(values, values[1:]))
            net = round(abs(values[-1] - values[0]), 6)
            draw_range = round(max(draw_values) - min(draw_values), 6)
            if monotonic and net >= config.threshold(raw["rule_id"], "endpoint_net_change_min") and draw_range <= config.threshold(raw["rule_id"], "draw_range_max") and draw_values[-1] <= draw_values[0]:
                qualifying.setdefault((endpoint, direction), []).append((provider, nodes))
    provider_count = int(config.threshold(raw["rule_id"], "provider_count_min"))
    group = next((values for values in qualifying.values() if len(values) >= provider_count), None)
    if group:
        selected = group[:provider_count]
        events.append(_trigger(raw, providers=[item[0] for item in selected], snapshots=[snap for _, nodes in selected for snap in nodes], observations={"qualifying_providers": [item[0] for item in selected], "provider_count": len(selected)}))
    else:
        reason = "insufficient_data" if not qualifying else "threshold_not_met"
        events.append(_not_triggered(raw, reason, qualifying_provider_count=max((len(item) for item in qualifying.values()), default=0)))

    # Rule 6.
    target = underdog if underdog in {"home", "away"} else Selection.AWAY.value
    raw = _base_event("lsl-underdog-kelly-defense", "one_x_two", target, one_baseline, [AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.KELLY_INDEX.value])
    if euro_error or kelly_error or underdog not in {"home", "away"}:
        events.append(_not_triggered(raw, "insufficient_data"))
    else:
        odds_values = [_number(item, underdog) for item in euro]
        kelly_values = [_number(item, underdog) for item in kelly]
        if any(value is None for value in [*odds_values, *kelly_values]):
            events.append(_not_triggered(raw, "insufficient_data"))
        else:
            threshold = config.threshold(raw["rule_id"], "minimum_fall")
            monotonic = all(right <= left for values in (odds_values, kelly_values) for left, right in zip(values, values[1:]))
            falls = (_delta(odds_values[0], odds_values[-1]), _delta(kelly_values[0], kelly_values[-1]))
            if monotonic and min(falls) >= threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=[*euro, *kelly], observations={"odds_fall": falls[0], "kelly_fall": falls[1]}, correlation_keys=["macau:odds-kelly"]))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", monotonic=monotonic, odds_fall=falls[0], kelly_fall=falls[1]))

    # Rule 7.
    raw = _base_event("lsl-kelly-narrow-range", "one_x_two", Selection.DRAW.value, one_baseline, [AnalysisDimension.KELLY_INDEX.value, AnalysisDimension.ASIAN_HANDICAP_MARKET.value])
    if kelly_error or asian_error or favorite not in {"home", "away"}:
        events.append(_not_triggered(raw, "insufficient_data"))
    else:
        late_values = [_number(kelly[-1], key) for key in ("home", "draw", "away")]
        line_values = [_number(item, "home_line") for item in asian]
        water_values = [_number(item, f"{favorite}_water") for item in asian]
        if any(value is None for value in [*late_values, *line_values, *water_values]):
            events.append(_not_triggered(raw, "insufficient_data"))
        else:
            spread = round(max(late_values) - min(late_values), 6)
            sign = -1 if favorite == "home" else 1
            depths = [sign * value for value in line_values]
            water_rise = _delta(water_values[-1], water_values[0])
            same_line_rise = depths[0] == depths[-1] and water_rise > config.threshold(raw["rule_id"], "favorite_water_rise_strict")
            line_drop = depths[-1] < max(depths[:-1])
            if spread <= config.threshold(raw["rule_id"], "kelly_spread_max") and (same_line_rise or line_drop):
                events.append(_trigger(raw, providers=["macau"], snapshots=[*kelly, *asian], observations={"kelly_spread": spread, "same_line_water_rise": same_line_rise, "late_line_drop": line_drop}, correlation_keys=["macau:kelly-asian"]))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", kelly_spread=spread, same_line_water_rise=same_line_rise, late_line_drop=line_drop))

    # Rule 8.
    raw = _base_event("lsl-extreme-over-calibration", "fixed_handicap_1x2", fixed_favorite, fixed_baseline, [AnalysisDimension.TOTAL_GOALS_MARKET.value])
    qualifying_total: tuple[str, list[MarketSnapshot]] | None = None
    exact_line = config.threshold(raw["rule_id"], "exact_total_line")
    for provider in config.recognized_providers:
        nodes, error = _three_nodes(
            metadata,
            "total_goals",
            provider,
            policy.asian_water_odds_format,
            cutoff,
            policy.late_window_minutes,
        )
        if error or nodes is None:
            continue
        line = _number(nodes[-1], "line")
        over = _number(nodes[-1], "over_water")
        if line == exact_line and over is not None and over <= config.threshold(raw["rule_id"], "over_water_max"):
            qualifying_total = (provider, nodes)
            break
    if qualifying_total:
        provider, nodes = qualifying_total
        events.append(_trigger(raw, providers=[provider], snapshots=nodes, observations={"late_line": exact_line, "late_over_water": _number(nodes[-1], "over_water"), "operator": "<=", "threshold": config.threshold(raw["rule_id"], "over_water_max")}))
    else:
        events.append(_not_triggered(raw, "insufficient_data", exact_line=exact_line))

    if config.schema_version == 2:
        events.extend(
            _new_experimental_events(
                metadata,
                config,
                profile,
                one_baseline,
                fixed_baseline,
                cutoff=cutoff,
                favorite=favorite,
                fixed_favorite=fixed_favorite,
            )
        )

    cover_ids = [item.rule_id for item in events if item.triggered and item.rule_id in {"lsl-asian-rise-water-rise", "lsl-deep-line-drop-risk", "lsl-deep-line-falling-water"}]
    if "lsl-deep-line-falling-water" in cover_ids and not set(cover_ids) & {"lsl-asian-rise-water-rise", "lsl-deep-line-drop-risk"}:
        summary.asian_handicap.cover_signal = "support"
    elif set(cover_ids) & {"lsl-asian-rise-water-rise", "lsl-deep-line-drop-risk"}:
        summary.asian_handicap.cover_signal = "risk"
    summary.asian_handicap.cover_signal_rule_ids = cover_ids
    return profile, events, summary
