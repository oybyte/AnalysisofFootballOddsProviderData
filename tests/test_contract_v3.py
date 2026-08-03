from datetime import datetime
from pathlib import Path
import json
import shutil

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from odds_journal.calibration import evaluate_calibration, load_calibration_config
from odds_journal.analysis_context import parse_receipt, validate_analysis_receipt
from odds_journal.cli import app
from odds_journal.lock_lifecycle import prepare_lock_candidate
import odds_journal.lock_lifecycle as lifecycle_module
from odds_journal.markdown import MatchDocument
from odds_journal.models import (
    AnalysisOutlook,
    BaselineGate,
    CalibrationEvent,
    CandidateDisposition,
    MatchMetadata,
    MultiMarketScoreMatrix,
    synthesize_baseline,
)
from odds_journal.rules import load_ruleset
from odds_journal.services import parse_datetime

from .test_analysis_context import factual_match
from .test_models import base_metadata


CONFIG = Path("knowledge/rule-proposals/football-analysis/1.4.0/calibration/football-analysis-v3.yml")


def matrix(*, correlated: bool = True) -> MultiMarketScoreMatrix:
    def cell(scores: dict[str, float] | None = None, reason: str | None = None) -> dict:
        return {"status": "assessed", "scores": scores} if scores is not None else {"status": "not_applicable", "reason": reason or "该维度不适用"}

    one = {"home": 0.5, "draw": 0.0, "away": -0.5}
    asian = {"home_handicap": 1.0, "away_handicap": -1.0}
    fixed = {"handicap_home": 1.0, "handicap_draw": 0.0, "handicap_away": -1.0}
    total = {"over": 1.0, "under": -1.0}
    rows = []
    for dimension, weight, scores in (
        ("asian_handicap_market", 60, {"one_x_two": one, "asian_handicap": asian, "fixed_handicap_1x2": fixed, "total_goals": None}),
        ("european_odds", 20, {"one_x_two": one, "asian_handicap": asian, "fixed_handicap_1x2": fixed, "total_goals": total}),
        ("kelly_index", 15, {"one_x_two": one, "asian_handicap": asian, "fixed_handicap_1x2": fixed, "total_goals": total}),
        ("total_goals_market", 5, {"one_x_two": {"home": 0.0, "draw": 0.0, "away": 0.0}, "asian_handicap": {"home_handicap": 0.0, "away_handicap": 0.0}, "fixed_handicap_1x2": {"handicap_home": 0.0, "handicap_draw": 0.0, "handicap_away": 0.0}, "total_goals": total}),
    ):
        rows.append({
            "dimension": dimension,
            "configured_weight": weight,
            "market_scores": {key: cell(value) for key, value in scores.items()},
            "fact_refs": ["snapshot:test"],
            "rule_ids": ["football-analysis-framework"],
            "supporting_evidence": ["支持"],
            "counter_evidence": ["反证"],
            "source_provider_ids": ["macau"],
            "source_snapshot_ids": [f"{dimension}-snapshot"],
            "evidence_ids": ["shared-evidence"] if dimension in {"european_odds", "kelly_index"} else [f"{dimension}-evidence"],
            "correlated_with": (["kelly_index"] if dimension == "european_odds" and correlated else ["european_odds"] if dimension == "kelly_index" and correlated else []),
        })
    return MultiMarketScoreMatrix.model_validate({"rows": rows})


def test_baseline_gate_forces_pass_on_unexplained_divergence() -> None:
    with pytest.raises(ValidationError, match="必须 pass"):
        BaselineGate.model_validate({
            "facts_status": "complete",
            "theoretical_positioning": "established",
            "market_relation": "unexplained_divergence",
            "decision": "ready",
            "fact_refs": ["fact:1"],
        })


def test_matrix_halves_kelly_only_with_reciprocal_verified_lineage() -> None:
    summary = synthesize_baseline(matrix(correlated=True))
    assert summary.markets["one_x_two"].effective_weights["kelly_index"] == 7.5
    uncorrelated = synthesize_baseline(matrix(correlated=False))
    assert uncorrelated.markets["one_x_two"].effective_weights["kelly_index"] == 15.0


