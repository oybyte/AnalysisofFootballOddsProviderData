from __future__ import annotations

from pathlib import Path

from odds_journal.analysis_context import set_analysis_content
from odds_journal.indexing import build_index, search_index
from odds_journal.markdown import MatchDocument
from odds_journal.models import EvaluationValue, PrimaryMarket, Selection
from odds_journal.services import finish_match, lock_match, parse_datetime, review_match

from .test_markdown_lock import prepare_match


def reviewed_match(root: Path) -> Path:
    path = prepare_match(root)
    document = MatchDocument.load(path)
    document.replace_section(
        "prematch-reasoning",
        set_analysis_content(
            document.sections["prematch-reasoning"],
            "升盘降水是候选信号，但仍需反向证据。",
        ),
    )
    document.save()
    lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.AWAY_HANDICAP,
        secondary=None,
        confidence=0.6,
    )
    finish_match(
        path,
        score="1-1",
        result_1x2="draw",
        handicap_result="away_handicap",
        recorded_at=parse_datetime("2026-07-30T21:00:00+08:00"),
        key_events="终场独特词",
    )
    document = MatchDocument.load(path)
    document.replace_section("postmatch-review", "## 六、赛后复盘\n\n终场独特词只应在赛后时间可见，并记录规则反例。")
    document.save()
    review_match(
        path,
        reviewed_at=parse_datetime("2026-07-30T22:00:00+08:00"),
        primary=EvaluationValue.CORRECT,
        handicap=EvaluationValue.CORRECT,
        total_goals_range=EvaluationValue.PARTIAL,
        score_range=EvaluationValue.PARTIAL,
        confidence_calibration=EvaluationValue.CORRECT,
        changed_main=False,
    )
    return path


def test_chinese_short_terms_and_time_filter(project_root: Path) -> None:
    path = reviewed_match(project_root)
    _, count = build_index(project_root)
    assert count > 0
    assert search_index(project_root, "升盘")

    before_result = search_index(
        project_root,
        "终场独特词",
        as_of=parse_datetime("2026-07-30T18:00:00+08:00"),
    )
    assert before_result == []
    after_result = search_index(
        project_root,
        "终场独特词",
        as_of=parse_datetime("2026-07-30T23:00:00+08:00"),
    )
    assert after_result
    match_id = MatchDocument.load(path).metadata.match_id
    assert search_index(project_root, "终场独特词", exclude_match_id=match_id) == []
