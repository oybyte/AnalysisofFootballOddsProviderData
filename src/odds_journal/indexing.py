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


INDEX_SCHEMA_VERSION = 1
SOURCE_EFFECTIVE_AT = "2026-07-28T00:00:00+08:00"


@dataclass
class SearchResult:
    chunk_id: str
    source_path: str
    document_id: str
    match_id: str | None
    section_type: str
    competition_code: str | None
    team_ids: list[str]
    effective_at: str | None
    reliability: str
    trusted_instruction: bool
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
    value = f"{source}|{section}|{index}|{content}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _create_database(path: Path) -> sqlite3.Connection:
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
            competition_code TEXT,
            team_ids TEXT NOT NULL,
            effective_at TEXT,
            reliability TEXT NOT NULL,
            trusted_instruction INTEGER NOT NULL,
            content TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE chunks_fts USING fts5(search_text, chunk_id UNINDEXED);
        """
    )
    connection.execute("INSERT INTO metadata VALUES (?, ?)", ("schema_version", str(INDEX_SCHEMA_VERSION)))
    connection.execute(
        "INSERT INTO metadata VALUES (?, ?)",
        ("built_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
    )
    return connection


def _insert_chunk(connection: sqlite3.Connection, record: dict) -> None:
    connection.execute(
        """INSERT INTO chunks VALUES
        (:chunk_id, :source_path, :document_id, :match_id, :section_type,
         :competition_code, :team_ids, :effective_at, :reliability,
         :trusted_instruction, :content)""",
        record,
    )
    connection.execute(
        "INSERT INTO chunks_fts(search_text, chunk_id) VALUES (?, ?)",
        (_search_tokens(record["content"]), record["chunk_id"]),
    )


def build_index(root: Path) -> tuple[Path, int]:
    index_path = root / "ai" / "index" / "catalog.sqlite3"
    connection = _create_database(index_path)
    count = 0
    try:
        for path in match_files(root):
            document = MatchDocument.load(path)
            metadata = document.metadata
            source = path.relative_to(root).as_posix()
            for section_name, section_text in document.sections.items():
                if section_name in {"prematch-facts", "prematch-reasoning", "prematch-locked"}:
                    pairs = [(chunk, _utc_iso(metadata.data_cutoff_at or metadata.analysis_started_at)) for chunk in _chunk_text(section_text)]
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
                        "competition_code": metadata.competition_code,
                        "team_ids": f"{metadata.home_team_id},{metadata.away_team_id}",
                        "effective_at": effective_at,
                        "reliability": "supported" if metadata.status == "reviewed" else "experimental",
                        "trusted_instruction": 0,
                        "content": content,
                    }
                    _insert_chunk(connection, record)
                    count += 1

        knowledge_paths = sorted((root / "knowledge").glob("**/*.md"))
        ai_paths = [root / "ai" / "analysis_prompt.md", root / "ai" / "review_prompt.md"]
        for path in [*knowledge_paths, *[p for p in ai_paths if p.exists()]]:
            metadata, body = generic_front_matter(path)
            if metadata.get("index") is False:
                continue
            source = path.relative_to(root).as_posix()
            in_sources = "knowledge/sources/" in source
            trusted = source.startswith("ai/")
            document_id = str(metadata.get("document_id") or source)
            section_type = "instruction" if trusted else str(metadata.get("document_type") or "source")
            reliability = str(metadata.get("reliability") or "experimental")
            effective_at = metadata.get("effective_at") or (SOURCE_EFFECTIVE_AT if in_sources else None)
            for index, content in enumerate(_chunk_text(body)):
                record = {
                    "chunk_id": _chunk_id(source, section_type, index, content),
                    "source_path": source,
                    "document_id": document_id,
                    "match_id": None,
                    "section_type": section_type,
                    "competition_code": None,
                    "team_ids": "",
                    "effective_at": _utc_iso(effective_at) if effective_at else None,
                    "reliability": reliability,
                    "trusted_instruction": int(trusted),
                    "content": content,
                }
                _insert_chunk(connection, record)
                count += 1
        connection.commit()
    finally:
        connection.close()
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
    sql += """ ORDER BY
        CASE
            WHEN c.section_type = 'instruction' THEN 0
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
            competition_code=row["competition_code"],
            team_ids=[value for value in row["team_ids"].split(",") if value],
            effective_at=row["effective_at"],
            reliability=row["reliability"],
            trusted_instruction=bool(row["trusted_instruction"]),
            score=row["score"],
            content=row["content"],
        )
        for row in rows
    ]


def search_results_json(results: list[SearchResult]) -> str:
    return json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2)
