from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

import yaml

from .analysis_context import parse_receipt
from .markdown import MatchDocument
from .paths import match_files
from .rules import sha256_file
from .ledger import read_ledger
from .rule_intakes import ATOM_LEDGER, DISPOSITION_LEDGER, INTAKE_LEDGER, RULE_BUILD_NAME
from .observations import (
    FIXTURE_FACT_LEDGER,
    MARKET_OBSERVATION_LEDGER,
    MARKET_SOURCE_LEDGER,
    MATCH_RESULT_LEDGER,
    conflict_report,
    market_feature_snapshot,
    observation_status,
)


SCHEMA_VERSION = 5


def analytics_path(root: Path) -> Path:
    return root / "ai" / "analytics" / "football.sqlite3"


def _fingerprint(root: Path) -> tuple[str, list[Path]]:
    files = match_files(root)
    raw_root = root / "raw" / "matches"
    analysis_artifacts = sorted(
        path
        for pattern in (
            "analysis-outlook.yml",
            "analysis-draft-input.yml",
            "rule-evaluation-*.yml",
            "experiment-analysis-receipt.yml",
            "experiment-rule-evaluation-*.yml",
            "experimental-analysis-outlook.yml",
            "experiment-predictions/*.yml",
            "experimental-outcome.yml",
            "experimental-advisories.yml",
            "experimental-advisory-dispositions.yml",
            "experimental-advisories/*.yml",
            "experimental-advisory-outcome.yml",
            "live-experiments/*.yml",
        )
        for path in raw_root.glob(f"*/{pattern}")
        if path.is_file()
    )
    observation_ledgers = [
        root / relative
        for relative in (
            MARKET_OBSERVATION_LEDGER,
            MARKET_SOURCE_LEDGER,
            FIXTURE_FACT_LEDGER,
            MATCH_RESULT_LEDGER,
        )
        if (root / relative).is_file()
    ]
    intake_ledgers = [
        root / relative
        for relative in (INTAKE_LEDGER, ATOM_LEDGER, DISPOSITION_LEDGER)
        if (root / relative).is_file()
    ]
    rule_builds = sorted((root / "knowledge/rule-proposals/football-analysis").glob(f"*/{RULE_BUILD_NAME}"))
    rows = [
        f"{path.relative_to(root).as_posix()}|{sha256_file(path)}"
        for path in [*files, *analysis_artifacts, *observation_ledgers, *intake_ledgers, *rule_builds]
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
        CREATE TABLE experimental_runs (
            experiment_run_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            ruleset_version TEXT NOT NULL,
            experiment_revision INTEGER NOT NULL,
            proposal_sha256 TEXT NOT NULL,
            cutoff_at TEXT NOT NULL,
            receipt_sha256 TEXT NOT NULL,
            snapshot_path TEXT NOT NULL
        );
        CREATE TABLE experimental_rule_events (
            experiment_run_id TEXT NOT NULL REFERENCES experimental_runs(experiment_run_id),
            rule_id TEXT NOT NULL,
            status TEXT NOT NULL,
            suppressed_by_rule_id TEXT,
            signal_direction TEXT NOT NULL,
            disposition TEXT,
            PRIMARY KEY (experiment_run_id, rule_id)
        );
        CREATE TABLE experimental_predictions (
            receipt_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            status TEXT NOT NULL,
            prepared_at TEXT NOT NULL,
            experiment_outlook_sha256 TEXT,
            official_lock_candidate_id TEXT NOT NULL
        );
        CREATE TABLE experimental_outcomes (
            outcome_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            prediction_receipt_id TEXT NOT NULL,
            final_score TEXT NOT NULL,
            comparison TEXT NOT NULL,
            primary_range_hit INTEGER NOT NULL,
            modal_goal_hit INTEGER NOT NULL,
            tail_range_hit INTEGER NOT NULL,
            score_hit INTEGER NOT NULL
        );
        CREATE TABLE official_experiment_deltas (
            match_id TEXT PRIMARY KEY REFERENCES fixtures(match_id),
            official_outlook_sha256 TEXT NOT NULL,
            experiment_outlook_sha256 TEXT NOT NULL,
            ranking_deltas_json TEXT NOT NULL,
            official_range_json TEXT,
            experiment_range_json TEXT NOT NULL
        );
        CREATE TABLE experimental_advisories (
            receipt_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            status TEXT NOT NULL,
            prepared_at TEXT NOT NULL,
            advisory_bundle_sha256 TEXT,
            official_lock_candidate_id TEXT NOT NULL
        );
        CREATE TABLE experimental_advisory_events (
            receipt_id TEXT NOT NULL REFERENCES experimental_advisories(receipt_id),
            advisory_id TEXT NOT NULL,
            pack_id TEXT NOT NULL,
            status TEXT NOT NULL,
            severity TEXT NOT NULL,
            disposition TEXT,
            PRIMARY KEY (receipt_id, advisory_id)
        );
        CREATE TABLE experimental_advisory_outcomes (
            outcome_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            advisory_receipt_id TEXT NOT NULL,
            final_score TEXT NOT NULL,
            rule_results_json TEXT NOT NULL
        );
        CREATE TABLE fixture_fact_observations (
            fact_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            competition_code TEXT NOT NULL,
            kickoff_at TEXT NOT NULL,
            venue TEXT,
            weather_raw TEXT,
            temperature_min REAL,
            temperature_max REAL,
            source_ref TEXT NOT NULL,
            source_sha256 TEXT NOT NULL
        );
        CREATE TABLE market_observations (
            observation_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            source_kind TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            received_at TEXT NOT NULL,
            source_captured_at TEXT,
            capture_batch_id TEXT NOT NULL,
            provider_id TEXT NOT NULL,
            market TEXT NOT NULL,
            quote_role TEXT NOT NULL,
            odds_format TEXT NOT NULL,
            time_precision TEXT NOT NULL,
            observed_at TEXT,
            phase_hint TEXT,
            normalized_line REAL,
            normalized_prices_json TEXT NOT NULL,
            raw_values_json TEXT NOT NULL,
            availability_status TEXT NOT NULL,
            normalization_eligible INTEGER NOT NULL,
            prediction_eligible INTEGER NOT NULL,
            retrospective_validation_eligible TEXT NOT NULL
        );
        CREATE TABLE observation_sources (
            source_link_id TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL REFERENCES market_observations(observation_id),
            source_ref TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_line_start INTEGER,
            source_line_end INTEGER
        );
        CREATE TABLE observation_conflicts (
            conflict_group_id TEXT NOT NULL,
            observation_id TEXT NOT NULL REFERENCES market_observations(observation_id),
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            PRIMARY KEY (conflict_group_id, observation_id)
        );
        CREATE TABLE market_series (
            series_key TEXT NOT NULL,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            provider_id TEXT NOT NULL,
            market TEXT NOT NULL,
            quote_role TEXT NOT NULL,
            line_path_json TEXT NOT NULL,
            line_rises INTEGER NOT NULL,
            line_drops INTEGER NOT NULL,
            stable_throughout INTEGER NOT NULL,
            PRIMARY KEY (match_id, series_key)
        );
        CREATE TABLE market_series_nodes (
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            series_key TEXT NOT NULL,
            observation_id TEXT NOT NULL REFERENCES market_observations(observation_id),
            ordinal INTEGER NOT NULL,
            PRIMARY KEY (match_id, series_key, observation_id)
        );
        CREATE TABLE market_series_features (
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            series_key TEXT NOT NULL,
            feature_json TEXT NOT NULL,
            feature_snapshot_sha256 TEXT NOT NULL,
            PRIMARY KEY (match_id, series_key)
        );
        CREATE TABLE match_result_observations (
            result_id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            period TEXT NOT NULL,
            score TEXT NOT NULL,
            result_status TEXT NOT NULL,
            observed_at TEXT,
            source_ref TEXT NOT NULL,
            source_sha256 TEXT NOT NULL
        );
        CREATE TABLE match_result_sources (
            result_source_link_id TEXT PRIMARY KEY,
            result_id TEXT NOT NULL REFERENCES match_result_observations(result_id),
            match_id TEXT NOT NULL REFERENCES fixtures(match_id),
            source_ref TEXT NOT NULL,
            source_sha256 TEXT NOT NULL
        );
        CREATE TABLE market_observation_coverage (
            match_id TEXT PRIMARY KEY REFERENCES fixtures(match_id),
            observation_count INTEGER NOT NULL,
            coverage_json TEXT NOT NULL
        );
        CREATE TABLE rule_intakes (
            intake_id TEXT PRIMARY KEY,
            source_path TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            received_at TEXT NOT NULL,
            trust_status TEXT NOT NULL
        );
        CREATE TABLE rule_atoms (
            atom_id TEXT PRIMARY KEY,
            intake_id TEXT NOT NULL REFERENCES rule_intakes(intake_id),
            source_line_start INTEGER NOT NULL,
            source_line_end INTEGER NOT NULL,
            rule_domain TEXT NOT NULL,
            timing TEXT NOT NULL,
            classification TEXT NOT NULL,
            atom_sha256 TEXT NOT NULL
        );
        CREATE TABLE rule_dispositions (
            atom_id TEXT NOT NULL REFERENCES rule_atoms(atom_id),
            disposition TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            PRIMARY KEY (atom_id, disposition, recorded_at)
        );
        CREATE TABLE rule_builds (
            proposal_version TEXT PRIMARY KEY,
            compiler_version TEXT NOT NULL,
            build_sha256 TEXT NOT NULL,
            source_intakes_json TEXT NOT NULL,
            selected_atoms_json TEXT NOT NULL,
            generated_rule_specs_json TEXT NOT NULL
        );
        CREATE TABLE experiment_rule_specs (
            proposal_version TEXT NOT NULL REFERENCES rule_builds(proposal_version),
            rule_id TEXT NOT NULL,
            rule_spec_sha256 TEXT NOT NULL,
            PRIMARY KEY (proposal_version, rule_id)
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


def _ledger_payloads(root: Path, relative: Path) -> list[dict[str, Any]]:
    path = root / relative
    return [event.payload for event in read_ledger(path)] if path.is_file() else []


def _populate_observation_projection(
    connection: sqlite3.Connection, root: Path, files: list[Path]
) -> None:
    for item in _ledger_payloads(root, MARKET_OBSERVATION_LEDGER):
        if item.get("event_type") != "recorded":
            continue
        connection.execute(
            "INSERT OR IGNORE INTO market_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.get("observation_id"), item.get("match_id"), item.get("source_kind"),
                item.get("source_ref"), item.get("source_sha256"), item.get("received_at"),
                item.get("source_captured_at"), item.get("capture_batch_id"),
                item.get("provider_id"), item.get("market"), item.get("quote_role"),
                item.get("odds_format"), item.get("time_precision"),
                item.get("observed_at"), item.get("phase_hint"), item.get("normalized_line"),
                json.dumps(item.get("normalized_prices", {}), ensure_ascii=False, sort_keys=True),
                json.dumps(item.get("raw_values", {}), ensure_ascii=False, sort_keys=True),
                item.get("availability_status", "available"),
                int(bool(item.get("normalization_eligible"))),
                int(bool(item.get("prediction_eligible"))),
                item.get("retrospective_validation_eligible"),
            ),
        )


def _populate_rule_intake_projection(connection: sqlite3.Connection, root: Path, files: list[Path]) -> None:
    for item in _ledger_payloads(root, INTAKE_LEDGER):
        connection.execute(
            "INSERT OR IGNORE INTO rule_intakes VALUES (?, ?, ?, ?, ?)",
            (item.get("intake_id"), item.get("source_path"), item.get("source_sha256"), item.get("received_at"), item.get("trust_status")),
        )
    for item in _ledger_payloads(root, ATOM_LEDGER):
        connection.execute(
            "INSERT OR IGNORE INTO rule_atoms VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item.get("atom_id"), item.get("intake_id"), item.get("source_line_start"), item.get("source_line_end"),
             item.get("rule_domain"), item.get("timing"), item.get("classification"), item.get("atom_sha256")),
        )
    for item in _ledger_payloads(root, DISPOSITION_LEDGER):
        connection.execute(
            "INSERT OR IGNORE INTO rule_dispositions VALUES (?, ?, ?, ?, ?)",
            (item.get("atom_id"), item.get("disposition"), item.get("actor"), item.get("reason"), item.get("recorded_at")),
        )
    for build_path in sorted((root / "knowledge/rule-proposals/football-analysis").glob(f"*/{RULE_BUILD_NAME}")):
        data = yaml.safe_load(build_path.read_text(encoding="utf-8")) or {}
        version = data.get("proposal_version")
        connection.execute(
            "INSERT INTO rule_builds VALUES (?, ?, ?, ?, ?, ?)",
            (version, data.get("compiler_version"), data.get("build_sha256"),
             json.dumps(data.get("source_intakes", []), ensure_ascii=False, sort_keys=True),
             json.dumps(data.get("selected_atoms", []), ensure_ascii=False, sort_keys=True),
             json.dumps(data.get("generated_rule_specs", []), ensure_ascii=False, sort_keys=True)),
        )
        for spec in data.get("generated_rule_specs", []):
            connection.execute("INSERT INTO experiment_rule_specs VALUES (?, ?, ?)",
                               (version, spec.get("rule_id"), spec.get("rule_spec_sha256")))
    for item in _ledger_payloads(root, MARKET_SOURCE_LEDGER):
        connection.execute(
            "INSERT OR IGNORE INTO observation_sources VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.get("source_link_id"), item.get("observation_id"), item.get("source_ref"),
                item.get("source_sha256"), item.get("source_line_start"), item.get("source_line_end"),
            ),
        )
    for group in conflict_report(root):
        for item in group["observations"]:
            connection.execute(
                "INSERT OR IGNORE INTO observation_conflicts VALUES (?, ?, ?)",
                (group["conflict_group_id"], item["observation_id"], group["match_id"]),
            )
    for item in _ledger_payloads(root, FIXTURE_FACT_LEDGER):
        connection.execute(
            "INSERT OR IGNORE INTO fixture_fact_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item.get("fact_id"), item.get("match_id"), item.get("competition_code"),
                item.get("kickoff_at"), item.get("venue"), item.get("weather_raw"),
                item.get("temperature_min"), item.get("temperature_max"),
                item.get("source_ref"), item.get("source_sha256"),
            ),
        )
    for item in _ledger_payloads(root, MATCH_RESULT_LEDGER):
        event_type = item.get("event_type", "recorded")
        if event_type == "recorded":
            connection.execute(
                "INSERT OR IGNORE INTO match_result_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.get("result_id"), item.get("match_id"), item.get("period"), item.get("score"),
                    item.get("result_status"), item.get("observed_at"), item.get("source_ref"),
                    item.get("source_sha256"),
                ),
            )
        elif event_type == "source_link":
            connection.execute(
                "INSERT OR IGNORE INTO match_result_sources VALUES (?, ?, ?, ?, ?)",
                (
                    item.get("result_source_link_id"), item.get("result_id"),
                    item.get("match_id"), item.get("source_ref"), item.get("source_sha256"),
                ),
            )
    for path in files:
        document = MatchDocument.load(path)
        feature = market_feature_snapshot(
            root, document.metadata.match_id, document.metadata.kickoff_at
        )
        for series in [*feature["series"], *feature.get("phase_only_series", [])]:
            line_change = series.get("line_change")
            connection.execute(
                "INSERT INTO market_series VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    series["series_key"], document.metadata.match_id, series["provider_id"],
                    series["market"], series["quote_role"],
                    json.dumps(series.get("line_path", series.get("line_endpoints", [])), ensure_ascii=False),
                    series.get("line_rises", int(line_change is not None and line_change > 0)),
                    series.get("line_drops", int(line_change is not None and line_change < 0)),
                    int(series.get("stable_throughout") is True),
                ),
            )
            for ordinal, observation_id in enumerate(series["observation_ids"], start=1):
                connection.execute(
                    "INSERT INTO market_series_nodes VALUES (?, ?, ?, ?)",
                    (document.metadata.match_id, series["series_key"], observation_id, ordinal),
                )
            connection.execute(
                "INSERT INTO market_series_features VALUES (?, ?, ?, ?)",
                (
                    document.metadata.match_id, series["series_key"],
                    json.dumps(series, ensure_ascii=False, sort_keys=True),
                    feature["feature_snapshot_sha256"],
                ),
            )
        coverage = observation_status(root, match_id=document.metadata.match_id)
        connection.execute(
            "INSERT INTO market_observation_coverage VALUES (?, ?, ?)",
            (
                document.metadata.match_id, coverage["observations"],
                json.dumps(coverage, ensure_ascii=False, sort_keys=True),
            ),
        )