def test_matrix_primary_market_uses_unique_margin() -> None:
    summary = synthesize_baseline(matrix())
    assert summary.primary_market == "handicap"
    assert summary.primary_selection == "home_handicap"


def test_contract_three_uses_global_rules_outside_profiles() -> None:
    config = load_calibration_config(CONFIG)
    assert config.profile_for("EPL") == "global"
    assert len(config.applicable_rule_ids("EPL")) == 6
    assert len(config.applicable_rule_ids("NOR-ELITESERIEN")) == 14
    assert len(config.applicable_rule_ids("KOR-K1")) == 8


def test_contract_three_emits_not_applicable_overlay_events() -> None:
    score_matrix = matrix()
    summary = synthesize_baseline(score_matrix)
    outlook = AnalysisOutlook.model_validate({
        "schema_version": 3,
        "data_mode": "pass",
        "pass_reasons": ["离线规则事件测试"],
        "weight_model": {"model_id": "asian-core-v1"},
        "competition_profile": "global",
        "calibration_contract_version": 3,
        "baseline_gate": {
            "facts_status": "conflicted",
            "theoretical_positioning": "established",
            "market_relation": "aligned",
            "decision": "pass",
            "fact_refs": ["fact:1"],
            "reasons": ["测试"],
        },
        "score_matrix": score_matrix.model_dump(mode="json"),
        "baseline_summary_v3": summary.model_dump(mode="json"),
    })
    metadata = base_metadata() | {"schema_version": 2, "competition_code": "EPL", "market_snapshots": []}
    profile, events, summary = evaluate_calibration(
        MatchMetadata.model_validate(metadata),
        outlook,
        load_calibration_config(CONFIG),
        cutoff=datetime.fromisoformat("2026-07-30T18:00:00+08:00"),
    )
    assert profile == "global"
    assert summary is None
    assert len(events) == 16
    assert {item.rule_id for item in events if item.applicability == "not_applicable"} >= {
        "korea-goal-drop-v1", "lsl-extreme-over-calibration"
    }


def test_proposal_ruleset_is_explicitly_loadable() -> None:
    ruleset = load_ruleset(Path("."), "football-analysis@1.4.0", allow_proposal=True)
    assert ruleset.origin == "proposal"
    assert ruleset.manifest.calibration_contract_version == 3


def _event(
    rule_id: str,
    *,
    effect: str,
    target_market: str | None,
    target_selection: str,
    triggered: bool = False,
    adopted: bool = True,
) -> dict:
    if not triggered:
        return {
            "rule_id": rule_id,
            "contract_version": 3,
            "triggered": False,
            "not_triggered_reason": "threshold_not_met",
            "applicability": "applicable",
            "effect": effect,
            "target_market": target_market,
            "target_selection": target_selection,
            "before_ranking": [],
            "proposed_ranking": [],
            "final_ranking": [],
            "adjustment_level": 0,
        }
    ranking = {
        "one_x_two": ["home", "draw", "away"],
        "asian_handicap": ["home_handicap", "away_handicap"],
        "fixed_handicap_1x2": ["handicap_home", "handicap_draw", "handicap_away"],
        "total_goals": ["over", "under"],
    }.get(target_market or "", [])
    proposed = list(ranking)
    if effect == "ranking":
        index = proposed.index(target_selection)
        if index:
            proposed[index - 1], proposed[index] = proposed[index], proposed[index - 1]
    decision = {"disposition": "adopted"} if adopted else {
        "disposition": "excluded",
        "exclusion_reason": "与已核验的反证不一致",
        "counter_evidence_refs": ["evidence:counter"],
    }
    return {
        "rule_id": rule_id,
        "contract_version": 3,
        "triggered": True,
        "applicability": "applicable",
        "effect": effect,
        "target_market": target_market,
        "target_selection": target_selection,
        "source_dimensions": ["asian_handicap_market"],
        "source_provider_ids": ["macau"],
        "source_snapshot_ids": [f"{rule_id}-snapshot"],
        "threshold_observations": {"threshold": 1},
        "before_ranking": ranking,
        "proposed_ranking": proposed,
        "final_ranking": ranking,
        "adjustment_level": 1 if effect == "ranking" else 0,
        "supporting_evidence": ["支持"],
        "counter_evidence": ["反证"],
        "decision": decision,
    }


