"""离线历史模拟脚本

对 historical_finished 比赛执行知识引擎推理，验证推理质量。
标记为 offline_historical_simulation，不用于官方统计或 ReleaseEvidence。

用法：
    python scripts/offline_historical_simulation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml

from odds_journal.markdown import MatchDocument
from odds_journal.ledger import sha256_json
from odds_journal.knowledge_engine.domain.features import (
    FeatureSnapshotV2,
    PolicyKernelBaselineV1,
)
from odds_journal.knowledge_engine.domain.retrieval import KnowledgeRetrievalReceiptV1
from odds_journal.knowledge_engine.adapters.sqlite_index import SQLiteIndexAdapter
from odds_journal.knowledge_engine.adapters.deterministic_reasoner import (
    DeterministicKnowledgeReasoner,
)
from odds_journal.knowledge_engine.adapters.snapshot_repository import (
    KnowledgeSnapshotRepository,
)


def find_historical_finished_matches(root: Path) -> list[tuple[Path, MatchDocument]]:
    """找到所有 historical_finished 比赛。"""
    matches_dir = root / "matches"
    results: list[tuple[Path, MatchDocument]] = []
    for path in sorted(matches_dir.glob("**/*.md")):
        try:
            doc = MatchDocument.load(path)
            if doc.metadata.status == "historical_finished":
                results.append((path, doc))
        except Exception:
            pass
    return results


def build_feature(match_id: str, as_of, kickoff_at) -> FeatureSnapshotV2:
    """构建简化版 FeatureSnapshotV2。"""
    raw = {
        "schema_version": 2,
        "match_id": match_id,
        "as_of": as_of.isoformat(),
        "kickoff_at": kickoff_at.isoformat(),
        "compiler_version": "knowledge-engine-v1",
        "config_sha256": "0" * 64,
        "observation_collection_sha256": "0" * 64,
        "feature_sha256": "0" * 64,
    }
    raw["feature_sha256"] = sha256_json(
        {k: v for k, v in raw.items() if k != "feature_sha256"}
    )
    return FeatureSnapshotV2.model_validate(raw)


def build_baseline(match_id: str, as_of, result_1x2: str | None = None) -> PolicyKernelBaselineV1:
    """构建 PolicyKernelBaselineV1，基于比赛结果构建差异化模拟排序。

    注意：这是离线模拟，用 result_1x2 构建"后视"排序以产生决策差异。
    正式流程中 market_rankings 来自 analysis-outlook.yml 的 final_rankings。
    """
    # 基于 result_1x2 构建不同排序
    if result_1x2 == "home":
        one_x_two = ("home", "draw", "away")
        asian = ("home_handicap", "away_handicap")
        total_goals = ("over", "under")
    elif result_1x2 == "draw":
        one_x_two = ("draw", "home", "away")
        asian = ("away_handicap", "home_handicap")
        total_goals = ("under", "over")
    elif result_1x2 == "away":
        one_x_two = ("away", "draw", "home")
        asian = ("away_handicap", "home_handicap")
        total_goals = ("under", "over")
    else:
        one_x_two = ("home", "draw", "away")
        asian = ("home_handicap", "away_handicap")
        total_goals = ("over", "under")

    raw = {
        "schema_version": 1,
        "match_id": match_id,
        "as_of": as_of.isoformat(),
        "policy_kernel_sha256": "0" * 64,
        "independent_evidence_total_goals": True,
        "market_rankings": {
            "one_x_two": one_x_two,
            "asian_handicap": asian,
            "total_goals": total_goals,
        },
    }
    raw["policy_kernel_sha256"] = sha256_json(
        {k: v for k, v in raw.items() if k != "policy_kernel_sha256"}
    )
    return PolicyKernelBaselineV1.model_validate(raw)


def build_retrieval(
    adapter: SQLiteIndexAdapter,
    snapshot_sha: str,
    index_manifest_sha: str,
    match_id: str,
    query_text: str,
    decision_card_ids: list[str],
) -> KnowledgeRetrievalReceiptV1:
    """执行知识检索并构建检索回执。

    decision_card_ids 是 DECISION_POLICY 卡片的 ID 列表，
    直接注入检索回执的 retrieved_decision_cards。
    """
    policy_cards = adapter.search(tier="mandatory", limit=12)
    explanation_cards = adapter.search(category="explanation", limit=12)

    all_cards = list(set(explanation_cards + policy_cards))
    fts_results = (
        adapter.search_fts5(query_text, all_cards, limit=12) if query_text else []
    )
    counter_cards = adapter.get_counter_cards(fts_results) if fts_results else []

    retrieval_raw = {
        "schema_version": 1,
        "retrieval_id": f"retrieval:{match_id}",
        "query_plan_sha256": "0" * 64,
        "snapshot_sha256": snapshot_sha,
        "index_manifest_sha256": index_manifest_sha,
        "retriever_version": "knowledge-engine-v1",
        "retrieval_time_ms": 0.0,
        "fts5_query_count": 1 if query_text else 0,
        "mandatory_policy_cards": tuple(policy_cards),
        "retrieved_decision_cards": tuple(decision_card_ids),
        "retrieved_explanation_cards": tuple(explanation_cards),
        "counter_and_conflict_cards": tuple(counter_cards),
        "retrieval_sha256": "0" * 64,
    }
    retrieval_raw["retrieval_sha256"] = sha256_json(
        {k: v for k, v in retrieval_raw.items() if k != "retrieval_sha256"}
    )
    return KnowledgeRetrievalReceiptV1.model_validate(retrieval_raw)


def load_decision_cards(root: Path) -> dict:
    """加载 DECISION_POLICY 卡片到 card_resolver 字典。"""
    cards_dir = root / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0" / "decision-cards"
    resolver: dict = {}
    if not cards_dir.is_dir():
        return resolver
    import yaml
    for path in sorted(cards_dir.glob("*.yml")):
        if path.name == "index.yml":
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("category") == "decision_policy":
            from odds_journal.knowledge_engine.domain.knowledge import KnowledgeCardV1
            card = KnowledgeCardV1.model_validate(data)
            resolver[card.card_id] = card
    return resolver


def main() -> int:
    root = ROOT

    # 加载 Snapshot
    repo = KnowledgeSnapshotRepository(root)
    snapshots = sorted(repo.snapshots_dir.glob("*.yml"))
    if not snapshots:
        print("错误：没有已封存的 Snapshot")
        return 1
    snapshot_sha = snapshots[0].stem
    snapshot_manifest = repo.load(snapshot_sha)

    # 加载索引
    index_db = root / "raw" / "knowledge-engine" / "index" / f"{snapshot_sha}.db"
    if not index_db.exists():
        print(f"错误：索引文件不存在：{index_db}")
        return 1

    index_manifest_path = (
        root / "raw" / "knowledge-engine" / "index" / f"{snapshot_sha}.manifest.yml"
    )
    index_manifest_data = (
        yaml.safe_load(index_manifest_path.read_text(encoding="utf-8")) or {}
    )
    index_manifest_sha = index_manifest_data.get("index_manifest_sha256", "0" * 64)

    adapter = SQLiteIndexAdapter(index_db)

    # 找到所有 historical_finished 比赛
    matches = find_historical_finished_matches(root)

    # 加载 DECISION_POLICY 卡片
    card_resolver = load_decision_cards(root)
    decision_card_ids = list(card_resolver.keys())
    print(f"=== 离线历史模拟（offline_historical_simulation）===")
    print(f"Snapshot: {snapshot_sha[:16]}...")
    print(f"DECISION_POLICY 卡片: {len(decision_card_ids)} 张")
    print(f"找到 {len(matches)} 场 historical_finished 比赛")
    print()

    reasoner = DeterministicKnowledgeReasoner(card_resolver=card_resolver)

    results: list[dict] = []
    for path, doc in matches:
        match_id = doc.metadata.match_id
        kickoff_at = doc.metadata.kickoff_at
        as_of = kickoff_at - timedelta(hours=1)

        try:
            feature = build_feature(match_id, as_of, kickoff_at)
            result_1x2 = getattr(doc.metadata, "result_1x2", None)
            baseline = build_baseline(match_id, as_of, result_1x2)

            query_text = f"{doc.metadata.home_team} {doc.metadata.away_team}"
            retrieval = build_retrieval(
                adapter, snapshot_sha, index_manifest_sha, match_id, query_text,
                decision_card_ids,
            )

            bundle = reasoner.analyze(feature, retrieval, baseline)

            results.append(
                {
                    "match_id": match_id,
                    "match_path": str(path.relative_to(root)),
                    "kickoff_at": kickoff_at.isoformat(),
                    "result_1x2": result_1x2,
                    "baseline_rankings": dict(baseline.market_rankings),
                    "market_decisions": bundle.market_decisions,
                    "degraded": bundle.degraded,
                    "degraded_reasons": list(bundle.degraded_reasons),
                    "confidence": bundle.confidence,
                    "retrieved_decision_cards": list(
                        retrieval.retrieved_decision_cards
                    ),
                    "retrieved_explanation_cards": list(
                        retrieval.retrieved_explanation_cards
                    ),
                    "counter_cards": list(retrieval.counter_and_conflict_cards),
                    "adjudication_log": list(bundle.adjudication_log),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "match_id": match_id,
                    "match_path": str(path.relative_to(root)),
                    "error": str(exc),
                }
            )

    adapter.close()

    # 保存详细结果
    output_path = root / ".tmp" / "offline_historical_simulation_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 汇总统计
    success = sum(1 for r in results if "error" not in r)
    errors = sum(1 for r in results if "error" in r)
    degraded = sum(1 for r in results if r.get("degraded"))
    total_cards = sum(len(r.get("retrieved_decision_cards", [])) for r in results)

    print(f"=== 汇总 ===")
    print(f"总比赛数: {len(results)}")
    print(f"成功: {success}")
    print(f"失败: {errors}")
    print(f"降级: {degraded}")
    print(f"检索决策卡片总数: {total_cards}")
    print(f"详细结果: {output_path}")
    print()

    # 每场比赛摘要
    for r in results:
        if "error" in r:
            print(f"  [错误] {r['match_id']}: {r['error'][:80]}")
        else:
            decisions = r["market_decisions"]
            statuses = {m: d.get("status", "?") for m, d in decisions.items()}
            assessed = sum(1 for s in statuses.values() if s == "assessed")
            passed = sum(1 for s in statuses.values() if s == "pass")
            degraded_flag = " [降级]" if r["degraded"] else ""
            cards = len(r.get("retrieved_decision_cards", []))
            print(
                f"  [评估:{assessed} 跳过:{passed} 卡片:{cards}]{degraded_flag} "
                f"{r['match_id']}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
