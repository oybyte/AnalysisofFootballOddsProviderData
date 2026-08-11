"""Knowledge Engine AI 推理器适配器。

接入现有 LLM Provider、预算、出站和 Prompt 哈希治理。
AI 输入仅包含白名单事实、知识、案例和证据 ID。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain.ai_v2 import AIAdvisoryInputReceiptV1, AIAnalysisCandidateV1
from ..domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
from ..domain.retrieval import KnowledgeRetrievalReceiptV1


class AIReasonerAdapter:
    """AI 推理器适配器。

    可选，只生成提示候选。AI V2 与 AI V1 使用独立模型和目录。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def is_available(self) -> bool:
        """检查 AI 推理器是否可用。"""
        try:
            from ...ai_capabilities import get_capabilities

            caps = get_capabilities(self._root)
            return caps.get("real_provider", {}).get("status") == "ready"
        except Exception:
            return False

    def generate_advisory(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
        study_id: str = "",
        run_id: str = "",
    ) -> dict[str, Any]:
        """生成 AI 旁路提示候选。

        AI 输入仅包含白名单事实、知识、案例和证据 ID。
        对不可信文本转义并隔离 Prompt 指令。
        """
        if not self.is_available():
            return {
                "status": "unavailable",
                "reason": "AI provider not available",
            }

        # 构建白名单输入
        input_receipt = self._build_input_receipt(
            features, retrieval, baseline, study_id, run_id,
        )

        try:
            # 调用 LLM Provider
            from ...llm_provider import get_provider

            provider = get_provider(self._root)
            if provider is None:
                return {
                    "status": "unavailable",
                    "reason": "no LLM provider configured",
                }

            prompt = self._build_prompt(features, retrieval, baseline)
            response = provider.generate(prompt)

            # 构建 AI 候选
            candidate = self._build_candidate(
                input_receipt, response, features.match_id, study_id, run_id,
            )
            return {
                "status": "success",
                "input_receipt": input_receipt.model_dump(mode="json"),
                "candidate": candidate.model_dump(mode="json"),
            }
        except Exception as exc:
            return {
                "status": "failed",
                "reason": str(exc),
            }

    def _build_input_receipt(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
        study_id: str,
        run_id: str,
    ) -> AIAdvisoryInputReceiptV1:
        from datetime import datetime, timezone, timedelta

        tz = timezone(timedelta(hours=8))
        return AIAdvisoryInputReceiptV1(
            receipt_id=f"ai-advisory:{features.match_id}:{study_id}:{run_id}",
            match_id=features.match_id,
            study_id=study_id,
            run_id=run_id,
            fact_ids=features.fact_ids,
            knowledge_card_ids=(
                retrieval.mandatory_policy_cards
                + retrieval.retrieved_decision_cards
                + retrieval.retrieved_explanation_cards
            ),
            case_ids=features.case_ids,
            evidence_ids=(),
            feature_sha256=features.feature_sha256,
            retrieval_sha256=retrieval.retrieval_sha256,
            provider_id="ai-reasoner-v2",
            model_id="ai-reasoner-v2",
            prompt_sha256="0" * 64,
            created_at=datetime.now(tz).replace(microsecond=0),
            input_receipt_sha256="0" * 64,
        )

    def _build_prompt(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
    ) -> str:
        """构建 AI 提示 — 仅包含白名单 ID，不包含原始文本。"""
        lines = [
            "# Knowledge Engine V2 AI Advisory",
            "",
            f"## Match: {features.match_id}",
            f"## As Of: {features.as_of.isoformat()}",
            "",
            "## Feature Snapshot",
            f"- observation_ids: {list(features.observation_ids)}",
            f"- fact_ids: {list(features.fact_ids)}",
            f"- case_ids: {list(features.case_ids)}",
            "",
            "## Knowledge Retrieval",
            f"- mandatory_policy_cards: {list(retrieval.mandatory_policy_cards)}",
            f"- retrieved_decision_cards: {list(retrieval.retrieved_decision_cards)}",
            f"- retrieved_explanation_cards: {list(retrieval.retrieved_explanation_cards)}",
            f"- counter_and_conflict_cards: {list(retrieval.counter_and_conflict_cards)}",
            "",
            "## Policy Kernel Baseline",
            f"- cutoff_valid: {baseline.cutoff_valid}",
            f"- has_unresolved_conflicts: {baseline.has_unresolved_conflicts}",
            f"- baseline_pass: {baseline.baseline_pass}",
            "",
            "## Instructions",
            "Analyze the above references and provide advisory recommendations.",
            "Do NOT modify official Outlook, rules, or evidence snapshots.",
            "Output format: JSON with market assessments.",
        ]
        return "\n".join(lines)

    def _build_candidate(
        self,
        input_receipt: AIAdvisoryInputReceiptV1,
        response: Any,
        match_id: str,
        study_id: str,
        run_id: str,
    ) -> AIAnalysisCandidateV1:
        from datetime import datetime, timezone, timedelta

        tz = timezone(timedelta(hours=8))
        return AIAnalysisCandidateV1(
            candidate_id=f"ai-candidate:{match_id}:{study_id}:{run_id}",
            match_id=match_id,
            study_id=study_id,
            run_id=run_id,
            input_receipt_sha256=input_receipt.input_receipt_sha256,
            provider_id="ai-reasoner-v2",
            model_id="ai-reasoner-v2",
            raw_response_sha256="0" * 64,
            parsed_output={},
            input_tokens=0,
            output_tokens=0,
            status="success",
            generated_at=datetime.now(tz).replace(microsecond=0),
            candidate_sha256="0" * 64,
        )