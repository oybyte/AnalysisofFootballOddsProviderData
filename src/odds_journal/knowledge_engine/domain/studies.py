"""Knowledge Engine 前瞻研究模型。

定义 Study、Primary、Exposure、Outcome 和 Failure 台账。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── 官方基线快照 ──────────────────────────────────────────


class OfficialBaselineSnapshotV1(BaseModel):
    """官方基线快照 — 冻结 1.8.0 正式赛前 Outlook 和报告。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    as_of: datetime
    kickoff_at: datetime

    # 正式分析产物引用
    analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    outlook_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    lock_candidate_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    # 基线状态
    baseline_valid: bool = True
    baseline_invalid_reason: str | None = None

    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of", "kickoff_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value


# ── 前瞻 Study ────────────────────────────────────────────


class KnowledgeProspectiveStudyV1(BaseModel):
    """前瞻 Study 注册。

    每个 Study 定义研究范围、cohort 和停止条件。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    study_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    study_name: str = Field(min_length=1)
    proposal_id: str = "football-analysis"
    proposal_version: str = "2.0.0"

    # 研究范围
    target_markets: tuple[Literal["one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"], ...] = Field(
        min_length=1
    )
    target_cohort_size: int = Field(ge=20)
    stop_conditions: tuple[str, ...] = Field(default_factory=tuple)
    exclusion_conditions: tuple[str, ...] = Field(default_factory=tuple)

    # 注册信息
    registered_at: datetime
    registered_by: Literal["lcz"]
    status: Literal["active", "completed", "terminated", "superseded"] = "active"

    study_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("registered_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registered_at 必须包含时区")
        return value


# ── Study Run ─────────────────────────────────────────────


class KnowledgeStudyRunV1(BaseModel):
    """Study 单场运行记录。

    每个 study_id + match_id + snapshot_sha 只能有一个 primary run。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    study_id: str
    match_id: str
    run_at: datetime
    kickoff_at: datetime

    # 快照绑定
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    # 运行类型
    run_type: Literal["primary", "counterfactual"] = "primary"
    primary_run: bool = True

    # 结果
    run_status: Literal["completed", "failed", "exposed", "not_run"] = "completed"

    run_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("run_at", "kickoff_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_primary_constraint(self) -> "KnowledgeStudyRunV1":
        if self.primary_run and self.run_at >= self.kickoff_at:
            raise ValueError("Primary run 必须在开赛前执行")
        if self.run_type == "counterfactual" and self.primary_run:
            raise ValueError("counterfactual 运行不能标记为 primary")
        return self


# ── Primary Claim ─────────────────────────────────────────


class KnowledgeStudyPrimaryClaimV1(BaseModel):
    """Study Primary Claim。

    每个 study_id + match_id + snapshot_sha 唯一。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    claim_id: str = Field(min_length=1)
    study_id: str
    match_id: str
    run_id: str
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 候选
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    claimed_at: datetime
    claim_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("claimed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("claimed_at 必须包含时区")
        return value


# ── Exposure Event ────────────────────────────────────────


class KnowledgeStudyExposureEventV1(BaseModel):
    """Study Exposure 事件。

    显式暴露后追加，不可撤销。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str = Field(min_length=1)
    study_id: str
    match_id: str
    run_id: str
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    exposed_at: datetime
    exposed_by: Literal["lcz"]
    exposure_reason: str = Field(min_length=1)

    exposure_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("exposed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("exposed_at 必须包含时区")
        return value


# ── Study Outcome ─────────────────────────────────────────


class KnowledgeStudyOutcomeV1(BaseModel):
    """Study Outcome — 完赛后追加。

    纠错必须追加带 supersedes_event_id 的新事件。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    outcome_id: str = Field(min_length=1)
    study_id: str
    match_id: str
    run_id: str

    # 赛果
    final_score: str | None = None
    result_one_x_two: Literal["home", "draw", "away"] | None = None
    result_handicap: Literal["home_handicap", "away_handicap", "push"] | None = None
    total_goals: int | None = Field(default=None, ge=0)

    # 评估
    market_outcomes: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # 纠错
    supersedes_event_id: str | None = None

    recorded_at: datetime
    outcome_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at 必须包含时区")
        return value


# ── Rendered Official Baseline ────────────────────────────


class RenderedOfficialBaselineV1(BaseModel):
    """赛前渲染后的正式基线快照。

    替代以锁定文件为基线的旧适配器。要求已成功 validate-draft 和
    render-draft，且 as_of < validated_at <= rendered_at < kickoff_at。
    不要求 lock，也不得把 lock 后产物作为 Primary 基线。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str = Field(min_length=1)
    as_of: datetime
    kickoff_at: datetime

    # 正式分析产物引用（1.8.0 Contract 7/8 可解析版本）
    analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_input_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evaluation_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    analysis_outlook_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    rendered_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    # 时间戳
    validated_at: datetime
    rendered_at: datetime

    # 基线状态
    ruleset_id: str = Field(min_length=1)
    ruleset_version: str = Field(min_length=1)
    has_result: bool = False
    has_post_kickoff_observation: bool = False

    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of", "kickoff_at", "validated_at", "rendered_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_time_ordering(self) -> "RenderedOfficialBaselineV1":
        if self.as_of >= self.kickoff_at:
            raise ValueError("as_of 必须在 kickoff_at 之前")
        if self.validated_at <= self.as_of:
            raise ValueError("validated_at 必须晚于 as_of")
        if self.rendered_at < self.validated_at:
            raise ValueError("rendered_at 不能早于 validated_at")
        if self.rendered_at >= self.kickoff_at:
            raise ValueError("rendered_at 必须在 kickoff_at 之前")
        if self.has_result:
            raise ValueError("基线存在赛果，拒绝冻结")
        if self.has_post_kickoff_observation:
            raise ValueError("基线存在赛后观测，拒绝冻结")
        return self


# ── 统一台账事件 ──────────────────────────────────────────


class StudyEventType(StrEnum):
    """Study 台账事件类型。"""

    STUDY_REGISTERED = "study_registered"
    PRIMARY_CLAIMED = "primary_claimed"
    EXPOSED = "exposed"
    OUTCOME_RECORDED = "outcome_recorded"
    FAILURE_RECORDED = "failure_recorded"
    AI_ADVISORY_RECORDED = "ai_advisory_recorded"


class KnowledgeStudyLedgerEventV1(BaseModel):
    """统一 Study 台账事件 V1。

    所有 Study 事件采用统一格式，支持幂等键、哈希校验和 supersedes 链。
    JSONL 任一行不可解析、哈希错误或 supersedes 链断裂时 fail closed。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str = Field(min_length=1)
    event_type: StudyEventType
    aggregate_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    recorded_at: datetime

    payload: dict[str, Any] = Field(default_factory=dict)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    supersedes_event_id: str | None = None
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_payload_hash(self) -> "KnowledgeStudyLedgerEventV1":
        import hashlib
        import json

        recomputed = hashlib.sha256(
            json.dumps(self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        if recomputed != self.payload_sha256:
            raise ValueError("payload_sha256 与 payload 不一致")
        return self


# ── Study 状态机 ──────────────────────────────────────────


class StudyState(StrEnum):
    """Study 状态机固定状态。"""

    REGISTERED = "registered"
    BASELINE_READY = "baseline_ready"
    PRIMARY_SEALED = "primary_sealed"
    EXPOSED = "exposed"
    OFFICIAL_LOCKED = "official_locked"
    COMPLETED = "completed"
    EVALUATED = "evaluated"
    REPORTED = "reported"


# ── Study Failure ─────────────────────────────────────────


class KnowledgeStudyFailureV1(BaseModel):
    """Study Failure 事件 — 运行失败封存。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    failure_id: str = Field(min_length=1)
    study_id: str
    match_id: str
    run_id: str | None = None

    failure_type: Literal["index_corrupted", "snapshot_inconsistent", "ai_unavailable", "timeout", "write_error", "other"]
    failure_message: str = Field(min_length=1)
    failure_context: dict[str, Any] = Field(default_factory=dict)

    recorded_at: datetime
    failure_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at 必须包含时区")
        return value
