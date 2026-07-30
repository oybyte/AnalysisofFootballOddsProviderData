from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import jieba

jieba.setLogLevel(logging.WARNING)

from .markdown import MatchDocument, generic_front_matter
from .paths import match_files
from .rules import canonical_text, sha256_file, sha256_text


INDEX_SCHEMA_VERSION = 3
CHUNKER_VERSION = 2
INDEX_BUILD_VERSION = 2
SOURCE_EFFECTIVE_AT = "2026-07-28T00:00:00+08:00"
TRUSTED_INSTRUCTIONS = {
    "ai/analysis_prompt.md": "ai-analysis-instruction",
    "ai/review_prompt.md": "ai-review-instruction",
}


@dataclass
class SearchResult:
    chunk_id: str
    source_path: str
    document_id: str
    match_id: str | None
    section_type: str
    document_type: str
    competition_code: str | None
    team_ids: list[str]
    effective_at: str | None
    reliability: str
    trusted_instruction: bool
    rule_version: str | None
    ruleset_id: str | None
    ruleset_version: str | None
    document_status: str
    markets: list[str]
    phases: list[str]
    content_sha256: str
    artifact_type: str
    case_id: str | None
    case_revision: int | None
    scenario_type_ids: list[str]
    chronology: str | None
    completeness: str | None
    statistics_eligible: bool
    source_atom_ids: list[str]
    media_ids: list[str]
    retrieval_contract_version: int
    score: float
    content: str


def _utc_iso(value: datetime | str | None, timezone_name: str = "Asia/Shanghai") -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=ZoneInfo(timezone_name))
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _search_tokens(text: str) -> str:
    return " ".join(token.strip().casefold() for token in jieba.cut_for_search(text) if token.strip())


def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    paragraphs = re.split(r"\n{2,}(?=\S)", text)
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            start = 0
            while start < len(paragraph):
                chunks.append(paragraph[start : start + max_chars].strip())
                if start + max_chars >= len(paragraph):
                    break
                start += max_chars - overlap
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) > max_chars:
            chunks.append(current.strip())
            tail = current[-overlap:] if current else ""
            current = f"{tail}\n\n{paragraph}".strip()
        else:
            current = candidate
    if current:
        chunks.append(current.strip())
    return chunks


def _live_update_chunks(text: str, timezone_name: str) -> list[tuple[str, str | None]]:
    pattern = re.compile(r"(?m)^###\s+(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?:\s|$)")
    matches = list(pattern.finditer(text))
    if not matches:
        return [(chunk, None) for chunk in _chunk_text(text)]
    output: list[tuple[str, str | None]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        timestamp = datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}:00").replace(
            tzinfo=ZoneInfo(timezone_name)
        )
        for chunk in _chunk_text(text[match.start() : end]):
            output.append((chunk, _utc_iso(timestamp)))
    return output


def _chunk_id(source: str, section: str, index: int, content: str) -> str:
    value = f"{source}|{section}|{index}|{canonical_text(content)}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def legacy_chunks(source: str, section: str, content: str) -> list[dict[str, str]]:
    chunks = [
        {
            "chunk_id": _chunk_id(source, section, index, chunk),
            "content_sha256": sha256_text(chunk),
            "content": chunk,
        }
        for index, chunk in enumerate(_chunk_text(content))
    ]
    return sorted(chunks, key=lambda item: item["chunk_id"])


def _indexed_paths(root: Path) -> list[Path]:
    knowledge = sorted(
        path
        for path in (root / "knowledge").glob("**/*.md")
        if "rule-proposals" not in path.parts and "_revisions" not in path.parts
    )
    ruleset_configuration = sorted(
        path
        for path in (root / "knowledge" / "rulesets").glob("**/*.yml")
        if path.name != "active.yml"
    )
    instructions = [root / path for path in TRUSTED_INSTRUCTIONS if (root / path).exists()]
    return [*match_files(root), *knowledge, *ruleset_configuration, *instructions]


