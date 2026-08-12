"""Knowledge Engine 确定性推理器适配器。

实现 Policy Kernel 强制规则、分层检索、裁决权限和评估包生成。
"""

from __future__ import annotations

from typing import Any

from ..domain.decisions import (
    DecisionAuthorityContractV1,
    KnowledgeEvaluationBundleV1,
)
from ..domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
from ..domain.retrieval import KnowledgeRetrievalReceiptV1
from ..domain.knowledge import KnowledgeCardV1, KnowledgeCategory, KnowledgeEffect
from ..ports.knowledge import KnowledgeReasoner


class DeterministicKnowledgeReasoner:
    """确定性知识推理器。

    正式必需、完全离线。
    实现裁决权限的全部固定规则。
    """

    def __init__(
        self,
        authority: DecisionAuthorityContractV1 | None = None,
        card_resolver: dict[str, KnowledgeCardV1] | None = None,
    ) -> None:
        self._authority = authority or DecisionAuthorityContractV1(
            contract_id="knowledge-engine-v1-default",
        )
        self._cards = card_resolver or {}

    def analyze(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
        authority: DecisionAuthorityContractV1 | None = None,
    ) -> KnowledgeEvaluationBundleV1:
        auth = authority or self._authority

        adjudication_log: list[str] = []
        market_decisions: dict[str, dict[str, Any]] = {}
        degraded = False
        degraded_reasons: list[str] = []

        # 1. 强制 Policy Kernel 检查
        if baseline.baseline_pass:
            adjudication_log.append("policy_kernel: baseline_pass 已设置，跳过所有市场裁决")
            market_decisions = {
                market: {"status": "pass", "reason": "baseline_pass"}
                for market in ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2")
            }
            return self._build_bundle(
                features, retrieval, baseline, auth,
                market_decisions, adjudication_log, degraded, degraded_reasons,
            )

        # 2. 检查时间边界和赛后泄漏
        if not baseline.cutoff_valid or baseline.post_kickoff_leak:
            adjudication_log.append("policy_kernel: 时间边界无效或赛后泄漏，全部 pass")
            market_decisions = {
                market: {"status": "pass", "reason": "time_boundary_invalid"}
                for market in ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2")
            }
            return self._build_bundle(
                features, retrieval, baseline, auth,
                market_decisions, adjudication_log, degraded, degraded_reasons,
            )

        # 3. 检查冲突门禁
        if baseline.has_unresolved_conflicts:
            adjudication_log.append(
                f"policy_kernel: 未解决冲突 {len(baseline.conflict_ids)} 个"
            )

        # 4. 逐市场裁决
        markets = ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2")
        for market in markets:
            decision = self._adjudicate_market(
                market, features, retrieval, baseline, auth, adjudication_log,
            )
            market_decisions[market] = decision
            if decision.get("degraded"):
                degraded = True
                degraded_reasons.extend(decision.get("degradation_reasons", []))

        return self._build_bundle(
            features, retrieval, baseline, auth,
            market_decisions, adjudication_log, degraded, degraded_reasons,
        )

    def _adjudicate_market(
        self,
        market: str,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
        authority: DecisionAuthorityContractV1,
        log: list[str],
    ) -> dict[str, Any]:
        """裁决单个市场。"""
        # Policy kernel 检查
        if market in baseline.pass_markets and authority.baseline_pass_never_reopen:
            log.append(f"adjudicate: {market} baseline_pass，不可重新打开")
            return {"status": "pass", "reason": "baseline_pass_never_reopen"}

        # 独立证据要求
        if market == "score" and not baseline.independent_evidence_score:
            log.append(f"adjudicate: {market} 缺少独立正式规则，pass")
            return {"status": "pass", "reason": "no_independent_score_rule"}
        if market == "fixed_handicap_1x2" and not baseline.independent_evidence_fixed_handicap:
            log.append(f"adjudicate: {market} 缺少独立正式规则，pass")
            return {"status": "pass", "reason": "no_independent_fixed_handicap_rule"}
        if market == "total_goals" and not baseline.independent_evidence_total_goals:
            log.append(f"adjudicate: {market} 缺少独立正式规则，pass")
            return {"status": "pass", "reason": "no_independent_total_goals_rule"}

        baseline_ranking = list(baseline.market_rankings.get(market, ()))
        if not baseline_ranking:
            log.append(f"adjudicate: {market} 缺少冻结正式基线排序，pass")
            return {"status": "pass", "reason": "missing_official_baseline_ranking"}

        # The receipt holds references only.  Effect/category/market authority
        # comes from the sealed KnowledgeCard, never from an ID convention.
        decision_cards = [
            self._cards[cid] for cid in retrieval.retrieved_decision_cards
            if cid in self._cards
            and market in self._cards[cid].applicable_markets
            and self._cards[cid].category == KnowledgeCategory.DECISION_POLICY
        ]
        counter_cards = [
            self._cards[cid] for cid in retrieval.counter_and_conflict_cards
            if cid in self._cards and market in self._cards[cid].applicable_markets
        ]

        if not decision_cards:
            log.append(f"adjudicate: {market} 无适用决策卡，保留正式基线")
            return {"status": "assessed", "ranking": baseline_ranking, "degraded": False,
                    "applied_cards": [], "suppressed_cards": []}

        # 按优先级处理卡片效果
        result = self._apply_card_effects(
            market, baseline_ranking, decision_cards, counter_cards, authority, log,
        )
        return result

    def _apply_card_effects(
        self,
        market: str,
        baseline_ranking: list[str],
        decision_cards: list[KnowledgeCardV1],
        counter_cards: list[KnowledgeCardV1],
        authority: DecisionAuthorityContractV1,
        log: list[str],
    ) -> dict[str, Any]:
        """按优先级应用卡片效果。

        实现裁决权限的全部固定规则：
        - 单张卡不能改变第一选择
        - 第一选择变化至少需要两个同市场、同选择、独立 provenance group
        - 共享 source family 只算一个来源
        - 正反卡不进行数值抵消
        - 同级冲突保留基线排序并降级
        - 第一选择改变后市场固定 degraded，置信度不超过 0.69
        """
        result: dict[str, Any] = {
            "status": "assessed",
            "ranking": baseline_ranking,
            "degraded": False,
            "degradation_reasons": [],
            "applied_cards": [],
            "suppressed_cards": [],
            "confidence": None,
        }

        if not decision_cards:
            log.append(f"adjudicate: {market} 无决策卡片，保持基线")
            return result

        # 分组：按效果优先级分组
        force_pass_cards = []
        suppress_cards = []
        confidence_cap_cards = []
        rank_adjust_cards = []
        support_cards = []
        explain_cards = []

        for card in decision_cards:
            effects = set(card.allowed_effects)
            if KnowledgeEffect.FORCE_PASS in effects:
                force_pass_cards.append(card)
            if KnowledgeEffect.SUPPRESS_CANDIDATE in effects:
                suppress_cards.append(card)
            if effects & {KnowledgeEffect.CONFIDENCE_CAP, KnowledgeEffect.DEGRADE}:
                confidence_cap_cards.append(card)
            if KnowledgeEffect.BOUNDED_RANK_ADJUSTMENT in effects:
                rank_adjust_cards.append(card)
            if KnowledgeEffect.SUPPORT_EXISTING_DIRECTION in effects:
                support_cards.append(card)
            if KnowledgeEffect.EXPLAIN in effects:
                explain_cards.append(card)

        # 1. force_pass 优先级最高
        if force_pass_cards:
            log.append(f"adjudicate: {market} force_pass 触发，市场 pass")
            result["status"] = "pass"
            result["reason"] = "force_pass_triggered"
            result["applied_cards"] = [item.card_id for item in force_pass_cards]
            return result

        # 2. suppress_candidate
        if suppress_cards:
            result["suppressed_cards"].extend(item.card_id for item in suppress_cards)
            log.append(f"adjudicate: {market} suppress_candidate: {len(suppress_cards)} 张卡")

        # 3. confidence_cap / degrade
        if confidence_cap_cards:
            result["degraded"] = True
            result["degradation_reasons"].append("confidence_cap_or_degrade_triggered")
            result["confidence"] = min(
                result.get("confidence") or 0.69,
                authority.max_confidence_after_anchor_change,
            )
            log.append(f"adjudicate: {market} confidence_cap: 置信度上限 {result['confidence']}")

        # 4. bounded_rank_adjustment
        if rank_adjust_cards:
            # 检查是否满足锚点变化条件
            if authority.single_card_cannot_flip and len(rank_adjust_cards) < 2:
                log.append(f"adjudicate: {market} 单张卡不足以改变第一选择（{len(rank_adjust_cards)} 张）")
                result["suppressed_cards"].extend(item.card_id for item in rank_adjust_cards)
            elif authority.anchor_change_requires_two_independent:
                independent = {
                    (item.provenance_group, item.source_family)
                    for item in rank_adjust_cards
                }
                if len(independent) >= 2:
                    # Card V1 deliberately has no selection payload.  It may
                    # lower confidence and record an audit, but cannot invent
                    # or reverse a formal baseline ranking.
                    log.append(f"adjudicate: {market} 两个独立来源仅触发降级审计，保持基线排序")
                    result["applied_cards"].extend(item.card_id for item in rank_adjust_cards)
                    result["degraded"] = True
                    result["degradation_reasons"].append("bounded_rank_adjustment_audit")
                    result["confidence"] = authority.max_confidence_after_anchor_change
                else:
                    log.append(f"adjudicate: {market} 锚点变化需要两个独立 provenance/source family")
                    result["suppressed_cards"].extend(item.card_id for item in rank_adjust_cards)

        # 5. support_existing_direction
        if support_cards:
            result["applied_cards"].extend(item.card_id for item in support_cards)
            log.append(f"adjudicate: {market} support_existing_direction: {len(support_cards)} 张卡")

        # 6. explain（仅展示，不影响决策）
        if explain_cards:
            result["applied_cards"].extend(item.card_id for item in explain_cards)
            log.append(f"adjudicate: {market} explain: {len(explain_cards)} 张卡")

        # 反证和冲突卡处理
        if counter_cards and authority.no_netting_positive_negative:
            independent_counter = {
                (item.provenance_group, item.source_family) for item in counter_cards
            }
            log.append(f"adjudicate: {market} 正反卡不抵消，{len(independent_counter)} 个独立反证来源")
            if authority.same_level_conflict_downgrade:
                result["degraded"] = True
                result["degradation_reasons"].append("counter_evidence_present")
                result["confidence"] = min(
                    result.get("confidence") or 0.69,
                    authority.max_confidence_after_anchor_change,
                )

        return result

    def _build_bundle(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
        authority: DecisionAuthorityContractV1,
        market_decisions: dict[str, dict[str, Any]],
        adjudication_log: list[str],
        degraded: bool,
        degraded_reasons: list[str],
    ) -> KnowledgeEvaluationBundleV1:
        import hashlib
        import json

        confidence = None
        if not degraded and all(
            d.get("status") == "assessed" for d in market_decisions.values()
        ):
            confidence = 0.8

        raw = {
            "schema_version": 1,
            "match_id": features.match_id,
            "as_of": features.as_of.isoformat(),
            "feature_sha256": features.feature_sha256,
            "retrieval_sha256": retrieval.retrieval_sha256,
            "baseline_sha256": baseline.policy_kernel_sha256,
            "authority_contract_id": authority.contract_id,
            "market_decisions": market_decisions,
            "adjudication_log": tuple(adjudication_log),
            "confidence": confidence,
            "degraded": degraded,
            "degraded_reasons": tuple(degraded_reasons),
            "bundle_sha256": "0" * 64,
        }
        bundle_hash = hashlib.sha256(
            json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        raw["bundle_sha256"] = bundle_hash

        return KnowledgeEvaluationBundleV1.model_validate(raw)
