"""Immutable repository storage for knowledge snapshots and local indexes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Iterable

import yaml

from ...ledger import atomic_write_text
from ...transaction import RepositoryTransaction
from ..domain.knowledge import KnowledgeCardV1
from ..domain.snapshot import KnowledgeIndexManifestV1, KnowledgeSnapshotManifestV1
from .sqlite_index import SQLiteIndexAdapter


class KnowledgeSnapshotRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @property
    def snapshots_dir(self) -> Path:
        return self.root / "raw/knowledge-engine/snapshots"

    @property
    def cards_dir(self) -> Path:
        return self.root / "raw/knowledge-engine/cards"

    @property
    def indexes_dir(self) -> Path:
        return self.root / "raw/knowledge-engine/index"

    def snapshot_path(self, snapshot_sha256: str) -> Path:
        return self.snapshots_dir / f"{snapshot_sha256}.yml"

    def index_manifest_path(self, snapshot_sha256: str) -> Path:
        return self.indexes_dir / f"{snapshot_sha256}.manifest.yml"

    def seal(self, snapshot: KnowledgeSnapshotManifestV1, cards: Iterable[KnowledgeCardV1]) -> Path:
        cards = list(cards)
        if snapshot.card_count != len(cards) or set(snapshot.card_ids) != {card.card_id for card in cards}:
            raise ValueError("Snapshot 与卡片集合不一致")
        if snapshot.source_disposition_coverage < 1:
            raise ValueError("来源处置未完整，拒绝封存 Snapshot")
        target = self.snapshot_path(snapshot.snapshot_sha256)
        if target.exists():
            existing = self.load(snapshot.snapshot_sha256)
            if existing != snapshot:
                raise ValueError("相同 Snapshot 哈希已存在不同内容")
            self.load_cards(snapshot)
            return target
        with RepositoryTransaction(
            self.root,
            files=[target],
            directories=[self.cards_dir],
            operation="knowledge-snapshot-seal",
        ) as transaction:
            for card in cards:
                if snapshot.card_content_sha256s.get(card.card_id) != card.card_content_sha256:
                    raise ValueError(f"Snapshot 卡片哈希不一致：{card.card_id}")
                card_path = self.cards_dir / f"{card.card_content_sha256}.yml"
                payload = yaml.safe_dump(card.model_dump(mode="json"), allow_unicode=True, sort_keys=True)
                if card_path.exists() and card_path.read_text(encoding="utf-8") != payload:
                    raise ValueError(f"相同卡片内容哈希出现不同内容：{card.card_id}")
                if not card_path.exists():
                    atomic_write_text(card_path, payload)
            atomic_write_text(target, yaml.safe_dump(snapshot.model_dump(mode="json"), allow_unicode=True, sort_keys=True))
            transaction.commit()
        return target

    def load(self, snapshot_sha256: str) -> KnowledgeSnapshotManifestV1:
        path = self.snapshot_path(snapshot_sha256)
        if not path.is_file():
            raise FileNotFoundError(f"知识 Snapshot 不存在：{snapshot_sha256}")
        snapshot = KnowledgeSnapshotManifestV1.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        if snapshot.snapshot_sha256 != snapshot_sha256:
            raise ValueError("Snapshot 文件名与内容哈希不一致")
        return snapshot

    def load_cards(self, snapshot: KnowledgeSnapshotManifestV1) -> list[KnowledgeCardV1]:
        cards: list[KnowledgeCardV1] = []
        for card_id in snapshot.card_ids:
            card_hash = snapshot.card_content_sha256s.get(card_id)
            if not card_hash:
                raise ValueError(f"Snapshot 缺少卡片哈希：{card_id}")
            card_path = self.cards_dir / f"{card_hash}.yml"
            card = KnowledgeCardV1.model_validate(yaml.safe_load(card_path.read_text(encoding="utf-8")) or {})
            if card.card_id != card_id or card.card_content_sha256 != card_hash:
                raise ValueError(f"Snapshot 卡片血缘无效：{card_id}")
            cards.append(card)
        return cards

    def build_index(self, snapshot: KnowledgeSnapshotManifestV1) -> tuple[Path, KnowledgeIndexManifestV1]:
        cards = self.load_cards(snapshot)
        db_path = self.indexes_dir / f"{snapshot.snapshot_sha256}.db"
        manifest_path = self.index_manifest_path(snapshot.snapshot_sha256)
        if db_path.exists() or manifest_path.exists():
            if not (db_path.exists() and manifest_path.exists()):
                raise ValueError("知识索引产物不完整，拒绝覆盖")
            manifest = KnowledgeIndexManifestV1.model_validate(yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {})
            if manifest.snapshot_sha256 != snapshot.snapshot_sha256:
                raise ValueError("索引 Manifest Snapshot 不一致")
            return db_path, manifest
        self.indexes_dir.mkdir(parents=True, exist_ok=True)
        temporary = db_path.with_suffix(".db.tmp")
        with RepositoryTransaction(
            self.root,
            files=[db_path, manifest_path],
            directories=[self.indexes_dir],
            operation="knowledge-index-build",
        ) as transaction:
            adapter = SQLiteIndexAdapter(temporary)
            try:
                adapter.initialize_schema()
                for card in cards:
                    adapter.insert_card(card.model_dump(mode="json"))
                    for related in card.conflicts:
                        adapter.insert_relation(card.card_id, related, "conflict")
                    for related in card.counter_cards:
                        adapter.insert_relation(card.card_id, related, "counter")
                if not adapter.validate_index():
                    raise ValueError("知识 SQLite 索引完整性校验失败")
            finally:
                adapter.close()
            file_hash = hashlib.sha256(temporary.read_bytes()).hexdigest()
            from ..application.build_snapshot import build_index_manifest
            manifest = build_index_manifest(snapshot, sqlite_file_sha256=file_hash)
            temporary.replace(db_path)
            atomic_write_text(manifest_path, yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=True))
            transaction.commit()
        return db_path, manifest
