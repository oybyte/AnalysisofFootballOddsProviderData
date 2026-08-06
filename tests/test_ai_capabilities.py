from __future__ import annotations

from pathlib import Path

from odds_journal.ai_capabilities import status, validate


def test_capability_status_preserves_controlled_disabled_state(tmp_path: Path) -> None:
    payload = status(tmp_path)
    by_name = {item["capability"]: item["status"] for item in payload["checks"]}
    assert by_name["governance"] == "ready"
    assert by_name["case_rerank"] == "controlled_disabled"
    assert validate(tmp_path) == []