def _source_fingerprint(root: Path, paths: list[Path]) -> str:
    rows = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        rows.append(f"{relative}|{path.stat().st_size}|{sha256_file(path)}")
    return hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def _existing_metadata(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        connection = sqlite3.connect(path)
        return dict(connection.execute("SELECT key, value FROM metadata").fetchall())
    except sqlite3.Error:
        return {}
    finally:
        if "connection" in locals():
            connection.close()


def _create_database(path: Path, source_fingerprint: str) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            document_id TEXT NOT NULL,
            match_id TEXT,
            section_type TEXT NOT NULL,
            document_type TEXT NOT NULL,
            competition_code TEXT,
            team_ids TEXT NOT NULL,
            effective_at TEXT,
            reliability TEXT NOT NULL,
            trusted_instruction INTEGER NOT NULL,
            rule_version TEXT,
            ruleset_id TEXT,
            ruleset_version TEXT,
            document_status TEXT NOT NULL,
            markets TEXT NOT NULL,
            phases TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            case_id TEXT,
            case_revision INTEGER,
            scenario_type_ids TEXT NOT NULL,
            chronology TEXT,
            completeness TEXT,
            statistics_eligible INTEGER NOT NULL,
            source_atom_ids TEXT NOT NULL,
            media_ids TEXT NOT NULL,
            retrieval_contract_version INTEGER NOT NULL,
            content TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(search_text, chunk_id UNINDEXED);
        """
    )
    metadata = {
        "schema_version": str(INDEX_SCHEMA_VERSION),
        "build_version": str(INDEX_BUILD_VERSION),
        "built_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_fingerprint": source_fingerprint,
        "chunk_count": "0",
    }
    connection.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
    return connection


def _insert_chunk(connection: sqlite3.Connection, record: dict) -> None:
    record = {
        "artifact_type": "knowledge",
        "case_id": None,
        "case_revision": None,
        "scenario_type_ids": "",
        "chronology": None,
        "completeness": None,
        "statistics_eligible": 0,
        "source_atom_ids": "",
        "media_ids": "",
        "retrieval_contract_version": 1,
        **record,
    }
    connection.execute(
        """INSERT INTO chunks (
         chunk_id, source_path, document_id, match_id, section_type,
         document_type, competition_code, team_ids, effective_at,
         reliability, trusted_instruction, rule_version, ruleset_id,
         ruleset_version, document_status, markets, phases,
         content_sha256, artifact_type, case_id, case_revision,
         scenario_type_ids, chronology, completeness, statistics_eligible,
         source_atom_ids, media_ids, retrieval_contract_version, content
        ) VALUES
        (:chunk_id, :source_path, :document_id, :match_id, :section_type,
         :document_type, :competition_code, :team_ids, :effective_at,
         :reliability, :trusted_instruction, :rule_version, :ruleset_id,
         :ruleset_version, :document_status, :markets, :phases,
         :content_sha256, :artifact_type, :case_id, :case_revision,
         :scenario_type_ids, :chronology, :completeness, :statistics_eligible,
         :source_atom_ids, :media_ids, :retrieval_contract_version, :content)""",
        record,
    )
    connection.execute(
        "INSERT INTO chunks_fts(search_text, chunk_id) VALUES (?, ?)",
        (_search_tokens(record["content"]), record["chunk_id"]),
    )


def _ruleset_from_path(path: Path) -> tuple[str | None, str | None]:
    parts = path.as_posix().split("/")
    try:
        marker = parts.index("rulesets")
        ruleset_id = parts[marker + 1]
        version = parts[marker + 2]
    except (ValueError, IndexError):
        return None, None
    return ruleset_id, version if re.fullmatch(r"\d+\.\d+\.\d+", version) else None


def build_index(root: Path) -> tuple[Path, int]:
    index_path = root / "ai" / "index" / "catalog.sqlite3"
    paths = _indexed_paths(root)
    fingerprint = _source_fingerprint(root, paths)
    existing = _existing_metadata(index_path)
    if (
        existing.get("schema_version") == str(INDEX_SCHEMA_VERSION)
        and existing.get("build_version") == str(INDEX_BUILD_VERSION)
        and existing.get("source_fingerprint") == fingerprint
    ):
        return index_path, int(existing.get("chunk_count", "0"))

    temporary_path = index_path.with_suffix(".sqlite3.tmp")
    connection = _create_database(temporary_path, fingerprint)
    count = 0
    try:
        for path in match_files(root):
            document = MatchDocument.load(path)
            metadata = document.metadata
            source = path.relative_to(root).as_posix()
            for section_name, section_text in document.sections.items():
                if section_name in {"prematch-facts", "prematch-reasoning", "prematch-locked"}:
                    pairs = [
                        (chunk, _utc_iso(metadata.data_cutoff_at or metadata.analysis_started_at))
                        for chunk in _chunk_text(section_text)
                    ]
                elif section_name == "live-update":
                    pairs = _live_update_chunks(section_text, metadata.timezone)
                elif section_name == "result":
                    pairs = [(chunk, _utc_iso(metadata.result_recorded_at)) for chunk in _chunk_text(section_text)]
                else:
                    pairs = [(chunk, _utc_iso(metadata.reviewed_at)) for chunk in _chunk_text(section_text)]
                for index, (content, effective_at) in enumerate(pairs):
                    record = {
                        "chunk_id": _chunk_id(source, section_name, index, content),
                        "source_path": source,
                        "document_id": metadata.match_id,
                        "match_id": metadata.match_id,
                        "section_type": section_name,
                        "document_type": "match",
                        "competition_code": metadata.competition_code,
                        "team_ids": f"{metadata.home_team_id},{metadata.away_team_id}",
                        "effective_at": effective_at,
                        "reliability": "supported" if metadata.status == "reviewed" else "experimental",
                        "trusted_instruction": 0,
                        "rule_version": None,
                        "ruleset_id": None,
                        "ruleset_version": None,
                        "document_status": str(metadata.status),
                        "markets": metadata.primary_market or "",
                        "phases": "",
                        "content_sha256": sha256_text(content),
                        "artifact_type": "match",
                        "case_id": metadata.match_id,
                        "case_revision": 1,
                        "scenario_type_ids": "",
                        "chronology": "prematch_verified" if metadata.locked_at else "unknown",
                        "completeness": str(metadata.record_integrity),
                        "statistics_eligible": int(str(metadata.status) == "reviewed"),
                        "source_atom_ids": "",
                        "media_ids": "",
                        "retrieval_contract_version": 2,
                        "content": content,
                    }
                    _insert_chunk(connection, record)
                    count += 1

        knowledge_paths = sorted(
            path
            for path in (root / "knowledge").glob("**/*.md")
            if "rule-proposals" not in path.parts and "_revisions" not in path.parts
        )
        instruction_paths = [root / value for value in TRUSTED_INSTRUCTIONS]
        for path in [*knowledge_paths, *[item for item in instruction_paths if item.exists()]]:
            metadata, body = generic_front_matter(path)
            if metadata.get("index") is False:
                continue
            source = path.relative_to(root).as_posix()
            in_sources = "knowledge/sources/" in source
            expected_instruction = TRUSTED_INSTRUCTIONS.get(source)
            trusted = bool(
                expected_instruction
                and metadata.get("document_id") == expected_instruction
                and metadata.get("document_type") == "instruction"
                and metadata.get("trusted_instruction") is True
            )
            if expected_instruction and not trusted:
                raise ValueError(f"可信指令元数据不匹配：{source}")
            is_case = bool(metadata.get("case_id"))
            document_id = str(metadata.get("document_id") or metadata.get("case_id") or source)
            document_type = (
                "instruction"
                if trusted
                else "legacy_case"
                if is_case
                else str(metadata.get("document_type") or "source")
            )
            reliability = str(metadata.get("reliability") or "experimental")
            effective_at = (
                metadata.get("effective_at")
                or (metadata.get("source_effective_at") if is_case else None)
                or (SOURCE_EFFECTIVE_AT if in_sources else None)
            )
            ruleset_id, ruleset_version = _ruleset_from_path(path.relative_to(root))
            for index, content in enumerate(_chunk_text(body)):
                record = {
                    "chunk_id": _chunk_id(source, document_type, index, content),
                    "source_path": source,
                    "document_id": document_id,
                    "match_id": None,
                    "section_type": document_type,
                    "document_type": document_type,
                    "competition_code": metadata.get("competition_code"),
                    "team_ids": ",".join(
                        value
                        for value in (metadata.get("home_team_id"), metadata.get("away_team_id"))
                        if value
                    ),
                    "effective_at": _utc_iso(effective_at) if effective_at else None,
                    "reliability": reliability,
                    "trusted_instruction": int(trusted),
                    "rule_version": metadata.get("rule_version"),
                    "ruleset_id": ruleset_id,
                    "ruleset_version": ruleset_version,
                    "document_status": str(metadata.get("status") or "active"),
                    "markets": ",".join(metadata.get("markets") or []),
                    "phases": ",".join(metadata.get("phases") or []),
                    "content_sha256": sha256_text(content),
                    "artifact_type": (
                        "instruction"
                        if trusted
                        else "legacy_case"
                        if is_case
                        else "rule"
                        if ruleset_id
                        else "source"
                        if in_sources
                        else "knowledge"
                    ),
                    "case_id": metadata.get("case_id"),
                    "case_revision": metadata.get("case_revision"),
                    "scenario_type_ids": ",".join(metadata.get("scenario_type_ids") or []),
                    "chronology": metadata.get("chronology"),
                    "completeness": metadata.get("completeness"),
                    "statistics_eligible": int(metadata.get("statistics_eligible") is True),
                    "source_atom_ids": ",".join(metadata.get("source_atom_ids") or []),
                    "media_ids": ",".join(metadata.get("media_ids") or []),
                    "retrieval_contract_version": 2,
                    "content": content,
                }
                _insert_chunk(connection, record)
                count += 1
        connection.execute("UPDATE metadata SET value = ? WHERE key = 'chunk_count'", (str(count),))
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"索引完整性检查失败：{integrity}")
    except Exception:
        connection.close()
        if temporary_path.exists():
            temporary_path.unlink()
        raise
    else:
        connection.close()
        temporary_path.replace(index_path)
    return index_path, count


def search_index(
    root: Path,
    query: str,
    *,
    competition_code: str | None = None,
    team_id: str | None = None,
    section_type: str | None = None,
    as_of: datetime | None = None,
    exclude_match_id: str | None = None,
    limit: int = 10,
    document_ids: set[str] | None = None,
    ruleset_id: str | None = None,
    ruleset_version: str | None = None,
    artifact_type: str | None = None,
    scenario_type: str | None = None,
    statistics_eligible: bool | None = None,
) -> list[SearchResult]:
    index_path = root / "ai" / "index" / "catalog.sqlite3"
    if not index_path.exists():
        raise ValueError("索引不存在，请先运行 build-index")
    tokens = list(dict.fromkeys(token for token in _search_tokens(query).split() if token))
    if not tokens:
        return []
    fts_query = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
    sql = """
        SELECT c.*, bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
        WHERE chunks_fts MATCH ?
    """
    parameters: list[object] = [fts_query]
    if competition_code:
        sql += " AND c.competition_code = ?"
        parameters.append(competition_code)
    if team_id:
        sql += " AND instr(',' || c.team_ids || ',', ',' || ? || ',') > 0"
        parameters.append(team_id)
    if section_type:
        sql += " AND c.section_type = ?"
        parameters.append(section_type)
    if as_of:
        sql += " AND c.effective_at IS NOT NULL AND c.effective_at <= ?"
        parameters.append(_utc_iso(as_of))
    if exclude_match_id:
        sql += " AND (c.match_id IS NULL OR c.match_id != ?)"
        parameters.append(exclude_match_id)
    if document_ids is not None:
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        sql += f" AND c.document_id IN ({placeholders})"
        parameters.extend(sorted(document_ids))
    if ruleset_id:
        sql += " AND c.ruleset_id = ?"
        parameters.append(ruleset_id)
    if ruleset_version:
        sql += " AND c.ruleset_version = ?"
        parameters.append(ruleset_version)
    if artifact_type:
        sql += " AND c.artifact_type = ?"
        parameters.append(artifact_type)
    if scenario_type:
        sql += " AND instr(',' || c.scenario_type_ids || ',', ',' || ? || ',') > 0"
        parameters.append(scenario_type)
    if statistics_eligible is not None:
        sql += " AND c.statistics_eligible = ?"
        parameters.append(int(statistics_eligible))
    sql += """ ORDER BY
        CASE
            WHEN c.trusted_instruction = 1 THEN 0
            WHEN c.reliability = 'established' THEN 1
            WHEN c.reliability = 'supported' THEN 2
            WHEN c.reliability = 'experimental' THEN 3
            ELSE 4
        END,
        score
        LIMIT ?"""
    parameters.append(max(1, min(limit, 100)))

    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()
    return [
        SearchResult(
            chunk_id=row["chunk_id"],
            source_path=row["source_path"],
            document_id=row["document_id"],
            match_id=row["match_id"],
            section_type=row["section_type"],
            document_type=row["document_type"],
            competition_code=row["competition_code"],
            team_ids=[value for value in row["team_ids"].split(",") if value],
            effective_at=row["effective_at"],
            reliability=row["reliability"],
            trusted_instruction=bool(row["trusted_instruction"]),
            rule_version=row["rule_version"],
            ruleset_id=row["ruleset_id"],
            ruleset_version=row["ruleset_version"],
            document_status=row["document_status"],
            markets=[value for value in row["markets"].split(",") if value],
            phases=[value for value in row["phases"].split(",") if value],
            content_sha256=row["content_sha256"],
            artifact_type=row["artifact_type"],
            case_id=row["case_id"],
            case_revision=row["case_revision"],
            scenario_type_ids=[value for value in row["scenario_type_ids"].split(",") if value],
            chronology=row["chronology"],
            completeness=row["completeness"],
            statistics_eligible=bool(row["statistics_eligible"]),
            source_atom_ids=[value for value in row["source_atom_ids"].split(",") if value],
            media_ids=[value for value in row["media_ids"].split(",") if value],
            retrieval_contract_version=int(row["retrieval_contract_version"]),
            score=row["score"],
            content=row["content"],
        )
        for row in rows
    ]


def index_metadata(root: Path) -> dict[str, str]:
    return _existing_metadata(root / "ai" / "index" / "catalog.sqlite3")


def document_chunks(
    root: Path,
    document_ids: set[str],
    *,
    ruleset_id: str | None = None,
    ruleset_version: str | None = None,
) -> dict[str, list[dict[str, str]]]:
    if not document_ids:
        return {}
    index_path = root / "ai" / "index" / "catalog.sqlite3"
    placeholders = ",".join("?" for _ in document_ids)
    sql = f"""
        SELECT document_id, chunk_id, content_sha256, content
        FROM chunks
        WHERE document_id IN ({placeholders})
    """
    parameters: list[object] = sorted(document_ids)
    if ruleset_id:
        sql += " AND ruleset_id = ?"
        parameters.append(ruleset_id)
    if ruleset_version:
        sql += " AND ruleset_version = ?"
        parameters.append(ruleset_version)
    sql += " ORDER BY source_path, chunk_id"
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()
    output: dict[str, list[dict[str, str]]] = {item: [] for item in document_ids}
    for row in rows:
        output[row["document_id"]].append(
            {
                "chunk_id": row["chunk_id"],
                "content_sha256": row["content_sha256"],
                "content": row["content"],
            }
        )
    return output


def search_results_json(results: list[SearchResult]) -> str:
    return json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2)
