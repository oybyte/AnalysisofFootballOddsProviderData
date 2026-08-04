from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import shutil

from typer.testing import CliRunner

from odds_journal.calibration import load_calibration_config
from odds_journal.models import MatchMetadata
from odds_journal.rule_engine.evaluation import AnalysisDraftInput, build_outlook, evaluate_draft
from odds_journal.rule_engine.evaluators import evaluate
from odds_journal.rule_engine.evaluation import ReasoningDisposition
from odds_journal.cli import app
from odds_journal import analytics

from .test_contract_v3 import matrix
from .test_analysis_context import factual_match
from .test_models import base_metadata


CONFIG = Path("knowledge/rule-proposals/football-analysis/1.5.0/calibration/football-analysis-v4.yml")


def draft_input() -> AnalysisDraftInput:
    return AnalysisDraftInput.model_validate({
        "analysis_input_mode": "market_only",
        "baseline_gate": {
            "facts_status": "complete",
            "theoretical_positioning": "established",
            "market_relation": "aligned",
            "decision": "ready",
            "fact_refs": ["fact:market-snapshots"],
        },
        "score_matrix": matrix().model_dump(mode="json"),
        "baseline_output": {
            "asian_line_display": "主让半球",
            "asian_home_line": -0.5,
            "total_goals_minimum": 2,
            "total_goals_maximum": 3,
            "score_candidates": ["1-0", "2-0"],
            "fixed_handicap_home_line": -1,
            "fixed_handicap_source_type": "official",
        },
        "fact_refs": ["fact:market-snapshots"],
        "hypothesis_a": "盘口信息存在延续性。",
        "hypothesis_b": "盘口信息可能只是短时再平衡。",
    })


def test_contract_four_config_has_profiles_rules_and_controls() -> None:
    config = load_calibration_config(CONFIG)
    assert config.schema_version == 4
    assert len(config.rules) == 21
    assert config.profile_chain_for("KOR-K1") == ["global", "korea"]
    assert config.profile_chain_for("NOR-ELITESERIEN") == ["global", "legacy-low-stability", "nor_eliteserien"]
    assert len(config.applicable_rule_ids("EPL")) == 11


def test_contract_four_evaluates_every_rule_without_inventing_a_direction() -> None:
    metadata = MatchMetadata.model_validate(base_metadata() | {
        "schema_version": 2,
        "competition_code": "EPL",
        "competition": "英超",
        "market_snapshots": [],
    })
    bundle = evaluate_draft(
        match_id=metadata.match_id,
        metadata=metadata,
        cutoff=datetime.fromisoformat("2026-07-30T18:00:00+08:00"),
        config=load_calibration_config(CONFIG),
        calibration_config_sha256="a" * 64,
        market_snapshot_sha256="b" * 64,
        draft=draft_input(),
    )
    assert len(bundle.events) == 21
    assert bundle.competition_profile == "global"
    assert bundle.events[0].not_triggered_reason == "not_applicable"
    assert bundle.baseline_summary["primary_market"] == "handicap"
    outlook = build_outlook(draft_input(), bundle, [])
    assert outlook.schema_version == 4
    assert outlook.calibration_contract_version == 4
    assert outlook.score_candidates == ["1-0", "2-0"]


