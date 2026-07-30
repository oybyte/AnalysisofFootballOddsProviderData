from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from odds_journal.cases import (
    CASE_SECTIONS,
    _case_relative_path,
    _settlement,
    append_case_material,
    case_id_for_fixture,
    historical_case,
    latest_cases,
    load_case,
    revision_relative_path,
    validate_cases,
)
from odds_journal.extraction import EXTRACTION_RELATIVE
from odds_journal.ledger import append_payloads, read_ledger


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_repository_cases_are_independent_v2_projections_with_history() -> None:
    root = repository_root()
    cases = latest_cases(root)
    assert len(cases) == 13
    assert all(case.schema_version == 2 for case in cases.values())
    for case in cases.values():
        current = root / _case_relative_path(case)
        revision = historical_case(root, case.case_id, case.case_revision)
        assert current.exists()
        assert revision is not None
        assert revision.read_bytes() == current.read_bytes()
        assert (root / revision_relative_path(case.case_id, 1)).exists()


def test_user_result_records_keep_asian_quarter_settlement_and_provenance() -> None:
    root = repository_root()
    malmo = latest_cases(root)["legacy-malmo-elfsborg"]
    assert malmo.result_record is not None
    assert malmo.result_record.home_goals == 1
    assert malmo.result_record.away_goals == 2
    assert malmo.result_record.total_goals_market is not None
    assert malmo.result_record.total_goals_market.over_settlement == "half_win"
    assert malmo.result_record.total_goals_market.under_settlement == "half_loss"
    assert _settlement(3, 2.75, over=True) == "half_win"
    assert _settlement(3, 2.75, over=False) == "half_loss"

    manifest_path = root / "knowledge/evidence/user-results/2026-07-29/MANIFEST.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["records"]) == 4
    for record in manifest["records"]:
        evidence = root / record["archived_path"]
        assert evidence.exists()
        assert hashlib.sha256(evidence.read_bytes()).hexdigest() == record["sha256"]
        assert record["identity_basis"] == "user-provided-context"


def test_full_text_current_projection_is_larger_than_pre_migration_snapshot() -> None:
    root = repository_root()
    hacken = latest_cases(root)["legacy-hacken-aik"]
    current = root / _case_relative_path(hacken)
    v2 = root / revision_relative_path(hacken.case_id, 2)
    assert current.stat().st_size > v2.stat().st_size
    loaded = load_case(current)
    assert loaded.prematch_analysis_present
    assert len(loaded.sections["source-prematch"]) > 24_000


def _minimal_case_payload(case_id: str, fixture_fingerprint: str) -> dict:
    return {
        "schema_version": 2,
        "case_id": case_id,
        "case_revision": 1,
        "title": case_id,
        "competition_code": None,
        "home_team_id": None,
        "away_team_id": None,
        "kickoff_at": None,
        "fixture_fingerprint": fixture_fingerprint,
        "source_effective_at": "2026-07-28T00:00:00+08:00",
        "chronology": "unknown",
        "completeness": "fragment",
        "statistics_eligible": False,
        "source_atom_ids": [],
        "media_ids": [],
        "scenario_instance_ids": [],
        "result_known": False,
        "prematch_analysis_present": False,
        "source_review_present": False,
        "external_result_present": False,
        "result_record": None,
        "evidence_ids": [],
        "projection_sha256": "0" * 64,
        "status": "draft",
        "sections": {section: "无。" for section in CASE_SECTIONS},
    }


def _write_minimal_case_ledger(root: Path, payloads: list[dict]) -> None:
    extraction = root / EXTRACTION_RELATIVE
    extraction.mkdir(parents=True)
    (extraction / "text-inventory.jsonl").write_text("", encoding="utf-8")
    (extraction / "media-inventory.jsonl").write_text("", encoding="utf-8")
    append_payloads(
        extraction / "case-events.jsonl",
        payloads,
        recorded_at=datetime(2026, 7, 29, 12, tzinfo=ZoneInfo("Asia/Shanghai")),
        actor="test",
        event_id_factory=lambda item, index: f"case:test:{item['case_id']}:{index}",
    )


def test_append_material_updates_one_existing_case_without_creating_duplicate(tmp_path: Path) -> None:
    _write_minimal_case_ledger(tmp_path, [_minimal_case_payload("legacy-home-away", "fixture-1")])
    recorded_at = datetime(2026, 7, 29, 13, tzinfo=ZoneInfo("Asia/Shanghai"))
    path = append_case_material(
        tmp_path,
        case_id=case_id_for_fixture(tmp_path, "fixture-1"),
        section="source-live",
        content="临场盘口由平半升至半球。",
        recorded_at=recorded_at,
    )
    assert path is not None
    assert len(latest_cases(tmp_path)) == 1
    case = latest_cases(tmp_path)["legacy-home-away"]
    assert case.case_revision == 2
    assert "临场盘口由平半升至半球。" in load_case(path).sections["source-live"]
    assert (tmp_path / revision_relative_path(case.case_id, 1)).exists()
    assert (tmp_path / revision_relative_path(case.case_id, 2)).exists()

    event_count = len(read_ledger(tmp_path / EXTRACTION_RELATIVE / "case-events.jsonl"))
    assert append_case_material(
        tmp_path,
        case_id=case.case_id,
        section="source-live",
        content="临场盘口由平半升至半球。",
        recorded_at=recorded_at,
    ) is None
    assert len(read_ledger(tmp_path / EXTRACTION_RELATIVE / "case-events.jsonl")) == event_count
    assert latest_cases(tmp_path)[case.case_id].case_revision == 2


def test_duplicate_fixture_fingerprint_is_rejected(tmp_path: Path) -> None:
    _write_minimal_case_ledger(tmp_path, [
        _minimal_case_payload("legacy-home-away", "fixture-duplicate"),
        _minimal_case_payload("legacy-other-away", "fixture-duplicate"),
    ])
    try:
        case_id_for_fixture(tmp_path, "fixture-duplicate")
    except ValueError as exc:
        assert "未能唯一定位" in str(exc)
    else:
        raise AssertionError("重复比赛指纹必须拒绝定位")
    errors = validate_cases(tmp_path)
    assert any("fixture_fingerprint 重复" in error for values in errors.values() for error in values)
