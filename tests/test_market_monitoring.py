from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from odds_journal.journal import FixtureCandidate
from odds_journal.market_archive import (
    MarketArchiveDraftV1,
    MarketArchiveError,
    MarketArchiveRowV1,
    archive_market_draft,
    prepare_market_comparison,
)
from odds_journal.market_monitoring import (
    EvaluatorType,
    PrematchRiskWatchlistDraftV1,
    PrematchRiskWatchlistV1,
    RiskConditionV1,
    RiskStatus,
    compare_snapshots,
    evaluate_watchlist,
    load_watchlist,
    prepare_watchlist,
)
from odds_journal.markdown import MatchDocument
from odds_journal.models import MarketSnapshot, MarketType, OddsFormat, SnapshotPhase

from .test_scenarios import _prepared_v2_match


TZ = ZoneInfo("Asia/Shanghai")


def _row(market: MarketType, provider: str, phase: SnapshotPhase, values: dict[str, str], ordinal: int = 1) -> MarketArchiveRowV1:
    return MarketArchiveRowV1(
        market=market,
        provider_id=provider,
        provider_name=provider,
        phase=phase,
        raw_values=values,
        source_screenshot="market.png",
        row_ordinal=ordinal,
    )


def _draft(captured_at: datetime, rows: list[MarketArchiveRowV1]) -> MarketArchiveDraftV1:
    return MarketArchiveDraftV1(
        fixture=FixtureCandidate(
            competition="测试联赛",
            home_team="测试主队",
            away_team="测试客队",
            kickoff_at=datetime(2027, 8, 5, 2, 0, tzinfo=TZ),
        ),
        captured_at=captured_at,
        screenshots=["market.png"],
        rows=rows,
    )


def _euro_snapshot(identity: str, value: float, captured_at: datetime) -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id=identity,
        market=MarketType.EUROPEAN_ODDS,
        phase=SnapshotPhase.LATE,
        captured_at=captured_at,
        provider_id="macau",
        source_ref=f"test:{identity}",
        odds_format=OddsFormat.DECIMAL,
        raw_values={"home_win": "3.10", "draw": "3.00", "away_win": f"{value:.2f}"},
        normalized_values={"home_win": 3.10, "draw": 3.00, "away_win": value},
    )


def _macau_timeline_snapshot(
    identity: str,
    captured_at: datetime,
    *,
    phase: SnapshotPhase,
    home_water: str,
    line: str = "-0/0.5",
    away_water: str = "0.96",
) -> MarketSnapshot:
    return MarketSnapshot(
        snapshot_id=identity,
        market=MarketType.ASIAN_HANDICAP,
        phase=phase,
        captured_at=captured_at,
        provider_id="macau",
        source_ref=f"test:{identity}",
        odds_format=OddsFormat.HONG_KONG,
        raw_values={"home_water": home_water, "line": line, "away_water": away_water},
        normalized_values={
            "home_water": float(home_water),
            "line": -0.25 if line == "-0/0.5" else float(line),
            "away_water": float(away_water),
        },
    )


def _watchlist() -> PrematchRiskWatchlistV1:
    return PrematchRiskWatchlistV1(
        watchlist_id="watchlist-test-1",
        match_id="match-test",
        source_text="若客胜赔率突破2.50且继续上行。",
        conditions=[RiskConditionV1(
            condition_id="away-above-250",
            original_risk_text="若客胜赔率突破2.50且继续上行。",
            trigger_text="客胜赔率突破2.50且继续上行",
            consequence_text="使用原赛前风险说明",
            evaluator_type=EvaluatorType.MARKET_AND_TREND,
            market=MarketType.EUROPEAN_ODDS,
            provider_id="macau",
            field="away_win",
            operator=">",
            threshold=2.50,
            required_trend="rising",
            source_location="后市观测清单/风险预警信号",
        )],
        created_at=datetime(2027, 8, 4, 12, 0, tzinfo=TZ),
        data_cutoff_at=datetime(2027, 8, 4, 12, 0, tzinfo=TZ),
        source_analysis_receipt_sha256="1" * 64,
        source_section_sha256="2" * 64,
        watchlist_sha256="3" * 64,
    )


