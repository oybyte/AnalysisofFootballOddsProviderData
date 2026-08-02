from pathlib import Path

import pytest

from odds_journal.history_migration import (
    HISTORY_EXTRACTION_DIR,
    _units,
    build_history_inventory,
)


def _history_text(count: int = 349) -> str:
    return "".join(
        f"# {index}、测试段落\n**问题详情：**\n问题 {index}\n---\n回答 {index}\n"
        for index in range(1, count + 1)
    )


def test_numbered_history_inventory_is_contiguous(tmp_path: Path) -> None:
    source = tmp_path / "history.md"
    source.write_text(_history_text(), encoding="utf-8")
    record = build_history_inventory(tmp_path, source)
    assert record["unit_count"] == 349
    assert record["text_atom_count"] > 349
    assert record["byte_coverage"] == 1.0
    inventory = tmp_path / HISTORY_EXTRACTION_DIR / "text-inventory.jsonl"
    rows = inventory.read_text(encoding="utf-8").splitlines()
    assert rows[0]
    assert rows[-1]
    assert (tmp_path / HISTORY_EXTRACTION_DIR / "case-link-candidates.jsonl").exists()

    second = build_history_inventory(tmp_path, source)
    assert second["text_atom_count"] == record["text_atom_count"]


def test_numbered_history_inventory_rejects_gaps(tmp_path: Path) -> None:
    source = tmp_path / "history.md"
    source.write_text(_history_text().replace("# 10、", "# 11、", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="1..349"):
        build_history_inventory(tmp_path, source)
