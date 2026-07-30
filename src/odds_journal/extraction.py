from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from .ledger import append_payloads, atomic_write_text, latest_payloads, read_ledger


ROUND_RE = re.compile(r"^###\s+(?P<role>👤 用户|主讲/作者)（第\s*(?P<round>\d+)\s*轮）\s*$")
IMAGE_RE = re.compile(r"!\[[^]]*]\((?P<path>[^)]+)\)")
SOURCE_FILES = {
    "doubao-2026-07-28-text": "原始学习合集.md",
    "doubao-2026-07-28-illustrated": "原始图文学习合集.md",
}
EXTRACTION_RELATIVE = Path("knowledge/extraction/doubao-2026-07-28")


class TextAtom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    atom_id: str
    source_id: str
    source_path: str
    round_no: int | None = None
    role: Literal["user", "author", "preamble"]
    atom_type: Literal[
        "heading", "paragraph", "list", "table", "code", "image", "separator", "gap"
    ]
    byte_start: int = Field(ge=0)
    byte_end: int = Field(gt=0)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    heading_path: list[str] = Field(default_factory=list)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    companion_atom_ids: list[str] = Field(default_factory=list)
    comparison_status: Literal["identical", "media_only", "text_divergent", "unmatched"]


class MediaLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_path: str
    line: int | None = None
    round_no: int | None = None


class MediaInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    media_id: str
    source_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    mime_type: str | None = None
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    decode_status: Literal["valid", "zero_byte", "corrupt"]
    reference_locations: list[MediaLocation] = Field(default_factory=list)
    html_locations: list[MediaLocation] = Field(default_factory=list)
    mapped_rounds: list[int] = Field(default_factory=list)
    mapping_status: Literal["referenced", "html_recovered", "orphan", "unavailable"]
    duplicate_of: str | None = None
    review_status: Literal["pending", "reviewed", "excluded", "unavailable"]


class CoverageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    source_family: str
    source_hashes_valid: bool
    round_count_by_source: dict[str, int]
    byte_coverage: dict[str, float]
    text_atoms: int
    text_atoms_disposed: int
    text_atom_disposition_rate: float
    media: int
    media_disposed: int
    media_disposition_rate: float
    accepted_targets: int
    accepted_targets_linked: int
    accepted_link_rate: float
    unresolved_targets: int
    stale_events: int
    conflict_count: int
    unresolved_conflicts: int
    blocker_count: int
    auditable_complete: bool


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _jsonl(path: Path, models: list[BaseModel]) -> None:
    text = "".join(
        json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        for item in models
    )
    atomic_write_text(path, text)


def _manifest_files(source_dir: Path) -> dict[str, dict[str, Any]]:
    manifest = yaml.safe_load((source_dir / "MANIFEST.yml").read_text(encoding="utf-8")) or {}
    return {item["archived_name"]: item for item in manifest.get("files", [])}


def verify_source_hashes(source_dir: Path) -> dict[str, dict[str, Any]]:
    expected = _manifest_files(source_dir)
    result: dict[str, dict[str, Any]] = {}
    for name, record in expected.items():
        path = source_dir / name
        if not path.exists():
            raise ValueError(f"原始资料不存在：{path}")
        raw = path.read_bytes()
        actual_hash = _sha256_bytes(raw)
        if actual_hash != str(record["sha256"]).lower() or len(raw) != int(record["size"]):
            raise ValueError(f"原始资料哈希或大小不一致：{name}")
        result[name] = {"size": len(raw), "sha256": actual_hash}
    return result


def _line_starts(raw: bytes) -> list[int]:
    starts = [0]
    for match in re.finditer(b"\n", raw):
        starts.append(match.end())
    if starts[-1] != len(raw):
        starts.append(len(raw))
    return starts


def _round_units(text: str) -> list[tuple[int | None, str, int, int]]:
    lines = text.splitlines(keepends=True)
    markers: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = ROUND_RE.fullmatch(line.rstrip("\r\n"))
        if match:
            role = "user" if match.group("role") == "👤 用户" else "author"
            markers.append((index, int(match.group("round")), role))
    rounds = [item[1] for item in markers]
    if rounds != list(range(1, 208)):
        raise ValueError(f"轮次必须连续为 1..207；当前数量 {len(rounds)}")
    units: list[tuple[int | None, str, int, int]] = []
    units.append((None, "preamble", 0, markers[0][0]))
    for index, (start, round_no, role) in enumerate(markers):
        end = markers[index + 1][0] if index + 1 < len(markers) else len(lines)
        units.append((round_no, role, start, end))
    return units


def _markdown_ranges(text: str) -> list[tuple[int, int, str]]:
    parser = MarkdownIt("commonmark").enable("table")
    tokens = parser.parse(text)
    type_map = {
        "heading_open": "heading",
        "paragraph_open": "paragraph",
        "bullet_list_open": "list",
        "ordered_list_open": "list",
        "table_open": "table",
        "fence": "code",
        "code_block": "code",
        "hr": "separator",
        "html_block": "paragraph",
        "blockquote_open": "paragraph",
    }
    candidates: list[tuple[int, int, str]] = []
    for token in tokens:
        if token.type not in type_map or token.map is None or token.level != 0:
            continue
        candidates.append((token.map[0], token.map[1], type_map[token.type]))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    cursor = 0
    line_count = len(text.splitlines(keepends=True))
    for start, end, atom_type in candidates:
        if start < cursor:
            continue
        if start > cursor:
            selected.append((cursor, start, "gap"))
        selected.append((start, end, atom_type))
        cursor = end
    if cursor < line_count:
        selected.append((cursor, line_count, "gap"))
    if not selected and line_count:
        selected.append((0, line_count, "gap"))
    return selected


def _atom_type(atom_type: str, content: str) -> str:
    stripped = content.strip()
    if atom_type == "paragraph" and stripped and IMAGE_RE.sub("", stripped).strip() == "":
        return "image"
    return atom_type


