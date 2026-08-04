from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from .analysis_context import parse_receipt
from .markdown import MatchDocument
from .paths import match_files
from .rules import sha256_file


SCHEMA_VERSION = 1


def analytics_path(root: Path) -> Path:
    return root / "ai" / "analytics" / "football.sqlite3"


def _fingerprint(root: Path) -> tuple[str, list[Path]]:
    files = match_files(root)
    raw_root = root / "raw" / "matches"
    analysis_artifacts = sorted(
        path
        for pattern in ("analysis-outlook.yml", "analysis-draft-input.yml", "rule-evaluation-*.yml")
        for path in raw_root.glob(f"*/{pattern}")
        if path.is_file()
    )
    rows = [
        f"{path.relative_to(root).as_posix()}|{sha256_file(path)}"
        for path in [*files, *analysis_artifacts]
    ]
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest(), files


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE fixtures (
            match_id TEXT PRIMARY KEY,
            match_path TEXT NOT NULL UNIQUE,
            competition_code TEXT NOT NULL,
            kickoff_at TEXT NOT NULL,
            home_team_id TEXT NOT NULL,
            away_team_id TEXT NOT NULL,
            status TEXT NOT NULL,
            source_sha256 TEXT NOT NULL
        );
        CREATE TABLE market_snapshots (
            snapshot_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            market TEXT NOT NULL,
            phase TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            evidence_id TEXT,
            odds_format TEXT NOT NULL,
            source_ref TEXT NOT NULL
        );
        CREATE TABLE snapshot_values (
            snapshot_id TEXT NOT NULL REFERENCES market_snapshots(snapshot_id),
            value_key TEXT NOT NULL,
            raw_value TEXT,
            numeric_value REAL,
            PRIMARY KEY (snapshot_id, value_key)
        );
        CREATE TABLE analysis_runs (
            analysis_run_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            ruleset_version TEXT,
            cutoff_at TEXT,
            receipt_digest TEXT,
            outlook_digest TEXT,
            ruleset_origin TEXT,
            prediction_eligible INTEGER NOT NULL
        );
        CREATE TABLE results (
            match_id TEXT PRIMARY KEY REFERENCES fixtures(match_id),
            final_score TEXT,
            result_recorded_at TEXT
        );
        CREATE TABLE evidence_links (
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            evidence_ref TEXT NOT NULL,
            PRIMARY KEY (match_id, evidence_ref)
        );
        CREATE TABLE validation_cases (
            case_id TEXT PRIMARY KEY,
            case_type TEXT NOT NULL,
            statistics_eligible INTEGER NOT NULL
        );
        """
    )


def _maybe_score(document: MatchDocument) -> tuple[str | None, str | None]:
    payload = document.metadata.model_dump(mode="json")
    for key in ("final_score", "score", "result_score"):
        value = payload.get(key)
        if value:
            return str(value), str(payload.get("result_recorded_at") or "") or None
    text = document.sections.get("result", "")
    import re

    match = re.search(r"\b(\d+)\s*[-:：]\s*(\d+)\b", text)
    return (f"{match.group(1)}-{match.group(2)}", None) if match else (None, None)


def build_analytics(root: Path) -> dict[str, Any]:
    fingerprint, files = _fingerprint(root)
    target = analytics_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = sqlite3.connect(target)
        try:
            row = existing.execute("SELECT value FROM build_metadata WHERE key = 'source_fingerprint'").fetchone()
            if row and row[0] == fingerprint:
                return {"path": target, "rebuilt": False, "source_fingerprint": fingerprint, "matches": len(files)}
        finally:
            existing.close()
    # A stale temporary database is harmless; use a process-unique path so an
    # interrupted or concurrent prior build cannot block the next transaction.
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    try:
        connection = sqlite3.connect(temporary)
        try:
            _create_schema(connection)
            connection.executemany(
                "INSERT INTO build_metadata(key, value) VALUES (?, ?)",
                [
                    ("schema_version", str(SCHEMA_VERSION)),
                    ("source_fingerprint", fingerprint),
                    ("match_count", str(len(files))),
                ],
            )
            for path in files:
                document = MatchDocument.load(path)
                metadata = document.metadata
                connection.execute(
                    "INSERT INTO fixtures VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        metadata.match_id, path.relative_to(root).as_posix(), metadata.competition_code,
                        metadata.kickoff_at.isoformat(), metadata.home_team_id, metadata.away_team_id,
                        str(metadata.status), sha256_file(path),
                    ),
                )
                for snapshot in metadata.market_snapshots:
                    connection.execute(
                        "INSERT INTO market_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            snapshot.snapshot_id, metadata.match_id, str(snapshot.market), str(snapshot.phase),
                            snapshot.captured_at.isoformat(), snapshot.provider_id, snapshot.evidence_id,
                            str(snapshot.odds_format), snapshot.source_ref,
                        ),
                    )
                    keys = set(snapshot.raw_values) | set(snapshot.normalized_values)
                    for key in keys:
                        connection.execute(
                            "INSERT INTO snapshot_values VALUES (?, ?, ?, ?)",
                            (snapshot.snapshot_id, key, snapshot.raw_values.get(key), snapshot.normalized_values.get(key)),
                        )
                receipt = parse_receipt(document.sections.get("analysis", ""))
                if receipt is not None:
                    outlook_file = root / "raw" / "matches" / metadata.match_id / "analysis-outlook.yml"
                    outlook_digest = sha256_file(outlook_file) if outlook_file.is_file() else None
                    run_id = hashlib.sha256(
                        f"{metadata.match_id}|{receipt.ruleset_version}|{receipt.as_of.isoformat()}|{receipt.context_sha256}|{outlook_digest or ''}".encode("utf-8")
                    ).hexdigest()
                    eligible = int(bool(metadata.locked_at and str(metadata.status) in {"locked", "finished", "reviewed"}))
                    connection.execute(
                        "INSERT INTO analysis_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (run_id, metadata.match_id, receipt.ruleset_version, receipt.as_of.isoformat(), receipt.context_sha256, outlook_digest, receipt.ruleset_origin, eligible),
                    )
                score, recorded_at = _maybe_score(document)
                if score:
                    connection.execute("INSERT INTO results VALUES (?, ?, ?)", (metadata.match_id, score, recorded_at))
                for snapshot in metadata.market_snapshots:
                    connection.execute("INSERT OR IGNORE INTO evidence_links VALUES (?, ?)", (metadata.match_id, snapshot.source_ref))
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise ValueError("Analytics Database integrity_check 失败")
            connection.commit()
        finally:
            # sqlite3's context manager commits but does not close the Windows
            # file handle. Close before os.replace so the atomic swap works.
            connection.close()
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {"path": target, "rebuilt": True, "source_fingerprint": fingerprint, "matches": len(files)}


def validate_analytics(root: Path) -> list[str]:
    target = analytics_path(root)
    if not target.is_file():
        return ["Analytics Database 尚未构建"]
    errors: list[str] = []
    with sqlite3.connect(target) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            errors.append("Analytics Database integrity_check 失败")
        version = connection.execute("SELECT value FROM build_metadata WHERE key = 'schema_version'").fetchone()
        if version != (str(SCHEMA_VERSION),):
            errors.append("Analytics Database schema_version 不匹配")
        expected, _ = _fingerprint(root)
        actual = connection.execute("SELECT value FROM build_metadata WHERE key = 'source_fingerprint'").fetchone()
        if actual != (expected,):
            errors.append("Analytics Database 源文件指纹已过期，请运行 analytics build")
    return errors


def analytics_status(root: Path) -> dict[str, Any]:
    target = analytics_path(root)
    if not target.is_file():
        return {"exists": False, "path": target.as_posix()}
    with sqlite3.connect(target) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("fixtures", "market_snapshots", "analysis_runs", "results")
        }
        fingerprint = connection.execute("SELECT value FROM build_metadata WHERE key = 'source_fingerprint'").fetchone()[0]
    return {"exists": True, "path": target.as_posix(), "source_fingerprint": fingerprint, "counts": counts, "errors": validate_analytics(root)}


def rule_report(root: Path, rule_id: str) -> list[dict[str, Any]]:
    target = analytics_path(root)
    if not target.is_file():
        raise ValueError("Analytics Database 尚未构建")
    # Contract 4 bundles stay authoritative files; this report deliberately does not invent rule outcomes.
    rows: list[dict[str, Any]] = []
    for bundle in (root / "raw" / "matches").glob("*/rule-evaluation-*.yml"):
        data = __import__("yaml").safe_load(bundle.read_text(encoding="utf-8")) or {}
        for event in data.get("events", []):
            if event.get("rule_id") == rule_id:
                rows.append({"match_id": data.get("match_id"), "bundle": bundle.relative_to(root).as_posix(), **event})
    return rows


def export_dataset(root: Path, output: Path, *, as_of: str) -> int:
    target = analytics_path(root)
    if not target.is_file():
        raise ValueError("Analytics Database 尚未构建")
    with sqlite3.connect(target) as connection:
        rows = connection.execute(
            """
            SELECT fixtures.match_id, fixtures.competition_code, fixtures.kickoff_at, analysis_runs.ruleset_version,
                   analysis_runs.cutoff_at, analysis_runs.prediction_eligible,
                   CASE WHEN results.result_recorded_at IS NOT NULL AND results.result_recorded_at <= ?
                        THEN results.final_score ELSE NULL END,
                   CASE WHEN results.result_recorded_at IS NOT NULL AND results.result_recorded_at <= ?
                        THEN results.result_recorded_at ELSE NULL END
            FROM fixtures LEFT JOIN analysis_runs USING(match_id) LEFT JOIN results USING(match_id)
            WHERE fixtures.kickoff_at <= ? ORDER BY fixtures.kickoff_at, fixtures.match_id
            """,
            (as_of, as_of, as_of),
        ).fetchall()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps({
                "match_id": row[0], "competition_code": row[1], "kickoff_at": row[2],
                "ruleset_version": row[3], "cutoff": row[4],
                "prediction_eligible": bool(row[5]), "label": row[6],
                "label_available_at": row[7],
            }, ensure_ascii=False) + "\n")
    return len(rows)