def test_explicit_baseline_has_priority_and_same_line_water_delta(project_root: Path) -> None:
    baseline = _draft(datetime(2027, 8, 4, 12, 0, tzinfo=TZ), [
        _row(MarketType.ASIAN_HANDICAP, "macau", SnapshotPhase.LATE, {"home_water": "0.82", "line": "-0/0.5", "away_water": "0.96"}),
    ])
    current = _draft(datetime(2027, 8, 4, 16, 0, tzinfo=TZ), [
        _row(MarketType.ASIAN_HANDICAP, "macau", SnapshotPhase.LATE, {"home_water": "0.88", "line": "-0/0.5", "away_water": "0.90"}),
    ])

    result = prepare_market_comparison(project_root, current, baseline_draft=baseline)

    assert result.baseline_source == "session_draft"
    home = next(item for item in result.change_events if item.field == "home_water")
    assert home.numeric_delta == pytest.approx(0.06)
    assert home.comparable is True


def test_cross_line_water_is_incomparable_and_missing_provider_is_not_unchanged(project_root: Path) -> None:
    baseline = _draft(datetime(2027, 8, 4, 12, 0, tzinfo=TZ), [
        _row(MarketType.ASIAN_HANDICAP, "macau", SnapshotPhase.LATE, {"home_water": "0.82", "line": "-0/0.5", "away_water": "0.96"}),
        _row(MarketType.EUROPEAN_ODDS, "bet365", SnapshotPhase.LATE, {"home_win": "2.00", "draw": "3.20", "away_win": "3.40"}, 2),
    ])
    current = _draft(datetime(2027, 8, 4, 16, 0, tzinfo=TZ), [
        _row(MarketType.ASIAN_HANDICAP, "macau", SnapshotPhase.LATE, {"home_water": "0.88", "line": "-0.5", "away_water": "0.90"}),
    ])

    result = prepare_market_comparison(project_root, current, baseline_draft=baseline)

    home = next(item for item in result.change_events if item.provider_id == "macau" and item.field == "home_water")
    assert home.change_type == "不可比较" and home.numeric_delta is None
    missing = [item for item in result.change_events if item.provider_id == "bet365"]
    assert missing and all(item.change_type == "本次未显示" for item in missing)


def test_macau_timeline_only_reports_new_time_nodes() -> None:
    t1 = datetime(2027, 8, 4, 10, 0, tzinfo=TZ)
    t2 = datetime(2027, 8, 4, 12, 0, tzinfo=TZ)
    t3 = datetime(2027, 8, 4, 14, 0, tzinfo=TZ)
    baseline = [
        _macau_timeline_snapshot("macau-t1", t1, phase=SnapshotPhase.OPENING, home_water="0.82"),
        _macau_timeline_snapshot("macau-t2", t2, phase=SnapshotPhase.MID, home_water="0.84"),
    ]
    current = baseline + [
        _macau_timeline_snapshot("macau-t3", t3, phase=SnapshotPhase.LATE, home_water="0.86"),
    ]

    events = compare_snapshots(current, baseline)

    assert len(events) == 3
    assert {item.current_snapshot_id for item in events} == {"macau-t3"}
    assert {item.change_type for item in events} == {"新增"}


def test_macau_timeline_same_time_different_value_is_conflict() -> None:
    t1 = datetime(2027, 8, 4, 10, 0, tzinfo=TZ)
    t2 = datetime(2027, 8, 4, 12, 0, tzinfo=TZ)
    baseline = [
        _macau_timeline_snapshot("macau-old", t1, phase=SnapshotPhase.OPENING, home_water="0.82"),
    ]
    current = [
        _macau_timeline_snapshot("macau-revised", t1, phase=SnapshotPhase.OPENING, home_water="0.83"),
        _macau_timeline_snapshot("macau-new", t2, phase=SnapshotPhase.LATE, home_water="0.84"),
    ]

    events = compare_snapshots(current, baseline)

    conflict = [item for item in events if item.current_snapshot_id == "macau-revised"]
    assert len(conflict) == 3
    assert {item.change_type for item in conflict} == {"来源冲突"}
    added = [item for item in events if item.current_snapshot_id == "macau-new"]
    assert len(added) == 3
    assert {item.change_type for item in added} == {"新增"}


