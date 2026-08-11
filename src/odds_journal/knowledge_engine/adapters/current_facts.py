"""Knowledge Engine 事实适配器。

接入现有 formal_draft 模块的 PrematchFact 系统。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..ports.observations import FactReaderPort


class CurrentFactReader:
    """当前事实读取适配器。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    def read_facts(
        self,
        match_id: str,
        cutoff: datetime,
    ) -> list[dict[str, Any]]:
        from ...formal_draft import _active_fact_bundle

        bundle = _active_fact_bundle(self._root, match_id, cutoff)
        if bundle is None:
            return []
        return [
            {
                "fact_id": fact.fact_id,
                "fact_type": fact.fact_type,
                "subject": fact.subject,
                "value": fact.value,
                "source_ref": fact.source_ref,
                "observed_at": fact.observed_at.isoformat(),
                "received_at": fact.received_at.isoformat(),
                "authentication_status": fact.authentication_status,
            }
            for fact in bundle.facts
            if fact.authentication_status == "authenticated"
            and fact.observed_at <= cutoff
            and fact.received_at <= cutoff
        ]

    def has_theoretical_positioning(
        self,
        match_id: str,
        cutoff: datetime,
    ) -> bool:
        from ...formal_draft import _active_fact_bundle, _has_theoretical_positioning

        bundle = _active_fact_bundle(self._root, match_id, cutoff)
        return _has_theoretical_positioning(bundle, cutoff)