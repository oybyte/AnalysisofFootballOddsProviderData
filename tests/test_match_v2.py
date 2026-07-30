from __future__ import annotations

import pytest
from pydantic import ValidationError

from odds_journal.analysis_context import prepare_analysis_context
from odds_journal.case_retrieval import retrieve_cases
from odds_journal.markdown import MatchDocument
from odds_journal.models import AnalysisOutlook, MarketSnapshot, MatchMetadata, PrimaryMarket, Selection
from odds_journal.scenarios import set_no_scenario
from odds_journal.services import finish_match, lock_match, parse_datetime, set_market_snapshots
from odds_journal.settlement import (
    score_candidate_hit,
    settle_asian_handicap,
    settle_fixed_handicap_1x2,
    total_goals_range_hit,
)

from .test_models import base_metadata


def outlook(mode: str = "complete") -> dict:
    if mode == "pass":
        return {"data_mode": "pass", "pass_reasons": ["缺少可核验盘口"]}
    return {
        "data_mode": mode,
        "missing_reasons": ["缺少临盘"] if mode == "degraded" else [],
        "dimension_assessments": [],
        "resonance_status": "insufficient",
        "one_x_two": {"choices": ["home", "draw"]},
        "asian_handicap": {
            "line_display": "主让0.5/1",
            "home_line": -0.75,
            "ranking": {"choices": ["home_handicap", "away_handicap"]},
        },
        "fixed_handicap_1x2": {
            "home_line": -1,
            "source_type": "official_lottery",
            "ranking": {"choices": ["handicap_draw", "handicap_away"]},
        },
        "total_goals": {"minimum": 2, "maximum": 3},
        "score_candidates": ["2-0", "2-1"],
    }


def test_match_v1_remains_supported() -> None:
    assert MatchMetadata.model_validate(base_metadata()).schema_version == 1


def test_match_v2_degraded_confidence_is_capped() -> None:
    values = base_metadata() | {
        "schema_version": 2,
        "primary_market": "one_x_two",
        "primary_selection": "home",
        "confidence": 0.70,
        "analysis_outlook": outlook("degraded"),
    }
    with pytest.raises(ValidationError, match="0.69"):
        MatchMetadata.model_validate(values)


def test_match_v2_pass_has_no_predictions() -> None:
    values = base_metadata() | {
        "schema_version": 2,
        "primary_market": "pass",
        "primary_selection": "pass",
        "analysis_outlook": outlook("pass"),
    }
    assert MatchMetadata.model_validate(values).analysis_outlook is not None


@pytest.mark.parametrize(
    ("home_goals", "away_goals", "line", "selection", "expected"),
    [
        (2, 1, -0.75, "home_handicap", "half_win"),
        (1, 1, -0.25, "home_handicap", "half_loss"),
        (2, 1, -1.0, "home_handicap", "push"),
        (1, 1, 0.0, "away_handicap", "push"),
        (1, 2, -0.5, "home_handicap", "full_loss"),
    ],
)
def test_asian_handicap_settlement(
    home_goals: int,
    away_goals: int,
    line: float,
    selection: str,
    expected: str,
) -> None:
    assert settle_asian_handicap(home_goals, away_goals, line, selection) == expected


def test_other_v2_settlements() -> None:
    assert settle_fixed_handicap_1x2(2, 1, -1) == "handicap_draw"
    assert total_goals_range_hit(2, 1, 2, 3)
    assert score_candidate_hit(2, 1, ["2-0", "2-1"])


def test_match_v2_locks_lines_and_derives_result(
    project_root, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_analysis_context import factual_match, fill_analysis
    from .test_rules_release import _activate_v2

    _activate_v2(project_root, monkeypatch)
    path = factual_match(project_root)
    document = MatchDocument.load(path)
    document.metadata.schema_version = 2
    document.save()
    set_market_snapshots(
        path,
        [
            MarketSnapshot(
                snapshot_id="macau-asian-opening",
                market="asian_handicap",
                phase="opening",
                captured_at=parse_datetime("2026-07-30T12:00:00+08:00"),
                provider_id="macau",
                source_ref="evidence:test",
                odds_format="hong_kong",
                raw_values={"home_line": "主让0.5/1", "home_water": "0.94"},
                normalized_values={"home_line": -0.75, "home_water": 0.94},
            )
        ],
    )
    prepare_analysis_context(
        project_root,
        path,
        prepared_at=parse_datetime("2026-07-30T17:40:00+08:00"),
        as_of=parse_datetime("2026-07-30T17:30:00+08:00"),
        markets=[PrimaryMarket.HANDICAP],
    )
    set_no_scenario(path, "节点不足，不强制归类")
    retrieve_cases(
        project_root,
        path,
        prepared_at=parse_datetime("2026-07-30T17:45:00+08:00"),
    )
    fill_analysis(path)
    locked = lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.HOME_HANDICAP,
        secondary=Selection.AWAY_HANDICAP,
        confidence=0.69,
        analysis_outlook=AnalysisOutlook.model_validate(outlook("degraded")),
    )
    assert locked.metadata.analysis_outlook.asian_handicap.home_line == -0.75
    finished = finish_match(
        path,
        score="2-1",
        result_1x2=None,
        handicap_result=None,
        recorded_at=parse_datetime("2026-07-30T21:00:00+08:00"),
        key_events="无红牌",
        result_source="官方赛果页",
    )
    assert finished.metadata.result_1x2 == "home"
    assert finished.metadata.settlement.asian_result == "half_win"
    assert finished.metadata.settlement.fixed_handicap_result == "handicap_draw"
    assert finished.metadata.settlement.total_goals_range_hit is True
    assert finished.metadata.settlement.score_candidate_hit is True
