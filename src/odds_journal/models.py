from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MatchStatus(StrEnum):
    DRAFT = "draft"
    TRACKING = "tracking"
    LOCKED = "locked"
    FINISHED = "finished"
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


class AnalysisOutlook(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

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
        return self


class MatchSettlement(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    asian_selection: Selection
    asian_result: AsianSettlement
    fixed_handicap_result: FixedHandicapResult
    total_goals_range_hit: bool
    score_candidate_hit: bool


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
        if status in {MatchStatus.FINISHED, MatchStatus.REVIEWED}:
            if not all((self.score, self.result_1x2, self.result_recorded_at)):
                raise ValueError("finished/reviewed 必须包含比分、胜平负结果和记录时间")
            if self.total_goals is None:
                raise ValueError("finished/reviewed 必须包含总进球")
            if self.schema_version == 2 and self.settlement is None:
                raise ValueError("V2 finished/reviewed 必须包含自动结算结果")
            if self.schema_version == 2 and not self.result_source:
                raise ValueError("V2 finished/reviewed 必须包含赛果来源")
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
