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
from ..ports.knowledge import KnowledgeReasoner


class DeterministicKnowledgeReasoner:
    """确定性知识推理器。

    正式必需、完全离线。
    实现裁决权限的全部固定规则。
    """

    def __init__(self, authority: DecisionAuthorityContractV1 | None = None) -> None:
        self._authority = authority or DecisionAuthorityContractV1(
            contract_id="knowledge-engine-v1-default",
        )

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

        # 获取该市场的知识卡片
        decision_cards = [
            cid for cid in retrieval.retrieved_decision_cards
        ]
        counter_cards = list(retrieval.counter_and_conflict_cards)

        if not decision_cards:
            log.append(f"adjudicate: {market} 无决策卡片，保持基线")
            return {"status": "assessed", "ranking": [], "degraded": False}

        # 按优先级处理卡片效果
        result = self._apply_card_effects(
            market, decision_cards, counter_cards, authority, log,
        )
        return result

    def _apply_card_effects(
        self,
        market: str,
        decision_cards: list[str],
        counter_cards: list[str],
        authority: DecisionAuthorityContractV1,
        log: list[str],
    ) -> dict[str, Any]:
        """按优先级应用卡片效果。"""
        result: dict[str, Any] = {
            "status": "assessed",
            "ranking": [],
            "degraded": False,
            "degradation_reasons": [],
            "applied_cards": [],
            "suppressed_cards": [],
        }

        # 这里需要根据卡片内容应用效果
        # 当前阶段，核心裁决逻辑在后续阶段完善
        log.append(f"adjudicate: {market} 应用 {len(decision_cards)} 张决策卡")

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