from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
import pytest

import odds_journal.lock_lifecycle as lifecycle_module
from odds_journal.analysis_context import prepare_analysis_context
from odds_journal.case_retrieval import retrieve_cases
from odds_journal.lock_lifecycle import (
    audit_lock_and_finish,
    load_lock_candidate,
    prepare_lock_candidate,
    validate_lock_candidate,
    validate_lifecycle,
)
from odds_journal.markdown import MatchDocument
from odds_journal.models import AnalysisOutlook, MarketSnapshot, PrimaryMarket, Selection
from odds_journal.scenarios import set_no_scenario
from odds_journal.services import parse_datetime, set_market_snapshots

from .test_analysis_context import factual_match, fill_analysis
from .test_match_v2 import outlook
from .test_rules_release import _activate_v2


class FixedDateTime(datetime):
    current = parse_datetime("2026-07-30T18:00:00+08:00")

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current


def _lock_ready_match(project_root: Path, monkeypatch) -> tuple[Path, Path]:
    _activate_v2(project_root, monkeypatch)
    path = factual_match(project_root)
    document = MatchDocument.load(path)
    document.metadata.schema_version = 2
    document.save()
    set_market_snapshots(
        path,
        [
            MarketSnapshot(
                snapshot_id="macau-asian-opening",
                market="asian_handicap",
                phase="opening",
                captured_at=parse_datetime("2026-07-30T12:00:00+08:00"),
                provider_id="macau",
                source_ref="evidence:test",
                odds_format="hong_kong",
                raw_values={"home_line": "主让0.5/1", "home_water": "0.94"},
                normalized_values={"home_line": -0.75, "home_water": 0.94},
            )
        ],
    )
    prepare_analysis_context(
        project_root,
        path,
        prepared_at=parse_datetime("2026-07-30T17:40:00+08:00"),
        as_of=parse_datetime("2026-07-30T17:30:00+08:00"),
        markets=[PrimaryMarket.HANDICAP],
    )
    set_no_scenario(path, "节点不足，不强制归类")
    retrieve_cases(project_root, path, prepared_at=parse_datetime("2026-07-30T17:45:00+08:00"))
    fill_analysis(path)
    outlook_path = project_root / "raw" / "matches" / MatchDocument.load(path).metadata.match_id / "analysis-outlook.yml"
    outlook_path.parent.mkdir(parents=True, exist_ok=True)
    outlook_path.write_text(
        yaml.safe_dump(outlook("degraded"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path, outlook_path


def test_prematch_candidate_supports_atomic_late_lock_and_finish(
    project_root: Path, monkeypatch
) -> None:
    path, outlook_path = _lock_ready_match(project_root, monkeypatch)
    monkeypatch.setattr(lifecycle_module, "datetime", FixedDateTime)
    candidate_path, receipt = prepare_lock_candidate(
        project_root,
        path,
        market=PrimaryMarket.HANDICAP,
        selection=Selection.HOME_HANDICAP,
        secondary=Selection.AWAY_HANDICAP,
        confidence=0.69,
        outlook_path=outlook_path,
        actor="lcz",
    )
    assert load_lock_candidate(candidate_path).receipt_sha256 == receipt.receipt_sha256
    latest_path, latest_receipt = prepare_lock_candidate(
        project_root,
        path,
        market=PrimaryMarket.HANDICAP,
        selection=Selection.HOME_HANDICAP,
        secondary=Selection.AWAY_HANDICAP,
        confidence=0.69,
        outlook_path=outlook_path,
        actor="lcz",
    )
    with pytest.raises(ValueError, match="最新有效回执"):
        validate_lock_candidate(project_root, path, receipt, require_current=True)

    FixedDateTime.current = parse_datetime("2026-07-30T20:00:00+08:00")
    finished = audit_lock_and_finish(
        project_root,
        path,
        latest_path,
        trigger_entry_id="journal-test-review",
        actor="lcz",
        score="2-1",
        source="user-provided-postmatch-review:journal-test-review",
        key_events=None,
    )
    assert finished.metadata.status == "finished"
    assert finished.metadata.locked_at == latest_receipt.data_cutoff_at
    assert finished.metadata.score == "2-1"
    assert finished.metadata.settlement.asian_result == "half_win"
    assert not next(iter(validate_lifecycle(project_root).values()))
