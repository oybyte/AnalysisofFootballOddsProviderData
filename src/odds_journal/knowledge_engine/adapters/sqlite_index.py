"""Knowledge Engine SQLite 索引适配器。

实现分层检索：先结构化过滤，再 FTS5 BM25。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class SQLiteIndexAdapter:
    """SQLite 索引适配器。

    普通 SQLite 表执行层级、市场、标签和数值范围过滤。
    FTS5 只对过滤后的小候选集执行 BM25。
    SQL 全部参数化，不接受原始 FTS 表达式。
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _ensure_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def initialize_schema(self) -> None:
        """创建知识卡片表和 FTS5 索引。"""
        conn = self._ensure_connection()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge_cards (
                card_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                tier TEXT NOT NULL,
                category TEXT NOT NULL,
                source_track TEXT NOT NULL,
                applicable_markets TEXT NOT NULL,
                provenance_group TEXT NOT NULL,
                source_family TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                interpretation TEXT NOT NULL,
                card_content_sha256 TEXT NOT NULL,
                original_rule_id TEXT,
                original_ruleset_id TEXT,
                original_ruleset_version TEXT,
                UNIQUE(card_id)
            );

            CREATE INDEX IF NOT EXISTS idx_cards_tier ON knowledge_cards(tier);
            CREATE INDEX IF NOT EXISTS idx_cards_category ON knowledge_cards(category);
            CREATE INDEX IF NOT EXISTS idx_cards_status ON knowledge_cards(status);
            CREATE INDEX IF NOT EXISTS idx_cards_provenance ON knowledge_cards(provenance_group);
            CREATE INDEX IF NOT EXISTS idx_cards_source_family ON knowledge_cards(source_family);

            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_cards_fts USING fts5(
                card_id,
                interpretation,
                content='knowledge_cards',
                content_rowid='rowid'
            );

            CREATE TABLE IF NOT EXISTS knowledge_card_relations (
                card_id TEXT NOT NULL,
                related_card_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                PRIMARY KEY (card_id, related_card_id, relation_type)
            );

            CREATE INDEX IF NOT EXISTS idx_relations_card ON knowledge_card_relations(card_id);
            CREATE INDEX IF NOT EXISTS idx_relations_related ON knowledge_card_relations(related_card_id);
        """)
        conn.commit()

    def insert_card(self, card: dict[str, Any]) -> None:
        """插入知识卡片。"""
        conn = self._ensure_connection()
        conn.execute(
            """INSERT INTO knowledge_cards
               (card_id, version, tier, category, source_track, applicable_markets,
                provenance_group, source_family, status, interpretation,
                card_content_sha256, original_rule_id, original_ruleset_id, original_ruleset_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                card["card_id"],
                card.get("version", 1),
                card["tier"],
                card["category"],
                card.get("source_track", "published_ruleset"),
                ",".join(card.get("applicable_markets", [])),
                card.get("provenance_group", ""),
                card.get("source_family", ""),
                card.get("status", "active"),
                card.get("interpretation", ""),
                card["card_content_sha256"],
                card.get("original_rule_id"),
                card.get("original_ruleset_id"),
                card.get("original_ruleset_version"),
            ),
        )
        conn.commit()

    def insert_relation(
        self,
        card_id: str,
        related_card_id: str,
        relation_type: str,
    ) -> None:
        """插入卡片关系（冲突、反证、覆盖等）。"""
        conn = self._ensure_connection()
        conn.execute(
            """INSERT INTO knowledge_card_relations
               (card_id, related_card_id, relation_type)
               VALUES (?, ?, ?)""",
            (card_id, related_card_id, relation_type),
        )
        conn.commit()

    def search(
        self,
        tier: str | None = None,
        category: str | None = None,
        market: str | None = None,
        limit: int = 12,
    ) -> list[str]:
        """结构化过滤检索。"""
        conn = self._ensure_connection()
        conditions: list[str] = ["status = 'active'"]
        params: list[Any] = []

        if tier:
            conditions.append("tier = ?")
            params.append(tier)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if market:
            conditions.append("applicable_markets LIKE ?")
            params.append(f"%{market}%")

        where = " AND ".join(conditions)
        query = f"SELECT card_id FROM knowledge_cards WHERE {where} ORDER BY tier, card_id LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return [row["card_id"] for row in rows]

    def search_fts5(
        self,
        query_text: str,
        card_ids: list[str],
        limit: int = 12,
    ) -> list[str]:
        """FTS5 BM25 检索（仅对过滤后候选集）。"""
        if not card_ids:
            return []
        conn = self._ensure_connection()
        placeholders = ",".join("?" for _ in card_ids)
        fts_query = conn.execute(
            f"""SELECT kc.card_id
                FROM knowledge_cards_fts fts
                JOIN knowledge_cards kc ON fts.rowid = kc.rowid
                WHERE knowledge_cards_fts MATCH ?
                  AND kc.card_id IN ({placeholders})
                ORDER BY rank
                LIMIT ?""",
            [query_text, *card_ids, limit],
        ).fetchall()
        return [row["card_id"] for row in fts_query]

    def get_counter_cards(self, card_ids: list[str]) -> list[str]:
        """获取反证、互斥和冲突卡。"""
        if not card_ids:
            return []
        conn = self._ensure_connection()
        placeholders = ",".join("?" for _ in card_ids)
        rows = conn.execute(
            f"""SELECT DISTINCT related_card_id
                FROM knowledge_card_relations
                WHERE card_id IN ({placeholders})
                  AND relation_type IN ('conflict', 'counter', 'mutually_exclusive')""",
            card_ids,
        ).fetchall()
        return [row["related_card_id"] for row in rows]

    def validate_index(self) -> bool:
        """验证索引完整性。"""
        try:
            conn = self._ensure_connection()
            result = conn.execute("PRAGMA integrity_check").fetchone()
            return result[0] == "ok"
        except Exception:
            return False

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
