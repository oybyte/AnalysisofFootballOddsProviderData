"""Knowledge Engine 案例适配器。

接入现有 case_retrieval 和 case_rerank 模块。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..ports.observations import CaseContextReaderPort


class CurrentCaseReader:
    """当前案例读取适配器。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    def read_case_receipt(
        self,
        match_id: str,
    ) -> dict[str, Any] | None:
        case_receipt_path = (
            self._root / "raw" / "matches" / match_id / "case-retrieval.yml"
        )
        if not case_receipt_path.is_file():
            return None
        import yaml

        data = yaml.safe_load(case_receipt_path.read_text(encoding="utf-8")) or {}
        if not data:
            return None
        return data

    def list_relevant_cases(
        self,
        match_id: str,
        market: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        receipt = self.read_case_receipt(match_id)
        if receipt is None:
            return []
        cases = receipt.get("cases", [])
        return [
            {
                "case_id": c.get("case_id", ""),
                "market": market,
                "similarity": c.get("similarity", 0),
                "summary": c.get("summary", ""),
            }
            for c in cases
            if c.get("market") == market
        ][:limit]