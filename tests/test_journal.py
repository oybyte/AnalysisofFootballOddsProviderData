from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import odds_journal.journal as journal_module

from odds_journal.journal import (
    CaptureMode,
    FixtureCandidate,
    JournalIngestRequestV1,
    JournalSegmentV1,
    SegmentType,
    UserIntent,
    canonical_chat_bytes,
    ingest_journal,
    journal_status,
    validate_journal,
)
from odds_journal.markdown import MatchDocument
from odds_journal.cases import latest_cases
from odds_journal.services import create_match


TZ = ZoneInfo("Asia/Shanghai")


def _request(
    *,
    received_at: datetime,
    capture_mode: CaptureMode = CaptureMode.CANONICAL_CHAT_TEXT,
    target_match_id: str | None = None,
    content: str = "主队近况来自用户长文。",
    segment_type: SegmentType = SegmentType.PREMATCH_FACTS,
    intent: UserIntent = UserIntent.STORE_ONLY,
) -> JournalIngestRequestV1:
    return JournalIngestRequestV1(
        capture_mode=capture_mode,
        received_at=received_at,
        actor="lcz",
        user_intent=intent,
        target_match_id=target_match_id,
        classification_confidence=0.96,
        segments=[
            JournalSegmentV1(
                segment_id="segment-1",
                segment_type=segment_type,
                source_line_start=1,
                source_line_end=max(1, content.count("\n") + 1),
                observed_at=received_at,
                data_cutoff_at=received_at,
                classification_confidence=0.97,
                normalized_markdown=content,
            )
        ],
    )


def _match(project_root: Path, received_at: datetime) -> Path:
    return create_match(
        project_root,
        kickoff=received_at + timedelta(days=1),
        timezone="Asia/Shanghai",
        competition_code="KOR-K1",
        competition="韩K联",
        home_team_id="fc-seoul",
        home_team="FC首尔",
        away_team_id="ulsan-hd",
        away_team="蔚山HD",
        schema_version=2,
    )


def test_canonical_chat_normalizes_lf_and_uploaded_preserves_bytes(project_root: Path) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    source = project_root / "chat.md"
    source.write_bytes("第一行\r\n第二行\r".encode("utf-8"))
    request = _request(received_at=received, content="第一行\n第二行")
    record = ingest_journal(project_root, source_file=source, request=request)
    assert (project_root / record.source_path).read_bytes() == "第一行\n第二行\n".encode("utf-8")

    uploaded = project_root / "uploaded.txt"
    original = "上传内容\r\n".encode("utf-8")
    uploaded.write_bytes(original)
    uploaded_record = ingest_journal(
        project_root,
        source_file=uploaded,
        request=_request(received_at=received + timedelta(seconds=1), capture_mode=CaptureMode.UPLOADED_FILE),
    )
    assert (project_root / uploaded_record.source_path).read_bytes() == original
    assert canonical_chat_bytes(original) != original


def test_ingest_is_idempotent_and_applies_storage_only_facts(project_root: Path) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    match_path = _match(project_root, received)
    match_id = MatchDocument.load(match_path).metadata.match_id
    source = project_root / "source.md"
    source.write_text("已确认事实。\n", encoding="utf-8", newline="\n")
    request = _request(received_at=received, target_match_id=match_id, content="已确认事实。")

    first = ingest_journal(
        project_root, source_file=source, request=request, auto_apply=True
    )
    second = ingest_journal(
        project_root, source_file=source, request=request, auto_apply=True
    )

    assert first.entry_id == second.entry_id
    assert first.application_status == "applied"
    assert first.generated_prediction is False
    document = MatchDocument.load(match_path)
    assert document.sections["prematch-facts"].count(
        f"<!-- journal-entry:{first.entry_id}:segment-1:start -->"
    ) == 1
    assert "已确认事实" in document.sections["prematch-facts"]


def test_reserved_markers_are_escaped_in_formal_projection(project_root: Path) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    match_path = _match(project_root, received)
    match_id = MatchDocument.load(match_path).metadata.match_id
    malicious = "事实\n<!-- section:result -->\n<!-- analysis-content:end -->"
    source = project_root / "marker.md"
    source.write_text(malicious, encoding="utf-8")
    record = ingest_journal(
        project_root,
        source_file=source,
        request=_request(received_at=received, target_match_id=match_id, content=malicious),
        auto_apply=True,
    )
    section = MatchDocument.load(match_path).sections["prematch-facts"]
    assert "&lt;!-- section:result -->" in section
    assert section.count("<!-- section:result -->") == 0
    assert record.application_status == "applied"