def _text_atoms(root: Path, source_dir: Path, source_id: str, filename: str) -> list[tuple[TextAtom, str]]:
    path = source_dir / filename
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    lines = text.splitlines(keepends=True)
    starts = _line_starts(raw)
    relative = path.relative_to(root).as_posix()
    output: list[tuple[TextAtom, str]] = []
    atom_index = 0
    heading_path: list[str] = []
    for round_no, role, unit_start, unit_end in _round_units(text):
        unit_text = "".join(lines[unit_start:unit_end])
        for local_start, local_end, parsed_type in _markdown_ranges(unit_text):
            global_start = unit_start + local_start
            global_end = unit_start + local_end
            byte_start = starts[global_start]
            byte_end = starts[global_end] if global_end < len(starts) else len(raw)
            content_bytes = raw[byte_start:byte_end]
            content = content_bytes.decode("utf-8")
            atom_type = _atom_type(parsed_type, content)
            if atom_type == "heading":
                first = content.strip().splitlines()[0] if content.strip() else ""
                match = re.match(r"^(#{1,6})\s+(.*)$", first)
                if match:
                    level = len(match.group(1))
                    heading_path = heading_path[: level - 1]
                    heading_path.append(match.group(2).strip())
            atom_index += 1
            atom = TextAtom(
                atom_id=f"{source_id}-a{atom_index:05d}",
                source_id=source_id,
                source_path=relative,
                round_no=round_no,
                role=role,
                atom_type=atom_type,
                byte_start=byte_start,
                byte_end=byte_end,
                line_start=global_start + 1,
                line_end=max(global_start + 1, global_end),
                heading_path=list(heading_path),
                content_sha256=_sha256_bytes(content_bytes),
                comparison_status="unmatched",
            )
            output.append((atom, content))
    if output:
        if output[0][0].byte_start != 0 or output[-1][0].byte_end != len(raw):
            raise ValueError(f"文本原子未覆盖完整文件：{filename}")
        for previous, current in zip(output, output[1:]):
            if previous[0].byte_end != current[0].byte_start:
                raise ValueError(f"文本原子存在缺口或重叠：{filename}")
    return output


def _comparison_text(content: str) -> str:
    value = IMAGE_RE.sub("", content)
    return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").splitlines()).strip()


def _align_atoms(
    left: list[tuple[TextAtom, str]], right: list[tuple[TextAtom, str]]
) -> tuple[list[TextAtom], list[TextAtom]]:
    right_by_key: dict[tuple[int | None, str, str], list[int]] = defaultdict(list)
    for index, (atom, content) in enumerate(right):
        right_by_key[(atom.round_no, atom.atom_type, _comparison_text(content))].append(index)
    used: set[int] = set()
    aligned_left: list[TextAtom] = []
    aligned_right = [item[0] for item in right]
    for atom, content in left:
        key = (atom.round_no, atom.atom_type, _comparison_text(content))
        candidates = [item for item in right_by_key.get(key, []) if item not in used]
        if candidates and key[2]:
            target = candidates[0]
            used.add(target)
            other = aligned_right[target]
            aligned_left.append(
                atom.model_copy(
                    update={"companion_atom_ids": [other.atom_id], "comparison_status": "identical"}
                )
            )
            aligned_right[target] = other.model_copy(
                update={"companion_atom_ids": [atom.atom_id], "comparison_status": "identical"}
            )
        else:
            status = "media_only" if atom.atom_type == "image" else "text_divergent"
            aligned_left.append(atom.model_copy(update={"comparison_status": status}))
    for index, atom in enumerate(aligned_right):
        if index not in used:
            status = "media_only" if atom.atom_type == "image" else "text_divergent"
            aligned_right[index] = atom.model_copy(update={"comparison_status": status})
    return aligned_left, aligned_right


def _round_for_line(atoms: list[TextAtom], line: int) -> int | None:
    for atom in atoms:
        if atom.line_start <= line <= atom.line_end:
            return atom.round_no
    return None


def _markdown_media_locations(root: Path, atoms: list[TextAtom]) -> dict[str, list[MediaLocation]]:
    result: dict[str, list[MediaLocation]] = defaultdict(list)
    by_source = {atom.source_path for atom in atoms}
    for relative in sorted(by_source):
        path = root / relative
        source_atoms = [atom for atom in atoms if atom.source_path == relative]
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in IMAGE_RE.finditer(line):
                target = match.group("path").split("#", 1)[0].split("?", 1)[0]
                filename = Path(target).name
                result[filename].append(
                    MediaLocation(
                        source_path=relative,
                        line=line_no,
                        round_no=_round_for_line(source_atoms, line_no),
                    )
                )
    return result


def _html_media_locations(root: Path, source_dir: Path) -> dict[str, list[MediaLocation]]:
    html_path = source_dir / "原始学习合集_单文件.html"
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    result: dict[str, list[MediaLocation]] = defaultdict(list)
    for image in soup.find_all("img"):
        source = image.get("src") or ""
        if not source.startswith("data:") or "," not in source:
            continue
        try:
            payload = base64.b64decode(source.split(",", 1)[1])
        except Exception:
            continue
        digest = _sha256_bytes(payload)
        turn = image.find_parent("div", class_="turn")
        round_no = None
        if turn:
            role = turn.find("div", class_="role")
            match = re.search(r"第\s*(\d+)\s*轮", role.get_text(" ", strip=True) if role else "")
            if match:
                round_no = int(match.group(1))
        result[digest].append(
            MediaLocation(
                source_path=html_path.relative_to(root).as_posix(),
                round_no=round_no,
            )
        )
    return result


def _media_inventory(root: Path, source_dir: Path, atoms: list[TextAtom]) -> list[MediaInventory]:
    references = _markdown_media_locations(root, atoms)
    html_locations = _html_media_locations(root, source_dir)
    output: list[MediaInventory] = []
    first_by_hash: dict[str, str] = {}
    for index, path in enumerate(sorted((source_dir / "images").iterdir()), start=1):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        digest = _sha256_bytes(raw)
        mime_type = None
        width = None
        height = None
        if not raw:
            decode_status = "zero_byte"
        else:
            try:
                with Image.open(BytesIO(raw)) as image:
                    image.verify()
                with Image.open(BytesIO(raw)) as image:
                    width, height = image.size
                    mime_type = Image.MIME.get(image.format)
                decode_status = "valid"
            except (UnidentifiedImageError, OSError, ValueError):
                decode_status = "corrupt"
        reference_locations = references.get(path.name, [])
        embedded_locations = html_locations.get(digest, [])
        rounds = sorted(
            {
                item.round_no
                for item in [*reference_locations, *embedded_locations]
                if item.round_no is not None
            }
        )
        duplicate_of = first_by_hash.get(digest) if raw else None
        if raw and digest not in first_by_hash:
            first_by_hash[digest] = f"media-{index:03d}"
        if decode_status != "valid":
            mapping_status = "unavailable"
            review_status = "unavailable"
        elif reference_locations:
            mapping_status = "referenced"
            review_status = "pending"
        elif embedded_locations:
            mapping_status = "html_recovered"
            review_status = "pending"
        else:
            mapping_status = "orphan"
            review_status = "pending"
        output.append(
            MediaInventory(
                media_id=f"media-{index:03d}",
                source_path=path.relative_to(root).as_posix(),
                sha256=digest,
                size=len(raw),
                mime_type=mime_type,
                width=width,
                height=height,
                decode_status=decode_status,
                reference_locations=reference_locations,
                html_locations=embedded_locations,
                mapped_rounds=rounds,
                mapping_status=mapping_status,
                duplicate_of=duplicate_of,
                review_status=review_status,
            )
        )
    return output


