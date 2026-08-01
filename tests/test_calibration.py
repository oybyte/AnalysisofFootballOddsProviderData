from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from odds_journal.calibration import evaluate_calibration, load_calibration_config
from odds_journal.models import AnalysisOutlook, CalibrationEvent, MatchMetadata

from .test_match_v2 import outlook
from .test_models import base_metadata


CONFIG = Path("knowledge/rule-proposals/football-analysis/1.2.0/calibration/low-stability-v1.yml")


def snapshot(
    identity: str,
    market: str,
    phase: str,
    captured_at: str,
    values: dict[str, float],
    *,
    provider: str = "macau",
    odds_format: str,
) -> dict:
    return {
        "snapshot_id": identity,
        "market": market,
        "phase": phase,
        "captured_at": captured_at,
        "provider_id": provider,
        "source_ref": f"evidence:{identity}",
        "odds_format": odds_format,
        "raw_values": {key: str(value) for key, value in values.items()},
        "normalized_values": values,
    }


def euro_nodes(provider: str = "macau") -> list[dict]:
    return [
        snapshot(f"{provider}-euro-open", "european_odds", "opening", "2026-07-30T12:00:00+08:00", {"home": 1.60, "draw": 3.80, "away": 4.50}, provider=provider, odds_format="decimal"),
        snapshot(f"{provider}-euro-mid", "european_odds", "mid", "2026-07-30T16:00:00+08:00", {"home": 1.58, "draw": 3.78, "away": 4.55}, provider=provider, odds_format="decimal"),
        snapshot(f"{provider}-euro-late", "european_odds", "late", "2026-07-30T18:00:00+08:00", {"home": 1.55, "draw": 3.75, "away": 4.60}, provider=provider, odds_format="decimal"),
    ]


def metadata_with(items: list[dict], competition_code: str = "NOR-ELITESERIEN") -> MatchMetadata:
    values = base_metadata() | {
        "schema_version": 2,
        "competition_code": competition_code,
        "competition": "挪威超",
        "market_snapshots": items,
    }
    return MatchMetadata.model_validate(values)


def evaluate(items: list[dict], competition_code: str = "NOR-ELITESERIEN"):
    return evaluate_calibration(
        metadata_with(items, competition_code),
        AnalysisOutlook.model_validate(outlook("degraded")),
        load_calibration_config(CONFIG),
        cutoff=datetime.fromisoformat("2026-07-30T18:05:00+08:00"),
    )


def event(events: list[CalibrationEvent], rule_id: str) -> CalibrationEvent:
    return next(item for item in events if item.rule_id == rule_id)


def test_rise_water_rule_uses_only_post_rise_same_line_nodes() -> None:
    asian = [
        snapshot("asian-open", "asian_handicap", "opening", "2026-07-30T12:00:00+08:00", {"home_line": -0.75, "home_water": 0.50, "away_water": 1.20}, odds_format="hong_kong"),
        snapshot("asian-mid", "asian_handicap", "mid", "2026-07-30T16:00:00+08:00", {"home_line": -1.00, "home_water": 0.80, "away_water": 0.98}, odds_format="hong_kong"),
        snapshot("asian-late", "asian_handicap", "late", "2026-07-30T18:00:00+08:00", {"home_line": -1.00, "home_water": 0.95, "away_water": 0.83}, odds_format="hong_kong"),
    ]
    _, events, _ = evaluate([*euro_nodes(), *asian])
    result = event(events, "lsl-asian-rise-water-rise")
    assert result.triggered is True
    assert result.source_snapshot_ids == ["asian-mid", "asian-late"]
    assert result.threshold_observations["water_delta"] == pytest.approx(0.15)


def test_cross_line_water_difference_cannot_trigger_rule_one() -> None:
    asian = [
        snapshot("asian-open", "asian_handicap", "opening", "2026-07-30T12:00:00+08:00", {"home_line": -0.75, "home_water": 0.50}, odds_format="hong_kong"),
        snapshot("asian-mid", "asian_handicap", "mid", "2026-07-30T16:00:00+08:00", {"home_line": -1.00, "home_water": 0.80}, odds_format="hong_kong"),
        snapshot("asian-late", "asian_handicap", "late", "2026-07-30T18:00:00+08:00", {"home_line": -1.00, "home_water": 0.90}, odds_format="hong_kong"),
    ]
    _, events, _ = evaluate([*euro_nodes(), *asian])
    assert event(events, "lsl-asian-rise-water-rise").triggered is False


@pytest.mark.parametrize(("delta", "triggered"), [(0.05, False), (0.051, True)])
def test_drop_rule_uses_strict_water_boundary(delta: float, triggered: bool) -> None:
    asian = [
        snapshot("asian-open", "asian_handicap", "opening", "2026-07-30T12:00:00+08:00", {"home_line": -1.75, "home_water": 0.80}, odds_format="hong_kong"),
        snapshot("asian-mid", "asian_handicap", "mid", "2026-07-30T16:00:00+08:00", {"home_line": -1.50, "home_water": 0.90}, odds_format="hong_kong"),
        snapshot("asian-late", "asian_handicap", "late", "2026-07-30T18:00:00+08:00", {"home_line": -1.50, "home_water": 0.90 + delta}, odds_format="hong_kong"),
    ]
    _, events, _ = evaluate([*euro_nodes(), *asian])
    assert event(events, "lsl-deep-line-drop-risk").triggered is triggered