def _v3_outlook(*, ranking_trigger: bool = False, adopted: bool = False) -> dict:
    summary = synthesize_baseline(matrix())
    events = [
        _event("draw-kelly-parity-v1", effect="ranking", target_market="one_x_two", target_selection="draw", triggered=ranking_trigger, adopted=adopted),
        _event("deep-line-stable-cover-v1", effect="handicap_signal", target_market="asian_handicap", target_selection="home_handicap"),
        _event("quarter-low-water-inducement-v1", effect="outcome_risk_pool", target_market="handicap", target_selection="home_handicap"),
        _event("hidden-draw-away-cut-v1", effect="ranking", target_market="one_x_two", target_selection="draw"),
        _event("total-goals-cross-market-v1", effect="total_goals_pool", target_market="total_goals", target_selection="over", triggered=True),
        _event("score-baseline-v1", effect="score_pool", target_market="one_x_two", target_selection="home", triggered=True),
        _event("korea-goal-drop-v1", effect="total_goals_pool", target_market="total_goals", target_selection="over", triggered=False),
        _event("korea-deep-line-loss-tolerance-v1", effect="outcome_risk_pool", target_market="one_x_two", target_selection="away", triggered=False),
    ]
    for rule_id in (
        "lsl-asian-rise-water-rise",
        "lsl-deep-line-falling-water",
        "lsl-deep-line-drop-risk",
        "lsl-favorite-kelly-draw-resonance",
        "lsl-single-side-draw-protection",
        "lsl-underdog-kelly-defense",
        "lsl-kelly-narrow-range",
        "lsl-extreme-over-calibration",
    ):
        events.append({
            "rule_id": rule_id,
            "contract_version": 3,
            "triggered": False,
            "not_triggered_reason": "not_applicable",
            "applicability": "not_applicable",
            "effect": "ranking",
            "target_selection": "not_applicable",
            "before_ranking": [],
            "proposed_ranking": [],
            "final_ranking": [],
            "adjustment_level": 0,
        })
    experimental = {key: list(value.ranking) for key, value in summary.markets.items()}
    final = {key: list(value.ranking) for key, value in summary.markets.items()}
    if ranking_trigger:
        experimental["one_x_two"] = ["draw", "home", "away"]
        if adopted:
            final["one_x_two"] = ["draw", "home", "away"]
    return {
        "schema_version": 3,
        "data_mode": "complete",
        "weight_model": {"model_id": "asian-core-v1"},
        "competition_profile": "global",
        "calibration_contract_version": 3,
        "baseline_gate": {
            "facts_status": "complete",
            "theoretical_positioning": "established",
            "market_relation": "aligned",
            "decision": "ready",
            "fact_refs": ["fact:1"],
        },
        "score_matrix": matrix().model_dump(mode="json"),
        "baseline_summary_v3": summary.model_dump(mode="json"),
        "experimental_rankings": experimental,
        "final_rankings": final,
        "one_x_two": {"choices": final["one_x_two"][:2]},
        "asian_handicap": {"line_display": "主让半球", "home_line": -0.5, "ranking": {"choices": final["asian_handicap"]}},
        "fixed_handicap_1x2": {"home_line": -1, "source_type": "official", "ranking": {"choices": final["fixed_handicap_1x2"][:2]}},
        "total_goals": {"minimum": 2, "maximum": 3},
        "score_candidates": ["1-0", "2-0"],
        "calibration_events": events,
        "total_goals_candidate_pool": [{"minimum": 2, "maximum": 3, "rule_id": "total-goals-cross-market-v1", "decision": {"disposition": "adopted"}}],
        "score_candidate_pool": [
            {"score": "1-0", "rule_id": "score-baseline-v1", "decision": {"disposition": "adopted"}},
            {"score": "2-0", "rule_id": "score-baseline-v1", "decision": {"disposition": "adopted"}},
        ],
    }


