"""Knowledge Engine 数据读取端口。

定义 Observation、Fact、Case 和 OfficialBaseline 的读取契约。
所有端口只定义 Protocol，不包含实现。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class ObservationReaderPort(Protocol):
    """观测读取端口。

    按比赛、市场和 cutoff 返回合格观测。
    """

    def read_observations(
        self,
        match_id: str,
        market: str,
        cutoff: datetime,
    ) -> list[dict[str, Any]]:
        """返回 cutoff 前的合格观测。

        强制 received_at <= as_of < kickoff_at。
        返回认证状态、时间精度、冲突和来源血缘。
        不暴露 cutoff 后观测和赛果。
        """
        ...

    def observation_conflicts(
        self,
        match_id: str,
        market: str,
        cutoff: datetime,
    ) -> list[str]:
        """返回冲突观测 ID 列表。"""
        ...


class FactReaderPort(Protocol):
    """事实读取端口。

    只让 authenticated 结构化事实影响决策。
    unverified 事实只用于展示。
    """

    def read_facts(
        self,
        match_id: str,
        cutoff: datetime,
    ) -> list[dict[str, Any]]:
        """返回 cutoff 前的已认证事实。

        禁止从球队名称、盘口或赛果反推实力、阵容或意图。
        """
        ...

    def has_theoretical_positioning(
        self,
        match_id: str,
        cutoff: datetime,
    ) -> bool:
        """是否存在可用的理论实力定位。"""
        ...


class CaseContextReaderPort(Protocol):
    """案例上下文读取端口。

    读取已冻结 Case Retrieval Receipt。
    案例只能用于条件比较和解释，不得直接创建候选或重新打开 pass。
    """

    def read_case_receipt(
        self,
        match_id: str,
    ) -> dict[str, Any] | None:
        """返回已冻结的案例检索回执。"""
        ...

    def list_relevant_cases(
        self,
        match_id: str,
        market: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """返回相关案例摘要。"""
        ...


class OfficialBaselineReaderPort(Protocol):
    """官方基线读取端口。

    读取已 validate/render 的正式赛前 Outlook 和报告。
    在任何知识或 AI 输出展示前生成 OfficialBaselineSnapshotV1。
    """

    def read_baseline(
        self,
        match_id: str,
    ) -> dict[str, Any] | None:
        """返回官方基线数据。

        基线不存在或已过期时返回 None。
        """
        ...

    def has_valid_baseline(
        self,
        match_id: str,
    ) -> bool:
        """是否存在有效的官方基线。"""
        ...