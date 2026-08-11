"""Knowledge Engine 知识与索引端口。

定义 KnowledgeSource、KnowledgeIndex、ArtifactStore 和 Reasoner 的契约。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from ..domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
from ..domain.decisions import DecisionAuthorityContractV1, KnowledgeEvaluationBundleV1
from ..domain.retrieval import KnowledgeRetrievalReceiptV1


class KnowledgeSourcePort(Protocol):
    """知识来源端口。

    proposal 模式只允许显式指定 2.0.0。
    正式模式只加载 Receipt 引用的已发布 Snapshot。
    Snapshot 缺失或哈希不符时 fail closed。
    """

    def load_knowledge_cards(
        self,
        snapshot_sha256: str,
        tier: str | None = None,
        category: str | None = None,
        market: str | None = None,
    ) -> list[dict[str, Any]]:
        """加载知识卡片。"""
        ...

    def load_snapshot_manifest(
        self,
        snapshot_sha256: str,
    ) -> dict[str, Any]:
        """加载快照清单。"""
        ...

    def validate_snapshot_integrity(
        self,
        snapshot_sha256: str,
    ) -> bool:
        """验证快照完整性。"""
        ...


class KnowledgeIndexPort(Protocol):
    """知识索引端口。

    普通 SQLite 表执行层级、市场、标签和数值范围过滤。
    FTS5 只对过滤后的小候选集执行 BM25。
    SQL 全部参数化，不接受原始 FTS 表达式。
    """

    def search(
        self,
        query: dict[str, Any],
        tier: str | None = None,
        market: str | None = None,
        limit: int = 12,
    ) -> list[str]:
        """分层检索，返回 card_id 列表。"""
        ...

    def search_fts5(
        self,
        query_text: str,
        card_ids: list[str],
        limit: int = 12,
    ) -> list[str]:
        """对过滤后候选集执行 BM25 检索。"""
        ...

    def get_counter_cards(
        self,
        card_ids: list[str],
    ) -> list[str]:
        """强制补齐反证、互斥和冲突卡。"""
        ...

    def validate_index(
        self,
    ) -> bool:
        """验证索引完整性。"""
        ...


class ArtifactStorePort(Protocol):
    """产物存储端口。

    提供内容寻址写入、追加事件、幂等键、事务和恢复。
    校验路径不得越出受管目录，不跟随越界符号链接。
    相同 ID、相同内容返回原产物；相同 ID、不同内容拒绝覆盖。
    """

    def write_artifact(
        self,
        artifact_id: str,
        content: dict[str, Any],
    ) -> str:
        """内容寻址写入，返回路径。"""
        ...

    def read_artifact(
        self,
        path: str,
    ) -> dict[str, Any]:
        """读取产物。"""
        ...

    def append_event(
        self,
        ledger_path: str,
        event: dict[str, Any],
    ) -> None:
        """追加事件到台账。"""
        ...

    def validate_path(
        self,
        path: str,
    ) -> bool:
        """校验路径不越出受管目录。"""
        ...


class KnowledgeReasoner(Protocol):
    """知识推理器端口。

    分析特征、检索结果和基线，生成评估包。
    """

    def analyze(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
        authority: DecisionAuthorityContractV1,
    ) -> KnowledgeEvaluationBundleV1:
        """分析并生成评估包。"""
        ...


class ClockPort(Protocol):
    """时钟端口。

    提供当前时间，便于测试替身。
    """

    def now(self) -> datetime:
        """返回当前时间（含时区）。"""
        ...