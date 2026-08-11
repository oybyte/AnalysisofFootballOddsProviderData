"""Knowledge Engine 裁决与决策模型。

定义裁决权限合约、评估包、草稿候选和构建回执。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── 裁决权限合约 ──────────────────────────────────────────


class DecisionAuthorityContractV1(BaseModel):
    """裁决权限合约。

    定义裁决优先级和固定规则。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    contract_id: str = Field(min_length=1)

    # 优先级
    priority_order: tuple[
        Literal[
            "force_pass",
            "suppress_candidate",
            "confidence_cap",
            "degrade",
            "bounded_rank_adjustment",
            "support_existing_direction",
            "explain",
        ],
        ...,
    ] = (
        "force_pass",
        "suppress_candidate",
        "confidence_cap",
        "degrade",
        "bounded_rank_adjustment",
        "support_existing_direction",
        "explain",
    )

    # 固定规则
    single_card_cannot_flip: bool = True
    anchor_change_requires_two_independent: bool = True
    same_source_family_counts_as_one: bool = True
    no_netting_positive_negative: bool = True
    same_level_conflict_downgrade: bool = True
    anchor_change_downgrades_confidence: bool = True
    max_confidence_after_anchor_change: float = Field(default=0.69, ge=0, le=1)
    knowledge_only_reduces_confidence: bool = True
    baseline_pass_never_reopen: bool = True
    advisory_separate_channel: bool = True
    research_only_postmatch: bool = True


# ── 知识评估包 ────────────────────────────────────────────


class KnowledgeEvaluationBundleV1(BaseModel):
    """知识评估包 V1。

    包含裁决结果、候选排序和裁决日志。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    as_of: datetime

    # 输入绑定
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authority_contract_id: str

    # 市场裁决
    market_decisions: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # 裁决日志
    adjudication_log: tuple[str, ...] = Field(default_factory=tuple)

    # 置信度
    confidence: float | None = Field(default=None, ge=0, le=1)
    degraded: bool = False
    degraded_reasons: tuple[str, ...] = Field(default_factory=tuple)

    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        return value


# ── 知识草稿候选 ──────────────────────────────────────────


class KnowledgeDraftCandidateV1(BaseModel):
    """知识草稿候选 V1。

    内容寻址的候选，不直接写正式 Match。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    as_of: datetime

    # 输入绑定
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 市场候选
    market_candidates: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # 合约
    contract_version: Literal[9] = 9

    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        return value


# ── 知识草稿构建回执 ──────────────────────────────────────


class KnowledgeDraftBuildReceiptV1(BaseModel):
    """知识草稿构建回执 V1。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    built_at: datetime
    as_of: datetime

    # 输入绑定
    ruleset_id: str
    ruleset_version: str
    ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 候选
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    compiler_version: str = "knowledge-engine-v1"
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("built_at", "as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value