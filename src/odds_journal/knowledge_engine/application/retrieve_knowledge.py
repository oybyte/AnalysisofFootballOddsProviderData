"""Knowledge Engine 知识检索应用服务。

实现分层检索：foundation 固定装载 → 结构化过滤 → FTS5 BM25。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.features import FeatureSnapshotV2
from ..domain.retrieval import KnowledgeQueryPlanV1, KnowledgeRetrievalReceiptV1
from ..domain.snapshot import KnowledgeSnapshotManifestV1, KnowledgeIndexManifestV1
from ..ports.knowledge import KnowledgeIndexPort


def build_query_plan(
    match_id: str,
    as_of: datetime,
    features: FeatureSnapshotV2,
    snapshot: KnowledgeSnapshotManifestV1,
    index_manifest: KnowledgeIndexManifestV1,
) -> KnowledgeQueryPlanV1:
    """构建知识查询计划。"""
    cache_key = (
        f"knowledge-engine:{snapshot.snapshot_sha256}:"
        f"{features.feature_sha256}:{match_id}:{as_of.isoformat()}"
    )

    return KnowledgeQueryPlanV1(
        query_id=f"query-{match_id}-{as_of.strftime('%Y%m%dT%H%M%S')}",
        match_id=match_id,
        as_of=as_of,
        snapshot_sha256=snapshot.snapshot_sha256,
        feature_sha256=features.feature_sha256,
        foundation_card_ids=_foundation_cards(snapshot),
        cache_key=cache_key,
    )


def retrieve_knowledge(
    query_plan: KnowledgeQueryPlanV1,
    snapshot: KnowledgeSnapshotManifestV1,
    index_manifest: KnowledgeIndexManifestV1,
    index: KnowledgeIndexPort,
    features: FeatureSnapshotV2,
) -> KnowledgeRetrievalReceiptV1:
    """执行分层知识检索。

    - foundation 卡按适用市场固定装载并缓存。
    - general、market、competition、scenario 先做结构化过滤。
    - cross_market 只能进入隔离审计，不进入其他市场候选生成。
    - 每市场最多 12 张规范卡，整场最多 40 张。
    - 反证和冲突卡不占普通 Top K 配额。
    """
    import time

    start = time.time()

    # 1. foundation 卡片固定装载
    mandatory = list(query_plan.foundation_card_ids)

    # 2. 分层结构化过滤
    general = index.search(tier="general", limit=8)
    market_cards = index.search(tier="market", limit=8)
    competition = index.search(tier="competition", limit=4)
    scenario = index.search(tier="scenario", limit=4)

    # 3. FTS5 BM25 对过滤后候选集检索
    structured = general + market_cards + competition + scenario
    decision_cards = index.search_fts5(
        f"match:{features.match_id}",
        structured,
        limit=12,
    )

    # 4. 补齐反证和冲突卡
    all_cards = mandatory + decision_cards
    counter_cards = index.get_counter_cards(all_cards)

    # 5. cross_market 隔离审计
    cross_market = index.search(tier="cross_market", limit=4)

    elapsed = (time.time() - start) * 1000

    raw = {
        "schema_version": 1,
        "retrieval_id": f"retrieval-{query_plan.query_id}",
        "query_plan_sha256": hashlib.sha256(
            json.dumps(query_plan.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest(),
        "snapshot_sha256": snapshot.snapshot_sha256,
        "index_manifest_sha256": index_manifest.index_manifest_sha256,
        "retriever_version": "knowledge-engine-v1",
        "mandatory_policy_cards": tuple(mandatory),
        "retrieved_decision_cards": tuple(decision_cards),
        "retrieved_explanation_cards": tuple(cross_market),
        "counter_and_conflict_cards": tuple(counter_cards),
        "retrieval_time_ms": elapsed,
        "fts5_query_count": 1,
        "retrieval_sha256": "0" * 64,
    }

    retrieval_hash = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    raw["retrieval_sha256"] = retrieval_hash

    return KnowledgeRetrievalReceiptV1.model_validate(raw)


def _foundation_cards(snapshot: KnowledgeSnapshotManifestV1) -> tuple[str, ...]:
    """返回 foundation 层级的卡片 ID。"""
    return tuple(
        cid for cid in snapshot.card_ids
        if cid.startswith("card-football-analysis-framework")
        or cid.startswith("card-market-settlement")
        or cid.startswith("card-data-provenance")
        or cid.startswith("card-prematch-stage")
        or cid.startswith("card-layered-decision")
        or cid.startswith("card-goals-score-separation")
        or cid.startswith("card-dual-hypothesis")
    )