def test_contract_four_proposal_start_requires_explicit_proposal(project_root, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    destination = project_root / "knowledge" / "rule-proposals" / "football-analysis" / "1.5.0"
    destination.parent.mkdir(parents=True)
    shutil.copytree(repository / "knowledge" / "rule-proposals" / "football-analysis" / "1.5.0", destination)
    path = factual_match(project_root)
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(app, [
        "agent", "start", str(path), "--ruleset", "football-analysis@1.5.0", "--proposal",
        "--as-of", "2026-07-30T17:30:00+08:00", "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["analysis_receipt_schema_version"] == 6
    assert payload["analysis_outlook_schema_version"] == 4
    assert payload["ruleset_origin"] == "proposal"
    assert payload["competition_profile"] == "korea"


def _thresholds(rule_id: str) -> dict:
    return next(rule.thresholds for rule in load_calibration_config(CONFIG).rules if rule.rule_id == rule_id)


def test_contract_four_rule_predicates_require_cross_market_inputs() -> None:
    hidden = {
        "away_odds_relative_change": -0.033333,
        "late_away_kelly": 0.92,
        "draw_odds_relative_change": 0.01,
        "draw_kelly_change": 0.0,
        "euro_three_nodes": True,
        "kelly_three_nodes": True,
    }
    assert not evaluate("hidden-draw-away-cut-v1", hidden, _thresholds("hidden-draw-away-cut-v1"))[0]
    hidden["away_odds_relative_change"] = -0.10
    assert evaluate("hidden-draw-away-cut-v1", hidden, _thresholds("hidden-draw-away-cut-v1"))[0]

    quarter = {
        "late_home_line": -0.5,
        "late_home_water": 0.75,
        "asian_home_water_change": -0.08,
        "home_odds_change": -0.05,
        "late_kelly_spread": 0.02,
        "asian_same_line_three_nodes": True,
        "asian_home_water_non_increasing": True,
        "euro_three_nodes": True,
        "kelly_three_nodes": True,
    }
    assert not evaluate("quarter-low-water-inducement-v1", quarter, _thresholds("quarter-low-water-inducement-v1"))[0]
    quarter["home_odds_change"] = 0.05
    assert evaluate("quarter-low-water-inducement-v1", quarter, _thresholds("quarter-low-water-inducement-v1"))[0]

    korea = {
        "late_home_line": -1.0,
        "late_home_water": 1.02,
        "home_odds_change": -0.02,
        "home_kelly_change": 0.0,
        "asian_three_nodes": True,
        "euro_three_nodes": True,
        "kelly_three_nodes": True,
    }
    assert not evaluate("korea-deep-line-loss-tolerance-v1", korea, _thresholds("korea-deep-line-loss-tolerance-v1"))[0]
    korea["home_kelly_change"] = 0.02
    assert evaluate("korea-deep-line-loss-tolerance-v1", korea, _thresholds("korea-deep-line-loss-tolerance-v1"))[0]


def test_contract_four_builds_pool_items_for_triggered_rules() -> None:
    snapshots = []
    for market, values in (
        ("asian_handicap", [
            {"home_line": -0.5, "home_water": 0.95},
            {"home_line": -0.5, "home_water": 0.85},
            {"home_line": -0.5, "home_water": 0.75},
        ]),
        ("european_odds", [
            {"home": 1.40, "draw": 3.5, "away": 6.0},
            {"home": 1.45, "draw": 3.5, "away": 5.9},
            {"home": 1.50, "draw": 3.5, "away": 5.8},
        ]),
        ("kelly_index", [
            {"home": 0.91, "draw": 0.92, "away": 0.93},
            {"home": 0.91, "draw": 0.92, "away": 0.93},
            {"home": 0.91, "draw": 0.92, "away": 0.93},
        ]),
        ("total_goals", [
            {"line": 2.5, "over_water": 0.90},
            {"line": 2.5, "over_water": 0.75},
            {"line": 2.5, "over_water": 0.61},
        ]),
    ):
        for index, values_at_phase in enumerate(values):
            phase = ("opening", "mid", "late")[index]
            snapshots.append({
                "snapshot_id": f"{market[:3]}-{phase}", "market": market, "phase": phase,
                "captured_at": f"2026-07-30T{10 + index * 2:02d}:00:00+08:00", "provider_id": "macau",
                "source_ref": f"source:{market}:{phase}",
                "odds_format": "kelly" if market == "kelly_index" else "decimal" if market == "european_odds" else "hong_kong",
                "raw_values": {key: str(value) for key, value in values_at_phase.items()},
                "normalized_values": values_at_phase,
            })
    metadata = MatchMetadata.model_validate(base_metadata() | {
        "schema_version": 2, "competition_code": "EPL", "competition": "英超", "market_snapshots": snapshots,
    })
    bundle = evaluate_draft(
        match_id=metadata.match_id, metadata=metadata,
        cutoff=datetime.fromisoformat("2026-07-30T18:00:00+08:00"),
        config=load_calibration_config(CONFIG), calibration_config_sha256="a" * 64,
        market_snapshot_sha256="b" * 64, draft=draft_input(),
    )
    dispositions = []
    for event in bundle.events:
        if not event.triggered:
            continue
        decision = {"disposition": "adopted"}
        if event.effect == "ranking":
            decision = {
                "disposition": "excluded", "exclusion_reason": "单条实验规则不得换位。",
                "counter_evidence_refs": ["baseline:anchor"],
            }
        payload = {
            "rule_id": event.rule_id, "disposition": decision,
            "hypothesis_a": "规则条件成立。", "hypothesis_b": "规则条件可能是噪声。",
            "supporting_evidence": ["snapshot:verified"], "counter_evidence": ["market:cross-check"],
            "invalidation_condition": "后续节点反向。", "actor": "lcz",
        }
        if event.effect == "score_pool":
            payload["score_candidates"] = ["1-0", "2-0"]
        dispositions.append(ReasoningDisposition.model_validate(payload))
    outlook = build_outlook(draft_input(), bundle, dispositions)
    assert any(item.rule_id == "score-baseline-v1" for item in outlook.score_candidate_pool)
    assert any(item.rule_id == "quarter-low-water-inducement-v1" for item in outlook.outcome_risk_pool)
    assert outlook.score_candidates == ["1-0", "2-0"]


def test_analytics_fingerprint_and_export_do_not_leak_future_results(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "raw" / "matches" / "fixture" / "analysis-outlook.yml"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("version: one\n", encoding="utf-8")
    monkeypatch.setattr(analytics, "match_files", lambda _root: [])
    first, _ = analytics._fingerprint(tmp_path)
    artifact.write_text("version: two\n", encoding="utf-8")
    second, _ = analytics._fingerprint(tmp_path)
    assert first != second

    database = analytics.analytics_path(tmp_path)
    database.parent.mkdir(parents=True)
    import sqlite3
    with sqlite3.connect(database) as connection:
        analytics._create_schema(connection)
        connection.execute("INSERT INTO fixtures VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
            "fixture", "matches/fixture.md", "EPL", "2026-07-30T18:00:00+08:00", "home", "away", "finished", "a" * 64,
        ))
        connection.execute("INSERT INTO results VALUES (?, ?, ?)", (
            "fixture", "2-1", "2026-07-30T21:00:00+08:00",
        ))
        connection.commit()
    before = tmp_path / "before.jsonl"
    analytics.export_dataset(tmp_path, before, as_of="2026-07-30T20:00:00+08:00")
    assert json.loads(before.read_text(encoding="utf-8"))["label"] is None
    after = tmp_path / "after.jsonl"
    analytics.export_dataset(tmp_path, after, as_of="2026-07-30T22:00:00+08:00")
    assert json.loads(after.read_text(encoding="utf-8"))["label_available_at"] == "2026-07-30T21:00:00+08:00"
