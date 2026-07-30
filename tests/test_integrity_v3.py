from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from odds_journal.case_retrieval import _eligible_artifacts
from odds_journal.cases import case_at, case_events, latest_cases, validate_cases
from odds_journal.evidence_registry import evidence_records, validate_evidence_registry
from odds_journal.indexing import build_index, search_index
from odds_journal.transaction import RepositoryTransaction, recover_pending_transactions


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def at(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Shanghai"))


def test_repository_legacy_cases_are_v3_and_all_revisions_are_audited() -> None:
    root = repository_root()
    cases = latest_cases(root)
    events = case_events(root)
    assert len(cases) == len({str(event.payload["case_id"]) for event in events})
    assert all(case.schema_version == 3 for case in cases.values())
    assert all(
        case.source_archived_at is not None
        and case.source_archived_at.tzinfo is not None
        and case.revision_effective_at is not None
        and case.source_archived_at <= case.revision_effective_at
        for case in cases.values()
    )
    assert len(list((root / "knowledge/cases/legacy/_revisions").glob("*.md"))) == len(events)
    assert all(not errors for errors in validate_cases(root).values())


def test_rejected_kickoff_binding_is_preserved_but_not_current() -> None:
    root = repository_root()
    records = evidence_records(root)
    incorrect = records["user-kickoff-20260730-05"].bindings[0]
    assert incorrect.status == "rejected"
    seoul = latest_cases(root)["legacy-seoul-ulsan"]
    assert all(reference.evidence_id != "user-kickoff-20260730-05" for reference in seoul.evidence_refs)
    assert not validate_evidence_registry(root)


def test_as_of_selects_revision_before_ranking() -> None:
    root = repository_root()
    assert case_at(root, "legacy-seoul-ulsan", at("2026-07-29T19:59:59+08:00")) is None
    selected = case_at(root, "legacy-seoul-ulsan", at("2026-07-29T20:30:00+08:00"))
    assert selected is not None and selected[0].case_revision == 1
    assert not _eligible_artifacts(root, at("2026-07-29T19:59:59+08:00"), "target")
    eligible = _eligible_artifacts(root, at("2026-07-29T20:30:00+08:00"), "target")
    assert eligible and all(item["case_revision"] == 1 for item in eligible.values())
    build_index(root)
    results = search_index(
        root, "FC首尔", as_of=at("2026-07-29T20:30:00+08:00"),
        artifact_type="legacy_case", limit=100,
    )
    assert results and all(item.case_revision == 1 for item in results)


def test_repository_transaction_restores_failed_changes(tmp_path: Path) -> None:
    root = tmp_path
    tracked = root / "tracked.txt"
    revisions = root / "revisions"
    revisions.mkdir(parents=True)
    tracked.write_text("before", encoding="utf-8")
    try:
        with RepositoryTransaction(
            root, files=[tracked], directories=[revisions], operation="test"
        ):
            tracked.write_text("after", encoding="utf-8")
            (revisions / "new.md").write_text("new", encoding="utf-8")
            raise RuntimeError("fail")
    except RuntimeError:
        pass
    assert tracked.read_text(encoding="utf-8") == "before"
    assert not (revisions / "new.md").exists()


def test_repository_transaction_recovers_interrupted_write(tmp_path: Path) -> None:
    tracked = tmp_path / "tracked.txt"
    revisions = tmp_path / "revisions"
    revisions.mkdir()
    tracked.write_text("before", encoding="utf-8")
    transaction = RepositoryTransaction(
        tmp_path, files=[tracked], directories=[revisions], operation="interrupted-test"
    )
    transaction.__enter__()
    tracked.write_text("after", encoding="utf-8")
    (revisions / "new.md").write_text("new", encoding="utf-8")

    assert recover_pending_transactions(tmp_path, force=True) == ["interrupted-test"]
    assert tracked.read_text(encoding="utf-8") == "before"
    assert not (revisions / "new.md").exists()
    assert not (tmp_path / ".odds-journal/write.lock").exists()


def test_repository_transaction_keeps_interrupted_committed_write(tmp_path: Path) -> None:
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before", encoding="utf-8")
    transaction = RepositoryTransaction(
        tmp_path, files=[tracked], directories=[], operation="committed-test"
    )
    transaction.__enter__()
    tracked.write_text("after", encoding="utf-8")
    transaction.commit()

    assert recover_pending_transactions(tmp_path, force=True) == []
    assert tracked.read_text(encoding="utf-8") == "after"
    assert not (tmp_path / ".odds-journal/write.lock").exists()
