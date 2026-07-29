from __future__ import annotations

from pathlib import Path

from odds_journal.markdown import MatchDocument
from odds_journal.models import PrimaryMarket, Selection
from odds_journal.services import create_match, lock_match, parse_datetime
from odds_journal.validation import validate_document
from odds_journal.aliases import AliasStore


def prepare_match(root: Path) -> Path:
    path = create_match(
        root,
        kickoff=parse_datetime("2026-07-30T18:30:00+08:00"),
        timezone="Asia/Shanghai",
        competition_code="KOR-K1",
        competition="韩K联",
        home_team_id="fc-seoul",
        home_team="FC首尔",
        away_team_id="ulsan-hd",
        away_team="蔚山HD",
    )
    document = MatchDocument.load(path)
    document.replace_section("prematch-facts", "## 一、赛前事实\n\n主队近期状态稳定，数据采集时间明确。")
    document.replace_section("prematch-reasoning", "## 二、赛前推演\n\n盘口变化支持下盘，同时保留主队方向反证。")
    document.replace_section(
        "prematch-locked",
        "## 三、赛前最终结论\n\n主线为客队受让，若临场升至一球则放弃。",
    )
    document.save()
    return path


def test_hash_covers_all_three_prematch_sections(project_root: Path) -> None:
    path = prepare_match(project_root)
    lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.AWAY_HANDICAP,
        secondary=Selection.DRAW,
        confidence=0.62,
    )
    locked = MatchDocument.load(path)
    assert validate_document(locked, AliasStore(project_root)) == []

    locked.replace_section("prematch-facts", locked.sections["prematch-facts"] + "\n赛后偷偷改动。")
    locked.save()
    changed = MatchDocument.load(path)
    assert any("哈希校验失败" in error for error in validate_document(changed, AliasStore(project_root)))


def test_unedited_template_cannot_be_locked(project_root: Path) -> None:
    path = create_match(
        project_root,
        kickoff=parse_datetime("2026-07-31T18:30:00+08:00"),
        timezone="Asia/Shanghai",
        competition_code="KOR-K1",
        competition="韩K联",
        home_team_id="fc-seoul",
        home_team="FC首尔",
        away_team_id="ulsan-hd",
        away_team="蔚山HD",
    )
    try:
        lock_match(
            path,
            at=parse_datetime("2026-07-31T18:00:00+08:00"),
            market=PrimaryMarket.HANDICAP,
            selection=Selection.AWAY_HANDICAP,
            secondary=None,
            confidence=0.5,
        )
    except ValueError as exc:
        assert "待填写标记" in str(exc)
    else:
        raise AssertionError("空模板不应允许锁定")


def test_tampered_locked_match_cannot_transition(project_root: Path) -> None:
    from odds_journal.models import HandicapResult, Result1X2
    from odds_journal.services import finish_match

    path = prepare_match(project_root)
    lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.AWAY_HANDICAP,
        secondary=None,
        confidence=0.6,
    )
    document = MatchDocument.load(path)
    document.replace_section("prematch-reasoning", document.sections["prematch-reasoning"] + "\n改写")
    document.save()
    try:
        finish_match(
            path,
            score="1-1",
            result_1x2=Result1X2.DRAW,
            handicap_result=HandicapResult.AWAY_HANDICAP,
            recorded_at=parse_datetime("2026-07-30T21:00:00+08:00"),
            key_events=None,
        )
    except ValueError as exc:
        assert "哈希校验失败" in str(exc)
    else:
        raise AssertionError("被改写的锁定比赛不应进入 finished")

