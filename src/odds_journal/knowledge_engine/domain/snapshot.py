"""Knowledge Engine 快照与索引模型。

定义知识快照清单和索引清单。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KnowledgeSnapshotManifestV1(BaseModel):
    """知识快照清单。

    封存后不可变，新快照必须创建新版本。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    snapshot_id: str = Field(min_length=1)
    proposal_id: str = "football-analysis"
    proposal_version: str = "2.0.0"

    # 卡片集合
    card_count: int = Field(ge=0)
    card_ids: tuple[str, ...] = Field(default_factory=tuple)

    # 层级分布
    tier_distribution: dict[str, int] = Field(default_factory=dict)

    # 类别分布
    category_distribution: dict[str, int] = Field(default_factory=dict)

    # 来源
    source_inventory_count: int = Field(ge=0)
    source_disposition_coverage: float = Field(ge=0, le=1)

    # 封存
    sealed_at: datetime | None = None
    sealed_by: Literal["lcz"] | None = None
    approved_by: Literal["lcz"] | None = None

    # 哈希
    cards_collection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    card_content_sha256s: dict[str, str] = Field(default_factory=dict)
    migration_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consolidation_manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("sealed_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("sealed_at 必须包含时区")
        return value


class KnowledgeIndexManifestV1(BaseModel):
    """知识索引清单。

    记录 SQLite 索引结构、FTS5 配置和缓存策略。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    index_id: str = Field(min_length=1)
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 索引配置
    fts5_enabled: bool = True
    fts5_tables: tuple[str, ...] = Field(default_factory=tuple)
    structured_indexes: tuple[str, ...] = Field(default_factory=tuple)

    # 缓存
    cache_enabled: bool = True
    cache_key_template: str = "knowledge-engine:{snapshot_sha256}:{feature_sha256}:{query_hash}:{retriever_version}"

    # SQLite 文件哈希（仅本地认证）
    sqlite_file_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    logical_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 构建
    built_at: datetime | None = None
    builder_version: str | None = None

    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("built_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("built_at 必须包含时区")
        return value
