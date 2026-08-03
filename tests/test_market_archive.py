from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from typer.testing import CliRunner

from odds_journal.aliases import AliasStore
from odds_journal.journal import FixtureCandidate
from odds_journal.market_archive import (
    MacauTimelineNodeV1,
    MarketArchiveDraftV1,
    MarketArchiveError,
    MarketArchiveRowV1,
    archive_market_draft,
    prepare_market_archive,
    resolve_fixture,
)
from odds_journal.models import MarketType, SnapshotPhase
from odds_journal.markdown import MatchDocument
from odds_journal.cli import app
from odds_journal.services import create_match


TZ = ZoneInfo("Asia/Shanghai")


def _draft(*, macau_timeline=None, rows=None, competition="测试联赛") -> MarketArchiveDraftV1:
    return MarketArchiveDraftV1(
        fixture=FixtureCandidate(
            competition=competition,
            home_team="测试主队",
            away_team="测试客队",
            kickoff_at=datetime(2027, 8, 4, 0, 0, tzinfo=TZ),
        ),
        captured_at=datetime(2027, 8, 3, 13, 13, 6, tzinfo=TZ),
        screenshots=["market.png"],
        rows=rows or [],
        macau_timeline=macau_timeline or [],
    )


def _row(*, market: MarketType, provider_id: str, provider_name: str, phase: SnapshotPhase, values: dict[str, str]) -> MarketArchiveRowV1:
    return MarketArchiveRowV1(
        market=market, provider_id=provider_id, provider_name=provider_name, phase=phase,
        raw_values=values, source_screenshot="market.png", row_ordinal=1,
    )


def test_preview_renders_fixed_sections_and_macau_timeline_is_authoritative(project_root: Path) -> None:
    draft = _draft(
        rows=[_row(market=MarketType.ASIAN_HANDICAP, provider_id="macau", provider_name="澳*", phase=SnapshotPhase.OPENING, values={"home_water": "0.99", "line": "-0/0.5", "away_water": "0.80"})],
        macau_timeline=[
            MacauTimelineNodeV1(displayed_at="08-03 10:01", home_water="0.83", line="-0.5", away_water="0.95", source_screenshot="market.png", row_ordinal=3),
            MacauTimelineNodeV1(displayed_at="07-28 20:36", home_water="0.98", line="-0/0.5", away_water="0.80", source_screenshot="market.png", row_ordinal=1),
            MacauTimelineNodeV1(displayed_at="08-01 07:59", home_water="1.03", line="-0/0.5", away_water="0.75", source_screenshot="market.png", row_ordinal=2),
        ],
    )

    preview = prepare_market_archive(project_root, draft)

    assert "## 澳门让球走势" in preview.rendered_markdown
    assert preview.rendered_markdown.index("2027-07-28 20:36") < preview.rendered_markdown.index("2027-08-01 07:59")
    macau = [item for item in preview.snapshots if item.provider_id == "macau"]
    assert [item.phase for item in macau] == [SnapshotPhase.OPENING, SnapshotPhase.MID, SnapshotPhase.LATE]
    assert macau[-1].raw_values["home_water"] == "0.83"


def test_static_macau_row_is_used_only_when_no_timeline(project_root: Path) -> None:
    draft = _draft(rows=[_row(
        market=MarketType.ASIAN_HANDICAP, provider_id="macau", provider_name="澳*", phase=SnapshotPhase.LATE,
        values={"home_water": "0.83", "line": "-0.5", "away_water": "0.95"},
    )])
    preview = prepare_market_archive(project_root, draft)

    assert "未提供澳门详细走势" in preview.rendered_markdown
    assert len([item for item in preview.snapshots if item.provider_id == "macau"]) == 1


def test_invalid_rows_are_kept_out_of_snapshots_and_kelly_aggregate_is_distinct(project_root: Path) -> None:
    draft = _draft(rows=[
        _row(market=MarketType.KELLY_INDEX, provider_id="kelly-aggregate-6avg", provider_name="6家平均", phase=SnapshotPhase.LATE, values={"home_win": "0.92", "draw": "0.91", "away_win": "0.93"}),
        _row(market=MarketType.TOTAL_GOALS, provider_id="book", provider_name="Book", phase=SnapshotPhase.LATE, values={"over_water": "不可读", "line": "2.5", "under_water": "0.90"}),
    ])
    preview = prepare_market_archive(project_root, draft)

    assert [item.provider_id for item in preview.snapshots] == ["kelly-aggregate-6avg"]
    assert any("Book/total_goals/late" in item for item in preview.missing_items)