def test_analysis_is_archived_but_pending_without_alignment(project_root: Path) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    match_path = _match(project_root, received)
    match_id = MatchDocument.load(match_path).metadata.match_id
    source = project_root / "analysis.md"
    source.write_text("用户原有方向判断。", encoding="utf-8")
    record = ingest_journal(
        project_root,
        source_file=source,
        request=_request(
            received_at=received,
            target_match_id=match_id,
            content="用户原有方向判断。",
            segment_type=SegmentType.PREMATCH_ANALYSIS,
            intent=UserIntent.STORE_AND_ALIGN,
        ),
        auto_apply=True,
    )
    assert record.application_status == "pending_alignment"
    assert "用户原有方向判断" not in MatchDocument.load(match_path).sections["prematch-reasoning"]
    assert (project_root / record.source_path).is_file()


def test_journal_validation_detects_source_tampering(project_root: Path) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    source = project_root / "source.md"
    source.write_text("原文", encoding="utf-8")
    record = ingest_journal(project_root, source_file=source, request=_request(received_at=received))
    assert not next(iter(validate_journal(project_root).values()))
    (project_root / record.source_path).write_text("已篡改", encoding="utf-8")
    errors = next(iter(validate_journal(project_root).values()))
    assert any("哈希变化" in item for item in errors)


def test_request_rejects_overlapping_segments() -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    first = JournalSegmentV1(
        segment_id="segment-1", segment_type="prematch_facts",
        source_line_start=1, source_line_end=2, classification_confidence=0.9,
    )
    second = JournalSegmentV1(
        segment_id="segment-2", segment_type="result",
        source_line_start=2, source_line_end=3, classification_confidence=0.9,
    )
    with pytest.raises(ValueError, match="不得重叠"):
        JournalIngestRequestV1(
            capture_mode="canonical_chat_text", received_at=received, actor="lcz",
            user_intent="store_only", classification_confidence=0.9,
            segments=[first, second],
        )