def build_source_inventory(root: Path, source_dir: Path) -> tuple[list[TextAtom], list[MediaInventory]]:
    source_dir = source_dir.resolve()
    hashes = verify_source_hashes(source_dir)
    extracted: dict[str, list[tuple[TextAtom, str]]] = {}
    for source_id, filename in SOURCE_FILES.items():
        extracted[source_id] = _text_atoms(root, source_dir, source_id, filename)
    left, right = _align_atoms(
        extracted["doubao-2026-07-28-text"],
        extracted["doubao-2026-07-28-illustrated"],
    )
    atoms = [*left, *right]
    media = _media_inventory(root, source_dir, atoms)
    extraction_dir = root / EXTRACTION_RELATIVE
    extraction_dir.mkdir(parents=True, exist_ok=True)
    source_record = {
        "schema_version": 1,
        "source_family": "doubao-2026-07-28",
        "content_immutable": True,
        "rounds": 207,
        "files": hashes,
        "text_atom_count": len(atoms),
        "media_count": len(media),
    }
    atomic_write_text(
        extraction_dir / "source.yml",
        yaml.safe_dump(source_record, allow_unicode=True, sort_keys=False),
    )
    _jsonl(extraction_dir / "text-inventory.jsonl", atoms)
    _jsonl(extraction_dir / "media-inventory.jsonl", media)
    for ledger_name in (
        "claim-events.jsonl",
        "disposition-events.jsonl",
        "conflict-events.jsonl",
        "case-events.jsonl",
    ):
        path = extraction_dir / ledger_name
        if not path.exists():
            atomic_write_text(path, "")
    evidence = root / "knowledge/evidence/rule-evidence.jsonl"
    if not evidence.exists():
        atomic_write_text(evidence, "")
    return atoms, media