def test_multiple_macau_mid_nodes_are_not_collapsed_into_conflict() -> None:
    t1 = datetime(2027, 8, 4, 10, 0, tzinfo=TZ)
    t2 = datetime(2027, 8, 4, 11, 0, tzinfo=TZ)
    t3 = datetime(2027, 8, 4, 12, 0, tzinfo=TZ)
    t4 = datetime(2027, 8, 4, 13, 0, tzinfo=TZ)
    baseline = [
        _macau_timeline_snapshot("macau-t1", t1, phase=SnapshotPhase.OPENING, home_water="0.82"),
        _macau_timeline_snapshot("macau-t2", t2, phase=SnapshotPhase.MID, home_water="0.83"),
        _macau_timeline_snapshot("macau-t3", t3, phase=SnapshotPhase.MID, home_water="0.84"),
    ]
    current = baseline + [
        _macau_timeline_snapshot("macau-t4", t4, phase=SnapshotPhase.LATE, home_water="0.85"),
    ]

    events = compare_snapshots(current, baseline)

    assert len(events) == 3
    assert all(item.current_snapshot_id == "macau-t4" for item in events)
    assert all(item.change_type != "来源冲突" for item in events)


def test_archived_batch_is_used_when_session_baseline_is_absent(project_root: Path) -> None:
    image = project_root / "market.png"
    image.write_bytes(b"immutable")
    baseline = _draft(datetime(2027, 8, 4, 12, 0, tzinfo=TZ), [
        _row(MarketType.EUROPEAN_ODDS, "macau", SnapshotPhase.LATE, {"home_win": "3.10", "draw": "3.00", "away_win": "2.40"}),
    ])
    archive_market_draft(project_root, baseline, [image])
    current = _draft(datetime(2027, 8, 4, 16, 0, tzinfo=TZ), [
        _row(MarketType.EUROPEAN_ODDS, "macau", SnapshotPhase.LATE, {"home_win": "3.10", "draw": "3.00", "away_win": "2.48"}),
    ])

    result = prepare_market_comparison(project_root, current)

    assert result.baseline_source == "archived_batch"
    assert result.comparison_status == "compared"


def test_baseline_must_be_same_fixture_and_earlier(project_root: Path) -> None:
    current = _draft(datetime(2027, 8, 4, 16, 0, tzinfo=TZ), [])
    future = _draft(datetime(2027, 8, 4, 17, 0, tzinfo=TZ), [])
    with pytest.raises(MarketArchiveError, match="早于"):
        prepare_market_comparison(project_root, current, baseline_draft=future)


@pytest.mark.parametrize(
    ("current_value", "expected"),
    [(2.51, RiskStatus.TRIGGERED), (2.50, RiskStatus.NEAR), (2.46, RiskStatus.NEAR), (2.44, RiskStatus.NOT_TRIGGERED)],
)
def test_strict_risk_threshold_and_fixed_near_band(current_value: float, expected: RiskStatus) -> None:
    baseline = [_euro_snapshot("baseline", 2.40, datetime(2027, 8, 4, 12, 0, tzinfo=TZ))]
    current = [_euro_snapshot("current", current_value, datetime(2027, 8, 4, 16, 0, tzinfo=TZ))]

    result = evaluate_watchlist(
        _watchlist(), current, baseline,
        captured_at=datetime(2027, 8, 4, 16, 0, tzinfo=TZ),
        kickoff_at=datetime(2027, 8, 5, 2, 0, tzinfo=TZ),
    )

    assert result[0].status == expected


