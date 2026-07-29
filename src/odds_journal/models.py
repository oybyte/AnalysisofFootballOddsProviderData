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
        if self.schema_version != 1:
            raise ValueError("仅支持 schema_version=1")
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

        status = MatchStatus(self.status)
        if status in {MatchStatus.LOCKED, MatchStatus.FINISHED, MatchStatus.REVIEWED}:
            if not all((self.data_cutoff_at, self.locked_at, self.prematch_lock_sha256)):
                raise ValueError("locked/finished/reviewed 必须包含锁定时间、截止时间和哈希")
            if not re.fullmatch(r"[0-9a-f]{64}", self.prematch_lock_sha256 or ""):
                raise ValueError("prematch_lock_sha256 格式无效")
            if market != PrimaryMarket.PASS and self.confidence is None:
                raise ValueError("非 pass 结论必须填写 confidence")
        if status in {MatchStatus.FINISHED, MatchStatus.REVIEWED}:
            if not all((self.score, self.result_1x2, self.result_recorded_at)):
                raise ValueError("finished/reviewed 必须包含比分、胜平负结果和记录时间")
            if self.total_goals is None:
                raise ValueError("finished/reviewed 必须包含总进球")
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