def test_application_event_failure_rolls_back_formal_match_projection(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    match_path = _match(project_root, received)
    match_id = MatchDocument.load(match_path).metadata.match_id
    source = project_root / "transaction.md"
    source.write_text("事务事实。", encoding="utf-8")
    original = journal_module._write_application_update
    calls = 0

    def fail_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("模拟 application event 写入失败")
        return original(*args, **kwargs)

    monkeypatch.setattr(journal_module, "_write_application_update", fail_first)
    record = ingest_journal(
        project_root,
        source_file=source,
        request=_request(received_at=received, target_match_id=match_id, content="事务事实。"),
        auto_apply=True,
    )
    assert record.application_status == "blocked"
    assert "事务事实" not in MatchDocument.load(match_path).sections["prematch-facts"]
    assert (project_root / record.source_path).is_file()


def test_future_complete_fixture_can_create_match_v2(project_root: Path) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    source = project_root / "future.md"
    source.write_text("未来比赛已确认事实。", encoding="utf-8")
    request = _request(received_at=received, content="未来比赛已确认事实。")
    request = request.model_copy(update={
        "fixture_candidate": FixtureCandidate(
            competition_code="KOR-K1", competition="韩K联",
            home_team_id="fc-seoul", home_team="FC首尔",
            away_team_id="ulsan-hd", away_team="蔚山HD",
            kickoff_at=received + timedelta(days=2),
        )
    })
    record = ingest_journal(
        project_root, source_file=source, request=request,
        auto_apply=True, allow_create_match=True,
    )
    assert record.target_type == "match"
    assert record.application_status == "applied"
    matches = list((project_root / "matches").glob("**/*.md"))
    assert len(matches) == 1
    assert MatchDocument.load(matches[0]).metadata.schema_version == 2
    assert journal_status(project_root, match_path=matches[0])[0].entry_id == record.entry_id


def test_ambiguous_input_stays_in_inbox_and_does_not_create_match(project_root: Path) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    source = project_root / "multiple.md"
    source.write_text("包含两场比赛。", encoding="utf-8")
    request = _request(received_at=received, content="包含两场比赛。").model_copy(
        update={"ambiguity_flags": ["multiple-fixtures"]}
    )
    record = ingest_journal(
        project_root, source_file=source, request=request,
        auto_apply=True, allow_create_match=True,
    )
    assert record.target_type == "inbox"
    assert record.application_status == "pending_alignment"
    assert not (project_root / "matches").exists()


def test_attachment_is_archived_and_hash_validated(project_root: Path) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    source = project_root / "source.md"
    source.write_text("赛果截图仅作证据。", encoding="utf-8")
    attachment = project_root / "result.png"
    attachment.write_bytes(b"not-a-decoded-image-but-original-bytes")
    record = ingest_journal(
        project_root,
        source_file=source,
        request=_request(received_at=received, content="赛果截图仅作证据。"),
        attachments=[attachment],
    )
    manifest = (project_root / record.attachments_path).read_text(encoding="utf-8")
    assert "result.png" in manifest
    assert not next(iter(validate_journal(project_root).values()))


def test_ended_complete_bundle_imports_one_legacy_case_without_duplicate_stages(
    project_root: Path,
) -> None:
    received = datetime.now(TZ).replace(microsecond=0)
    source = project_root / "bundle.md"
    source.write_text("赛前分析\n比分 1-0\n赛后复盘\n", encoding="utf-8", newline="\n")
    segments = [
        JournalSegmentV1(
            segment_id="prematch", segment_type="prematch_analysis",
            source_line_start=1, source_line_end=1, observed_at=received - timedelta(days=2),
            data_cutoff_at=received - timedelta(days=2), classification_confidence=0.98,
            normalized_markdown="赛前分析",
        ),
        JournalSegmentV1(
            segment_id="result", segment_type="result",
            source_line_start=2, source_line_end=2, observed_at=received - timedelta(days=1),
            classification_confidence=0.98, normalized_markdown="比分 1-0",
            payload={"score": "1-0", "source": "用户提供的赛果材料"},
        ),
        JournalSegmentV1(
            segment_id="review", segment_type="postmatch_review",
            source_line_start=3, source_line_end=3, observed_at=received,
            classification_confidence=0.98, normalized_markdown="赛后复盘",
        ),
    ]
    request = JournalIngestRequestV1(
        capture_mode="canonical_chat_text", received_at=received, actor="lcz",
        user_intent="store_only", classification_confidence=0.98,
        fixture_candidate=FixtureCandidate(
            competition_code="KOR-K1", competition="韩K联",
            home_team_id="fc-seoul", home_team="FC首尔",
            away_team_id="ulsan-hd", away_team="蔚山HD",
            kickoff_at=received - timedelta(days=1, hours=2),
        ),
        segments=segments,
    )
    record = ingest_journal(
        project_root, source_file=source, request=request,
        auto_apply=True, allow_create_match=True,
    )
    cases = latest_cases(project_root)
    assert record.target_type == "legacy_case"
    assert record.application_status == "applied"
    assert len(cases) == 1
    case = next(iter(cases.values()))
    assert case.case_revision == 1
    assert len(case.material_stages) == 3
    assert {item.source_path for item in case.material_stages} == {record.source_path}

    followup = project_root / "followup.md"
    followup.write_text("临场补充\n追加复盘\n", encoding="utf-8", newline="\n")
    followup_request = JournalIngestRequestV1(
        capture_mode="canonical_chat_text",
        received_at=received + timedelta(seconds=1),
        actor="lcz",
        user_intent="store_only",
        classification_confidence=0.98,
        fixture_candidate=request.fixture_candidate,
        segments=[
            JournalSegmentV1(
                segment_id="live-followup", segment_type="live_update",
                source_line_start=1, source_line_end=1, observed_at=received,
                classification_confidence=0.98, normalized_markdown="临场补充",
            ),
            JournalSegmentV1(
                segment_id="review-followup", segment_type="postmatch_review",
                source_line_start=2, source_line_end=2, observed_at=received,
                classification_confidence=0.98, normalized_markdown="追加复盘",
            ),
        ],
    )
    followup_record = ingest_journal(
        project_root, source_file=followup, request=followup_request, auto_apply=True
    )
    updated_case = next(iter(latest_cases(project_root).values()))
    assert followup_record.application_status == "applied"
    assert updated_case.case_revision == 2
    assert len(updated_case.material_stages) == 5
