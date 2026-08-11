"""Knowledge Engine 正式草稿适配器。

将 Knowledge Candidate 转换为 AnalysisDraftInput V4。
旁路阶段不注册到正式命令，发布后只处理 Contract 9。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class FormalDraftAdapter:
    """正式草稿适配器。

    旁路阶段不注册到正式命令。
    发布后只处理 Contract 9。
    将 Knowledge Candidate 转换为 AnalysisDraftInput V4。
    不直接 accept、evaluate、lock 或修改 Match。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def convert_to_draft_input(
        self,
        candidate: dict[str, Any],
        features: dict[str, Any],
        retrieval: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        """将 Knowledge Candidate 转换为 AnalysisDraftInput V4。

        evaluate 阶段重新计算 Feature、Retrieval 和 Evaluation Bundle，
        并拒绝不一致候选。
        """
        return {
            "schema_version": 4,
            "match_id": candidate.get("match_id", ""),
            "as_of": candidate.get("as_of", ""),
            "analysis_input_mode": "full_context",
            "compiler_version": "knowledge-engine-v1",
            "calibration_config_sha256": candidate.get("calibration_config_sha256", "0" * 64),
            "analysis_receipt_sha256": candidate.get("analysis_receipt_sha256", "0" * 64),
            "market_observations_sha256": candidate.get("market_observations_sha256", "0" * 64),
            "fact_bundle_sha256": candidate.get("fact_bundle_sha256"),
            "formal_gate": candidate.get("formal_gate", {}),
            "market_assessments": candidate.get("market_assessments", {}),
            "hypotheses": candidate.get("hypotheses", {}),
            "candidate_sha256": candidate.get("candidate_sha256", "0" * 64),
        }

    def validate_candidate_consistency(
        self,
        candidate: dict[str, Any],
        features: dict[str, Any],
        retrieval: dict[str, Any],
        evaluation: dict[str, Any],
    ) -> tuple[bool, str]:
        """验证候选与特征、检索、评估的一致性。

        拒绝不一致候选。
        """
        checks: list[tuple[bool, str]] = []

        # 检查 feature 绑定
        if candidate.get("feature_sha256") != features.get("feature_sha256"):
            checks.append((False, "feature_sha256 不一致"))

        # 检查 retrieval 绑定
        if candidate.get("retrieval_sha256") != retrieval.get("retrieval_sha256"):
            checks.append((False, "retrieval_sha256 不一致"))

        # 检查 evaluation 绑定
        if candidate.get("evaluation_bundle_sha256") != evaluation.get("bundle_sha256"):
            checks.append((False, "evaluation_bundle_sha256 不一致"))

        failed = [msg for ok, msg in checks if not ok]
        if failed:
            return False, "; ".join(failed)
        return True, "consistent"

    def is_contract_9(self, receipt: dict[str, Any]) -> bool:
        """检查是否为 Contract 9。"""
        return (
            receipt.get("schema_version") == 9
            or receipt.get("calibration_contract_version") == 9
        )

    def can_handle(self, receipt: dict[str, Any]) -> bool:
        """检查是否可以处理此回执。"""
        # 发布后只处理 Contract 9
        return self.is_contract_9(receipt)