def test_v3_requires_candidate_pool_and_adopted_scores_to_match_output() -> None:
    outcome = AnalysisOutlook.model_validate(_v3_outlook())
    assert outcome.total_goals_candidate_pool[0].minimum == outcome.total_goals.minimum
    invalid = _v3_outlook()
    invalid["score_candidate_pool"][1]["decision"] = {
        "disposition": "excluded",
        "exclusion_reason": "反证",
        "counter_evidence_refs": ["evidence:counter"],
    }
    with pytest.raises(ValidationError, match="两个已采纳比分候选"):
        AnalysisOutlook.model_validate(invalid)


def test_v3_keeps_single_ranking_rule_out_of_final_first_place() -> None:
    excluded = AnalysisOutlook.model_validate(_v3_outlook(ranking_trigger=True, adopted=False))
    assert excluded.experimental_rankings["one_x_two"][0] == "draw"
    assert excluded.final_rankings["one_x_two"][0] == "home"
    with pytest.raises(ValidationError, match="第一顺位换位需要两条独立"):
        AnalysisOutlook.model_validate(_v3_outlook(ranking_trigger=True, adopted=True))


def test_v3_tied_primary_market_forces_pass() -> None:
    tied = matrix().model_dump(mode="json")
    for row in tied["rows"]:
        for cell in row["market_scores"].values():
            if cell["status"] == "assessed":
                cell["scores"] = {key: 0.0 for key in cell["scores"]}
    summary = synthesize_baseline(MultiMarketScoreMatrix.model_validate(tied))
    payload = _v3_outlook()
    payload["score_matrix"] = tied
    payload["baseline_summary_v3"] = summary.model_dump(mode="json")
    with pytest.raises(ValidationError, match="必须 pass"):
        AnalysisOutlook.model_validate(payload)


class _PreKickoffDateTime(datetime):
    current = parse_datetime("2026-07-30T18:00:00+08:00")

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current


def test_proposal_cli_flow_is_explicit_and_cannot_prepare_lock(project_root: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    proposal_root = project_root / "knowledge" / "rule-proposals" / "football-analysis"
    proposal_root.mkdir(parents=True)
    shutil.copytree(
        repository / "knowledge" / "rule-proposals" / "football-analysis" / "1.4.0",
        proposal_root / "1.4.0",
    )
    path = factual_match(project_root)
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(
        app,
        [
            "agent",
            "start",
            str(path),
            "--ruleset",
            "football-analysis@1.4.0",
            "--proposal",
            "--as-of",
            "2026-07-30T17:30:00+08:00",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ruleset"] == "football-analysis@1.4.0"
    assert payload["analysis_receipt_schema_version"] == 5
    assert payload["analysis_outlook_schema_version"] == 3
    assert payload["ruleset_origin"] == "proposal"
    assert payload["competition_profile"] == "korea"
    assert "korea-goal-drop-v1" in payload["applicable_calibration_rule_ids"]

    document = MatchDocument.load(path)
    assert "提案规则回执必须显式使用 --proposal" in validate_analysis_receipt(project_root, document)
    assert not validate_analysis_receipt(project_root, document, allow_proposal=True)
    monkeypatch.setattr(lifecycle_module, "datetime", _PreKickoffDateTime)
    with pytest.raises(Exception, match="提案规则集只能离线分析"):
        prepare_lock_candidate(
            project_root,
            path,
            market="handicap",
            selection="home_handicap",
            secondary=None,
            confidence=0.60,
            outlook_path=project_root / "missing-outlook.yml",
            actor="lcz",
        )
