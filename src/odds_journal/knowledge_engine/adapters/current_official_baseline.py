"""Knowledge Engine 官方基线适配器。

接入现有正式分析产物（Outlook、锁定、结算）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..ports.observations import OfficialBaselineReaderPort


class CurrentOfficialBaselineReader:
    """当前官方基线读取适配器。"""

    def __init__(self, root: Path) -> None:
        self._root = root

    def read_baseline(
        self,
        match_id: str,
    ) -> dict[str, Any] | None:
        from ...markdown import MatchDocument

        match_path = self._find_match_path(match_id)
        if match_path is None:
            return None
        document = MatchDocument.load(match_path)
        return {
            "match_id": match_id,
            "status": str(document.metadata.status),
            "kickoff_at": document.metadata.kickoff_at.isoformat()
            if document.metadata.kickoff_at
            else None,
            "primary_market": (
                str(document.metadata.primary_market)
                if document.metadata.primary_market
                else None
            ),
            "primary_selection": document.metadata.primary_selection,
            "confidence": document.metadata.confidence,
            "locked_at": document.metadata.locked_at.isoformat()
            if document.metadata.locked_at
            else None,
            "prematch_lock_sha256": document.metadata.prematch_lock_sha256,
            "has_outlook": document.metadata.analysis_outlook is not None,
        }

    def has_valid_baseline(
        self,
        match_id: str,
    ) -> bool:
        baseline = self.read_baseline(match_id)
        if baseline is None:
            return False
        return (
            baseline.get("locked_at") is not None
            and baseline.get("prematch_lock_sha256") is not None
        )

    def _find_match_path(self, match_id: str) -> Path | None:
        matches_dir = self._root / "matches"
        for path in matches_dir.glob(f"*{match_id}*.md"):
            return path
        return None