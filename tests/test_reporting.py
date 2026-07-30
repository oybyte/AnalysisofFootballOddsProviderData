from __future__ import annotations

from pathlib import Path

from odds_journal.reporting import build_match_index, build_statistics
from odds_journal.exporting import export_matches
from odds_journal.services import create_match, parse_datetime, void_match

from .test_indexing import reviewed_match


def test_empty_statistics_report_has_explicit_empty_states(project_root: Path) -> None:
    markdown_path, _, payload = build_statistics(project_root)
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["reviewed_matches"] == 0
    assert "暂无可统计比赛。" in markdown
    assert "暂无可统计维度。" in markdown


def test_reports_are_rebuildable(project_root: Path) -> None:
    reviewed_match(project_root)
    void_path = create_match(
        project_root,
        kickoff=parse_datetime("2026-08-01T18:30:00+08:00"),
        timezone="Asia/Shanghai",
        competition_code="KOR-K1",
        competition="韩K联",
        home_team_id="fc-seoul",
        home_team="FC首尔",
        away_team_id="ulsan-hd",
        away_team="蔚山HD",
    )
    void_match(void_path, reason="比赛延期")
    exported, diagnostics = export_matches(project_root)
    index_path = build_match_index(project_root)
    markdown_path, json_path, payload = build_statistics(project_root)
    assert index_path.exists()
    assert markdown_path.exists()
    assert json_path.exists()
    assert payload["reviewed_matches"] == 1
    assert payload["excluded"]["void"] == 1
    assert exported == 2
    assert diagnostics == []
    assert "样本不足" in markdown_path.read_text(encoding="utf-8")


def test_export_replaces_directory_and_removes_stale_json(project_root: Path) -> None:
    reviewed_match(project_root)
    exported, diagnostics = export_matches(project_root)
    assert exported == 1 and diagnostics == []
    stale = project_root / "data/matches/deleted-match.json"
    stale.write_text("{}\n", encoding="utf-8")
    export_matches(project_root)
    assert not stale.exists()
