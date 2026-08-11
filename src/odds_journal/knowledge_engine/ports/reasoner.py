"""Knowledge Engine 推理器端口。

定义 DeterministicReasoner 和 AIReasoner 的契约。
"""

from __future__ import annotations

from typing import Any, Protocol

from ..domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
from ..domain.decisions import DecisionAuthorityContractV1, KnowledgeEvaluationBundleV1
from ..domain.retrieval import KnowledgeRetrievalReceiptV1


class DeterministicReasonerPort(Protocol):
    """确定性推理器端口。

    正式必需、完全离线。
    """

    def analyze(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
        authority: DecisionAuthorityContractV1,
    ) -> KnowledgeEvaluationBundleV1:
        """执行确定性分析，生成评估包。"""
        ...


class AIReasonerPort(Protocol):
    """AI 推理器端口。

    可选，只生成提示候选。
    """

    def generate_advisory(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
    ) -> dict[str, Any]:
        """生成 AI 旁路提示候选。"""
        ...

    def is_available(self) -> bool:
        """检查 AI 推理器是否可用。"""
        ...