def test_league_is_inferred_only_from_both_team_history(project_root: Path) -> None:
    aliases = AliasStore(project_root)
    aliases.add_team("team-home", "历史主队", [])
    aliases.add_team("team-away", "历史客队", [])
    aliases.add_competition("league-one", "联赛一", [])
    create_match(project_root, kickoff=datetime(2026, 6, 1, tzinfo=TZ), timezone="Asia/Shanghai", competition_code="league-one", competition="联赛一", home_team_id="team-home", home_team="历史主队", away_team_id="team-away", away_team="历史客队")

    fixture, resolution = resolve_fixture(project_root, FixtureCandidate(home_team="历史主队", away_team="历史客队", kickoff_at=datetime(2027, 6, 1, tzinfo=TZ)))
    assert resolution.status == "inferred"
    assert fixture.competition_code == "league-one"
    assert resolution.source_ids

    _, unresolved = resolve_fixture(project_root, FixtureCandidate(home_team="历史主队", away_team="陌生客队", kickoff_at=datetime(2027, 6, 1, tzinfo=TZ)))
    assert unresolved.status == "unresolved"


def test_archive_requires_declared_attachments_and_is_idempotent(project_root: Path) -> None:
    image = project_root / "market.png"
    image.write_bytes(b"not-an-image-but-an-immutable-user-attachment")
    draft = _draft(rows=[_row(
        market=MarketType.EUROPEAN_ODDS, provider_id="book", provider_name="Book", phase=SnapshotPhase.OPENING,
        values={"home_win": "2.80", "draw": "3.65", "away_win": "2.03"},
    )])
    with pytest.raises(MarketArchiveError, match="原始截图"):
        archive_market_draft(project_root, draft, [])

    first = archive_market_draft(project_root, draft, [image])
    second = archive_market_draft(project_root, draft, [image])
    assert first.target_type == "match"
    assert second.entry_id == first.entry_id
    assert first.snapshot_count == 1
    assert first.attachment_mappings[0].sha256


def test_ambiguous_identity_archives_to_inbox_without_creating_match(project_root: Path) -> None:
    image = project_root / "market.png"
    image.write_bytes(b"raw")
    draft = _draft(competition=None, rows=[_row(
        market=MarketType.EUROPEAN_ODDS, provider_id="book", provider_name="Book", phase=SnapshotPhase.OPENING,
        values={"home_win": "2.80", "draw": "3.65", "away_win": "2.03"},
    )])
    result = archive_market_draft(project_root, draft, [image])
    assert result.target_type == "inbox"
    assert result.journal is None
    assert not list((project_root / "matches").glob("**/*.md"))


def test_user_supplied_reserved_marker_is_escaped_before_match_projection(project_root: Path) -> None:
    image = project_root / "market.png"
    image.write_bytes(b"raw")
    draft = _draft(
        rows=[_row(market=MarketType.EUROPEAN_ODDS, provider_id="book", provider_name="Book", phase=SnapshotPhase.OPENING, values={"home_win": "2.80", "draw": "3.65", "away_win": "2.03"})],
    )
    draft.missing_items.append("<!-- section:result -->")
    archive_market_draft(project_root, draft, [image])
    document = MatchDocument.load(next((project_root / "matches").glob("**/*.md")))
    assert "&lt;!-- section:result -->" in document.sections["prematch-facts"]


def test_preview_cli_is_read_only(project_root: Path, monkeypatch) -> None:
    draft = _draft(rows=[_row(
        market=MarketType.EUROPEAN_ODDS, provider_id="book", provider_name="Book", phase=SnapshotPhase.OPENING,
        values={"home_win": "2.80", "draw": "3.65", "away_win": "2.03"},
    )])
    source = project_root / "draft.yml"
    source.write_text(yaml.safe_dump(draft.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(app, ["journal", "market-archive", "preview", "--file", str(source)])
    assert result.exit_code == 0, result.output
    assert "## 凯利指数" in result.output
    assert not (project_root / "raw").exists()
