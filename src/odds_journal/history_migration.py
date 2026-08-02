from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from .extraction import TextAtom
from .ledger import atomic_write_text


HISTORY_SOURCE_FAMILY = "doubao-football-history-2026-08-02"
HISTORY_SOURCE_DIR = Path("knowledge/sources") / HISTORY_SOURCE_FAMILY
HISTORY_EXTRACTION_DIR = Path("knowledge/extraction") / HISTORY_SOURCE_FAMILY
NUMBERED_HEADING_RE = re.compile(r"^#\s+(?P<number>\d+)、")
SCORE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-:：]\s*(\d{1,2})(?!\d)")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u200b", "").strip()).lower()


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(
        path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
    )


def _line_offsets(raw: bytes) -> list[tuple[int, int, str]]:
    text = raw.decode("utf-8")
    output: list[tuple[int, int, str]] = []
    cursor = 0
    for line in text.splitlines(keepends=True):
        end = cursor + len(line.encode("utf-8"))
        output.append((cursor, end, line))
        cursor = end
    if cursor < len(raw):
        output.append((cursor, len(raw), raw[cursor:].decode("utf-8")))
    return output


def _units(lines: list[tuple[int, int, str]]) -> list[tuple[int, int, int]]:
    starts: list[tuple[int, int]] = []
    for index, (_, _, line) in enumerate(lines):
        match = NUMBERED_HEADING_RE.match(line.rstrip("\r\n"))
        if match:
            starts.append((index, int(match.group("number"))))
    numbers = [number for _, number in starts]
    if numbers != list(range(1, 350)):
        raise ValueError(f"新聊天记录编号必须连续为 1..349，当前为 {numbers[:3]}...{numbers[-3:]}")
    result: list[tuple[int, int, int]] = []
    for position, (start, number) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        result.append((number, start, end))
    return result


def _role_map(lines: list[tuple[int, int, str]], start: int, end: int) -> tuple[set[int], bool]:
    question = next(
        (index for index in range(start, end) if "**问题详情：**" in lines[index][2]),
        None,
    )
    if question is None:
        return set(), False
    divider = next(
        (index for index in range(question + 1, end) if lines[index][2].strip() == "---"),
        end,
    )
    return set(range(question, divider)), True