@pytest.mark.parametrize(("line", "triggered"), [(2.5, True), (2.75, False)])
def test_extreme_over_requires_exact_two_point_five(line: float, triggered: bool) -> None:
    totals = [
        snapshot("total-open", "total_goals", "opening", "2026-07-30T12:00:00+08:00", {"line": line, "over_water": 0.60}, odds_format="hong_kong"),
        snapshot("total-mid", "total_goals", "mid", "2026-07-30T16:00:00+08:00", {"line": line, "over_water": 0.50}, odds_format="hong_kong"),
        snapshot("total-late", "total_goals", "late", "2026-07-30T18:00:00+08:00", {"line": line, "over_water": 0.40}, odds_format="hong_kong"),
    ]
    _, events, _ = evaluate([*euro_nodes(), *totals])
    assert event(events, "lsl-extreme-over-calibration").triggered is triggered


def calibration_event(
    rule_id: str,
    dimensions: list[str],
    snapshots: list[str],
    correlation: list[str],
    providers: list[str] | None = None,
) -> dict:
    return {
        "rule_id": rule_id,
        "triggered": True,
        "target_market": "one_x_two",
        "target_selection": "draw",
        "source_dimensions": dimensions,
        "source_provider_ids": providers or ["macau"],
        "source_snapshot_ids": snapshots,
        "correlation_keys": correlation,
        "threshold_observations": {"value": 1, "threshold": 1},
        "before_ranking": ["home", "draw", "away"],
        "proposed_ranking": ["home", "draw", "away"],
        "final_ranking": ["home", "draw", "away"],
        "adjustment_level": 1,
        "supporting_evidence": ["满足阈值"],
        "counter_evidence": ["仍有反证"],
    }


def test_same_source_rules_cannot_open_anchor_gate() -> None:
    raw = outlook("degraded") | {
        "schema_version": 2,
        "competition_profile": "nor_eliteserien",
        "calibration_contract_version": 1,
        "calibration_events": [
            calibration_event("lsl-favorite-kelly-draw-resonance", ["european_odds", "kelly_index"], ["a", "b"], ["macau:odds-kelly"]),
            calibration_event("lsl-underdog-kelly-defense", ["european_odds", "kelly_index"], ["c", "d"], ["macau:odds-kelly"]),
            *[
                {
                    **calibration_event(rule_id, ["total_goals_market"], [f"x-{index}"], []),
                    "triggered": False,
                    "not_triggered_reason": "insufficient_data",
                    "source_provider_ids": [],
                    "source_snapshot_ids": [],
                    "threshold_observations": {},
                    "adjustment_level": 0,
                }
                for index, rule_id in enumerate((
                    "lsl-asian-rise-water-rise", "lsl-deep-line-falling-water", "lsl-deep-line-drop-risk",
                    "lsl-single-side-draw-protection", "lsl-kelly-narrow-range", "lsl-extreme-over-calibration",
                ))
            ],
        ],
        "calibration_summary": {
            "one_x_two": {"baseline_ranking": ["home", "draw", "away"], "final_ranking": ["home", "draw", "away"], "anchor_change_eligible": True},
            "fixed_handicap_1x2": {"baseline_ranking": ["handicap_draw", "handicap_away", "handicap_home"], "final_ranking": ["handicap_draw", "handicap_away", "handicap_home"]},
            "asian_handicap": {"cover_signal": "neutral", "cover_signal_rule_ids": []},
        },
    }
    with pytest.raises(ValidationError, match="数据血缘门禁"):
        AnalysisOutlook.model_validate(raw)


def test_independent_same_target_rules_open_anchor_evaluation_gate() -> None:
    triggered = [
        calibration_event(
            "lsl-favorite-kelly-draw-resonance",
            ["european_odds", "kelly_index"],
            ["macau-euro", "macau-kelly"],
            ["macau:odds-kelly"],
        ),
        calibration_event(
            "lsl-single-side-draw-protection",
            ["european_odds"],
            ["william-euro", "ladbrokes-euro"],
            [],
            ["william-hill", "ladbrokes"],
        ),
    ]
    remaining = [
        "lsl-asian-rise-water-rise",
        "lsl-deep-line-falling-water",
        "lsl-deep-line-drop-risk",
        "lsl-underdog-kelly-defense",
        "lsl-kelly-narrow-range",
        "lsl-extreme-over-calibration",
    ]
    inactive = []
    for index, rule_id in enumerate(remaining):
        item = calibration_event(rule_id, ["total_goals_market"], [f"unused-{index}"], [])
        item.update(
            {
                "triggered": False,
                "not_triggered_reason": "insufficient_data",
                "source_provider_ids": [],
                "source_snapshot_ids": [],
                "threshold_observations": {},
                "adjustment_level": 0,
            }
        )
        inactive.append(item)
    raw = outlook("degraded") | {
        "schema_version": 2,
        "competition_profile": "nor_eliteserien",
        "calibration_contract_version": 1,
        "calibration_events": [*triggered, *inactive],
        "calibration_summary": {
            "one_x_two": {
                "baseline_ranking": ["home", "draw", "away"],
                "final_ranking": ["home", "draw", "away"],
                "anchor_change_eligible": True,
            },
            "fixed_handicap_1x2": {
                "baseline_ranking": ["handicap_draw", "handicap_away", "handicap_home"],
                "final_ranking": ["handicap_draw", "handicap_away", "handicap_home"],
            },
            "asian_handicap": {"cover_signal": "neutral", "cover_signal_rule_ids": []},
        },
    }
    assert AnalysisOutlook.model_validate(raw).calibration_summary.one_x_two.anchor_change_eligible