def build_analytics(root: Path) -> dict[str, Any]:
    fingerprint, files = _fingerprint(root)
    target = analytics_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = sqlite3.connect(target)
        try:
            row = existing.execute("SELECT value FROM build_metadata WHERE key = 'source_fingerprint'").fetchone()
            version = existing.execute("SELECT value FROM build_metadata WHERE key = 'schema_version'").fetchone()
            if row and row[0] == fingerprint and version == (str(SCHEMA_VERSION),):
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
                raw_base = root / "raw" / "matches" / metadata.match_id
                experiment_receipt_path = raw_base / "experiment-analysis-receipt.yml"
                if experiment_receipt_path.is_file():
                    import yaml

                    receipt_data = yaml.safe_load(experiment_receipt_path.read_text(encoding="utf-8")) or {}
                    run_id = str(receipt_data.get("receipt_sha256"))
                    connection.execute(
                        "INSERT INTO experimental_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            metadata.match_id,
                            receipt_data.get("experiment_ruleset_version"),
                            receipt_data.get("experiment_revision"),
                            receipt_data.get("proposal_sha256"),
                            receipt_data.get("as_of"),
                            receipt_data.get("receipt_sha256"),
                            receipt_data.get("snapshot_path"),
                        ),
                    )
                    bundles = sorted(raw_base.glob("experiment-rule-evaluation-*.yml"))
                    if bundles:
                        bundle_data = yaml.safe_load(bundles[-1].read_text(encoding="utf-8")) or {}
                        outlook_path = raw_base / "experimental-analysis-outlook.yml"
                        outlook_data = yaml.safe_load(outlook_path.read_text(encoding="utf-8")) if outlook_path.is_file() else {}
                        dispositions = {
                            item.get("rule_id"): item.get("disposition")
                            for item in (outlook_data or {}).get("dispositions", [])
                        }
                        for event in bundle_data.get("events", []):
                            connection.execute(
                                "INSERT INTO experimental_rule_events VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    run_id,
                                    event.get("rule_id"),
                                    event.get("status"),
                                    event.get("suppressed_by_rule_id"),
                                    event.get("signal_direction"),
                                    dispositions.get(event.get("rule_id")),
                                ),
                            )
                        if outlook_data:
                            official = metadata.analysis_outlook
                            official_range = (
                                [official.total_goals.minimum, official.total_goals.maximum]
                                if official and official.total_goals else None
                            )
                            connection.execute(
                                "INSERT INTO official_experiment_deltas VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    metadata.match_id,
                                    outlook_data.get("official_outlook_sha256"),
                                    outlook_data.get("outlook_sha256"),
                                    json.dumps(outlook_data.get("ranking_deltas", {}), ensure_ascii=False, sort_keys=True),
                                    json.dumps(official_range),
                                    json.dumps(outlook_data.get("final_primary_range")),
                                ),
                            )
                    for prediction_path in sorted((raw_base / "experiment-predictions").glob("*.yml")) if (raw_base / "experiment-predictions").is_dir() else []:
                        prediction = yaml.safe_load(prediction_path.read_text(encoding="utf-8")) or {}
                        connection.execute(
                            "INSERT INTO experimental_predictions VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                prediction.get("receipt_id"), metadata.match_id, prediction.get("status"),
                                prediction.get("prepared_at"), prediction.get("experiment_outlook_sha256"),
                                prediction.get("official_lock_candidate_id"),
                            ),
                        )
                    outcome_path = raw_base / "experimental-outcome.yml"
                    if outcome_path.is_file():
                        outcome = yaml.safe_load(outcome_path.read_text(encoding="utf-8")) or {}
                        connection.execute(
                            "INSERT INTO experimental_outcomes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                outcome.get("outcome_id"), metadata.match_id,
                                outcome.get("experiment_prediction_receipt_id"), outcome.get("final_score"),
                                outcome.get("comparison"), int(bool(outcome.get("primary_range_hit"))),
                                int(bool(outcome.get("modal_goal_hit"))), int(bool(outcome.get("tail_range_hit"))),
                                int(bool(outcome.get("score_hit"))),
                            ),
                        )
                    for advisory_path in sorted((raw_base / "experiment-advisories").glob("*.yml")) if (raw_base / "experiment-advisories").is_dir() else []:
                        advisory = yaml.safe_load(advisory_path.read_text(encoding="utf-8")) or {}
                        connection.execute(
                            "INSERT INTO experimental_advisories VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                advisory.get("receipt_id"), metadata.match_id, advisory.get("status"),
                                advisory.get("prepared_at"), advisory.get("advisory_bundle_sha256"),
                                advisory.get("official_lock_candidate_id"),
                            ),
                        )
                        bundle_ref = advisory.get("advisory_bundle_path")
                        if bundle_ref:
                            advisory_bundle = yaml.safe_load((root / bundle_ref).read_text(encoding="utf-8")) or {}
                            dispositions_path = raw_base / "experimental-advisory-dispositions.yml"
                            disposition_data = yaml.safe_load(dispositions_path.read_text(encoding="utf-8")) if dispositions_path.is_file() else {}
                            dispositions = {item.get("advisory_id"): item.get("disposition") for item in (disposition_data or {}).get("dispositions", [])}
                            for event in advisory_bundle.get("events", []):
                                connection.execute(
                                    "INSERT INTO experimental_advisory_events VALUES (?, ?, ?, ?, ?, ?)",
                                    (advisory.get("receipt_id"), event.get("advisory_id"), event.get("pack_id"), event.get("status"), event.get("severity"), dispositions.get(event.get("advisory_id"))),
                                )
                    advisory_outcome_path = raw_base / "experimental-advisory-outcome.yml"
                    if advisory_outcome_path.is_file():
                        advisory_outcome = yaml.safe_load(advisory_outcome_path.read_text(encoding="utf-8")) or {}
                        connection.execute(
                            "INSERT INTO experimental_advisory_outcomes VALUES (?, ?, ?, ?, ?)",
                            (advisory_outcome.get("outcome_id"), metadata.match_id, advisory_outcome.get("advisory_receipt_id"), advisory_outcome.get("final_score"), json.dumps(advisory_outcome.get("rule_results", {}), ensure_ascii=False, sort_keys=True)),
                        )
            _populate_observation_projection(connection, root, files)
            _populate_rule_intake_projection(connection, root, files)
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
            for table in (
                "fixtures", "market_snapshots", "analysis_runs", "results", "experimental_runs",
                "experimental_rule_events", "experimental_predictions", "experimental_outcomes",
                "official_experiment_deltas", "experimental_advisories", "experimental_advisory_events",
                "experimental_advisory_outcomes", "market_observations", "observation_sources",
                "observation_conflicts", "market_series", "match_result_observations",
                "match_result_sources", "market_observation_coverage",
            )
        }
        fingerprint = connection.execute("SELECT value FROM build_metadata WHERE key = 'source_fingerprint'").fetchone()[0]
    return {"exists": True, "path": target.as_posix(), "source_fingerprint": fingerprint, "counts": counts, "errors": validate_analytics(root)}


def rule_report(root: Path, rule_id: str) -> list[dict[str, Any]]:
    target = analytics_path(root)
    if not target.is_file():
        raise ValueError("Analytics Database 尚未构建")
    # Contract 4 bundles stay authoritative files; this report deliberately does not invent rule outcomes.
    rows: list[dict[str, Any]] = []
    for pattern in ("*/rule-evaluation-*.yml", "*/experiment-rule-evaluation-*.yml"):
        for bundle in (root / "raw" / "matches").glob(pattern):
            data = __import__("yaml").safe_load(bundle.read_text(encoding="utf-8")) or {}
            for event in data.get("events", []):
                if event.get("rule_id") == rule_id:
                    rows.append({"match_id": data.get("match_id"), "bundle": bundle.relative_to(root).as_posix(), **event})
    for bundle in (root / "raw" / "matches").glob("*/experimental-advisories.yml"):
        data = __import__("yaml").safe_load(bundle.read_text(encoding="utf-8")) or {}
        for event in data.get("events", []):
            if event.get("advisory_id") == rule_id:
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
