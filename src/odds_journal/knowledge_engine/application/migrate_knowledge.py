"""Knowledge Engine 知识迁移应用服务。

从已发布 1.8.0 和活动实验不可变 snapshot 读取来源，
每个来源必须唯一处置为 migrated/consolidated/advisory/research/duplicate/invalid/deferred。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..domain.knowledge import (
    KnowledgeCardV1,
    KnowledgeTier,
    KnowledgeCategory,
    SourceTrack,
    KnowledgeEffect,
    CardStatus,
    MigrationDisposition,
    SourceInventoryItem,
    KnowledgeMigrationManifestV1,
    KnowledgeConsolidationManifestV1,
)


def build_conservative_cards(inventory: list[SourceInventoryItem]) -> list[KnowledgeCardV1]:
    """Build auditable, non-directive cards from explicitly disposed sources.

    A text migration cannot grant itself a ranking effect.  Until a later
    proposal defines machine-verifiable semantics, all migrated/advisory items
    remain advisory and research items remain postmatch-only.
    """
    cards: list[KnowledgeCardV1] = []
    for item in inventory:
        if item.disposition not in {
            MigrationDisposition.MIGRATED,
            MigrationDisposition.CONSOLIDATED,
            MigrationDisposition.ADVISORY,
            MigrationDisposition.RESEARCH,
        }:
            continue
        category = (
            KnowledgeCategory.RESEARCH_ONLY
            if item.disposition == MigrationDisposition.RESEARCH
            else KnowledgeCategory.ADVISORY
        )
        source_track = (
            SourceTrack.EXPERIMENT_ACTIVE
            if item.ruleset_version.startswith("1.7.0@revision-")
            else SourceTrack.PUBLISHED_RULESET
        )
        markets = tuple(
            market for market in item.markets
            if market in {"one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"}
        ) or ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2")
        raw = {
            "card_id": item.target_card_id or _card_id_from_rule(item.rule_id),
            "version": 1,
            "tier": KnowledgeTier.GENERAL.value,
            "category": category.value,
            "source_track": source_track.value,
            "applicable_markets": markets,
            "required_features": (),
            "numerical_boundaries": {},
            "interpretation": f"迁移来源 {item.rule_id}；仅作{category.value}审计，不产生方向或候选。",
            "support_conditions": (),
            "counter_conditions": (),
            "invalidation_conditions": ("缺少结构化、可验证的执行语义",),
            "allowed_effects": (KnowledgeEffect.EXPLAIN.value,),
            "max_adjustment": 0.0,
            "provenance_group": f"ruleset:{item.ruleset_version}",
            "source_family": item.ruleset_id,
            "observation_lineage": (),
            "conflicts": (),
            "counter_cards": (),
            "supersedes": (),
            "original_rule_id": item.rule_id,
            "original_ruleset_id": item.ruleset_id,
            "original_ruleset_version": item.ruleset_version,
            "original_file_path": item.file_path,
            "original_file_sha256": item.file_sha256,
            "original_line_range": item.line_range,
            "status": CardStatus.ACTIVE.value,
            "card_content_sha256": "0" * 64,
        }
        digest = hashlib.sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        raw["card_content_sha256"] = digest
        cards.append(KnowledgeCardV1.model_validate(raw))
    if not cards:
        raise ValueError("没有可封存的迁移知识卡")
    return cards


def build_source_inventory(
    ruleset_source: Any,
    root: Path,
) -> list[SourceInventoryItem]:
    """从 1.8.0 已发布规则集和 1.7.0 活动实验构建来源清单。

    读取每个 RuleSpec，记录其来源信息。
    包括文档级规则和 rule-spec YAML 文件。
    """
    inventory: list[SourceInventoryItem] = []
    seen: set[str] = set()

    # 1.8.0 已发布规则集
    try:
        docs_180 = ruleset_source.load_ruleset_documents(
            "football-analysis", "1.8.0", allow_proposal=False,
        )
        for doc in docs_180:
            rule_id = doc["document_id"]
            if rule_id in seen:
                continue
            seen.add(rule_id)
            inventory.append(SourceInventoryItem(
                rule_id=rule_id,
                document_id=doc["document_id"],
                document_type=doc.get("document_type"),
                ruleset_id="football-analysis",
                ruleset_version="1.8.0",
                file_path=f"knowledge/rulesets/football-analysis/1.8.0/{rule_id}.md",
                file_sha256=doc["content_sha256"],
                reliability=doc["reliability"],
                markets=tuple(doc.get("markets", ["all"])),
            ))
    except Exception:
        pass

    # 1.7.0 may only be read through active_experiment(), which verifies the
    # active pointer, snapshot directory hash, config, precedence and map.
    # Never fall back to the mutable proposal directory.
    from ..adapters.rule_spec_reader import read_rule_spec_inventory
    inventory.extend(read_rule_spec_inventory(root, seen))

    return inventory


def auto_disposition(
    inventory: list[SourceInventoryItem],
) -> list[SourceInventoryItem]:
    """自动处置来源规则。

    自动相似度只生成建议；合并由显式 Manifest 决定。
    返回新的 SourceInventoryItem 列表（原对象不可变）。
    """
    result: list[SourceInventoryItem] = []

    for item in inventory:
        disposition = None
        target_card_id = None

        # 基础规则 → migrated
        if item.reliability in ("established", "supported"):
            if item.document_id in {
                "football-analysis-framework",
                "market-settlement-rules",
                "data-provenance-time-boundary",
                "prematch-stage-positioning",
                "theoretical-vs-actual-market",
                "market-timeline-cross-validation",
                "dual-hypothesis-evidence",
                "layered-decision-confidence-pass",
                "goals-score-separation",
                "prematch-checklist-v1",
                "data-quality-conflict-and-pass",
                "scenario-identification-and-case-retrieval",
                "live-update-and-postmatch-separation",
            }:
                disposition = MigrationDisposition.MIGRATED
                target_card_id = _card_id_from_rule(item.rule_id)

        # 条件规则 → migrated
        if disposition is None and item.reliability in ("experimental", "supported"):
            if item.document_id in {
                "draw-kelly-parity-v1",
                "deep-line-stable-cover-v1",
                "quarter-low-water-inducement-v1",
                "hidden-draw-away-cut-v1",
                "total-goals-cross-market-v1",
                "score-baseline-v1",
                "korea-goal-drop-v1",
                "korea-deep-line-loss-tolerance-v1",
            }:
                disposition = MigrationDisposition.MIGRATED
                target_card_id = _card_id_from_rule(item.rule_id)

        # 启发式规则 → advisory
        if disposition is None:
            if item.document_type == "heuristic" or item.rule_id.startswith("tg-"):
                disposition = MigrationDisposition.ADVISORY
                target_card_id = _card_id_from_rule(item.rule_id)

        # 低稳定性规则 → research
        if disposition is None:
            if item.reliability == "experimental":
                disposition = MigrationDisposition.RESEARCH
                target_card_id = _card_id_from_rule(item.rule_id)

        # 剩余 → deferred
        if disposition is None:
            disposition = MigrationDisposition.DEFERRED

        result.append(SourceInventoryItem(
            rule_id=item.rule_id,
            document_id=item.document_id,
            ruleset_id=item.ruleset_id,
            ruleset_version=item.ruleset_version,
            file_path=item.file_path,
            file_sha256=item.file_sha256,
            line_range=item.line_range,
            reliability=item.reliability,
            markets=item.markets,
            disposition=disposition,
            target_card_id=target_card_id,
        ))

    return result


def validate_coverage(inventory: list[SourceInventoryItem]) -> tuple[bool, dict[str, int]]:
    """验证 100% source disposition coverage。"""
    counts: dict[str, int] = {}
    for item in inventory:
        key = item.disposition.value if item.disposition else "unset"
        counts[key] = counts.get(key, 0) + 1

    total = len(inventory)
    # Deferred is a deliberate, auditable disposition.  It is not permission
    # to generate a card, but it must count as source coverage.
    covered = total - counts.get("unset", 0)
    coverage = covered / total if total > 0 else 0

    return coverage >= 1.0, counts


def _card_id_from_rule(rule_id: str) -> str:
    """从规则 ID 生成知识卡片 ID。"""
    return f"card-{rule_id}"
