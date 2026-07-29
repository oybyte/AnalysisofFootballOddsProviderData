from __future__ import annotations

from pathlib import Path

from odds_journal.markdown import MatchDocument
from odds_journal.models import EvaluationValue, MatchStatus, PrimaryMarket, Selection
from odds_journal.services import finish_match, lock_match, parse_datetime, review_match
from odds_journal.validation import validate_document
from odds_journal.aliases import AliasStore

from .test_markdown_lock import prepare_match


def test_complete_match_lifecycle(project_root: Path) -> None:
    path = prepare_match(project_root)
    lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.AWAY_HANDICAP,
        secondary=Selection.DRAW,
        confidence=0.62,
    )
    finish_match(
        path,
        score="1-1",
        result_1x2="draw",
        handicap_result="away_handicap",
        recorded_at=parse_datetime("2026-07-30T21:00:00+08:00"),
        key_events="无红牌",
    )
    document = MatchDocument.load(path)
    document.replace_section(
        "postmatch-review",
        "## 六、赛后复盘\n\n主线判断正确，但对主队进攻权重估计过高；新增一条平局反例。",
    )
    document.save()
    review_match(
        path,
        reviewed_at=parse_datetime("2026-07-30T22:00:00+08:00"),
        primary=EvaluationValue.CORRECT,
        handicap=EvaluationValue.CORRECT,
        total_goals_range=EvaluationValue.CORRECT,
        score_range=EvaluationValue.PARTIAL,
        confidence_calibration=EvaluationValue.PARTIAL,
        changed_main=False,
    )
    reviewed = MatchDocument.load(path)
    assert MatchStatus(reviewed.metadata.status) == MatchStatus.REVIEWED
    assert validate_document(reviewed, AliasStore(project_root)) == []