def test_wrong_trend_and_post_kickoff_do_not_trigger() -> None:
    baseline = [_euro_snapshot("baseline", 2.60, datetime(2027, 8, 4, 12, 0, tzinfo=TZ))]
    current = [_euro_snapshot("current", 2.55, datetime(2027, 8, 4, 16, 0, tzinfo=TZ))]
    before = evaluate_watchlist(
        _watchlist(), current, baseline,
        captured_at=datetime(2027, 8, 4, 16, 0, tzinfo=TZ),
        kickoff_at=datetime(2027, 8, 5, 2, 0, tzinfo=TZ),
    )
    after = evaluate_watchlist(
        _watchlist(), current, baseline,
        captured_at=datetime(2027, 8, 5, 2, 0, tzinfo=TZ),
        kickoff_at=datetime(2027, 8, 5, 2, 0, tzinfo=TZ),
    )

    assert before[0].status == RiskStatus.NOT_TRIGGERED
    assert after[0].status == RiskStatus.UNKNOWN


def test_conflicted_baseline_cannot_trigger_trend_condition() -> None:
    observed_at = datetime(2027, 8, 4, 12, 0, tzinfo=TZ)
    baseline = [
        _euro_snapshot("baseline-a", 2.40, observed_at),
        _euro_snapshot("baseline-b", 2.45, observed_at),
    ]
    current = [_euro_snapshot("current", 2.51, datetime(2027, 8, 4, 16, 0, tzinfo=TZ))]

    result = evaluate_watchlist(
        _watchlist(), current, baseline,
        captured_at=datetime(2027, 8, 4, 16, 0, tzinfo=TZ),
        kickoff_at=datetime(2027, 8, 5, 2, 0, tzinfo=TZ),
    )

    assert result[0].status == RiskStatus.UNKNOWN
    assert "基线存在来源冲突" in result[0].evidence


def test_manual_condition_is_always_unknown_from_market_screenshots() -> None:
    watchlist = _watchlist().model_copy(update={"conditions": [RiskConditionV1(
        condition_id="early-goal",
        original_risk_text="若比赛前20分钟出现早进球。",
        trigger_text="前20分钟出现早进球",
        consequence_text="原文影响",
        evaluator_type=EvaluatorType.MANUAL_ONLY,
        required_data_types=["live_event"],
        source_location="风险预警信号",
    )]})

    result = evaluate_watchlist(
        watchlist, [], [],
        captured_at=datetime(2027, 8, 4, 16, 0, tzinfo=TZ),
        kickoff_at=datetime(2027, 8, 5, 2, 0, tzinfo=TZ),
    )

    assert result[0].status == RiskStatus.UNKNOWN


def test_prepare_watchlist_is_immutable_idempotent_and_bound_to_source(project_root: Path) -> None:
    path = _prepared_v2_match(project_root)
    source_text = "若澳门客胜赔率突破2.50且继续上行，保留原赛前风险说明。"
    document = MatchDocument.load(path)
    document.replace_section("prematch-reasoning", document.sections["prematch-reasoning"] + "\n\n" + source_text)
    document.save()
    draft = PrematchRiskWatchlistDraftV1(
        watchlist_id="watchlist-kor-test",
        match_id=document.metadata.match_id,
        source_text=source_text,
        conditions=[RiskConditionV1(
            condition_id="away-above-250",
            original_risk_text=source_text,
            trigger_text="澳门客胜赔率突破2.50且继续上行",
            consequence_text="保留原赛前风险说明",
            evaluator_type=EvaluatorType.MARKET_AND_TREND,
            market=MarketType.EUROPEAN_ODDS,
            provider_id="macau",
            field="away_win",
            operator=">",
            threshold=2.50,
            required_trend="rising",
            source_location="后市观测清单/风险预警信号",
        )],
    )

    first_path, first = prepare_watchlist(
        project_root, path, draft,
        created_at=datetime(2026, 7, 30, 18, 0, tzinfo=TZ),
    )
    second_path, second = prepare_watchlist(
        project_root, path, draft,
        created_at=datetime(2026, 7, 30, 18, 0, tzinfo=TZ),
    )

    assert first_path == second_path
    assert first.watchlist_sha256 == second.watchlist_sha256
    assert load_watchlist(first_path).source_section_sha256 == first.source_section_sha256
    assert len(list(first_path.parent.glob("*.yml"))) == 1
