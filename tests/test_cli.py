from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from odds_journal.cli import app
from odds_journal.indexing import build_index


def test_cli_can_create_and_validate_match(project_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(project_root)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "new",
            "--kickoff",
            "2026-07-30T18:30:00+08:00",
            "--competition-code",
            "KOR-K1",
            "--competition",
            "韩K联",
            "--home-id",
            "fc-seoul",
            "--home",
            "FC首尔",
            "--away-id",
            "ulsan-hd",
            "--away",
            "蔚山HD",
        ],
    )
    assert result.exit_code == 0, result.output
    assert list((project_root / "matches" / "2026" / "07").glob("*.md"))
    validated = runner.invoke(app, ["validate", "--all"])
    assert validated.exit_code == 0, validated.output


def test_cli_rejects_unknown_alias(project_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(
        app,
        [
            "new",
            "--kickoff",
            "2026-07-30T18:30:00+08:00",
            "--competition-code",
            "UNKNOWN",
            "--competition",
            "未知联赛",
            "--home-id",
            "fc-seoul",
            "--home",
            "FC首尔",
            "--away-id",
            "ulsan-hd",
            "--away",
            "蔚山HD",
        ],
    )
    assert result.exit_code == 1
    assert "未知联赛代码" in result.output


def test_cli_json_output_handles_non_gbk_characters(project_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(project_root)
    knowledge = project_root / "knowledge"
    knowledge.mkdir(exist_ok=True)
    (knowledge / "warning.md").write_text(
        "---\ndocument_id: warning\ndocument_type: concept\n"
        "reliability: established\neffective_at: 2026-07-29T12:00:00+08:00\n---\n"
        "升盘提示 ⚠ 风险\n",
        encoding="utf-8",
    )
    build_index(project_root)
    result = CliRunner().invoke(app, ["search", "升盘", "--json"])
    assert result.exit_code == 0, result.output
    assert "升盘提示" in result.output
