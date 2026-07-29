from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from odds_journal.extraction import (
    load_media_inventory,
    load_text_inventory,
    source_coverage,
    verify_source_hashes,
)
from odds_journal.ledger import append_payloads, read_ledger


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_repository_source_inventory_is_complete_and_reconstructable() -> None:
    root = repository_root()
    source = root / "knowledge" / "sources" / "doubao-2026-07-28"
    verify_source_hashes(source)
    atoms = load_text_inventory(root)
    assert len({item.round_no for item in atoms if item.source_id.endswith("-text") and item.round_no}) == 207
    assert len({item.round_no for item in atoms if item.source_id.endswith("-illustrated") and item.round_no}) == 207
    for relative in {item.source_path for item in atoms}:
        items = sorted((item for item in atoms if item.source_path == relative), key=lambda item: item.byte_start)
        assert items[0].byte_start == 0
        assert items[-1].byte_end == (root / relative).stat().st_size
        assert all(left.byte_end == right.byte_start for left, right in zip(items, items[1:]))


def test_repository_media_inventory_classifies_every_archived_file() -> None:
    media = load_media_inventory(repository_root())
    assert len(media) == 251
    assert sum(item.decode_status == "valid" for item in media) == 184
    assert sum(item.decode_status == "corrupt" for item in media) == 46
    assert sum(item.decode_status == "zero_byte" for item in media) == 21
    assert all(item.mapping_status == "referenced" for item in media if item.decode_status == "valid")


def test_ledger_hash_chain_rejects_mutation(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    recorded_at = datetime(2026, 7, 29, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    append_payloads(
        path,
        [{"claim_id": "claim-1", "value": "升盘"}, {"claim_id": "claim-2", "value": "降水"}],
        recorded_at=recorded_at,
        actor="test",
        event_id_factory=lambda item, index: f"claim:test:{index}",
    )
    assert len(read_ledger(path)) == 2
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["value"] = "被改写"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    try:
        read_ledger(path)
    except ValueError as exc:
        assert "event_sha256" in str(exc) or "断链" in str(exc)
    else:
        raise AssertionError("被改写的事件链必须校验失败")


def test_reviewed_coverage_is_auditable_and_complete() -> None:
    result = source_coverage(repository_root())
    assert result.source_hashes_valid
    assert all(value == 1.0 for value in result.byte_coverage.values())
    assert result.auditable_complete
    assert result.unresolved_targets == 0
    assert result.unresolved_conflicts == 0
    assert result.blocker_count == 0
