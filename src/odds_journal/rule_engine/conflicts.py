from __future__ import annotations

from typing import Iterable


def independent_supports(events: Iterable[dict], market: str, selection: str) -> bool:
    """Require two adopted events whose frozen snapshots and correlation keys do not overlap."""
    candidates = [
        item for item in events
        if item.get("triggered") and item.get("disposition") == "adopted"
        and item.get("effect") == "ranking"
        and item.get("target_market") == market
        and item.get("target_selection") == selection
    ]
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if not (set(left.get("source_snapshot_ids", [])) & set(right.get("source_snapshot_ids", []))) and not (
                set(left.get("correlation_keys", [])) & set(right.get("correlation_keys", []))
            ):
                return True
    return False
