"""Knowledge Engine 核心知识模型。

定义 KnowledgeCardV1、知识层级、知识类别及其他基础类型。
所有领域对象使用 frozen=True 的 Pydantic 模型。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── 知识层级 ──────────────────────────────────────────────


class KnowledgeTier(StrEnum):
    """知识层级，从基础到跨市场。"""

    FOUNDATION = "foundation"
    GENERAL = "general"
    MARKET = "market"
    COMPETITION = "competition"
    SCENARIO = "scenario"
    CROSS_MARKET = "cross_market"


# ── 知识类别 ──────────────────────────────────────────────


class KnowledgeCategory(StrEnum):
    """知识类别，决定裁决中的适用方式。"""

    POLICY_KERNEL = "policy_kernel"
    DECISION_POLICY = "decision_policy"
    ADVISORY = "advisory"
    RESEARCH_ONLY = "research_only"


# ── 来源轨道 ──────────────────────────────────────────────


class SourceTrack(StrEnum):
    """知识来源轨道。"""

    PUBLISHED_RULESET = "published_ruleset"
    PROPOSAL_RULESET = "proposal_ruleset"
    EXPERIMENT_ACTIVE = "experiment_active"
    AI_RESEARCH = "ai_research"


# ── 知识效果 ──────────────────────────────────────────────


class KnowledgeEffect(StrEnum):
    """知识卡片允许的效果类型。"""

    FORCE_PASS = "force_pass"
    SUPPRESS_CANDIDATE = "suppress_candidate"
    CONFIDENCE_CAP = "confidence_cap"
    DEGRADE = "degrade"
    BOUNDED_RANK_ADJUSTMENT = "bounded_rank_adjustment"
    SUPPORT_EXISTING_DIRECTION = "support_existing_direction"
    EXPLAIN = "explain"


# ── 卡片状态 ──────────────────────────────────────────────


class CardStatus(StrEnum):
    """知识卡片状态。"""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"
    CONFLICTED = "conflicted"


# ── 迁移处置 ──────────────────────────────────────────────


class MigrationDisposition(StrEnum):
    """来源规则在迁移中的处置方式。"""

    MIGRATED = "migrated"
    CONSOLIDATED = "consolidated"
    ADVISORY = "advisory"
    RESEARCH = "research"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    DEFERRED = "deferred"


# ── 1.7.0 处置 ────────────────────────────────────────────


class Ruleset170Disposition(StrEnum):
    """1.7.0 发布前处置方式。"""

    CONTINUE_PARALLEL = "continue_parallel"
    DEACTIVATE_AFTER_2_0_RELEASE = "deactivate_after_2_0_release"
    ARCHIVE_WITHOUT_ACTIVATION = "archive_without_activation"


# ── 能力状态 ──────────────────────────────────────────────


class CapabilityStatus(StrEnum):
    """知识引擎能力状态。"""

    IMPLEMENTED_DISABLED = "implemented_disabled"
    SHADOW_READY = "shadow_ready"
    STUDY_ACTIVE = "study_active"
    RELEASE_ELIGIBLE = "release_eligible"
    FORMAL_ACTIVE = "formal_active"


# ── 知识卡片 ──────────────────────────────────────────────


class KnowledgeCardV1(BaseModel):
    """冻结的知识卡片，不可变的知识单元。

    每张卡片记录一个知识原子，包含适用条件、效果、来源血缘和冲突关系。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # 身份
    card_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    version: Literal[1] = 1
    tier: KnowledgeTier
    category: KnowledgeCategory
    source_track: SourceTrack

    # 适用条件
    applicable_markets: tuple[Literal["one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"], ...] = Field(
        min_length=1
    )
    required_features: tuple[str, ...] = Field(default_factory=tuple)
    numerical_boundaries: dict[str, dict[str, float]] = Field(default_factory=dict)
    interpretation: str = Field(min_length=1)

    # 条件
    support_conditions: tuple[str, ...] = Field(default_factory=tuple)
    counter_conditions: tuple[str, ...] = Field(default_factory=tuple)
    invalidation_conditions: tuple[str, ...] = Field(default_factory=tuple)

    # 效果
    allowed_effects: tuple[KnowledgeEffect, ...] = Field(min_length=1)
    max_adjustment: float = Field(ge=0, le=1)

    # 来源
    provenance_group: str = Field(min_length=1)
    source_family: str = Field(min_length=1)
    observation_lineage: tuple[str, ...] = Field(default_factory=tuple)
    conflicts: tuple[str, ...] = Field(default_factory=tuple)
    counter_cards: tuple[str, ...] = Field(default_factory=tuple)
    supersedes: tuple[str, ...] = Field(default_factory=tuple)

    # 原规则追溯
    original_rule_id: str | None = None
    original_ruleset_id: str | None = None
    original_ruleset_version: str | None = None
    original_file_path: str | None = None
    original_file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    original_line_range: tuple[int, int] | None = None

    # 状态
    status: CardStatus = CardStatus.ACTIVE
    card_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("applicable_markets")
    @classmethod
    def unique_markets(cls, value: tuple) -> tuple:
        if len(set(value)) != len(value):
            raise ValueError("applicable_markets 不得重复")
        return value

    @model_validator(mode="after")
    def validate_card(self) -> "KnowledgeCardV1":
        if self.category == KnowledgeCategory.POLICY_KERNEL:
            if KnowledgeEffect.FORCE_PASS not in self.allowed_effects:
                raise ValueError("policy_kernel 必须包含 force_pass 效果")
        if self.category == KnowledgeCategory.RESEARCH_ONLY:
            if any(
                effect not in {KnowledgeEffect.EXPLAIN}
                for effect in self.allowed_effects
            ):
                raise ValueError("research_only 卡片只能使用 explain 效果")
        return self


