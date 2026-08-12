"""Knowledge Engine 快照构建应用服务。

封存知识卡片集合，生成 Snapshot Manifest 和逻辑索引。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.knowledge import KnowledgeCardV1, KnowledgeCategory, KnowledgeTier
from ..domain.snapshot import KnowledgeSnapshotManifestV1, KnowledgeIndexManifestV1


def build_snapshot_manifest(
    cards: list[KnowledgeCardV1],
    proposal_id: str = "football-analysis",
    proposal_version: str = "2.0.0",
    source_inventory_count: int = 0,
    source_disposition_coverage: float = 0.0,
    migration_manifest_sha256: str = "0" * 64,
    consolidation_manifest_sha256: str | None = None,
) -> KnowledgeSnapshotManifestV1:
    """构建知识快照清单。

    封存后不可变，新快照必须创建新版本。
    """
    if not cards:
        raise ValueError("知识快照至少需要一张经迁移处置的卡片")
    if source_inventory_count <= 0 or source_disposition_coverage < 1:
        raise ValueError("知识快照必须绑定完整来源清单及 100% 处置覆盖")
    card_ids = tuple(sorted(c.card_id for c in cards))
    card_hashes = {card.card_id: card.card_content_sha256 for card in cards}

    tier_dist: dict[str, int] = {}
    cat_dist: dict[str, int] = {}
    for card in cards:
        tier_dist[card.tier.value] = tier_dist.get(card.tier.value, 0) + 1
        cat_dist[card.category.value] = cat_dist.get(card.category.value, 0) + 1

    # 卡片集合哈希
    cards_data = [
        card.model_dump(mode="json")
        for card in sorted(cards, key=lambda item: item.card_id)
    ]
    cards_hash = hashlib.sha256(
        json.dumps(cards_data, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    raw = {
        "schema_version": 1,
        "snapshot_id": f"snapshot-{proposal_version}-{cards_hash[:16]}",
        "proposal_id": proposal_id,
        "proposal_version": proposal_version,
        "card_count": len(cards),
        "card_ids": card_ids,
        "tier_distribution": tier_dist,
        "category_distribution": cat_dist,
        "source_inventory_count": source_inventory_count,
        "source_disposition_coverage": source_disposition_coverage,
        "sealed_at": None,
        "sealed_by": None,
        "approved_by": None,
        "cards_collection_sha256": cards_hash,
        "card_content_sha256s": card_hashes,
        "migration_manifest_sha256": migration_manifest_sha256,
        "consolidation_manifest_sha256": consolidation_manifest_sha256,
        "snapshot_sha256": "0" * 64,
    }

    snapshot_hash = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    raw["snapshot_sha256"] = snapshot_hash

    return KnowledgeSnapshotManifestV1.model_validate(raw)


def build_index_manifest(
    snapshot: KnowledgeSnapshotManifestV1,
    sqlite_file_sha256: str | None = None,
) -> KnowledgeIndexManifestV1:
    """构建知识索引清单。"""
    logical_rows = {
        "snapshot_sha256": snapshot.snapshot_sha256,
        "card_content_sha256s": snapshot.card_content_sha256s,
        "schema": "knowledge-index-v1/fts5",
        "retriever_version": "knowledge-engine-v1",
    }
    logical_hash = hashlib.sha256(
        json.dumps(logical_rows, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    raw = {
        "schema_version": 1,
        "index_id": f"index-{snapshot.snapshot_sha256[:16]}",
        "snapshot_sha256": snapshot.snapshot_sha256,
        "fts5_enabled": True,
        "fts5_tables": ("knowledge_cards_fts",),
        "structured_indexes": (
            "idx_cards_tier",
            "idx_cards_category",
            "idx_cards_status",
            "idx_cards_provenance",
            "idx_cards_source_family",
        ),
        "cache_enabled": True,
        "cache_key_template": "knowledge-engine:{snapshot_sha256}:{feature_sha256}:{query_hash}:{retriever_version}",
        "sqlite_file_sha256": sqlite_file_sha256,
        "logical_index_sha256": logical_hash,
        "built_at": None,
        "builder_version": None,
        "index_manifest_sha256": "0" * 64,
    }

    index_hash = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    raw["index_manifest_sha256"] = index_hash

    return KnowledgeIndexManifestV1.model_validate(raw)
