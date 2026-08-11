"""Knowledge Engine 检索模型。

定义知识查询、检索回执和假设图。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeQueryPlanV1(BaseModel):
    """知识查询计划。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    query_id: str = Field(min_length=1)
    match_id: str
    as_of: datetime
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 分层查询策略
    foundation_card_ids: tuple[str, ...] = Field(default_factory=tuple)
    general_filters: dict[str, list[str]] = Field(default_factory=dict)
    market_filters: dict[str, list[str]] = Field(default_factory=dict)
    competition_filters: dict[str, list[str]] = Field(default_factory=dict)
    scenario_filters: dict[str, list[str]] = Field(default_factory=dict)
    cross_market_audit_only: bool = True

    # 限制
    max_per_market: int = Field(default=12, ge=1, le=20)
    max_total: int = Field(default=40, ge=1, le=60)

    # 缓存
    cache_key: str = Field(min_length=1)

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        return value


class KnowledgeRetrievalReceiptV1(BaseModel):
    """知识检索回执。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    retrieval_id: str = Field(min_length=1)
    query_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retriever_version: str = Field(min_length=1)

    # 检索结果分组
    mandatory_policy_cards: tuple[str, ...] = Field(default_factory=tuple)
    retrieved_decision_cards: tuple[str, ...] = Field(default_factory=tuple)
    retrieved_explanation_cards: tuple[str, ...] = Field(default_factory=tuple)
    counter_and_conflict_cards: tuple[str, ...] = Field(default_factory=tuple)

    # 性能
    retrieval_time_ms: float = Field(ge=0)
    fts5_query_count: int = Field(ge=0)

    retrieval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class HypothesisGraphV1(BaseModel):
    """假设图 — 记录每个市场的支持假设、反证和失效条件。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    hypotheses: dict[str, dict[str, str]] = Field(min_length=1)

    # 每个市场必须包含: supporting_hypothesis, counter_hypothesis, invalidation_condition
    @field_validator("hypotheses")
    @classmethod
    def validate_hypothesis_structure(cls, value: dict) -> dict:
        required = {"supporting_hypothesis", "counter_hypothesis", "invalidation_condition"}
        for market, hypotheses in value.items():
            if set(hypotheses) != required:
                raise ValueError(f"{market} 双向假设不完整")
            if any(not text for text in hypotheses.values()):
                raise ValueError(f"{market} 假设内容不得为空")
        return value