# ── 来源清单项 ─────────────────────────────────────────────


class SourceInventoryItem(BaseModel):
    """来源清单中的单个 RuleSpec。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rule_id: str
    document_id: str
    document_type: str | None = None
    ruleset_id: str
    ruleset_version: str
    file_path: str
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    line_range: tuple[int, int] | None = None
    reliability: str
    markets: tuple[str, ...]
    disposition: MigrationDisposition | None = None
    target_card_id: str | None = None
    consolidated_into: str | None = None
    reason: str | None = None


# ── 基线冻结 ──────────────────────────────────────────────


class BaselineFreezeV1(BaseModel):
    """冻结 1.8.0、1.9.0、1.7.0r2 的哈希和黄金产物。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    frozen_at: datetime

    # 1.8.0 已发布规则集
    ruleset_180_id: str = "football-analysis"
    ruleset_180_version: str = "1.8.0"
    ruleset_180_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ruleset_180_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 1.9.0 提案
    proposal_190_id: str = "football-analysis"
    proposal_190_version: str = "1.9.0"
    proposal_190_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 1.7.0 活动实验 revision 2
    experiment_170_id: str = "football-analysis"
    experiment_170_version: str = "1.7.0"
    experiment_170_revision: int = 2
    experiment_170_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    experiment_170_source_inventory_count: int = Field(ge=0)

    # 处置
    ruleset_170_disposition: Ruleset170Disposition | None = None
    ruleset_170_disposition_reason: str | None = None
    ruleset_170_disposition_by: str | None = None
    ruleset_170_disposition_at: datetime | None = None

    @field_validator("frozen_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("frozen_at 必须包含时区")
        return value


# ── 取代事件 ──────────────────────────────────────────────


class ProposalSupersessionEventV1(BaseModel):
    """规则提案取代事件。

    1.9.0 原文件不修改，通过追加此事件标记为被 2.0.0 取代。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str = Field(min_length=1)
    superseded_proposal_id: str = "football-analysis"
    superseded_proposal_version: str
    superseded_by_proposal_id: str = "football-analysis"
    superseded_by_proposal_version: str
    reason: str = Field(min_length=1)
    recorded_at: datetime
    recorded_by: Literal["lcz"]

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at 必须包含时区")
        return value


# ── 知识迁移清单 ──────────────────────────────────────────


class KnowledgeMigrationManifestV1(BaseModel):
    """知识迁移清单。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    migration_id: str = Field(min_length=1)
    from_ruleset_id: str
    from_ruleset_version: str
    from_ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    to_proposal_id: str = "football-analysis"
    to_proposal_version: str = "2.0.0"
    source_inventory_count: int = Field(ge=0)
    dispositions: dict[str, int] = Field(default_factory=dict)
    prepared_at: datetime

    @field_validator("prepared_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("prepared_at 必须包含时区")
        return value


# ── 知识合并清单 ──────────────────────────────────────────


class KnowledgeConsolidationManifestV1(BaseModel):
    """知识合并清单，记录合并决策。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    consolidation_id: str = Field(min_length=1)
    proposal_id: str = "football-analysis"
    proposal_version: str = "2.0.0"
    source_cards: tuple[str, ...] = Field(min_length=2)
    target_card_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    consolidation_type: Literal["merge", "supersede", "group"]
    reason: str = Field(min_length=1)
    auto_similarity_score: float | None = Field(default=None, ge=0, le=1)
    manually_confirmed: bool = False
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None