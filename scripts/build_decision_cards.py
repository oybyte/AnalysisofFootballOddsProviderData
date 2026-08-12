"""构建 DECISION_POLICY 知识卡片。

从 1.8.0 校准配置的结构化规则生成 DECISION_POLICY 卡片。
卡片写入 knowledge/rule-proposals/football-analysis/2.0.0/decision-cards/。

用法：
    python scripts/build_decision_cards.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml

from odds_journal.knowledge_engine.domain.knowledge import (
    KnowledgeCardV1,
    KnowledgeCategory,
    KnowledgeEffect,
    KnowledgeTier,
    SourceTrack,
    CardStatus,
)


def _sha256(data: dict) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _make_card(
    card_id: str,
    tier: KnowledgeTier,
    applicable_markets: tuple[str, ...],
    interpretation: str,
    allowed_effects: tuple[KnowledgeEffect, ...],
    numerical_boundaries: dict[str, dict[str, float]],
    required_features: tuple[str, ...],
    provenance_group: str,
    source_family: str,
    support_conditions: tuple[str, ...] = (),
    counter_conditions: tuple[str, ...] = (),
    original_rule_id: str | None = None,
    max_adjustment: float = 0.0,
) -> KnowledgeCardV1:
    """构建单张 DECISION_POLICY 卡片。"""
    raw = {
        "card_id": card_id,
        "version": 1,
        "tier": tier.value,
        "category": KnowledgeCategory.DECISION_POLICY.value,
        "source_track": SourceTrack.PROPOSAL_RULESET.value,
        "applicable_markets": applicable_markets,
        "required_features": required_features,
        "numerical_boundaries": numerical_boundaries,
        "interpretation": interpretation,
        "support_conditions": support_conditions,
        "counter_conditions": counter_conditions,
        "invalidation_conditions": (),
        "allowed_effects": [e.value for e in allowed_effects],
        "max_adjustment": max_adjustment,
        "provenance_group": provenance_group,
        "source_family": source_family,
        "observation_lineage": [],
        "conflicts": [],
        "counter_cards": [],
        "supersedes": [],
        "original_rule_id": original_rule_id,
        "original_ruleset_id": "football-analysis",
        "original_ruleset_version": "1.8.0",
        "original_file_path": None,
        "original_file_sha256": None,
        "original_line_range": None,
        "status": CardStatus.ACTIVE.value,
        "card_content_sha256": "0" * 64,
    }
    raw["card_content_sha256"] = _sha256({k: v for k, v in raw.items() if k != "card_content_sha256"})
    return KnowledgeCardV1.model_validate(raw)


def build_all_cards() -> list[KnowledgeCardV1]:
    """构建全部 DECISION_POLICY 卡片。"""
    cards: list[KnowledgeCardV1] = []

    # 1. draw-kelly-parity — one_x_two, CONFIDENCE_CAP
    # 当平局凯利值与主客队凯利值差异超过阈值时，触发降级审计
    cards.append(_make_card(
        card_id="dp-draw-kelly-parity-v1",
        tier=KnowledgeTier.MARKET,
        applicable_markets=("one_x_two",),
        interpretation=(
            "平局凯利值与主客队凯利值差异超过阈值时，"
            "提示平局风险，触发置信度上限和降级审计。"
            "来源于 1.8.0 draw-kelly-parity-v1 规则。"
        ),
        allowed_effects=(KnowledgeEffect.CONFIDENCE_CAP, KnowledgeEffect.EXPLAIN),
        numerical_boundaries={
            "kelly_spread": {
                "parity_threshold": 0.02,
                "risk_threshold": 0.03,
                "low_stability_threshold": 0.05,
            },
        },
        required_features=("kelly_spread",),
        provenance_group="kelly-analysis",
        source_family="doubao-2026-07-28",
        support_conditions=(
            "kelly_spread > parity_threshold",
            "draw_kelly接近主队或客队kelly",
        ),
        counter_conditions=("kelly_spread < parity_threshold",),
        original_rule_id="draw-kelly-parity-v1",
    ))

    # 2. hidden-draw-away-cut — one_x_two, CONFIDENCE_CAP
    # 来自不同 provenance_group，可与 #1 共同触发 BOUNDED_RANK_ADJUSTMENT 的降级审计
    cards.append(_make_card(
        card_id="dp-hidden-draw-away-cut-v1",
        tier=KnowledgeTier.MARKET,
        applicable_markets=("one_x_two",),
        interpretation=(
            "客队赔率异常下降且平局赔率稳定时，"
            "提示隐性平局风险，触发置信度上限。"
            "来源于 1.8.0 hidden-draw-away-cut-v1 规则。"
        ),
        allowed_effects=(KnowledgeEffect.CONFIDENCE_CAP, KnowledgeEffect.EXPLAIN),
        numerical_boundaries={
            "euro_away_change": {
                "away_odds_fall_min": 0.10,
                "draw_range_max": 0.05,
                "draw_kelly_range_max": 0.01,
                "kelly_min": 0.90,
                "kelly_max": 0.95,
            },
        },
        required_features=("euro_away_change", "draw_stability", "draw_kelly"),
        provenance_group="euro-odds-analysis",
        source_family="doubao-football-history-2026-08-02",
        support_conditions=(
            "away_odds下降幅度 >= 0.10",
            "draw_odds变化 <= 0.05",
        ),
        counter_conditions=("away_odds下降幅度 < 0.10",),
        original_rule_id="hidden-draw-away-cut-v1",
    ))

    # 3. deep-line-stable-cover — asian_handicap, SUPPORT_EXISTING_DIRECTION
    cards.append(_make_card(
        card_id="dp-deep-line-stable-cover-v1",
        tier=KnowledgeTier.MARKET,
        applicable_markets=("asian_handicap",),
        interpretation=(
            "深盘(≥1.00)且赔率在0.80-0.95区间稳定时，"
            "支持现有让球方向，标记为支持信号。"
            "来源于 1.8.0 deep-line-stable-cover-v1 规则。"
        ),
        allowed_effects=(KnowledgeEffect.SUPPORT_EXISTING_DIRECTION, KnowledgeEffect.EXPLAIN),
        numerical_boundaries={
            "asian_line_depth": {
                "minimum_line_depth": 1.00,
                "deep_water_min": 0.80,
                "deep_water_max": 0.95,
                "half_one_line": 0.75,
                "half_line_water_max": 0.70,
            },
        },
        required_features=("asian_line_depth", "same_line_water_change", "trend_purity"),
        provenance_group="handicap-analysis",
        source_family="doubao-2026-07-28",
        support_conditions=(
            "asian_line_depth >= 1.00",
            "water in [0.80, 0.95]",
        ),
        counter_conditions=("asian_line_depth < 1.00",),
        original_rule_id="deep-line-stable-cover-v1",
    ))

    # 4. quarter-low-water-inducement — asian_handicap, SUPPRESS_CANDIDATE
    cards.append(_make_card(
        card_id="dp-quarter-low-water-inducement-v1",
        tier=KnowledgeTier.MARKET,
        applicable_markets=("asian_handicap",),
        interpretation=(
            "浅盘(0.25/0.50)且低水(≤0.80)且凯利差≤0.03时，"
            "提示诱导风险，抑制主队让球候选。"
            "来源于 1.8.0 quarter-low-water-inducement-v1 规则。"
        ),
        allowed_effects=(KnowledgeEffect.SUPPRESS_CANDIDATE, KnowledgeEffect.EXPLAIN),
        numerical_boundaries={
            "asian_water": {
                "half_line_water_max": 0.80,
                "kelly_spread_max": 0.03,
            },
        },
        required_features=("asian_line_depth", "asian_water", "euro_home_change", "kelly_spread"),
        provenance_group="inducement-analysis",
        source_family="doubao-football-history-2026-08-02",
        support_conditions=(
            "line_depth in [0.25, 0.50]",
            "water <= 0.80",
        ),
        counter_conditions=("line_depth > 0.50",),
        original_rule_id="quarter-low-water-inducement-v1",
    ))

    # 5. total-goals-cross-market — total_goals, SUPPORT_EXISTING_DIRECTION
    cards.append(_make_card(
        card_id="dp-total-goals-cross-market-v1",
        tier=KnowledgeTier.CROSS_MARKET,
        applicable_markets=("total_goals",),
        interpretation=(
            "大球水位≤0.60且下降≥0.20且总分线≤2.50时，"
            "支持大球方向。来源于 1.8.0 total-goals-cross-market-v1 规则。"
        ),
        allowed_effects=(KnowledgeEffect.SUPPORT_EXISTING_DIRECTION, KnowledgeEffect.EXPLAIN),
        numerical_boundaries={
            "total_over_water": {
                "over_water_max": 0.60,
                "over_water_fall_min": 0.20,
                "total_line_max": 2.50,
                "deep_line_min": 1.00,
                "deep_favorite_odds_max": 1.50,
                "shallow_line_max": 0.25,
                "shallow_favorite_odds_min": 1.80,
            },
        },
        required_features=("total_over_water", "asian_line_depth", "euro_favorite"),
        provenance_group="cross-market-analysis",
        source_family="doubao-2026-07-28",
        support_conditions=(
            "over_water <= 0.60",
            "over_water_fall >= 0.20",
        ),
        counter_conditions=("over_water > 0.60",),
        original_rule_id="total-goals-cross-market-v1",
    ))

    return cards


def main() -> int:
    cards = build_all_cards()
    output_dir = ROOT / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0" / "decision-cards"
    output_dir.mkdir(parents=True, exist_ok=True)

    for card in cards:
        path = output_dir / f"{card.card_content_sha256}.yml"
        path.write_text(
            yaml.safe_dump(card.model_dump(mode="json"), allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )
        print(f"  生成: {card.card_id} → {path.name}")

    # 生成索引文件
    index = {
        "card_count": len(cards),
        "cards": [
            {
                "card_id": c.card_id,
                "card_content_sha256": c.card_content_sha256,
                "tier": c.tier.value,
                "category": c.category.value,
                "applicable_markets": list(c.applicable_markets),
                "allowed_effects": [e.value for e in c.allowed_effects],
                "provenance_group": c.provenance_group,
                "source_family": c.source_family,
                "original_rule_id": c.original_rule_id,
            }
            for c in cards
        ],
    }
    index_path = output_dir / "index.yml"
    index_path.write_text(
        yaml.safe_dump(index, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )

    print(f"\n共生成 {len(cards)} 张 DECISION_POLICY 卡片")
    print(f"输出目录: {output_dir}")
    print(f"索引文件: {index_path.name}")
    print()
    print("卡片概览:")
    for c in cards:
        effects = ", ".join(e.value for e in c.allowed_effects)
        markets = ", ".join(c.applicable_markets)
        print(f"  {c.card_id}: [{markets}] effects=[{effects}] group={c.provenance_group}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
