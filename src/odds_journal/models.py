from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MatchStatus(StrEnum):
    DRAFT = "draft"
    TRACKING = "tracking"
    LOCKED = "locked"
    FINISHED = "finished"
    HISTORICAL_FINISHED = "historical_finished"
    REVIEWED = "reviewed"
    VOID = "void"


class PrimaryMarket(StrEnum):
    ONE_X_TWO = "one_x_two"
    HANDICAP = "handicap"
    TOTAL_GOALS = "total_goals"
    PASS = "pass"


class Selection(StrEnum):
    HOME = "home"
    DRAW = "draw"
    AWAY = "away"
    HOME_HANDICAP = "home_handicap"
    AWAY_HANDICAP = "away_handicap"
    OVER = "over"
    UNDER = "under"
    PASS = "pass"


class EvaluationValue(StrEnum):
    PENDING = "pending"
    CORRECT = "correct"
    WRONG = "wrong"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"


class Result1X2(StrEnum):
    HOME = "home"
    DRAW = "draw"
    AWAY = "away"


class HandicapResult(StrEnum):
    HOME_HANDICAP = "home_handicap"
    AWAY_HANDICAP = "away_handicap"
    PUSH = "push"


class MarketType(StrEnum):
    ASIAN_HANDICAP = "asian_handicap"
    EUROPEAN_ODDS = "european_odds"
    KELLY_INDEX = "kelly_index"
    TOTAL_GOALS = "total_goals"
    FIXED_HANDICAP_1X2 = "fixed_handicap_1x2"


class SnapshotPhase(StrEnum):
    OPENING = "opening"
    MID = "mid"
    LATE = "late"
    LIVE = "live"


class OddsFormat(StrEnum):
    HONG_KONG = "hong_kong"
    DECIMAL = "decimal"
    MALAY = "malay"
    INDONESIAN = "indonesian"
    KELLY = "kelly"
    RAW = "raw"


