"""Knowledge Engine 领域异常。"""

from __future__ import annotations


class KnowledgeEngineError(Exception):
    """知识引擎基础异常。"""


class SnapshotNotFoundError(KnowledgeEngineError):
    """知识快照不存在或哈希不匹配。"""


class IndexCorruptedError(KnowledgeEngineError):
    """检索索引损坏或不一致。"""


class CandidateInconsistencyError(KnowledgeEngineError):
    """候选输入与冻结快照不一致。"""


class AdjudicationBlockedError(KnowledgeEngineError):
    """裁决被 Policy Kernel 阻断。"""


class StudyPrimaryConflictError(KnowledgeEngineError):
    """Study primary run 违反唯一性约束。"""


class ExposureWindowExpiredError(KnowledgeEngineError):
    """Exposure 窗口已过期（开赛后不可暴露）。"""


class ProposalNotFoundError(KnowledgeEngineError):
    """指定的 Proposal 版本不存在。"""


class SnapshotSealRejectedError(KnowledgeEngineError):
    """Snapshot 封存被拒绝（验证未通过）。"""


class MigrationCoverageError(KnowledgeEngineError):
    """知识迁移未达到 100% source disposition coverage。"""


class AIAdvisoryUnavailableError(KnowledgeEngineError):
    """AI 旁路不可用。"""


class KnowledgeCardConflictError(KnowledgeEngineError):
    """知识卡片冲突（同一 card_id 不同内容）。"""


class PathTraversalError(KnowledgeEngineError):
    """路径越出受管目录。"""