def load_text_inventory(root: Path) -> list[TextAtom]:
    path = root / EXTRACTION_RELATIVE / "text-inventory.jsonl"
    return [TextAtom.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_media_inventory(root: Path) -> list[MediaInventory]:
    path = root / EXTRACTION_RELATIVE / "media-inventory.jsonl"
    return [MediaInventory.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def make_review_batches(root: Path, *, max_rounds: int = 20, max_chars: int = 50_000) -> list[Path]:
    atoms = load_text_inventory(root)
    media = load_media_inventory(root)
    primary = [atom for atom in atoms if atom.source_id == "doubao-2026-07-28-text" and atom.round_no]
    counts: dict[int, int] = defaultdict(int)
    for atom in primary:
        counts[int(atom.round_no)] += atom.byte_end - atom.byte_start
    batches: list[tuple[int, int]] = []
    start = 1
    current_chars = 0
    current_count = 0
    for round_no in range(1, 208):
        size = counts[round_no]
        if current_count and (current_count >= max_rounds or current_chars + size > max_chars):
            batches.append((start, round_no - 1))
            start = round_no
            current_chars = 0
            current_count = 0
        current_chars += size
        current_count += 1
    batches.append((start, 207))
    directory = root / EXTRACTION_RELATIVE / "batches"
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for start, end in batches:
        path = directory / f"{start:03d}-{end:03d}.review.yml"
        atom_ids = [atom.atom_id for atom in atoms if atom.round_no and start <= atom.round_no <= end]
        media_ids = [
            item.media_id
            for item in media
            if item.mapped_rounds and start <= min(item.mapped_rounds) <= end
        ]
        payload = {
            "schema_version": 1,
            "batch_id": f"{start:03d}-{end:03d}",
            "round_start": start,
            "round_end": end,
            "atom_ids": atom_ids,
            "media_ids": media_ids,
            "reviewed_by": None,
            "reviewed_at": None,
            "claims": [],
            "conflicts": [],
            "cases": [],
            "dispositions": [],
        }
        if not path.exists():
            atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
        paths.append(path)
    unmapped = [item.media_id for item in media if not item.mapped_rounds]
    preamble_atoms = [item.atom_id for item in atoms if item.round_no is None]
    if unmapped or preamble_atoms:
        path = directory / "media-unmapped.review.yml"
        payload = {
            "schema_version": 1,
            "batch_id": "media-unmapped",
            "round_start": None,
            "round_end": None,
            "atom_ids": preamble_atoms,
            "media_ids": unmapped,
            "reviewed_by": None,
            "reviewed_at": None,
            "claims": [],
            "conflicts": [],
            "cases": [],
            "dispositions": [],
        }
        if not path.exists():
            atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
        paths.append(path)
    return paths


def amend_preamble_review_batch(root: Path) -> Path:
    atoms = [item for item in load_text_inventory(root) if item.round_no is None]
    path = root / EXTRACTION_RELATIVE / "batches/media-unmapped.review.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    existing = {item.get("target_id") for item in raw.get("dispositions") or []}
    raw["atom_ids"] = [item.atom_id for item in atoms]
    dispositions = list(raw.get("dispositions") or [])
    for atom in atoms:
        if atom.atom_id in existing:
            continue
        if atom.source_id == "doubao-2026-07-28-illustrated" and atom.comparison_status == "identical":
            dispositions.append(
                {
                    "target_type": "text_atom",
                    "target_id": atom.atom_id,
                    "disposition": "duplicate",
                    "content_kinds": ["source_preamble"],
                    "claim_ids": [],
                    "case_ids": [],
                    "duplicate_of": atom.companion_atom_ids[0],
                    "severity": "info",
                    "reason": "图文版前言与纯文本版对应原子一致，不重复提炼。",
                }
            )
        else:
            dispositions.append(
                {
                    "target_type": "text_atom",
                    "target_id": atom.atom_id,
                    "disposition": "excluded",
                    "content_kinds": ["source_preamble"],
                    "claim_ids": [],
                    "case_ids": [],
                    "duplicate_of": None,
                    "severity": "info",
                    "reason": "来源说明、归档元数据、风险提示或结构空白；来源事实已在 source.yml 和 MANIFEST.yml 记录。",
                }
            )
    raw["dispositions"] = dispositions
    atomic_write_text(path, yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=1000))
    return path


LEGACY_CASE_SPECS = {
    "legacy-gimcheon-daejeon": {
        "title": "金泉尚武 vs 大田市民",
        "rounds": {20, 21, 22, 23, 24, 25, 26, 27, 64},
        "review_rounds": {27, 64},
        "result": "金泉尚武 3-2 大田市民",
    },
    "legacy-pohang-jeonbuk": {
        "title": "浦项制铁 vs 全北汽车",
        "rounds": {20, 28, 29, 30, 64},
        "review_rounds": {29, 64},
        "result": "浦项制铁 0-2 全北汽车",
    },
    "legacy-seoul-ulsan": {
        "title": "FC首尔 vs 蔚山HD",
        "rounds": {5, 6, 7, 20, 31, 49, 51, 53, 55, 57, 59, 61, 64},
        "review_rounds": {61, 64},
        "result": "FC首尔 1-3 蔚山HD",
    },
    "legacy-incheon-bucheon": {
        "title": "仁川联 vs 富川FC",
        "rounds": {20, 33, 35, 37, 39, 41, 49, 53, 55, 57, 64},
        "review_rounds": {41, 64},
        "result": "仁川联 1-1 富川FC",
    },
    "legacy-gwangju-jeju": {
        "title": "FC光州 vs 济州SK",
        "rounds": {20, 43, 45, 49, 53, 55, 64},
        "review_rounds": {64},
        "result": "FC光州 1-2 济州SK",
    },
    "legacy-anyang-gangwon": {
        "title": "FC安养 vs 江原FC",
        "rounds": {20, 47, 49, 53, 55, 64},
        "review_rounds": {64},
        "result": "FC安养 2-1 江原FC",
    },
    "legacy-hjk-tps": {
        "title": "赫尔辛基 vs TPS土尔库",
        "rounds": {66, 72, 99, 101, 103, 105, 113, 117, 119, 156, 159, 162},
        "review_rounds": {105, 156, 159, 162},
        "result": "赫尔辛基 1-0 TPS土尔库",
    },
    "legacy-malmo-elfsborg": {
        "title": "马尔默 vs 埃尔夫斯堡",
        "rounds": {68, 74},
        "review_rounds": set(),
        "result": None,
    },
    "legacy-gais-halmstad": {
        "title": "哥德堡盖斯 vs 哈姆斯塔德",
        "rounds": {70, 76, 78, 80, 82},
        "review_rounds": set(),
        "result": None,
    },
    "legacy-gremio-fluminense": {
        "title": "格雷米奥 vs 弗鲁米嫩塞",
        "rounds": {86, 88, 92, 96},
        "review_rounds": set(),
        "result": None,
    },
    "legacy-flamengo-sao-paulo": {
        "title": "弗拉门戈 vs 圣保罗",
        "rounds": {90, 92, 94},
        "review_rounds": set(),
        "result": None,
    },
    "legacy-hacken-aik": {
        "title": "赫根 vs AIK索尔纳",
        "rounds": {107, 111, 113, 121, 125, 127, 129, 134, 136, 138, 140, 142, 144, 149, 151, 153, 165, 170, 172, 174, 176, 178, 180, 182, 184, 186, 188, 190, 194, 200, 203, 205, 207},
        "review_rounds": {203, 205, 207},
        "result": "赫根 0-0 AIK索尔纳",
    },
    "legacy-rosenborg-fredrikstad": {
        "title": "罗森博格 vs 腓特烈斯塔",
        "rounds": {109, 111, 113, 123, 125, 127, 129, 147, 149, 151, 153, 165, 168, 170, 174, 176, 178, 182, 184, 192, 194, 196, 198, 203, 205, 207},
        "review_rounds": {203, 205, 207},
        "result": "罗森博格 4-0 腓特烈斯塔",
    },
}


def _atom_content(root: Path, atom: TextAtom) -> str:
    return (root / atom.source_path).read_bytes()[atom.byte_start : atom.byte_end].decode("utf-8")


def _semantic_atom(atom: TextAtom, content: str) -> bool:
    stripped = content.strip()
    if atom.role != "author" or atom.atom_type not in {"heading", "paragraph", "list", "table", "code"}:
        return False
    if not stripped or ROUND_RE.fullmatch(stripped):
        return False
    return len(re.sub(r"[#>*`|\-\s]", "", stripped)) >= 4


def _claim_metadata(content: str, heading_path: list[str]) -> tuple[str, str, str, str | None]:
    joined = " ".join([*heading_path, content])
    if any(term in joined for term in ("纠正", "勘误", "错误", "误区", "漏洞")):
        claim_type = "correction"
    elif any(term in joined for term in ("赛后", "赛果", "复盘", "反例", "踩坑")):
        claim_type = "counterexample"
    elif any(term in joined for term in ("诱盘", "阻盘", "热度", "筹码", "阈值", "水位")):
        claim_type = "heuristic"
    elif any(term in joined for term in ("流程", "步骤", "顺序", "框架", "清单", "观察")):
        claim_type = "method"
    else:
        claim_type = "concept"
    if any(term in joined for term in ("可能", "倾向", "如果", "若", "前提", "场景", "条件")):
        certainty = "conditional"
    elif any(term in joined for term in ("推演", "预测", "概率", "大概率", "优先")):
        certainty = "speculative"
    else:
        certainty = "factual" if claim_type in {"concept", "correction"} else "conditional"
    if any(term in joined for term in ("赛后", "赛果", "复盘", "终局")):
        phase = "postmatch"
    elif any(term in joined for term in ("临场", "临盘", "实时", "开赛仅剩")):
        phase = "live"
    else:
        phase = "prematch"
    candidate = None
    mappings = (
        (("结算", "走水", "赢一半", "输一半"), "market-settlement-rules"),
        (("数据来源", "截止时间", "采集时间"), "data-provenance-time-boundary"),
        (("基本面", "球队档位", "定位"), "prematch-stage-positioning"),
        (("理论盘口", "实际盘口", "浅盘", "深盘"), "theoretical-vs-actual-market"),
        (("时序", "初盘", "中盘", "临场"), "market-timeline-cross-validation"),
        (("两种", "双向", "反证", "失效"), "dual-hypothesis-evidence"),
        (("置信度", "放弃", "观望", "回避"), "layered-decision-confidence-pass"),
        (("总进球", "大小球", "比分"), "goals-score-separation"),
        (("欧亚", "机构分歧", "盘口不统一"), "operator-market-divergence"),
        (("交叉盘", "关联盘", "同型盘"), "cross-related-same-pattern"),
        (("诱盘", "阻盘", "升盘", "降盘"), "handicap-inducement-resistance"),
        (("热度", "筹码", "人气"), "market-heat-chip-distribution"),
        (("水位", "阈值", "0.95"), "water-threshold-operator-style"),
    )
    for terms, identity in mappings:
        if any(term in joined for term in terms):
            candidate = identity
            break
    return claim_type, certainty, phase, candidate


def _round_case_ids(round_no: int | None) -> list[str]:
    if round_no is None:
        return []
    return [
        case_id for case_id, spec in LEGACY_CASE_SPECS.items() if round_no in spec["rounds"]
    ]


def _case_payloads(
    root: Path,
    atoms: list[TextAtom],
    media: list[MediaInventory],
    claims_by_atom: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    primary = [
        atom
        for atom in atoms
        if atom.source_id == "doubao-2026-07-28-text"
        and atom.atom_id in claims_by_atom
    ]
    output: list[dict[str, Any]] = []
    for case_id, spec in LEGACY_CASE_SPECS.items():
        selected = [atom for atom in primary if atom.round_no in spec["rounds"]]
        selected_media = [
            item.media_id
            for item in media
            if set(item.mapped_rounds) & set(spec["rounds"])
        ]
        prematch_parts: list[str] = []
        review_parts: list[str] = []
        timeline_parts: list[str] = []
        lessons: list[str] = []
        for atom in selected:
            text = _atom_content(root, atom).strip()
            if not text:
                continue
            excerpt = text
            if atom.round_no in spec["review_rounds"]:
                review_parts.append(excerpt)
            else:
                prematch_parts.append(excerpt)
            if any(term in text for term in ("初盘", "中盘", "临场", "水位", "盘口", "欧赔")):
                timeline_parts.append(excerpt)
            claim = claims_by_atom[atom.atom_id]
            if claim["claim_type"] in {"correction", "counterexample"}:
                lessons.append(claim["normalized_claim"])

        def joined(parts: list[str], fallback: str, maximum: int | None = None) -> str:
            value = "\n\n".join(parts).strip() or fallback
            return value if maximum is None else value[:maximum]

        result = spec["result"] or "原始资料中未确认最终赛果。"
        output.append(
            {
                "schema_version": 1,
                "case_id": case_id,
                "case_revision": 1,
                "title": spec["title"],
                "competition_code": None,
                "home_team_id": None,
                "away_team_id": None,
                "kickoff_at": None,
                "fixture_fingerprint": hashlib.sha256(
                    f"{case_id}|doubao-2026-07-28".encode("utf-8")
                ).hexdigest(),
                "source_effective_at": "2026-07-28T00:00:00+08:00",
                "chronology": "mixed" if spec["result"] else "unknown",
                "completeness": "partial",
                "statistics_eligible": False,
                "source_atom_ids": [item.atom_id for item in selected],
                "media_ids": sorted(set(selected_media)),
                "scenario_instance_ids": [],
                "result_known": bool(spec["result"]),
                "status": "draft",
                "sections": {
                    "facts": f"原始资料明确讨论：{spec['title']}。日期和完整外部来源未独立核验。",
                    "market-timeline": joined(timeline_parts, "原始资料未保留可确认的完整盘口时间线。"),
                    "source-prematch": joined(prematch_parts, "未找到可确认的独立赛前判断。"),
                    "source-live": "原始对话未提供可独立证明时间边界的临场记录；相关内容保留在赛前判断和限制章节。",
                    "result": result,
                    "source-review": joined(review_parts, "原始资料未提供明确赛后复盘。"),
                    "lessons": joined(lessons, "案例仅供检索学习，不从单场结果提升规则可信度。", 8_000),
                    "limitations": "原始资料统一于 2026-07-28 纳入；多数对话缺少可证明的赛前采集链，chronology 因此标记为 mixed/unknown，statistics_eligible 固定为 false。盘口资金与机构意图均只能视为解释假设。",
                },
            }
        )
    return output


def _conflict_payloads(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def ids(*terms: str, rounds: set[int] | None = None) -> list[str]:
        output = []
        for item in claims:
            quote = item["source_quote"]
            atom_id = item["source_atom_ids"][0]
            atom_round = int(item.get("round_no") or 0)
            if (not rounds or atom_round in rounds) and any(term in quote for term in terms):
                output.append(item["claim_id"])
        return output[:20]

    return [
        {
            "conflict_id": "settlement-rules-early-errors",
            "conflict_type": "settlement_error",
            "claim_ids": ids("平手（0）", "平手/半球", rounds={2, 8, 18, 23, 35}),
            "resolution_status": "resolved",
            "adopted_conclusion": "平手盘平局走盘；平半盘平局时让球方输一半，不能按全输处理。",
            "preserved_conditions": ["具体结算仍以所记录市场与方向为准"],
            "rationale": "早期表格存在结算错误，后续讲解已出现正确版本；正式规则采用标准结算。",
            "severity": "blocker",
        },
        {
            "conflict_id": "fixed-water-threshold",
            "conflict_type": "later_correction",
            "claim_ids": ids("0.95", "低水", "高水", rounds={2, 8, 9, 18, 174}),
            "resolution_status": "resolved",
            "adopted_conclusion": "水位高低只能在机构、市场、时点和历史区间内相对比较，不设唯一通用阈值。",
            "preserved_conditions": ["原始数值作为案例原文保留"],
            "rationale": "后文明确指出 0.95 等固定阈值忽略盘路前置历史。",
            "severity": "blocker",
        },
        {
            "conflict_id": "public-market-vs-internal-flow",
            "conflict_type": "terminology_difference",
            "claim_ids": ids("资金持续", "资金涌入", "筹码"),
            "resolution_status": "resolved",
            "adopted_conclusion": "公开盘赔只能支持资金倾向或风险调整假设，不能证明真实内部资金流。",
            "preserved_conditions": ["保留原文机构意图解释作为 speculative 假设"],
            "rationale": "历史资料没有机构内部成交或风险敞口数据。",
            "severity": "blocker",
        },
        {
            "conflict_id": "postmatch-explanation-boundary",
            "conflict_type": "chronology_uncertain",
            "claim_ids": ids("复盘", "最终赛果", "赛后"),
            "resolution_status": "resolved",
            "adopted_conclusion": "无法证明赛前存在的解释只进入 mixed/postmatch 案例，不进入准确率或规则晋级分母。",
            "preserved_conditions": ["可用于生成反例和检索候选"],
            "rationale": "原始长对话的统一归档时间不能证明每段判断的真实先后边界。",
            "severity": "blocker",
        },
        {
            "conflict_id": "absolute-pattern-claims",
            "conflict_type": "scope_difference",
            "claim_ids": ids("大概率", "必然", "铁律", "黄金区分"),
            "resolution_status": "resolved",
            "adopted_conclusion": "盘型只能作为带适用条件和反例的 experimental 假设，不得表达为必然规律。",
            "preserved_conditions": ["原文强表述保留用于追踪后续纠偏"],
            "rationale": "后续赫尔辛基、罗森博格等实战已给出反例。",
            "severity": "blocker",
        },
        {
            "conflict_id": "two-source-divergence",
            "conflict_type": "source_divergence",
            "claim_ids": [],
            "resolution_status": "resolved",
            "adopted_conclusion": "两份 Markdown 分别库存和逐原子比对；正文差异独立声明，图片差异由媒体库存处理。",
            "preserved_conditions": ["不假设图文版等于纯文本版加图片"],
            "rationale": "原子对齐结果包含 text_divergent 和 media_only，不能静默合并。",
            "severity": "blocker",
        },
    ]


def draft_review_batches(
    root: Path, *, reviewed_by: str, reviewed_at: datetime
) -> list[Path]:
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("reviewed_at 必须包含时区")
    extraction_dir = root / EXTRACTION_RELATIVE
    if any(read_ledger(extraction_dir / name) for name in (
        "claim-events.jsonl",
        "disposition-events.jsonl",
        "conflict-events.jsonl",
        "case-events.jsonl",
    )):
        raise ValueError("提取台账已有事件，不能重新生成初始批次")
    paths = make_review_batches(root)
    atoms = load_text_inventory(root)
    media = load_media_inventory(root)
    atom_by_id = {item.atom_id: item for item in atoms}
    media_by_id = {item.media_id: item for item in media}
    claims_by_atom: dict[str, dict[str, Any]] = {}
    for atom in atoms:
        content = _atom_content(root, atom)
        if atom.source_id == "doubao-2026-07-28-illustrated" and atom.comparison_status == "identical":
            continue
        if not _semantic_atom(atom, content):
            continue
        claim_type, certainty, phase, candidate = _claim_metadata(content, atom.heading_path)
        normalized = re.sub(r"\s+", " ", re.sub(r"^[#>*`\-\s]+", "", content.strip()))
        claim = {
            "claim_id": f"claim-{atom.atom_id}",
            "source_atom_ids": [atom.atom_id],
            "source_quote": content.strip()[:1200],
            "normalized_claim": normalized[:600],
            "claim_type": claim_type,
            "scope_conditions": ["必须结合该原子所在轮次、标题路径和原始上下文解释"],
            "failure_conditions": ["缺少数据时间边界或出现后续纠错时不得直接采用"],
            "certainty": certainty,
            "knowledge_phase": phase,
            "candidate_rule_id": candidate,
            "conflict_group_id": None,
            "round_no": atom.round_no,
        }
        claims_by_atom[atom.atom_id] = claim

    round_claims: dict[int, list[str]] = defaultdict(list)
    for atom_id, claim in claims_by_atom.items():
        round_no = atom_by_id[atom_id].round_no
        if round_no:
            round_claims[round_no].append(claim["claim_id"])
    case_payloads = _case_payloads(root, atoms, media, claims_by_atom)
    conflict_payloads = _conflict_payloads(list(claims_by_atom.values()))
    final_path = max(
        (path for path in paths if path.name != "media-unmapped.review.yml"),
        key=lambda item: int(item.stem.split("-")[-1].split(".")[0]),
    )

    for path in paths:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        batch_atoms = [atom_by_id[item] for item in raw.get("atom_ids") or []]
        batch_media = [media_by_id[item] for item in raw.get("media_ids") or []]
        raw["reviewed_by"] = reviewed_by
        raw["reviewed_at"] = reviewed_at.isoformat()
        raw["claims"] = [claims_by_atom[item.atom_id] for item in batch_atoms if item.atom_id in claims_by_atom]
        raw["conflicts"] = conflict_payloads if path == final_path else []
        raw["cases"] = case_payloads if path == final_path else []
        dispositions: list[dict[str, Any]] = []
        for atom in batch_atoms:
            content = _atom_content(root, atom).strip()
            case_ids = _round_case_ids(atom.round_no)
            claim = claims_by_atom.get(atom.atom_id)
            if atom.source_id == "doubao-2026-07-28-illustrated" and atom.comparison_status == "identical":
                dispositions.append({
                    "target_type": "text_atom",
                    "target_id": atom.atom_id,
                    "disposition": "duplicate",
                    "content_kinds": ["duplicate_text"],
                    "claim_ids": [],
                    "case_ids": case_ids,
                    "duplicate_of": atom.companion_atom_ids[0],
                    "severity": "info",
                    "reason": "与纯文本版对应原子内容一致，保留伴随关系但不重复提炼。",
                })
            elif claim:
                dispositions.append({
                    "target_type": "text_atom",
                    "target_id": atom.atom_id,
                    "disposition": "accepted",
                    "content_kinds": [claim["claim_type"]],
                    "claim_ids": [claim["claim_id"]],
                    "case_ids": case_ids,
                    "duplicate_of": None,
                    "severity": "info",
                    "reason": "作者正文包含可追溯观点；已按原子声明保存并标记确定性与阶段。",
                })
            elif atom.atom_type == "image":
                dispositions.append({
                    "target_type": "text_atom",
                    "target_id": atom.atom_id,
                    "disposition": "excluded",
                    "content_kinds": ["media_reference"],
                    "claim_ids": [],
                    "case_ids": case_ids,
                    "duplicate_of": None,
                    "severity": "info",
                    "reason": "Markdown 图片指针不作为独立观点；实际文件由媒体库存逐项处置。",
                })
            elif atom.role == "user" and case_ids and content:
                dispositions.append({
                    "target_type": "text_atom",
                    "target_id": atom.atom_id,
                    "disposition": "accepted",
                    "content_kinds": ["case_context"],
                    "claim_ids": [],
                    "case_ids": case_ids,
                    "duplicate_of": None,
                    "severity": "info",
                    "reason": "用户输入用于恢复案例上下文，不作为事实或规则声明。",
                })
            else:
                dispositions.append({
                    "target_type": "text_atom",
                    "target_id": atom.atom_id,
                    "disposition": "excluded",
                    "content_kinds": ["structure" if atom.atom_type in {"gap", "separator", "heading"} else "prompt"],
                    "claim_ids": [],
                    "case_ids": case_ids,
                    "duplicate_of": None,
                    "severity": "info",
                    "reason": "结构、空白、轮次标签或无独立知识主张的用户请求；字节仍由库存完整覆盖。",
                })
        for item in batch_media:
            linked_cases = sorted({case_id for round_no in item.mapped_rounds for case_id in _round_case_ids(round_no)})
            linked_claims = sorted({claim_id for round_no in item.mapped_rounds for claim_id in [*round_claims.get(round_no, []), *round_claims.get(round_no + 1, [])]})[:20]
            if item.decode_status != "valid":
                disposition = "excluded"
                reason = "文件为零字节或无法解码的 HTTP 403/错误响应，只登记媒体缺口，不生成 OCR 或正式观察。"
            elif item.duplicate_of:
                disposition = "duplicate"
                reason = "媒体内容哈希与先前文件一致，保留路径和引用位置但不重复提炼。"
            elif linked_cases or linked_claims:
                disposition = "accepted"
                reason = "有效原始截图已关联所在轮次的案例或声明；未生成未经视觉核对的结构化盘口数值。"
            else:
                disposition = "excluded"
                reason = "有效媒体已核对可解码，但缺少可靠语义归属，保留为来源文件而不生成正式观察。"
            media_disposition = {
                "target_type": "media",
                "target_id": item.media_id,
                "disposition": disposition,
                "content_kinds": ["source_media" if item.decode_status == "valid" else "unavailable_media"],
                "claim_ids": linked_claims if disposition == "accepted" else [],
                "case_ids": linked_cases if disposition == "accepted" else [],
                "duplicate_of": item.duplicate_of,
                "severity": "warning" if item.decode_status != "valid" else "info",
                "reason": reason,
            }
            dispositions.append(media_disposition)
        raw["dispositions"] = dispositions
        atomic_write_text(path, yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=1000))
    return paths


def accept_review_batch(root: Path, batch_path: Path) -> dict[str, int]:
    raw = yaml.safe_load(batch_path.read_text(encoding="utf-8")) or {}
    if raw.get("schema_version") != 1:
        raise ValueError("审查批次只支持 schema_version=1")
    actor = raw.get("reviewed_by")
    reviewed_at = raw.get("reviewed_at")
    if not actor or not reviewed_at:
        raise ValueError("审查批次必须填写 reviewed_by 和 reviewed_at")
    recorded_at = datetime.fromisoformat(str(reviewed_at))
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("reviewed_at 必须包含时区")
    batch_id = str(raw.get("batch_id") or "")
    if not re.fullmatch(r"[a-z0-9-]+", batch_id):
        raise ValueError("batch_id 格式无效")
    atom_ids = set(raw.get("atom_ids") or [])
    media_ids = set(raw.get("media_ids") or [])
    expected_targets = {f"text_atom:{item}" for item in atom_ids} | {
        f"media:{item}" for item in media_ids
    }
    dispositions = list(raw.get("dispositions") or [])
    actual_targets = {
        f"{item.get('target_type')}:{item.get('target_id')}" for item in dispositions
    }
    if actual_targets != expected_targets:
        missing = sorted(expected_targets - actual_targets)
        extra = sorted(actual_targets - expected_targets)
        raise ValueError(f"处置目标与批次不一致；缺少 {missing[:5]}；多出 {extra[:5]}")
    valid_dispositions = {"accepted", "duplicate", "excluded", "unresolved"}
    for item in dispositions:
        if item.get("disposition") not in valid_dispositions:
            raise ValueError(f"处置类型无效：{item.get('disposition')}")
        if not item.get("reason"):
            raise ValueError(f"处置缺少原因：{item.get('target_id')}")
        if item.get("disposition") == "accepted" and not (
            item.get("claim_ids") or item.get("case_ids") or item.get("verified_observations")
        ):
            raise ValueError(f"accepted 目标没有声明、案例或核验观察：{item.get('target_id')}")
    claims = list(raw.get("claims") or [])
    claim_ids = {str(item.get("claim_id")) for item in claims}
    if len(claim_ids) != len(claims) or "None" in claim_ids:
        raise ValueError("claim_id 缺失或重复")
    for claim in claims:
        references = set(claim.get("source_atom_ids") or [])
        if not references or not references.issubset(atom_ids):
            raise ValueError(f"声明引用了批次外原子：{claim.get('claim_id')}")
    conflicts = list(raw.get("conflicts") or [])
    cases = list(raw.get("cases") or [])
    extraction_dir = root / EXTRACTION_RELATIVE
    originals: dict[Path, bytes | None] = {}
    created_counts: dict[str, int] = {}
    ledgers = [
        ("claim", extraction_dir / "claim-events.jsonl", claims, "claim_id"),
        ("conflict", extraction_dir / "conflict-events.jsonl", conflicts, "conflict_id"),
        ("case", extraction_dir / "case-events.jsonl", cases, "case_id"),
        ("disposition", extraction_dir / "disposition-events.jsonl", dispositions, "target_id"),
    ]
    try:
        for label, path, payloads, identity in ledgers:
            originals[path] = path.read_bytes() if path.exists() else None
            created = append_payloads(
                path,
                [dict(item) for item in payloads],
                recorded_at=recorded_at,
                actor=str(actor),
                event_id_factory=lambda item, index, label=label, identity=identity: (
                    f"{label}:{batch_id}:{str(item.get(identity) or index).lower()}"
                ),
            )
            created_counts[label] = len(created)
    except Exception:
        for path, content in originals.items():
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                temporary = path.with_suffix(path.suffix + ".rollback")
                temporary.write_bytes(content)
                temporary.replace(path)
        raise
    return created_counts


def _source_byte_coverage(root: Path, atoms: list[TextAtom]) -> dict[str, float]:
    result: dict[str, float] = {}
    grouped: dict[str, list[TextAtom]] = defaultdict(list)
    for atom in atoms:
        grouped[atom.source_path].append(atom)
    for relative, items in grouped.items():
        items.sort(key=lambda item: item.byte_start)
        size = (root / relative).stat().st_size
        cursor = 0
        covered = 0
        for item in items:
            if item.byte_start != cursor:
                break
            covered += item.byte_end - item.byte_start
            cursor = item.byte_end
        result[relative] = round(covered / size, 6) if size else 1.0
    return result


def source_coverage(root: Path) -> CoverageResult:
    extraction_dir = root / EXTRACTION_RELATIVE
    atoms = load_text_inventory(root)
    media = load_media_inventory(root)
    source_dir = root / "knowledge/sources/doubao-2026-07-28"
    source_hashes_valid = True
    try:
        verify_source_hashes(source_dir)
    except Exception:
        source_hashes_valid = False
    disposition_events = read_ledger(extraction_dir / "disposition-events.jsonl")
    latest = latest_payloads(
        disposition_events, lambda item: f"{item.get('target_type')}:{item.get('target_id')}"
    )
    text_keys = {f"text_atom:{item.atom_id}" for item in atoms}
    media_keys = {f"media:{item.media_id}" for item in media}
    disposed_text = text_keys & set(latest)
    disposed_media = media_keys & set(latest)
    accepted = [item for key, item in latest.items() if key in text_keys | media_keys and item.get("disposition") == "accepted"]
    linked = [item for item in accepted if item.get("claim_ids") or item.get("case_ids") or item.get("verified_observations")]
    unresolved = [item for key, item in latest.items() if key in text_keys | media_keys and item.get("disposition") == "unresolved"]
    conflicts = read_ledger(extraction_dir / "conflict-events.jsonl")
    latest_conflicts = latest_payloads(conflicts, lambda item: str(item.get("conflict_id")))
    unresolved_conflicts = [item for item in latest_conflicts.values() if item.get("resolution_status") != "resolved"]
    blockers = [
        item
        for item in [*latest.values(), *latest_conflicts.values()]
        if item.get("severity") == "blocker" and item.get("resolution_status") != "resolved"
    ]
    byte_coverage = _source_byte_coverage(root, atoms)
    rounds: dict[str, int] = {}
    for source_id in SOURCE_FILES:
        rounds[source_id] = len({item.round_no for item in atoms if item.source_id == source_id and item.round_no})
    result = CoverageResult(
        source_family="doubao-2026-07-28",
        source_hashes_valid=source_hashes_valid,
        round_count_by_source=rounds,
        byte_coverage=byte_coverage,
        text_atoms=len(atoms),
        text_atoms_disposed=len(disposed_text),
        text_atom_disposition_rate=round(len(disposed_text) / len(atoms), 6) if atoms else 1.0,
        media=len(media),
        media_disposed=len(disposed_media),
        media_disposition_rate=round(len(disposed_media) / len(media), 6) if media else 1.0,
        accepted_targets=len(accepted),
        accepted_targets_linked=len(linked),
        accepted_link_rate=round(len(linked) / len(accepted), 6) if accepted else 1.0,
        unresolved_targets=len(unresolved),
        stale_events=0,
        conflict_count=len(latest_conflicts),
        unresolved_conflicts=len(unresolved_conflicts),
        blocker_count=len(blockers),
        auditable_complete=False,
    )
    complete = (
        result.source_hashes_valid
        and all(value == 1.0 for value in result.byte_coverage.values())
        and all(value == 207 for value in result.round_count_by_source.values())
        and result.text_atom_disposition_rate == 1.0
        and result.media_disposition_rate == 1.0
        and result.accepted_link_rate == 1.0
        and result.unresolved_targets == 0
        and result.unresolved_conflicts == 0
        and result.blocker_count == 0
    )
    return result.model_copy(update={"auditable_complete": complete})


def validate_extraction_state(root: Path) -> list[str]:
    errors: list[str] = []
    extraction_dir = root / EXTRACTION_RELATIVE
    try:
        atoms = load_text_inventory(root)
        media = load_media_inventory(root)
        atom_ids = {item.atom_id for item in atoms}
        media_ids = {item.media_id for item in media}
        claims = latest_payloads(
            read_ledger(extraction_dir / "claim-events.jsonl"),
            lambda item: str(item.get("claim_id")),
        )
        cases = latest_payloads(
            read_ledger(extraction_dir / "case-events.jsonl"),
            lambda item: str(item.get("case_id")),
        )
        dispositions = latest_payloads(
            read_ledger(extraction_dir / "disposition-events.jsonl"),
            lambda item: f"{item.get('target_type')}:{item.get('target_id')}",
        )
        conflicts = latest_payloads(
            read_ledger(extraction_dir / "conflict-events.jsonl"),
            lambda item: str(item.get("conflict_id")),
        )
        for claim_id, claim in claims.items():
            missing = sorted(set(claim.get("source_atom_ids") or []) - atom_ids)
            if missing:
                errors.append(f"声明 {claim_id} 引用不存在的原子：{missing[:3]}")
        for case_id, case in cases.items():
            missing_atoms = sorted(set(case.get("source_atom_ids") or []) - atom_ids)
            missing_media = sorted(set(case.get("media_ids") or []) - media_ids)
            if missing_atoms or missing_media:
                errors.append(
                    f"案例 {case_id} 引用不存在：atoms={missing_atoms[:3]} media={missing_media[:3]}"
                )
        for target, disposition in dispositions.items():
            missing_claims = sorted(set(disposition.get("claim_ids") or []) - set(claims))
            missing_cases = sorted(set(disposition.get("case_ids") or []) - set(cases))
            if missing_claims or missing_cases:
                errors.append(
                    f"处置 {target} 引用不存在：claims={missing_claims[:3]} cases={missing_cases[:3]}"
                )
        for conflict_id, conflict in conflicts.items():
            missing = sorted(set(conflict.get("claim_ids") or []) - set(claims))
            if missing:
                errors.append(f"冲突 {conflict_id} 引用不存在的声明：{missing[:3]}")
        coverage = source_coverage(root)
        if not coverage.auditable_complete:
            errors.append("历史资料覆盖门槛尚未完成")
        gate_path = extraction_dir / "release-gate.yml"
        gate = yaml.safe_load(gate_path.read_text(encoding="utf-8")) or {}
        report_path = root / "reports/历史资料提取覆盖报告.json"
        if gate.get("coverage_report_sha256") != _sha256_bytes(report_path.read_bytes()):
            errors.append("release-gate.yml 与覆盖报告哈希不一致")
        if gate.get("auditable_complete") is not True or gate.get("blocker_count") != 0:
            errors.append("release-gate.yml 尚未放行")
    except Exception as exc:
        errors.append(str(exc))
    return errors


def write_coverage_reports(root: Path) -> tuple[Path, Path, CoverageResult]:
    result = source_coverage(root)
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    json_path = reports / "历史资料提取覆盖报告.json"
    markdown_path = reports / "历史资料提取覆盖报告.md"
    atomic_write_text(json_path, json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")
    body = f"""# 历史资料提取覆盖报告

- 原始资料哈希：{'通过' if result.source_hashes_valid else '失败'}
- 文本原子：{result.text_atoms_disposed}/{result.text_atoms}
- 媒体：{result.media_disposed}/{result.media}
- 已采用内容关联：{result.accepted_targets_linked}/{result.accepted_targets}
- 未解决目标：{result.unresolved_targets}
- 未解决冲突：{result.unresolved_conflicts}
- 发布阻断项：{result.blocker_count}
- 可审计覆盖完成：{'是' if result.auditable_complete else '否'}
"""
    atomic_write_text(markdown_path, body)
    gate = {
        "schema_version": 1,
        "source_family": result.source_family,
        "auditable_complete": result.auditable_complete,
        "coverage_report_sha256": _sha256_bytes(json_path.read_bytes()),
        "blocker_count": result.blocker_count,
    }
    atomic_write_text(
        root / EXTRACTION_RELATIVE / "release-gate.yml",
        yaml.safe_dump(gate, allow_unicode=True, sort_keys=False),
    )
    return markdown_path, json_path, result