class AnalysisDataMode(StrEnum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    PASS = "pass"


class MarketDecisionStatus(StrEnum):
    ASSESSED = "assessed"
    PASS = "pass"


class AnalysisDimension(StrEnum):
    ASIAN_HANDICAP_MARKET = "asian_handicap_market"
    EUROPEAN_ODDS = "european_odds"
    KELLY_INDEX = "kelly_index"
    TOTAL_GOALS_MARKET = "total_goals_market"


class ResonanceStatus(StrEnum):
    RESONANT = "resonant"
    DIVERGENT = "divergent"
    INSUFFICIENT = "insufficient"


class AsianSettlement(StrEnum):
    FULL_WIN = "full_win"
    HALF_WIN = "half_win"
    PUSH = "push"
    HALF_LOSS = "half_loss"
    FULL_LOSS = "full_loss"


class FixedHandicapResult(StrEnum):
    HANDICAP_HOME = "handicap_home"
    HANDICAP_DRAW = "handicap_draw"
    HANDICAP_AWAY = "handicap_away"


class RecordIntegrity(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class Evaluation(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    primary: EvaluationValue = EvaluationValue.PENDING
    handicap: EvaluationValue = EvaluationValue.PENDING
    total_goals_range: EvaluationValue = EvaluationValue.PENDING
    score_range: EvaluationValue = EvaluationValue.PENDING
    confidence_calibration: EvaluationValue = EvaluationValue.PENDING


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    snapshot_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    market: MarketType
    phase: SnapshotPhase
    captured_at: datetime
    provider_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    source_ref: str = Field(min_length=1)
    evidence_id: str | None = None
    odds_format: OddsFormat
    raw_values: dict[str, str] = Field(min_length=1)
    normalized_values: dict[str, float] = Field(default_factory=dict)

    @field_validator("captured_at")
    @classmethod
    def require_snapshot_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("盘口快照时间必须包含时区")
        return value


class DimensionAssessment(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    dimension: AnalysisDimension
    configured_weight: int = Field(ge=0, le=100)
    effective_weight: float = Field(ge=0, le=100)
    candidate_scores: dict[str, float] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    fact_refs: list[str] = Field(default_factory=list)
    rule_ids: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    missing_reason: str | None = None
    correlated_with: list[AnalysisDimension] = Field(default_factory=list)

    @field_validator("candidate_scores")
    @classmethod
    def validate_scores(cls, value: dict[str, float]) -> dict[str, float]:
        allowed = {-1.0, -0.5, 0.0, 0.5, 1.0}
        if any(score not in allowed for score in value.values()):
            raise ValueError("维度评分只能为 -1、-0.5、0、0.5、1")
        return value

    @model_validator(mode="after")
    def validate_dimension_contract(self) -> "DimensionAssessment":
        dimension = AnalysisDimension(self.dimension)
        expected_weight = {
            AnalysisDimension.ASIAN_HANDICAP_MARKET: 60,
            AnalysisDimension.EUROPEAN_ODDS: 20,
            AnalysisDimension.KELLY_INDEX: 15,
            AnalysisDimension.TOTAL_GOALS_MARKET: 5,
        }[dimension]
        if self.configured_weight != expected_weight:
            raise ValueError(f"{dimension.value} configured_weight 必须为 {expected_weight}")
        allowed_keys = {
            AnalysisDimension.ASIAN_HANDICAP_MARKET: {
                Selection.HOME_HANDICAP.value,
                Selection.AWAY_HANDICAP.value,
            },
            AnalysisDimension.EUROPEAN_ODDS: {
                Selection.HOME.value,
                Selection.DRAW.value,
                Selection.AWAY.value,
            },
            AnalysisDimension.KELLY_INDEX: {
                Selection.HOME.value,
                Selection.DRAW.value,
                Selection.AWAY.value,
            },
            AnalysisDimension.TOTAL_GOALS_MARKET: {
                Selection.OVER.value,
                Selection.UNDER.value,
            },
        }[dimension]
        invalid = set(self.candidate_scores) - allowed_keys
        if invalid:
            raise ValueError(f"{dimension.value} 包含非法候选：{', '.join(sorted(invalid))}")
        if self.effective_weight == 0:
            if not self.missing_reason:
                raise ValueError(f"{dimension.value} 权重为零时必须记录 missing_reason")
            if self.candidate_scores:
                raise ValueError(f"{dimension.value} 缺失时不得填写候选评分")
        else:
            if self.effective_weight != self.configured_weight:
                raise ValueError("有效维度不得重分配或缩放固定权重")
            required = (
                self.candidate_scores,
                self.fact_refs,
                self.rule_ids,
                self.supporting_evidence,
                self.counter_evidence,
            )
            if any(not item for item in required):
                raise ValueError(
                    f"{dimension.value} 非零时必须包含评分、事实引用、规则、支持证据和反证"
                )
            if self.missing_reason:
                raise ValueError(f"{dimension.value} 非零时不得填写 missing_reason")
        if len(self.correlated_with) != len(set(self.correlated_with)):
            raise ValueError("correlated_with 不得重复")
        if dimension.value in {str(item) for item in self.correlated_with}:
            raise ValueError("维度不能与自身相关")
        return self


class WeightModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    model_id: str = "asian-core-v1"
    weights: dict[AnalysisDimension, int] = Field(
        default_factory=lambda: {
            AnalysisDimension.ASIAN_HANDICAP_MARKET: 60,
            AnalysisDimension.EUROPEAN_ODDS: 20,
            AnalysisDimension.KELLY_INDEX: 15,
            AnalysisDimension.TOTAL_GOALS_MARKET: 5,
        }
    )

    @model_validator(mode="after")
    def validate_policy(self) -> "WeightModel":
        expected = {
            AnalysisDimension.ASIAN_HANDICAP_MARKET.value: 60,
            AnalysisDimension.EUROPEAN_ODDS.value: 20,
            AnalysisDimension.KELLY_INDEX.value: 15,
            AnalysisDimension.TOTAL_GOALS_MARKET.value: 5,
        }
        normalized = {str(key): value for key, value in self.weights.items()}
        if self.model_id != "asian-core-v1" or normalized != expected:
            raise ValueError("asian-core-v1 权重必须固定为亚盘60、欧赔20、凯利15、大小球5")
        return self


class RankedOutcomes(BaseModel):
    choices: list[str] = Field(min_length=2, max_length=2)

    @field_validator("choices")
    @classmethod
    def require_distinct_choices(cls, value: list[str]) -> list[str]:
        if len(set(value)) != 2:
            raise ValueError("前两顺位必须不同")
        return value


class AsianHandicapOutlook(BaseModel):
    line_display: str = Field(min_length=1)
    home_line: float
    ranking: RankedOutcomes

    @field_validator("home_line")
    @classmethod
    def require_quarter_line(cls, value: float) -> float:
        if abs(value * 4 - round(value * 4)) > 1e-8:
            raise ValueError("亚洲让球必须按 0.25 档位记录")
        return value

    @model_validator(mode="after")
    def validate_ranking(self) -> "AsianHandicapOutlook":
        allowed = {Selection.HOME_HANDICAP.value, Selection.AWAY_HANDICAP.value}
        if set(self.ranking.choices) != allowed:
            raise ValueError("亚洲让球前两顺位必须覆盖主队与客队方向")
        return self


class FixedHandicapOutlook(BaseModel):
    home_line: int
    source_type: str = Field(min_length=1)
    ranking: RankedOutcomes

    @model_validator(mode="after")
    def validate_ranking(self) -> "FixedHandicapOutlook":
        allowed = {item.value for item in FixedHandicapResult}
        if any(choice not in allowed for choice in self.ranking.choices):
            raise ValueError("固定让球胜平负顺位无效")
        return self


class TotalGoalsOutlook(BaseModel):
    minimum: int = Field(ge=0)
    maximum: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "TotalGoalsOutlook":
        if self.minimum > self.maximum:
            raise ValueError("总进球区间下限不能大于上限")
        return self


class TotalGoalsSignalV5(BaseModel):
    """A verified market direction, deliberately not an invented score range."""

    model_config = ConfigDict(extra="forbid")

    side: Literal["over", "under"]
    provider_ids: list[str] = Field(min_length=2)
    observation_ids: list[str] = Field(min_length=6)
    line: float = Field(gt=0)

    @field_validator("provider_ids", "observation_ids")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("总进球信号来源不得重复")
        return value


# Contract 3 deliberately keeps the analyst's judgement separate from the
# deterministic aggregation.  The journal validates the input matrix but never
# derives a directional score from raw market snapshots.
SCORE_MARKETS: dict[str, tuple[str, ...]] = {
    "one_x_two": (Selection.HOME.value, Selection.DRAW.value, Selection.AWAY.value),
    "asian_handicap": (Selection.HOME_HANDICAP.value, Selection.AWAY_HANDICAP.value),
    "fixed_handicap_1x2": (
        FixedHandicapResult.HANDICAP_HOME.value,
        FixedHandicapResult.HANDICAP_DRAW.value,
        FixedHandicapResult.HANDICAP_AWAY.value,
    ),
    "total_goals": (Selection.OVER.value, Selection.UNDER.value),
}


class BaselineGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts_status: Literal["complete", "incomplete", "conflicted"]
    theoretical_positioning: Literal["established", "unavailable"]
    market_relation: Literal["aligned", "explained_divergence", "unexplained_divergence"]
    decision: Literal["ready", "degraded", "pass"]
    fact_refs: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision(self) -> "BaselineGate":
        forced_pass = (
            self.facts_status == "conflicted"
            or self.theoretical_positioning == "unavailable"
            or self.market_relation == "unexplained_divergence"
        )
        if forced_pass:
            if self.decision != "pass" or not self.reasons:
                raise ValueError("理论定位缺失、事实冲突或未解释背离必须 pass 并记录原因")
        elif self.facts_status == "incomplete":
            if self.decision != "degraded" or not self.reasons:
                raise ValueError("基本面不完整但理论盘可用时必须 degraded 并记录原因")
        elif self.decision != "ready" or self.reasons:
            raise ValueError("完整且已解释的基础定位必须使用 ready，且不得填写原因")
        if not self.fact_refs:
            raise ValueError("基础门禁必须引用事实材料")
        return self


class MarketScoreCell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["assessed", "not_applicable"]
    scores: dict[str, float] = Field(default_factory=dict)
    reason: str | None = None

    @field_validator("scores")
    @classmethod
    def discrete_scores(cls, value: dict[str, float]) -> dict[str, float]:
        if any(item not in {-1.0, -0.5, 0.0, 0.5, 1.0} for item in value.values()):
            raise ValueError("评分矩阵只能使用 -1、-0.5、0、0.5、1")
        return value

    @model_validator(mode="after")
    def validate_status(self) -> "MarketScoreCell":
        if self.status == "assessed":
            if self.reason or not self.scores:
                raise ValueError("已评分市场必须给出全部分数且不得填写 reason")
        elif self.scores or not self.reason:
            raise ValueError("不适用市场不得给分且必须说明原因")
        return self


class ScoreMatrixRow(BaseModel):
    model_config = ConfigDict(use_enum_values=True, extra="forbid")

    dimension: AnalysisDimension
    configured_weight: int = Field(ge=0, le=100)
    market_scores: dict[str, MarketScoreCell]
    fact_refs: list[str] = Field(min_length=1)
    rule_ids: list[str] = Field(min_length=1)
    supporting_evidence: list[str] = Field(min_length=1)
    counter_evidence: list[str] = Field(min_length=1)
    source_provider_ids: list[str] = Field(min_length=1)
    source_snapshot_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    correlated_with: list[AnalysisDimension] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_row(self) -> "ScoreMatrixRow":
        expected_weight = {
            AnalysisDimension.ASIAN_HANDICAP_MARKET: 60,
            AnalysisDimension.EUROPEAN_ODDS: 20,
            AnalysisDimension.KELLY_INDEX: 15,
            AnalysisDimension.TOTAL_GOALS_MARKET: 5,
        }[AnalysisDimension(self.dimension)]
        if self.configured_weight != expected_weight:
            raise ValueError(f"{self.dimension} 必须使用固定权重 {expected_weight}")
        if set(self.market_scores) != set(SCORE_MARKETS):
            raise ValueError("每个维度必须完整声明四个评分市场")
        for market, candidates in SCORE_MARKETS.items():
            cell = self.market_scores[market]
            if cell.status == "assessed" and set(cell.scores) != set(candidates):
                raise ValueError(f"{self.dimension}/{market} 必须覆盖全部候选")
        if len(self.source_provider_ids) != len(set(self.source_provider_ids)):
            raise ValueError("source_provider_ids 不得重复")
        if len(self.source_snapshot_ids) != len(set(self.source_snapshot_ids)):
            raise ValueError("source_snapshot_ids 不得重复")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids 不得重复")
        if AnalysisDimension(self.dimension) in {AnalysisDimension(value) for value in self.correlated_with}:
            raise ValueError("评分维度不能与自身相关")
        return self


class MultiMarketScoreMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[ScoreMatrixRow] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_rows(self) -> "MultiMarketScoreMatrix":
        dimensions = [AnalysisDimension(item.dimension) for item in self.rows]
        if len(set(dimensions)) != len(dimensions) or set(dimensions) != set(AnalysisDimension):
            raise ValueError("评分矩阵必须且只能覆盖四个固定维度")
        by_dimension = {AnalysisDimension(item.dimension): item for item in self.rows}
        euro = by_dimension[AnalysisDimension.EUROPEAN_ODDS]
        kelly = by_dimension[AnalysisDimension.KELLY_INDEX]
        reciprocal = (
            AnalysisDimension.KELLY_INDEX in {AnalysisDimension(item) for item in euro.correlated_with}
            and AnalysisDimension.EUROPEAN_ODDS in {AnalysisDimension(item) for item in kelly.correlated_with}
        )
        if reciprocal and not (set(euro.source_provider_ids) & set(kelly.source_provider_ids) and set(euro.evidence_ids) & set(kelly.evidence_ids)):
            raise ValueError("欧赔与凯利相关必须共享可核验 provider 和 evidence_id")
        return self


class MarketScoreSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_scores: dict[str, float]
    effective_weights: dict[str, float]
    ranking: list[str]
    tie_groups: list[list[str]]
    top_tied: bool
    top_margin: float | None


class BaselineSummaryV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markets: dict[str, MarketScoreSummary]
    primary_market: PrimaryMarket | None = None
    primary_selection: str | None = None
    pass_reasons: list[str] = Field(default_factory=list)


class CandidateDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disposition: Literal["adopted", "excluded"]
    exclusion_reason: str | None = None
    counter_evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_disposition(self) -> "CandidateDisposition":
        if self.disposition == "excluded":
            if not self.exclusion_reason or not self.counter_evidence_refs:
                raise ValueError("排除候选必须记录理由和反证引用")
        elif self.exclusion_reason or self.counter_evidence_refs:
            raise ValueError("采纳候选不得填写排除理由或反证引用")
        return self


class TotalGoalsCandidate(BaseModel):
    minimum: int = Field(ge=0)
    maximum: int = Field(ge=0)
    rule_id: str
    decision: CandidateDisposition

    @model_validator(mode="after")
    def validate_range(self) -> "TotalGoalsCandidate":
        if self.minimum > self.maximum:
            raise ValueError("总进球候选下限不能大于上限")
        return self


class ScoreCandidate(BaseModel):
    score: str
    rule_id: str
    decision: CandidateDisposition

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: str) -> str:
        if not re.fullmatch(r"\d+-\d+", value):
            raise ValueError("比分候选必须使用 H-A 格式")
        return value


class OutcomeRiskCandidate(BaseModel):
    market: PrimaryMarket
    selection: Selection
    rule_id: str
    decision: CandidateDisposition

    @model_validator(mode="after")
    def validate_market_selection(self) -> "OutcomeRiskCandidate":
        if self.market == PrimaryMarket.PASS or self.selection not in MARKET_SELECTIONS[self.market]:
            raise ValueError("风险候选市场与方向不匹配")
        return self


def synthesize_baseline(matrix: MultiMarketScoreMatrix) -> BaselineSummaryV3:
    """Aggregate explicit analyst scores without inferring any market direction."""
    rows = {AnalysisDimension(item.dimension): item for item in matrix.rows}
    euro = rows[AnalysisDimension.EUROPEAN_ODDS]
    kelly = rows[AnalysisDimension.KELLY_INDEX]
    kelly_is_correlated = (
        AnalysisDimension.KELLY_INDEX in {AnalysisDimension(item) for item in euro.correlated_with}
        and AnalysisDimension.EUROPEAN_ODDS in {AnalysisDimension(item) for item in kelly.correlated_with}
        and bool(set(euro.source_provider_ids) & set(kelly.source_provider_ids))
        and bool(set(euro.evidence_ids) & set(kelly.evidence_ids))
    )
    summaries: dict[str, MarketScoreSummary] = {}
    for market, candidates in SCORE_MARKETS.items():
        totals = {candidate: 0.0 for candidate in candidates}
        effective: dict[str, float] = {}
        for dimension, row in rows.items():
            cell = row.market_scores[market]
            weight = float(row.configured_weight) if cell.status == "assessed" else 0.0
            if dimension == AnalysisDimension.KELLY_INDEX and kelly_is_correlated and weight:
                weight /= 2
            effective[dimension.value] = weight
            if cell.status == "assessed":
                for candidate in candidates:
                    totals[candidate] += weight * cell.scores[candidate]
        totals = {candidate: round(value, 6) for candidate, value in totals.items()}
        ranking = sorted(candidates, key=lambda candidate: (-totals[candidate], candidates.index(candidate)))
        groups: dict[float, list[str]] = {}
        for candidate in ranking:
            groups.setdefault(totals[candidate], []).append(candidate)
        tie_groups = [values for values in groups.values() if len(values) > 1]
        margin = None if totals[ranking[0]] == totals[ranking[1]] else round(totals[ranking[0]] - totals[ranking[1]], 6)
        summaries[market] = MarketScoreSummary(
            candidate_scores=totals,
            effective_weights=effective,
            ranking=ranking,
            tie_groups=tie_groups,
            top_tied=margin is None,
            top_margin=margin,
        )

    primary_map = {
        PrimaryMarket.ONE_X_TWO: "one_x_two",
        PrimaryMarket.HANDICAP: "asian_handicap",
        PrimaryMarket.TOTAL_GOALS: "total_goals",
    }
    candidates = [
        (market, summaries[key]) for market, key in primary_map.items()
        if not summaries[key].top_tied
    ]
    if not candidates:
        return BaselineSummaryV3(markets=summaries, pass_reasons=["所有可选主市场第一顺位并列"])
    best_margin = max(float(summary.top_margin) for _, summary in candidates if summary.top_margin is not None)
    leaders = [item for item in candidates if item[1].top_margin == best_margin]
    if len(leaders) != 1:
        return BaselineSummaryV3(markets=summaries, pass_reasons=["可选主市场最高分差并列"])
    market, summary = leaders[0]
    return BaselineSummaryV3(
        markets=summaries,
        primary_market=market,
        primary_selection=summary.ranking[0],
    )


CALIBRATION_RULE_IDS = (
    "lsl-asian-rise-water-rise",
    "lsl-deep-line-falling-water",
    "lsl-deep-line-drop-risk",
    "lsl-favorite-kelly-draw-resonance",
    "lsl-single-side-draw-protection",
    "lsl-underdog-kelly-defense",
    "lsl-kelly-narrow-range",
    "lsl-extreme-over-calibration",
)
CALIBRATION_RULE_IDS_V2 = (
    *CALIBRATION_RULE_IDS,
    "draw-kelly-parity-v1",
    "deep-line-stable-cover-v1",
    "quarter-low-water-inducement-v1",
    "hidden-draw-away-cut-v1",
    "total-goals-cross-market-v1",
    "score-baseline-v1",
    "korea-goal-drop-v1",
    "korea-deep-line-loss-tolerance-v1",
)
CALIBRATION_RULE_IDS_V3 = CALIBRATION_RULE_IDS_V2
CALIBRATION_CONTROL_IDS_V4 = (
    "trend-purity-v1",
    "provider-consensus-divergence-v1",
    "cross-dimension-netting-v1",
    "late-market-anomaly-v1",
    "single-kelly-value-guard-v1",
)
CALIBRATION_RULE_IDS_V4 = (*CALIBRATION_RULE_IDS_V3, *CALIBRATION_CONTROL_IDS_V4)


class CalibrationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    rule_id: str
    contract_version: Literal[1, 2, 3, 4, 7] = 2
    reliability: Literal["experimental"] = "experimental"
    triggered: bool
    not_triggered_reason: str | None = None
    applicability: Literal["applicable", "not_applicable"] = "applicable"
    effect: Literal[
        "ranking", "handicap_signal", "total_goals_pool", "score_pool", "outcome_risk_pool", "control"
    ] = "ranking"
    target_market: Literal["one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "handicap"] | None = None
    target_selection: str
    source_dimensions: list[AnalysisDimension] = Field(default_factory=list)
    source_provider_ids: list[str] = Field(default_factory=list)
    source_snapshot_ids: list[str] = Field(default_factory=list)
    correlation_keys: list[str] = Field(default_factory=list)
    threshold_observations: dict[str, Any] = Field(default_factory=dict)
    before_ranking: list[str] = Field(default_factory=list)
    proposed_ranking: list[str] = Field(default_factory=list)
    final_ranking: list[str] = Field(default_factory=list)
    adjustment_level: int = Field(ge=-1, le=1)
    primary_changed: bool = False
    supporting_evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    decision: CandidateDisposition | None = None

    @field_validator(
        "source_dimensions", "source_provider_ids", "source_snapshot_ids", "correlation_keys"
    )
    @classmethod
    def unique_list(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("校准事件来源列表不得重复")
        return value

    @model_validator(mode="after")
    def validate_event(self) -> "CalibrationEvent":
        expected_ids = CALIBRATION_RULE_IDS_V4 if self.contract_version in {4, 7} else CALIBRATION_RULE_IDS_V3 if self.contract_version == 3 else CALIBRATION_RULE_IDS_V2 if self.contract_version == 2 else CALIBRATION_RULE_IDS
        if self.rule_id not in expected_ids:
            raise ValueError(f"未知低稳定性校准规则：{self.rule_id}")
        if self.contract_version in {3, 4, 7}:
            if self.applicability == "not_applicable":
                if self.triggered or self.not_triggered_reason != "not_applicable" or self.decision is not None:
                    raise ValueError("不适用规则必须明确 not_applicable 且不得产生候选")
                return self
            if self.target_market is None:
                raise ValueError("适用的 contract 3 规则必须声明目标市场")
            if self.triggered:
                required = (
                    self.source_dimensions,
                    self.source_provider_ids,
                    self.source_snapshot_ids,
                    self.threshold_observations,
                    self.supporting_evidence,
                    self.counter_evidence,
                    self.decision,
                )
                if any(not item for item in required) or self.not_triggered_reason is not None:
                    raise ValueError("已触发 contract 3 规则必须完整记录证据和候选处置")
                if self.effect == "ranking" and self.adjustment_level == 0:
                    raise ValueError("排序候选必须调整一级")
                if self.effect != "ranking" and self.adjustment_level != 0:
                    raise ValueError("非排序规则不得修改排序")
            elif not self.not_triggered_reason or self.decision is not None or self.adjustment_level != 0:
                raise ValueError("未触发 contract 3 规则必须记录原因且不得处置或调整")
            return self
        if self.triggered:
            required = (
                self.source_dimensions,
                self.source_provider_ids,
                self.source_snapshot_ids,
                self.threshold_observations,
                self.supporting_evidence,
                self.counter_evidence,
            )
            if any(not item for item in required):
                raise ValueError("已触发校准必须记录来源、阈值、支持证据和反证")
            if self.not_triggered_reason is not None or self.adjustment_level == 0:
                raise ValueError("已触发校准必须有非零调整且不得填写未触发原因")
        else:
            if not self.not_triggered_reason or self.adjustment_level != 0:
                raise ValueError("未触发校准必须填写原因且不得调整顺位")
            if self.proposed_ranking != self.before_ranking or self.final_ranking != self.before_ranking:
                raise ValueError("未触发校准不得修改排序")
        if len(self.before_ranking) < 2 or len(set(self.before_ranking)) != len(self.before_ranking):
            raise ValueError("校准前排序必须包含至少两个不重复方向")
        if set(self.proposed_ranking) != set(self.before_ranking):
            raise ValueError("校准建议不得增加或删除方向")
        if set(self.final_ranking) != set(self.before_ranking):
            raise ValueError("校准最终排序不得增加或删除方向")
        if self.triggered:
            old_index = self.before_ranking.index(self.target_selection)
            proposed_index = self.proposed_ranking.index(self.target_selection)
            if abs(old_index - proposed_index) > 1:
                raise ValueError("单条校准规则最多移动一个名次")
            if old_index > 0 and proposed_index == 0:
                raise ValueError("单条校准规则不得越过基础第一顺位")
        if self.primary_changed:
            raise ValueError("单个校准事件不得直接标记第一顺位变化")
        return self


class CalibrationMarketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_ranking: list[str] = Field(min_length=2)
    final_ranking: list[str] = Field(min_length=2)
    anchor_change_eligible: bool = False
    anchor_changed: bool = False
    anchor_change_reason: str | None = None

    @model_validator(mode="after")
    def validate_summary(self) -> "CalibrationMarketSummary":
        if len(set(self.baseline_ranking)) != len(self.baseline_ranking):
            raise ValueError("基础排序不得重复")
        if set(self.final_ranking) != set(self.baseline_ranking):
            raise ValueError("校准不得增加或删除候选方向")
        changed = self.baseline_ranking[0] != self.final_ranking[0]
        if changed != self.anchor_changed:
            raise ValueError("anchor_changed 必须与第一顺位实际变化一致")
        if self.anchor_changed and not self.anchor_change_eligible:
            raise ValueError("未满足换位门禁不得改变第一顺位")
        if self.anchor_changed and not self.anchor_change_reason:
            raise ValueError("改变第一顺位必须填写人工可审计理由")
        if not self.anchor_changed and self.anchor_change_reason:
            raise ValueError("第一顺位未变化时不得填写换位理由")
        return self


class AsianCalibrationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cover_signal: Literal["support", "risk", "neutral"] = "neutral"
    cover_signal_rule_ids: list[str] = Field(default_factory=list)


class CalibrationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    one_x_two: CalibrationMarketSummary
    fixed_handicap_1x2: CalibrationMarketSummary
    asian_handicap: AsianCalibrationSummary = Field(default_factory=AsianCalibrationSummary)


class AnalysisOutlook(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    schema_version: Literal[1, 2, 3, 4, 5] = 1
    data_mode: AnalysisDataMode
    missing_reasons: list[str] = Field(default_factory=list)
    pass_reasons: list[str] = Field(default_factory=list)
    weight_model: WeightModel = Field(default_factory=WeightModel)
    dimension_assessments: list[DimensionAssessment] = Field(default_factory=list)
    resonance_status: ResonanceStatus = ResonanceStatus.INSUFFICIENT
    independent_dimensions: list[AnalysisDimension] = Field(default_factory=list)
    correlated_dimensions: list[AnalysisDimension] = Field(default_factory=list)
    one_x_two: RankedOutcomes | None = None
    asian_handicap: AsianHandicapOutlook | None = None
    fixed_handicap_1x2: FixedHandicapOutlook | None = None
    total_goals: TotalGoalsOutlook | None = None
    score_candidates: list[str] = Field(default_factory=list)
    competition_profile: str | None = None
    calibration_contract_version: Literal[1, 2, 3, 4, 7] | None = None
    calibration_events: list[CalibrationEvent] = Field(default_factory=list)
    calibration_summary: CalibrationSummary | None = None
    baseline_gate: BaselineGate | None = None
    score_matrix: MultiMarketScoreMatrix | None = None
    baseline_summary_v3: BaselineSummaryV3 | None = None
    experimental_rankings: dict[str, list[str]] = Field(default_factory=dict)
    final_rankings: dict[str, list[str]] = Field(default_factory=dict)
    total_goals_candidate_pool: list[TotalGoalsCandidate] = Field(default_factory=list)
    score_candidate_pool: list[ScoreCandidate] = Field(default_factory=list)
    outcome_risk_pool: list[OutcomeRiskCandidate] = Field(default_factory=list)
    anchor_change_reason: str | None = None
    decision_actor: str | None = None
    analysis_input_mode: Literal["market_only", "full_context"] | None = None
    profile_chain: list[str] = Field(default_factory=list)
    evaluation_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    market_statuses: dict[Literal["one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score"], MarketDecisionStatus] = Field(default_factory=dict)
    market_pass_reasons: dict[Literal["one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score"], list[str]] = Field(default_factory=dict)
    total_goals_signal: TotalGoalsSignalV5 | None = None

    @field_validator("score_candidates")
    @classmethod
    def validate_scores(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"\d+-\d+", score) for score in value):
            raise ValueError("参考比分必须使用 H-A 格式")
        if len(value) != len(set(value)):
            raise ValueError("参考比分不能重复")
        return value

    @model_validator(mode="after")
    def validate_mode(self) -> "AnalysisOutlook":
        if self.schema_version in {3, 4, 5}:
            return self._validate_v3()
        mode = AnalysisDataMode(self.data_mode)
        dimensions = [AnalysisDimension(item.dimension) for item in self.dimension_assessments]
        expected_dimensions = set(AnalysisDimension)
        if len(dimensions) != len(set(dimensions)) or set(dimensions) != expected_dimensions:
            raise ValueError("dimension_assessments 必须且只能逐项覆盖四个固定维度")
        assessment_by_dimension = {
            AnalysisDimension(item.dimension): item for item in self.dimension_assessments
        }
        independent = [AnalysisDimension(item) for item in self.independent_dimensions]
        correlated = [AnalysisDimension(item) for item in self.correlated_dimensions]
        if len(independent) != len(set(independent)) or len(correlated) != len(set(correlated)):
            raise ValueError("独立维度和相关维度不得重复")
        if set(independent) & set(correlated):
            raise ValueError("同一维度不能同时标记为独立和相关")
        nonzero = {
            dimension
            for dimension, assessment in assessment_by_dimension.items()
            if assessment.effective_weight > 0
        }
        if not set(independent).issubset(nonzero) or not set(correlated).issubset(nonzero):
            raise ValueError("独立或相关维度必须是有效非零维度")
        if self.resonance_status == ResonanceStatus.RESONANT.value:
            if len(independent) < 2:
                raise ValueError("共振至少需要两个独立有效维度")
            for dimension in independent:
                related = {AnalysisDimension(item) for item in assessment_by_dimension[dimension].correlated_with}
                if related & set(independent):
                    raise ValueError("相互关联的维度不能作为独立共振维度")
        predictions = (
            self.one_x_two,
            self.asian_handicap,
            self.fixed_handicap_1x2,
            self.total_goals,
        )
        if mode == AnalysisDataMode.PASS:
            if not self.pass_reasons:
                raise ValueError("pass 必须记录原因")
            if any(item is not None for item in predictions) or self.score_candidates:
                raise ValueError("pass 不得保留四层预测")
        else:
            if self.pass_reasons:
                raise ValueError("非 pass 不得填写 pass_reasons")
            if any(item is None for item in predictions) or len(self.score_candidates) != 2:
                raise ValueError("非 pass 必须包含胜平负、两类让球、总进球和两个参考比分")
            if mode == AnalysisDataMode.DEGRADED and not self.missing_reasons:
                raise ValueError("degraded 必须记录缺失原因")
            if mode == AnalysisDataMode.COMPLETE:
                if self.missing_reasons or any(item.effective_weight == 0 for item in self.dimension_assessments):
                    raise ValueError("complete 不得包含缺失维度或缺失原因")
            if mode == AnalysisDataMode.DEGRADED and not any(
                item.effective_weight == 0 for item in self.dimension_assessments
            ):
                raise ValueError("degraded 至少应有一个明确缺失且计零的维度")
        if self.schema_version == 1:
            if any(
                (
                    self.competition_profile,
                    self.calibration_contract_version,
                    self.calibration_events,
                    self.calibration_summary,
                )
            ):
                raise ValueError("AnalysisOutlook V1 不支持校准字段")
        else:
            if not self.competition_profile or self.calibration_contract_version not in {1, 2}:
                raise ValueError("AnalysisOutlook V2 必须声明赛事 profile 和校准契约 1/2")
            if mode == AnalysisDataMode.PASS:
                if self.calibration_events or self.calibration_summary is not None:
                    raise ValueError("pass 不得保留校准事件或校准后预测")
                return self
            if self.calibration_summary is None:
                raise ValueError("AnalysisOutlook V2 必须包含 calibration_summary")
            if self.competition_profile == "not_applicable":
                if self.calibration_events:
                    raise ValueError("非白名单赛事不得产生低稳定性校准事件")
            else:
                ids = [item.rule_id for item in self.calibration_events]
                expected_ids = (
                    CALIBRATION_RULE_IDS_V2
                    if self.calibration_contract_version == 2
                    else CALIBRATION_RULE_IDS
                )
                if len(ids) != len(set(ids)) or set(ids) != set(expected_ids):
                    raise ValueError(
                        f"白名单赛事必须逐项处置全部 {len(expected_ids)} 条校准规则"
                    )
            if self.one_x_two and (
                self.calibration_summary.one_x_two.final_ranking[:2] != self.one_x_two.choices
            ):
                raise ValueError("胜平负最终排序必须与 calibration_summary 一致")
            if self.fixed_handicap_1x2 and (
                self.calibration_summary.fixed_handicap_1x2.final_ranking[:2]
                != self.fixed_handicap_1x2.ranking.choices
            ):
                raise ValueError("固定让球最终排序必须与 calibration_summary 一致")
            self._validate_calibration_gate()
        return self

    def _validate_v3(self) -> "AnalysisOutlook":
        expected_contract = 7 if self.schema_version == 5 else 4 if self.schema_version == 4 else 3
        if self.calibration_contract_version != expected_contract or not self.competition_profile:
            raise ValueError(f"AnalysisOutlook V{self.schema_version} 必须声明 profile 和 calibration contract {expected_contract}")
        if self.schema_version in {4, 5}:
            if not self.analysis_input_mode or not self.profile_chain or not self.evaluation_bundle_sha256:
                raise ValueError("AnalysisOutlook V4/V5 必须绑定输入模式、profile 链和评估 bundle")
            if self.profile_chain[-1] != self.competition_profile:
                raise ValueError("AnalysisOutlook V4/V5 profile 链必须以精确 profile 结束")
        if self.dimension_assessments:
            raise ValueError("AnalysisOutlook V3 必须使用 score_matrix，不得混用旧维度评分")
        if not self.baseline_gate or not self.score_matrix or not self.baseline_summary_v3:
            raise ValueError("AnalysisOutlook V3 必须包含基础门禁、评分矩阵和基础汇总")
        expected = synthesize_baseline(self.score_matrix)
        if self.baseline_summary_v3.model_dump(mode="json") != expected.model_dump(mode="json"):
            raise ValueError("基础汇总必须由评分矩阵确定性合成")
        gate = self.baseline_gate
        mode = AnalysisDataMode(self.data_mode)
        no_primary_market = expected.primary_market is None
        if no_primary_market and mode != AnalysisDataMode.PASS:
            raise ValueError("可选主市场第一顺位或最高分差并列时必须 pass")
        if gate.decision == "pass":
            if mode != AnalysisDataMode.PASS or not self.pass_reasons:
                raise ValueError("基础门禁 pass 时分析输出必须 pass")
        elif gate.decision == "degraded":
            if mode != AnalysisDataMode.DEGRADED or not self.missing_reasons:
                raise ValueError("基础门禁 degraded 时分析输出必须 degraded")
        elif mode == AnalysisDataMode.PASS:
            if not self.pass_reasons:
                raise ValueError("pass 必须记录原因")
        if mode == AnalysisDataMode.PASS:
            if any((self.one_x_two, self.asian_handicap, self.fixed_handicap_1x2, self.total_goals, self.score_candidates)):
                raise ValueError("pass 不得保留预测输出")
            if self.calibration_events or self.total_goals_candidate_pool or self.score_candidate_pool or self.outcome_risk_pool:
                raise ValueError("pass 不得保留校准候选")
            return self
        if self.schema_version == 5:
            expected_markets = {"one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score"}
            if set(self.market_statuses) != expected_markets:
                raise ValueError("AnalysisOutlook V5 必须声明全部市场的 assessed/pass 状态")
            for market, status in self.market_statuses.items():
                reasons = self.market_pass_reasons.get(market, [])
                if status == MarketDecisionStatus.PASS:
                    if not reasons:
                        raise ValueError(f"{market} 为 pass 时必须记录原因")
                elif reasons:
                    raise ValueError(f"{market} 为 assessed 时不得填写 pass 原因")
            if self.market_statuses["one_x_two"] == MarketDecisionStatus.PASS and self.one_x_two is not None:
                raise ValueError("胜平负 pass 时不得保留输出")
            if self.market_statuses["asian_handicap"] == MarketDecisionStatus.PASS and self.asian_handicap is not None:
                raise ValueError("亚洲让球 pass 时不得保留输出")
            if self.market_statuses["fixed_handicap_1x2"] == MarketDecisionStatus.PASS and self.fixed_handicap_1x2 is not None:
                raise ValueError("固定让球胜平负 pass 时不得保留输出")
            if self.market_statuses["total_goals"] == MarketDecisionStatus.PASS:
                if self.total_goals is not None or self.total_goals_candidate_pool or self.total_goals_signal is not None:
                    raise ValueError("总进球 pass 时不得保留区间或候选")
            if self.market_statuses["score"] == MarketDecisionStatus.PASS:
                if self.score_candidates or self.score_candidate_pool:
                    raise ValueError("比分 pass 时不得保留候选")
            required_outputs = (
                ("one_x_two", self.one_x_two),
                ("asian_handicap", self.asian_handicap),
                ("fixed_handicap_1x2", self.fixed_handicap_1x2),
                ("total_goals", self.total_goals),
            )
            for market, output in required_outputs:
                if market == "total_goals":
                    continue
                if self.market_statuses[market] == MarketDecisionStatus.ASSESSED and output is None:
                    raise ValueError(f"{market} 为 assessed 时必须保留输出")
            if self.market_statuses["total_goals"] == MarketDecisionStatus.ASSESSED and not (self.total_goals or self.total_goals_signal):
                raise ValueError("总进球为 assessed 时必须保留经验证信号或规则候选")
            if self.market_statuses["score"] == MarketDecisionStatus.ASSESSED and len(self.score_candidates) != 2:
                raise ValueError("比分为 assessed 时必须恰好保留两个候选")
            return self
        if any(item is None for item in (self.one_x_two, self.asian_handicap, self.fixed_handicap_1x2, self.total_goals)):
            raise ValueError("V3 非 pass 必须包含四层市场输出")
        if len(self.score_candidates) != 2:
            raise ValueError("V3 非 pass 必须恰好保留两个比分")
        expected_ids = set(CALIBRATION_RULE_IDS_V4 if self.schema_version == 4 else CALIBRATION_RULE_IDS_V3)
        ids = [item.rule_id for item in self.calibration_events]
        if len(ids) != len(set(ids)) or set(ids) != expected_ids:
            raise ValueError("V3 必须逐项处置全部校准规则")
        baseline_markets = self.baseline_summary_v3.markets
        if set(self.experimental_rankings) != set(SCORE_MARKETS) or set(self.final_rankings) != set(SCORE_MARKETS):
            raise ValueError("V3 实验和最终排序必须且只能覆盖四个市场")

        def apply_ranking_candidates(market: str, *, adopted_only: bool) -> list[str]:
            ranking = list(baseline_markets[market].ranking)
            events = sorted(
                (
                    item
                    for item in self.calibration_events
                    if item.triggered
                    and item.effect == "ranking"
                    and item.target_market == market
                    and (not adopted_only or item.decision and item.decision.disposition == "adopted")
                ),
                key=lambda item: item.rule_id,
            )
            for item in events:
                index = ranking.index(item.target_selection)
                if index:
                    ranking[index - 1], ranking[index] = ranking[index], ranking[index - 1]
            return ranking

        for key, expected_market in SCORE_MARKETS.items():
            baseline = baseline_markets[key].ranking
            experimental = self.experimental_rankings.get(key)
            final = self.final_rankings.get(key)
            if experimental is None or final is None:
                raise ValueError("V3 必须保存每个市场的基础、实验和最终排序")
            if set(experimental) != set(expected_market) or set(final) != set(expected_market):
                raise ValueError("实验和最终排序不得增删市场候选")
            if experimental != apply_ranking_candidates(key, adopted_only=False):
                raise ValueError("实验排序必须逐条反映所有已触发排序规则")
            if final != apply_ranking_candidates(key, adopted_only=True):
                raise ValueError("最终排序只能反映已采纳的排序规则")
            if final[0] != baseline[0]:
                supporting = [
                    item for item in self.calibration_events
                    if item.triggered and item.effect == "ranking" and item.target_market == key
                    and item.target_selection == final[0]
                    and item.decision and item.decision.disposition == "adopted"
                ]
                independent = any(
                    not (set(left.source_snapshot_ids) & set(right.source_snapshot_ids))
                    and not (set(left.correlation_keys) & set(right.correlation_keys))
                    for index, left in enumerate(supporting) for right in supporting[index + 1 :]
                )
                if len(supporting) < 2 or not independent or not self.anchor_change_reason or not self.decision_actor:
                    raise ValueError("第一顺位换位需要两条独立已采纳规则、理由和操作者标签")
        assert self.one_x_two is not None
        assert self.asian_handicap is not None
        assert self.fixed_handicap_1x2 is not None
        if self.one_x_two.choices != self.final_rankings["one_x_two"][:2]:
            raise ValueError("胜平负输出必须匹配最终排序前两位")
        if self.asian_handicap.ranking.choices != self.final_rankings["asian_handicap"]:
            raise ValueError("亚洲让球输出必须匹配最终排序")
        if self.fixed_handicap_1x2.ranking.choices != self.final_rankings["fixed_handicap_1x2"][:2]:
            raise ValueError("固定让球输出必须匹配最终排序前两位")

        events_by_id = {item.rule_id: item for item in self.calibration_events}
        pools = (
            ("total_goals_pool", self.total_goals_candidate_pool),
            ("score_pool", self.score_candidate_pool),
            ("outcome_risk_pool", self.outcome_risk_pool),
        )
        for effect, pool in pools:
            for candidate in pool:
                if self.schema_version == 4 and candidate.rule_id == "baseline":
                    continue
                event = events_by_id.get(candidate.rule_id)
                if event is None or not event.triggered:
                    raise ValueError("候选池不得引用未触发或未知规则")
                if event.effect != effect and not (
                    candidate.rule_id == "korea-deep-line-loss-tolerance-v1" and effect == "score_pool"
                ):
                    raise ValueError("候选池规则影响面与配置不一致")
        for event in self.calibration_events:
            if not event.triggered:
                continue
            if self.schema_version == 4 and event.effect == "control":
                continue
            if event.effect == "total_goals_pool" and not any(item.rule_id == event.rule_id for item in self.total_goals_candidate_pool):
                raise ValueError("已触发总进球规则必须形成总进球候选")
            if event.effect == "score_pool" and not any(item.rule_id == event.rule_id for item in self.score_candidate_pool):
                raise ValueError("已触发比分规则必须形成比分候选")
            if event.effect == "outcome_risk_pool" and not any(item.rule_id == event.rule_id for item in self.outcome_risk_pool):
                raise ValueError("已触发结果风险规则必须形成风险候选")
        if events_by_id["korea-deep-line-loss-tolerance-v1"].triggered and not any(
            item.rule_id == "korea-deep-line-loss-tolerance-v1" and item.score == "0-1"
            for item in self.score_candidate_pool
        ):
            raise ValueError("韩国深盘输球风险触发时必须登记 0-1 比分风险候选")
        adopted_total = [item for item in self.total_goals_candidate_pool if item.decision.disposition == "adopted"]
        if len(adopted_total) != 1 or (adopted_total[0].minimum, adopted_total[0].maximum) != (self.total_goals.minimum, self.total_goals.maximum):
            raise ValueError("最终总进球必须匹配唯一已采纳候选")
        adopted_scores = [item.score for item in self.score_candidate_pool if item.decision.disposition == "adopted"]
        if len(adopted_scores) != 2 or set(adopted_scores) != set(self.score_candidates):
            raise ValueError("最终比分必须匹配两个已采纳比分候选")
        if self.anchor_change_reason and not self.decision_actor:
            raise ValueError("换位理由必须记录操作者标签")
        return self

    def _validate_calibration_gate(self) -> None:
        assert self.calibration_summary is not None
        summaries = {
            "one_x_two": self.calibration_summary.one_x_two,
            "fixed_handicap_1x2": self.calibration_summary.fixed_handicap_1x2,
        }
        for market, summary in summaries.items():
            for item in self.calibration_events:
                if item.target_market != market:
                    continue
                if item.before_ranking != summary.baseline_ranking:
                    raise ValueError(f"{market} 校准事件基础排序与 summary 不一致")
                if item.triggered and item.final_ranking != summary.final_ranking:
                    raise ValueError(f"{market} 已触发事件最终排序与 summary 不一致")
            eligible = False
            events = [
                item
                for item in self.calibration_events
                if item.triggered
                and item.target_market == market
                and item.adjustment_level > 0
                and item.target_selection != summary.baseline_ranking[0]
            ]
            for index, left in enumerate(events):
                for right in events[index + 1 :]:
                    if left.target_selection != right.target_selection:
                        continue
                    if set(left.source_snapshot_ids) & set(right.source_snapshot_ids):
                        continue
                    if set(left.source_dimensions) == set(right.source_dimensions):
                        continue
                    if set(left.correlation_keys) & set(right.correlation_keys):
                        continue
                    left_dims = {str(item) for item in left.source_dimensions}
                    right_dims = {str(item) for item in right.source_dimensions}
                    odds_kelly = {"european_odds", "kelly_index"}
                    if (
                        set(left.source_provider_ids) & set(right.source_provider_ids)
                        and left_dims <= odds_kelly
                        and right_dims <= odds_kelly
                    ):
                        continue
                    eligible = True
                    break
                if eligible:
                    break
            if summary.anchor_change_eligible != eligible:
                raise ValueError(f"{market} anchor_change_eligible 与数据血缘门禁不一致")
            if not eligible and summary.final_ranking[0] != summary.baseline_ranking[0]:
                raise ValueError(f"{market} 未满足独立双规则门禁，不得改变第一顺位")


class MatchSettlement(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    asian_selection: Selection
    asian_result: AsianSettlement
    fixed_handicap_result: FixedHandicapResult
    total_goals_range_hit: bool | None = None
    score_candidate_hit: bool | None = None


MARKET_SELECTIONS = {
    PrimaryMarket.ONE_X_TWO: {Selection.HOME, Selection.DRAW, Selection.AWAY},
    PrimaryMarket.HANDICAP: {Selection.HOME_HANDICAP, Selection.AWAY_HANDICAP},
    PrimaryMarket.TOTAL_GOALS: {Selection.OVER, Selection.UNDER},
    PrimaryMarket.PASS: {Selection.PASS},
}


class MatchMetadata(BaseModel):
    model_config = ConfigDict(use_enum_values=True, validate_assignment=True)

    schema_version: int = 1
    match_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    supersedes_match_id: str | None = None
    kickoff_at: datetime
    timezone: str = "Asia/Shanghai"
    competition_code: str = Field(min_length=1)
    competition: str = Field(min_length=1)
    season: int | None = None
    home_team_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    home_team: str = Field(min_length=1)
    away_team_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    away_team: str = Field(min_length=1)
    status: MatchStatus = MatchStatus.DRAFT
    record_integrity: RecordIntegrity = RecordIntegrity.COMPLETE
    analysis_started_at: datetime
    data_cutoff_at: datetime | None = None
    locked_at: datetime | None = None
    prematch_lock_sha256: str | None = None
    primary_market: PrimaryMarket | None = None
    primary_selection: Selection | None = None
    secondary_selection: Selection | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    result_recorded_at: datetime | None = None
    result_source: str | None = None
    reviewed_at: datetime | None = None
    void_reason: str | None = None
    score: str | None = None
    result_1x2: Result1X2 | None = None
    handicap_result: HandicapResult | None = None
    total_goals: int | None = Field(default=None, ge=0)
    key_events: str | None = None
    live_update_changed_main: bool | None = None
    tags: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    market_snapshots: list[MarketSnapshot] = Field(default_factory=list)
    analysis_outlook: AnalysisOutlook | None = None
    settlement: MatchSettlement | None = None
    evaluation: Evaluation = Field(default_factory=Evaluation)

    @field_validator(
        "kickoff_at",
        "analysis_started_at",
        "data_cutoff_at",
        "locked_at",
        "result_recorded_at",
        "reviewed_at",
    )
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("时间必须包含时区")
        return value

    @field_validator("timezone")
    @classmethod
    def require_known_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区：{value}") from exc
        return value

    @field_validator("tags", "data_sources")
    @classmethod
    def require_unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("列表中存在重复值")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "MatchMetadata":
        if self.schema_version not in {1, 2}:
            raise ValueError("仅支持 schema_version=1/2")
        if self.home_team_id == self.away_team_id:
            raise ValueError("主客队不能相同")
        if self.supersedes_match_id == self.match_id:
            raise ValueError("比赛不能关联自身为前序记录")

        market = PrimaryMarket(self.primary_market) if self.primary_market else None
        selection = Selection(self.primary_selection) if self.primary_selection else None
        if market and selection and selection not in MARKET_SELECTIONS[market]:
            raise ValueError(f"{selection.value} 不适用于 {market.value}")
        if market and not selection and self.status in {
            MatchStatus.LOCKED,
            MatchStatus.FINISHED,
            MatchStatus.REVIEWED,
        }:
            raise ValueError("锁定后必须填写 primary_selection")
        if selection and not market:
            raise ValueError("填写 primary_selection 时必须填写 primary_market")
        if market == PrimaryMarket.PASS and self.confidence is not None:
            raise ValueError("pass 不填写 confidence")

        if self.schema_version == 1 and any(
            (self.market_snapshots, self.analysis_outlook is not None, self.settlement is not None)
        ):
            raise ValueError("schema_version=1 不支持结构化盘口、四层输出或自动结算")
        if self.schema_version == 2:
            if len({snapshot.snapshot_id for snapshot in self.market_snapshots}) != len(
                self.market_snapshots
            ):
                raise ValueError("market_snapshots 中 snapshot_id 重复")
            if self.analysis_outlook:
                mode = AnalysisDataMode(self.analysis_outlook.data_mode)
                snapshot_ids = {snapshot.snapshot_id for snapshot in self.market_snapshots}
                for assessment in self.analysis_outlook.dimension_assessments:
                    if assessment.effective_weight == 0:
                        continue
                    snapshot_refs = {
                        ref.removeprefix("snapshot:")
                        for ref in assessment.fact_refs
                        if ref.startswith("snapshot:")
                    }
                    if not snapshot_refs:
                        raise ValueError(f"{assessment.dimension} 必须引用至少一个结构化盘口快照")
                    missing_refs = snapshot_refs - snapshot_ids
                    if missing_refs:
                        raise ValueError("分析维度引用不存在的快照：" + ", ".join(sorted(missing_refs)))
                macau_phases = {
                    str(snapshot.phase)
                    for snapshot in self.market_snapshots
                    if str(snapshot.market) == MarketType.ASIAN_HANDICAP.value
                    and snapshot.provider_id == "macau"
                    and str(snapshot.odds_format) == OddsFormat.HONG_KONG.value
                    and "home_line" in snapshot.normalized_values
                    and ({"home_water", "away_water"} & set(snapshot.normalized_values))
                }
                macau_complete = {"opening", "mid", "late"}.issubset(macau_phases)
                if not macau_complete and mode == AnalysisDataMode.COMPLETE:
                    raise ValueError("缺少澳门亚盘或初盘/中盘/临盘三个可比节点时不得使用 complete")
                if mode == AnalysisDataMode.PASS:
                    if market not in {None, PrimaryMarket.PASS} or selection not in {
                        None,
                        Selection.PASS,
                    }:
                        raise ValueError("V2 pass 必须与兼容字段保持一致")
                elif market == PrimaryMarket.PASS:
                    raise ValueError("非 pass 四层输出不能使用 primary_market=pass")
                if mode == AnalysisDataMode.DEGRADED and self.confidence is not None:
                    if self.confidence > 0.69:
                        raise ValueError("degraded 分析置信度不得超过 0.69")

        status = MatchStatus(self.status)
        if status in {MatchStatus.LOCKED, MatchStatus.FINISHED, MatchStatus.REVIEWED}:
            if not all((self.data_cutoff_at, self.locked_at, self.prematch_lock_sha256)):
                raise ValueError("locked/finished/reviewed 必须包含锁定时间、截止时间和哈希")
            if not re.fullmatch(r"[0-9a-f]{64}", self.prematch_lock_sha256 or ""):
                raise ValueError("prematch_lock_sha256 格式无效")
            if market != PrimaryMarket.PASS and self.confidence is None:
                raise ValueError("非 pass 结论必须填写 confidence")
            if self.schema_version == 2 and self.analysis_outlook is None:
                raise ValueError("V2 锁定后必须包含 analysis_outlook")
        if status in {MatchStatus.FINISHED, MatchStatus.HISTORICAL_FINISHED, MatchStatus.REVIEWED}:
            if not all((self.score, self.result_1x2, self.result_recorded_at)):
                raise ValueError("finished/historical_finished/reviewed 必须包含比分、胜平负结果和记录时间")
            if self.total_goals is None:
                raise ValueError("finished/historical_finished/reviewed 必须包含总进球")
            if status != MatchStatus.HISTORICAL_FINISHED and self.schema_version == 2 and self.settlement is None:
                raise ValueError("V2 finished/reviewed 必须包含自动结算结果")
            if (status == MatchStatus.HISTORICAL_FINISHED or self.schema_version == 2) and not self.result_source:
                raise ValueError("historical_finished 与 V2 finished/reviewed 必须包含赛果来源")
        if status == MatchStatus.HISTORICAL_FINISHED:
            if any((self.data_cutoff_at, self.locked_at, self.prematch_lock_sha256, self.settlement)):
                raise ValueError("historical_finished 不得伪造赛前锁定或自动结算")
        if status == MatchStatus.REVIEWED:
            if not self.reviewed_at:
                raise ValueError("reviewed 必须包含 reviewed_at")
            if self.evaluation.primary == EvaluationValue.PENDING:
                raise ValueError("reviewed 必须评价主线")
        if status == MatchStatus.VOID and not self.void_reason:
            raise ValueError("void 必须填写原因")

        if self.score:
            match = re.fullmatch(r"(\d+)-(\d+)", self.score)
            if not match:
                raise ValueError("score 必须使用 H-A 格式，例如 2-1")
            goals = int(match.group(1)) + int(match.group(2))
            if self.total_goals is not None and goals != self.total_goals:
                raise ValueError("total_goals 与 score 不一致")
        return self