def _atom_rows(root: Path, source_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw = source_path.read_bytes()
    lines = _line_offsets(raw)
    units = _units(lines)
    unit_by_line: dict[int, int] = {}
    unresolved: list[int] = []
    user_lines: set[int] = set()
    for number, start, end in units:
        unit_by_line.update({line: number for line in range(start, end)})
        users, valid = _role_map(lines, start, end)
        user_lines |= users
        if not valid:
            unresolved.append(number)
    atoms: list[dict[str, Any]] = []
    for index, (byte_start, byte_end, line) in enumerate(lines, start=1):
        number = unit_by_line.get(index - 1)
        role = "preamble" if number is None else ("user" if index - 1 in user_lines else "author")
        stripped = line.strip()
        if not stripped:
            atom_type = "gap"
        elif NUMBERED_HEADING_RE.match(line.rstrip("\r\n")):
            atom_type = "heading"
        elif stripped == "---":
            atom_type = "separator"
        else:
            atom_type = "paragraph"
        atom_id = f"{HISTORY_SOURCE_FAMILY}-text-a{index:06d}"
        atoms.append(
            {
                "schema_version": 1,
                "atom_id": atom_id,
                "source_family_id": HISTORY_SOURCE_FAMILY,
                "source_id": f"{HISTORY_SOURCE_FAMILY}-text",
                "source_path": source_path.relative_to(root).as_posix(),
                "round_no": number,
                "unit_no": number,
                "role": role,
                "atom_type": atom_type,
                "byte_start": byte_start,
                "byte_end": byte_end,
                "line_start": index,
                "line_end": index,
                "heading_path": [],
                "content_sha256": _sha256(_canonical(line).encode("utf-8")),
                "canonical_text": _canonical(line),
                "companion_atom_ids": [],
                "comparison_status": "unmatched",
                "duplicate_of": None,
            }
        )
    return atoms, [{"unit_no": number, "status": "unresolved", "reason": "缺少问题详情边界"} for number in unresolved]


def _old_atom_hashes(root: Path) -> dict[str, str]:
    inventory_path = root / "knowledge/extraction/doubao-2026-07-28/text-inventory.jsonl"
    result: dict[str, str] = {}
    if not inventory_path.exists():
        return result
    raw_cache: dict[str, bytes] = {}
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        source_path = str(row.get("source_path") or "")
        if source_path not in raw_cache:
            path = root / source_path
            if path.exists():
                raw_cache[source_path] = path.read_bytes()
        raw = raw_cache.get(source_path)
        if raw is None:
            continue
        start = int(row.get("byte_start", 0))
        end = int(row.get("byte_end", 0))
        canonical_hash = _sha256(_canonical(raw[start:end].decode("utf-8")).encode("utf-8"))
        result.setdefault(canonical_hash, str(row.get("atom_id")))
    return result


def build_history_inventory(root: Path, source_file: Path) -> dict[str, Any]:
    source_file = source_file.resolve()
    source_dir = root / HISTORY_SOURCE_DIR
    extraction_dir = root / HISTORY_EXTRACTION_DIR
    source_dir.mkdir(parents=True, exist_ok=True)
    extraction_dir.mkdir(parents=True, exist_ok=True)
    archived = source_dir / "足球竞猜机构数据分析.md"
    if archived.exists() and archived.read_bytes() != source_file.read_bytes():
        raise ValueError(f"归档文件已存在且内容不同：{archived}")
    if not archived.exists():
        shutil.copyfile(source_file, archived)
    raw = archived.read_bytes()
    manifest = {
        "schema_version": 1,
        "source_family_id": HISTORY_SOURCE_FAMILY,
        "source_family": HISTORY_SOURCE_FAMILY,
        "content_immutable": True,
        "parser": "numbered-dialogue",
        "unit_count": 349,
        "image_reference_count": 0,
        "migration_status": "inventory_ready",
        "files": [{"archived_name": archived.name, "size": len(raw), "sha256": _sha256(raw)}],
    }
    atomic_write_text(source_dir / "MANIFEST.yml", yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    atoms, unresolved_units = _atom_rows(root, archived)
    old_hashes = _old_atom_hashes(root)
    mappings: list[dict[str, Any]] = []
    for atom in atoms:
        old_id = old_hashes.get(atom["content_sha256"])
        if old_id:
            atom["comparison_status"] = "identical"
            atom["duplicate_of"] = old_id
            mappings.append({"new_atom_id": atom["atom_id"], "old_atom_id": old_id, "match_type": "exact", "status": "duplicate"})
        else:
            mappings.append({"new_atom_id": atom["atom_id"], "old_atom_id": None, "match_type": "unmatched", "status": "new"})
    _jsonl(extraction_dir / "text-inventory.jsonl", atoms)
    _jsonl(extraction_dir / "source-mapping.jsonl", mappings)
    _jsonl(extraction_dir / "case-link-candidates.jsonl", _case_candidates(atoms))
    atomic_write_text(extraction_dir / "unresolved-units.yml", yaml.safe_dump(unresolved_units, allow_unicode=True, sort_keys=False))
    source_record = {**manifest, "text_atom_count": len(atoms), "byte_coverage": 1.0, "unresolved_unit_count": len(unresolved_units)}
    atomic_write_text(extraction_dir / "source.yml", yaml.safe_dump(source_record, allow_unicode=True, sort_keys=False))
    for name in ("claim-events.jsonl", "case-events.jsonl", "disposition-events.jsonl", "conflict-events.jsonl", "rule-confirmation-events.jsonl"):
        path = extraction_dir / name
        if not path.exists():
            atomic_write_text(path, "")
    return source_record


def _case_candidates(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_unit: dict[int, list[dict[str, Any]]] = {}
    for atom in atoms:
        if atom.get("unit_no") is not None:
            by_unit.setdefault(int(atom["unit_no"]), []).append(atom)
    rows: list[dict[str, Any]] = []
    for unit_no, items in sorted(by_unit.items()):
        text = " ".join(item.get("canonical_text", "") for item in items)
        scores = [f"{a}-{b}" for a, b in SCORE_RE.findall(text)]
        if not scores and not any(token in text for token in ("vs", " VS ", "比赛", "盘口")):
            continue
        candidate_id = f"{HISTORY_SOURCE_FAMILY}-unit-{unit_no:03d}"
        rows.append({
            "candidate_id": candidate_id,
            "source_family_id": HISTORY_SOURCE_FAMILY,
            "source_atom_ids": [item["atom_id"] for item in items],
            "source_unit_no": unit_no,
            "title": next((item["canonical_text"] for item in items if item["atom_type"] == "heading"), ""),
            "score_claim": scores[0] if scores else None,
            "candidate_case_ids": [],
            "match_basis": [],
            "confidence": 0.0,
            "status": "pending",
            "reviewed_by": None,
            "reviewed_at": None,
            "decision_reason": None,
            "resolved_case_id": None,
        })
    return rows


def make_history_batches(root: Path, *, max_units: int = 20, max_chars: int = 50_000) -> list[Path]:
    extraction_dir = root / HISTORY_EXTRACTION_DIR
    atoms = [json.loads(line) for line in (extraction_dir / "text-inventory.jsonl").read_text(encoding="utf-8").splitlines() if line]
    sizes: dict[int, int] = {}
    for atom in atoms:
        if atom.get("unit_no") is not None:
            unit = int(atom["unit_no"])
            sizes[unit] = sizes.get(unit, 0) + int(atom["byte_end"]) - int(atom["byte_start"])
    batches: list[Path] = []
    start = 1
    current_units = 0
    current_chars = 0
    for unit in range(1, 350):
        size = sizes.get(unit, 0)
        if current_units and (current_units >= max_units or current_chars + size > max_chars):
            batches.append(_write_batch(extraction_dir, start, unit - 1, atoms))
            start, current_units, current_chars = unit, 0, 0
        current_units += 1
        current_chars += size
    batches.append(_write_batch(extraction_dir, start, 349, atoms))
    source_path = extraction_dir / "source.yml"
    if source_path.exists():
        source = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
        source["batch_count"] = len(batches)
        source["migration_status"] = "batches_ready"
        atomic_write_text(source_path, yaml.safe_dump(source, allow_unicode=True, sort_keys=False))
    return batches


def _write_batch(extraction_dir: Path, start: int, end: int, atoms: list[dict[str, Any]]) -> Path:
    path = extraction_dir / "batches" / f"{start:03d}-{end:03d}.review.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "source_family_id": HISTORY_SOURCE_FAMILY,
        "batch_id": f"{start:03d}-{end:03d}",
        "unit_start": start,
        "unit_end": end,
        "atom_ids": [a["atom_id"] for a in atoms if a.get("unit_no") is not None and start <= int(a["unit_no"]) <= end],
        "reviewed_by": None,
        "reviewed_at": None,
        "claims": [], "cases": [], "conflicts": [], "dispositions": [], "mappings": [],
    }
    if not path.exists():
        atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return path


def history_status(root: Path) -> dict[str, Any]:
    extraction_dir = root / HISTORY_EXTRACTION_DIR
    source = extraction_dir / "source.yml"
    if not source.exists():
        return {"source_family_id": HISTORY_SOURCE_FAMILY, "status": "not_started"}
    record = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    inventory = extraction_dir / "text-inventory.jsonl"
    count = len(inventory.read_text(encoding="utf-8").splitlines()) if inventory.exists() else 0
    batches = len(list((extraction_dir / "batches").glob("*.review.yml"))) if (extraction_dir / "batches").exists() else 0
    return {**record, "inventory_lines": count, "batch_count": batches}
