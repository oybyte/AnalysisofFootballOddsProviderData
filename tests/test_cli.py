from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from typer.testing import CliRunner
import yaml

from odds_journal.cli import app
from odds_journal.indexing import build_index
from odds_journal.journal import (
    CaptureMode,
    FixtureCandidate,
    JournalIngestRequestV1,
    JournalSegmentV1,
    UserIntent,
)
from odds_journal.markdown import MatchDocument


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


def test_cli_journal_new_append_finish_and_review_return_stable_json(project_root: Path, monkeypatch) -> None:
    monkeypatch.chdir(project_root)
    runner = CliRunner()
    received = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)

    def invoke(operation: str, name: str, content: str, segment_type: str, *, target_match_id: str | None = None):
        source = project_root / f"{name}.md"
        source.write_text(content, encoding="utf-8")
        request = JournalIngestRequestV1(
            capture_mode=CaptureMode.CANONICAL_CHAT_TEXT,
            received_at=received + timedelta(seconds=len(name)),
            actor="lcz",
            user_intent=UserIntent.STORE_ONLY,
            target_match_id=target_match_id,
            classification_confidence=0.96,
            fixture_candidate=FixtureCandidate(
                competition="命令测试联赛",
                home_team="命令测试主队",
                away_team="命令测试客队",
                kickoff_at=received + timedelta(days=1),
            ),
            segments=[JournalSegmentV1(
                segment_id=f"{name}-segment",
                segment_type=segment_type,
                source_line_start=1,
                source_line_end=1,
                observed_at=received,
                classification_confidence=0.96,
                normalized_markdown=content,
            )],
        )
        request_path = project_root / f"{name}.yml"
        request_path.write_text(
            yaml.safe_dump(request.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        result = runner.invoke(app, ["journal", operation, "--source-file", str(source), "--request-file", str(request_path), "--json"])
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    created = invoke("new", "new", "首次事实", "prematch_facts")
    assert created["requested_operation"] == "new"
    assert created["effective_operation"] == "new"
    assert created["entry"]["target_type"] == "match"

    path = next((project_root / "matches").glob("**/*.md"))
    match_id = MatchDocument.load(path).metadata.match_id
    appended = invoke("append", "append", "后续赛前分析", "prematch_analysis", target_match_id=match_id)
    assert appended["requested_operation"] == "append"
    assert appended["entry"]["target_id"] == match_id
    assert appended["entry"]["application_status"] == "pending_in_target"

    finished = invoke("finish", "finish", "赛后复盘原文", "postmatch_review", target_match_id=match_id)
    assert finished["requested_operation"] == "finish"
    assert finished["effective_operation"] == "finish"
    assert finished["entry"]["target_id"] == match_id
    assert finished["entry"]["application_status"] == "pending_in_target"

    legacy = invoke("review", "review", "旧入口赛后复盘原文", "postmatch_review", target_match_id=match_id)
    assert legacy["requested_operation"] == "review"
    assert legacy["effective_operation"] == "finish"
    assert legacy["deprecation_notice"] == "请改用 journal finish；review 保留为兼容别名"
    assert legacy["entry"]["target_id"] == finished["entry"]["target_id"]
    assert legacy["entry"]["application_status"] == finished["entry"]["application_status"]

    legacy_human = runner.invoke(
        app,
        ["journal", "review", "--source-file", str(project_root / "review.md"), "--request-file", str(project_root / "review.yml")],
    )
    assert legacy_human.exit_code == 0, legacy_human.output
    assert "请改用 journal finish；review 保留为兼容别名" in legacy_human.output
