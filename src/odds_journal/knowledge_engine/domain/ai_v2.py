"""Knowledge Engine AI V2 模型。

AI V2 与 AI V1 使用独立模型和目录，不得迁移、重算或覆盖。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AIAdvisoryInputReceiptV1(BaseModel):
    """AI V2 旁路输入回执。

    AI 输入仅包含白名单事实、知识、案例和证据 ID。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str = Field(min_length=1)
    match_id: str
    study_id: str
    run_id: str

    # 白名单输入
    fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    knowledge_card_ids: tuple[str, ...] = Field(default_factory=tuple)
    case_ids: tuple[str, ...] = Field(default_factory=tuple)
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)

    # 输入绑定
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 模型信息
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    created_at: datetime
    input_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at 必须包含时区")
        return value


class AIAnalysisCandidateV1(BaseModel):
    """AI V2 分析候选 — AI 生成的提示候选。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    candidate_id: str = Field(min_length=1)
    match_id: str
    study_id: str
    run_id: str

    # 输入绑定
    input_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 模型信息
    provider_id: str
    model_id: str
    model_version: str | None = None

    # AI 输出
    raw_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parsed_output: dict[str, Any] = Field(default_factory=dict)

    # Token 用量
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    # 状态
    status: Literal["success", "unavailable", "failed", "not_run"] = "success"
    failure_reason: str | None = None

    generated_at: datetime
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("generated_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at 必须包含时区")
        return value


class AICandidateComparisonV1(BaseModel):
    """AI V2 候选比较 — AI 与确定性结果的对比。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    comparison_id: str = Field(min_length=1)
    match_id: str
    study_id: str
    run_id: str

    # 确定性候选
    deterministic_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # AI 候选
    ai_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 差异
    agreement: dict[str, bool] = Field(default_factory=dict)
    divergence_markets: tuple[str, ...] = Field(default_factory=tuple)
    divergence_details: dict[str, str] = Field(default_factory=dict)

    compared_at: datetime
    comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("compared_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("compared_at 必须包含时区")
        return value


class AIAdvisoryReceiptV1(BaseModel):
    """AI V2 旁路回执。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str = Field(min_length=1)
    match_id: str
    study_id: str
    run_id: str

    # 输入/输出绑定
    input_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ai_candidate_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    comparison_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    # 状态
    advisory_status: Literal["completed", "unavailable", "failed", "not_run"] = "not_run"

    completed_at: datetime | None = None
    advisory_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")