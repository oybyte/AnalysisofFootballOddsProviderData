from __future__ import annotations

from pathlib import Path
import json
import shutil
import sqlite3

import yaml
from typer.testing import CliRunner

from odds_journal.calibration import load_calibration_config
from odds_journal.analytics import build_analytics
from odds_journal.formal_draft import (
    AnalysisDraftInputV3,
    EvaluationBundleV3,
    _asian,
    _one_x_two,
    _total_goals,
    _has_theoretical_positioning,
    build_outlook_v6,
)
from odds_journal.cli import app
from odds_journal.markdown import MatchDocument
from odds_journal.models import AnalysisOutlook, CalibrationEvent
from odds_journal.rule_engine.evaluation import MachineRuleEvent, ReasoningDisposition
from odds_journal.rules import load_ruleset
from odds_journal.services import create_match, parse_datetime


CONFIG = Path("knowledge/rule-proposals/football-analysis/1.9.0/calibration/football-analysis-v8.yml")


def _row(provider: str, observation: str, prices: dict[str, float], *, line: float | None = None,
         odds_format: str = "decimal", at: str = "2026-08-10T10:00:00+08:00") -> dict:
    return {
        "provider_id": provider, "observation_id": observation,
        "normalized_prices": prices, "normalized_line": line,
        "odds_format": odds_format, "observed_at": at,
    }


def test_market_only_compiler_assesses_one_x_two_as_degraded() -> None:
    config = load_calibration_config(CONFIG)
    rows = [
        _row("macau", "e1", {"home": 1.50, "draw": 4.20, "away": 6.00}),
        _row("bet365", "e2", {"home": 1.55, "draw": 4.00, "away": 5.80}),
        _row("william-hill", "e3", {"home": 1.60, "draw": 3.90, "away": 5.50}),
    ]
    result = _one_x_two(rows, "market_only", config, [], positioned=False)
    assert result.status == "degraded"
    assert result.ranking[0] == "home"
    assert result.degradation_reasons == ["theoretical_positioning_unavailable"]


def test_one_x_two_probability_gap_boundary_fails_closed() -> None:
    config = load_calibration_config(CONFIG)
    rows = [
        _row("macau", "e1", {"home": 2.85, "draw": 2.90, "away": 3.00}),
        _row("bet365", "e2", {"home": 2.82, "draw": 2.92, "away": 3.02}),
        _row("william-hill", "e3", {"home": 2.88, "draw": 2.93, "away": 3.05}),
    ]
    result = _one_x_two(rows, "market_only", config, [], positioned=False)
    assert result.status == "pass"
    assert result.pass_reasons == ["insufficient_directional_separation"]


def test_one_x_two_ignores_unconfigured_provider_and_uses_latest_timestamp() -> None:
    config = load_calibration_config(CONFIG)
    rows = [
        _row("macau", "late", {"home": 1.50, "draw": 4.20, "away": 6.00}, at="2026-08-10T10:00:00+08:00"),
        _row("macau", "early", {"home": 6.00, "draw": 4.20, "away": 1.50}, at="2026-08-10T08:00:00+08:00"),
        _row("bet365", "e2", {"home": 1.55, "draw": 4.00, "away": 5.80}),
        _row("william-hill", "e3", {"home": 1.60, "draw": 3.90, "away": 5.50}),
        _row("untrusted-provider", "e4", {"home": 8.00, "draw": 4.00, "away": 1.20}),
    ]
    result = _one_x_two(rows, "market_only", config, [], positioned=False)
    assert result.ranking[0] == "home"
    assert result.provider_ids == ["bet365", "macau", "william-hill"]
    assert "late" in result.observation_ids
    assert "early" not in result.observation_ids


def test_latest_provider_observation_uses_instant_not_iso_string_order() -> None:
    config = load_calibration_config(CONFIG)
    rows = [
        _row("macau", "older-local", {"home": 6.00, "draw": 4.20, "away": 1.50}, at="2026-08-10T10:00:00+08:00"),
        _row("macau", "newer-utc", {"home": 1.50, "draw": 4.20, "away": 6.00}, at="2026-08-10T02:30:00+00:00"),
        _row("bet365", "e2", {"home": 1.55, "draw": 4.00, "away": 5.80}),
        _row("william-hill", "e3", {"home": 1.60, "draw": 3.90, "away": 5.50}),
    ]
    result = _one_x_two(rows, "market_only", config, [], positioned=False)
    assert result.ranking[0] == "home"
    assert "newer-utc" in result.observation_ids
    assert "older-local" not in result.observation_ids


def test_asian_requires_same_line_provider_coverage() -> None:
    config = load_calibration_config(CONFIG)
    rows = [
        _row("macau", "a1", {"home": 0.70, "away": 1.10}, line=-0.5, odds_format="hong_kong"),
        _row("bet365", "a2", {"home": 0.72, "away": 1.08}, line=-0.75, odds_format="hong_kong"),
    ]
    result = _asian(rows, "market_only", config, [], positioned=False)
    assert result.status == "pass"
    assert result.pass_reasons == ["insufficient_same_line_coverage"]


def test_total_goals_requires_two_same_line_exact_series() -> None:
    config = load_calibration_config(CONFIG)
    rows = []
    for provider in ("macau", "bet365"):
        rows.extend([
            _row(provider, f"{provider}-1", {"over": 0.80, "under": 1.10}, line=2.5, odds_format="hong_kong", at="2026-08-10T08:00:00+08:00"),
            _row(provider, f"{provider}-2", {"over": 0.85, "under": 1.04}, line=2.5, odds_format="hong_kong", at="2026-08-10T09:00:00+08:00"),
            _row(provider, f"{provider}-3", {"over": 0.90, "under": 1.00}, line=2.5, odds_format="hong_kong", at="2026-08-10T10:00:00+08:00"),
        ])
    result = _total_goals(rows, "market_only", config, [])
    assert result.status == "assessed"
    assert result.ranking == ["under"]
    assert result.provider_ids == ["bet365", "macau"]


def test_theoretical_positioning_requires_same_source_method_and_validity() -> None:
    from odds_journal.formal_draft import PrematchFactBundleV1

    cutoff = parse_datetime("2026-08-10T10:00:00+08:00")
    common = {
        "fact_type": "team_strength_rating",
        "value": {
            "provider_id": "rating-provider", "method_id": "elo-v1", "rating": 1500,
            "valid_from": "2026-08-01T00:00:00+08:00",
            "valid_until": "2026-08-31T23:59:59+08:00",
        },
        "source_ref": "rating-source:august", "observed_at": cutoff,
        "received_at": cutoff, "authentication_status": "authenticated",
    }
    bundle = PrematchFactBundleV1.model_validate({
        "match_id": "fixture", "as_of": cutoff,
        "facts": [
            {**common, "fact_id": "home-rating", "subject": "home"},
            {**common, "fact_id": "away-rating", "subject": "away"},
        ],
        "bundle_sha256": "a" * 64,
    })
    assert _has_theoretical_positioning(bundle, cutoff)
    mismatched = bundle.model_copy(deep=True)
    mismatched.facts[1].source_ref = "rating-source:other"
    assert not _has_theoretical_positioning(mismatched, cutoff)


def test_outlook_v6_allows_partial_market_pass() -> None:
    config = load_calibration_config(CONFIG)
    events = [CalibrationEvent.model_validate({
        "rule_id": rule.rule_id, "contract_version": 8, "triggered": False,
        "not_triggered_reason": "not_applicable", "applicability": "not_applicable",
        "effect": rule.effect, "target_market": rule.target_market,
        "target_selection": rule.target_selection or "pass", "adjustment_level": 0,
    }) for rule in config.rules]
    assessments = {
        "one_x_two": {"market": "one_x_two", "status": "degraded", "ranking": ["home", "draw", "away"], "degradation_reasons": ["theoretical_positioning_unavailable"]},
        "asian_handicap": {"market": "asian_handicap", "status": "degraded", "ranking": ["home_handicap", "away_handicap"], "degradation_reasons": ["theoretical_positioning_unavailable"]},
        "fixed_handicap_1x2": {"market": "fixed_handicap_1x2", "status": "pass", "ranking": [], "pass_reasons": ["no_independent_structured_market"]},
        "total_goals": {"market": "total_goals", "status": "pass", "ranking": [], "pass_reasons": ["insufficient_exact_series"]},
        "score": {"market": "score", "status": "pass", "ranking": [], "pass_reasons": ["no_released_score_rule"]},
    }
    outlook = AnalysisOutlook.model_validate({
        "schema_version": 6, "data_mode": "degraded",
        "missing_reasons": ["theoretical_positioning_unavailable"],
        "competition_profile": "global", "calibration_contract_version": 8,
        "analysis_input_mode": "market_only", "profile_chain": ["global"],
        "evaluation_bundle_sha256": "a" * 64,
        "formal_gate": {"lifecycle_status": "ready", "identity_status": "valid", "cutoff_status": "valid", "reasons": [], "evidence_refs": ["receipt:x"]},
        "market_assessments": assessments,
        "market_statuses": {key: value["status"] for key, value in assessments.items()},
        "market_pass_reasons": {key: value.get("pass_reasons", []) for key, value in assessments.items() if value["status"] == "pass"},
        "one_x_two": {"choices": ["home", "draw"]},
        "asian_handicap": {"line_display": "-0.5", "home_line": -0.5, "ranking": {"choices": ["home_handicap", "away_handicap"]}},
        "calibration_events": [item.model_dump(mode="json") for item in events],
    })
    assert outlook.market_statuses["total_goals"] == "pass"
    assert outlook.one_x_two is not None


def test_ruleset_1_9_proposal_loads_without_changing_active_ruleset() -> None:
    root = Path(__file__).resolve().parents[1]
    proposal = load_ruleset(root, "football-analysis@1.9.0", allow_proposal=True)
    assert proposal.manifest.schema_version == 9
    assert proposal.manifest.calibration_contract_version == 8
    active = load_ruleset(root, "football-analysis@1.8.0")
    assert active.manifest.calibration_contract_version == 7


def test_contract_eight_cli_build_accept_and_evaluate(project_root: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    proposal_root = project_root / "knowledge/rule-proposals/football-analysis"
    proposal_root.mkdir(parents=True)
    shutil.copytree(repository / "knowledge/rule-proposals/football-analysis/1.9.0", proposal_root / "1.9.0")
    path = create_match(
        project_root, kickoff=parse_datetime("2099-08-10T18:30:00+08:00"), timezone="Asia/Shanghai",
        competition_code="KOR-K1", competition="韩K联", home_team_id="fc-seoul",
        home_team="FC首尔", away_team_id="ulsan-hd", away_team="蔚山HD", schema_version=2,
    )
    document = MatchDocument.load(path)
    document.replace_section("prematch-facts", "## 一、赛前事实\n\n仅有赛前盘口资料，暂无认证基本面。")
    document.save()

    euro = [
        _row("macau", "e1", {"home": 1.50, "draw": 4.20, "away": 6.00}),
        _row("bet365", "e2", {"home": 1.55, "draw": 4.00, "away": 5.80}),
        _row("william-hill", "e3", {"home": 1.60, "draw": 3.90, "away": 5.50}),
    ]
    asian = [
        _row("macau", "a1", {"home": 0.70, "away": 1.10}, line=-0.5, odds_format="hong_kong"),
        _row("bet365", "a2", {"home": 0.72, "away": 1.08}, line=-0.5, odds_format="hong_kong"),
    ]
    from odds_journal import formal_draft
    monkeypatch.setattr(formal_draft, "prediction_eligible_market_observations", lambda _root, *, match_id, market, cutoff: euro if market == "european_odds" else asian if market == "asian_handicap" else [])
    monkeypatch.setattr(formal_draft, "observation_conflict_ids", lambda *args, **kwargs: set())
    monkeypatch.chdir(project_root)
    runner = CliRunner()
    started = runner.invoke(app, [
        "agent", "start", str(path), "--ruleset", "football-analysis@1.9.0", "--proposal",
        "--as-of", "2099-08-10T10:00:00+08:00", "--json",
    ])
    assert started.exit_code == 0, started.output
    assert json.loads(started.output)["analysis_receipt_schema_version"] == 8
    scenario = runner.invoke(app, [
        "scenario", "no-scenario", str(path),
        "--reason", "确定性市场编译不自动推断比赛语境",
    ])
    assert scenario.exit_code == 0, scenario.output
    cases = runner.invoke(app, [
        "retrieve-cases", str(path), "--prepared-at", "2099-08-10T10:00:00+08:00", "--proposal",
    ])
    assert cases.exit_code == 0, cases.output
    built = runner.invoke(app, ["agent", "build-draft", str(path), "--json"])
    assert built.exit_code == 0, built.output
    candidate_sha = json.loads(built.output)["candidate_sha256"]
    accepted = runner.invoke(app, [
        "agent", "accept-draft", str(path), "--candidate-sha", candidate_sha,
        "--approved-by", "lcz", "--confirm-draft", "--json",
    ])
    assert accepted.exit_code == 0, accepted.output
    built_again = runner.invoke(app, ["agent", "build-draft", str(path), "--json"])
    accepted_again = runner.invoke(app, [
        "agent", "accept-draft", str(path), "--candidate-sha", candidate_sha,
        "--approved-by", "lcz", "--confirm-draft", "--json",
    ])
    assert built_again.exit_code == 0, built_again.output
    assert accepted_again.exit_code == 0, accepted_again.output
    assert json.loads(built_again.output) == json.loads(built.output)
    assert json.loads(accepted_again.output) == json.loads(accepted.output)
    dispositions = project_root / "empty-dispositions.yml"
    dispositions.write_text(yaml.safe_dump({"dispositions": []}), encoding="utf-8")
    evaluated = runner.invoke(app, [
        "agent", "evaluate-draft", str(path), "--proposal",
        "--dispositions-file", str(dispositions), "--json",
    ])
    assert evaluated.exit_code == 0, evaluated.output
    outlook = yaml.safe_load((project_root / "raw/matches" / document.metadata.match_id / "analysis-outlook.yml").read_text(encoding="utf-8"))
    assert outlook["schema_version"] == 6
    assert outlook["market_statuses"]["one_x_two"] == "degraded"
    assert outlook["market_statuses"]["score"] == "pass"
    assert (project_root / "raw/matches" / document.metadata.match_id / "reasoning-dispositions.yml").is_file()
    validated = runner.invoke(app, ["agent", "validate-draft", str(path), "--proposal", "--json"])
    assert validated.exit_code == 0, validated.output
    rendered = runner.invoke(app, ["agent", "render-draft", str(path), "--proposal", "--json"])
    assert rendered.exit_code == 0, rendered.output
    blocked_lock = runner.invoke(app, [
        "agent", "prepare-lock", str(path), "--market", "one_x_two",
        "--selection", "home", "--confidence", "0.69",
    ])
    assert blocked_lock.exit_code == 1
    assert "提案规则集" in blocked_lock.output
    analytics = build_analytics(project_root)
    with sqlite3.connect(analytics["path"]) as connection:
        assert connection.execute("SELECT COUNT(*) FROM formal_draft_candidates").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM formal_draft_acceptances").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM formal_market_assessments").fetchone() == (5,)
        statuses = dict(connection.execute("SELECT market, status FROM formal_outlook_market_statuses"))
        assert statuses["one_x_two"] == "degraded"
        assert statuses["score"] == "pass"
    outlook_path = project_root / "raw/matches" / document.metadata.match_id / "analysis-outlook.yml"
    tampered = yaml.safe_load(outlook_path.read_text(encoding="utf-8"))
    tampered["one_x_two"]["choices"] = ["draw", "home"]
    outlook_path.write_text(yaml.safe_dump(tampered, allow_unicode=True, sort_keys=False), encoding="utf-8")
    rejected = runner.invoke(app, ["agent", "validate-draft", str(path), "--proposal", "--json"])
    assert rejected.exit_code == 1, rejected.output
    assert "dispositions 不一致" in rejected.output


def _contract_eight_models(events: list[MachineRuleEvent]) -> tuple[AnalysisDraftInputV3, EvaluationBundleV3]:
    assessments = {
        "one_x_two": {"market": "one_x_two", "status": "degraded", "input_mode": "market_only", "ranking": ["home", "draw", "away"], "degradation_reasons": ["theoretical_positioning_unavailable"]},
        "asian_handicap": {"market": "asian_handicap", "status": "degraded", "input_mode": "market_only", "ranking": ["home_handicap", "away_handicap"], "line": -0.5, "degradation_reasons": ["theoretical_positioning_unavailable"]},
        "fixed_handicap_1x2": {"market": "fixed_handicap_1x2", "status": "pass", "input_mode": "market_only", "ranking": [], "pass_reasons": ["no_independent_structured_market"]},
        "total_goals": {"market": "total_goals", "status": "pass", "input_mode": "market_only", "ranking": [], "pass_reasons": ["insufficient_exact_series"]},
        "score": {"market": "score", "status": "pass", "input_mode": "market_only", "ranking": [], "pass_reasons": ["no_released_score_rule"]},
    }
    gate = {"lifecycle_status": "ready", "identity_status": "valid", "cutoff_status": "valid", "reasons": [], "evidence_refs": ["receipt:x"]}
    draft = AnalysisDraftInputV3.model_validate({
        "match_id": "fixture", "as_of": "2026-08-10T10:00:00+08:00",
        "analysis_input_mode": "market_only",
        "calibration_config_sha256": "a" * 64, "analysis_receipt_sha256": "b" * 64,
        "market_observations_sha256": "c" * 64, "formal_gate": gate,
        "market_assessments": assessments,
        "hypotheses": {market: {"supporting_hypothesis": "support", "counter_hypothesis": "counter", "invalidation_condition": "changed"} for market in assessments},
        "candidate_sha256": "d" * 64,
    })
    configured = load_calibration_config(CONFIG).rules
    event_by_id = {event.rule_id: event for event in events}
    complete_events = []
    for rule in configured:
        complete_events.append(event_by_id.get(rule.rule_id) or MachineRuleEvent(
            rule_id=rule.rule_id, triggered=False, not_triggered_reason="not_applicable",
            applicability="not_applicable", effect=rule.effect,
            target_market=rule.target_market or "handicap",
            target_selection=rule.target_selection or "pass",
        ))
    bundle = EvaluationBundleV3.model_validate({
        "match_id": "fixture", "cutoff_at": "2026-08-10T10:00:00+08:00",
        "ruleset_version": "1.9.0", "calibration_config_sha256": "a" * 64,
        "draft_input_sha256": "e" * 64, "market_observations_sha256": "c" * 64,
        "feature_snapshot_sha256": "f" * 64, "profile_chain": ["global"],
        "competition_profile": "global", "formal_gate": gate,
        "market_assessments": assessments, "features": {},
        "events": [event.model_dump(mode="json") for event in complete_events], "bundle_sha256": "1" * 64,
    })
    return draft, bundle


def _triggered(rule_id: str, selection: str, snapshot: str, *, market: str = "one_x_two", correlation: str = "") -> MachineRuleEvent:
    return MachineRuleEvent(
        rule_id=rule_id, triggered=True, applicability="applicable", effect="ranking",
        target_market=market, target_selection=selection, source_snapshot_ids=[snapshot],
        source_provider_ids=[snapshot.split(":", 1)[0]],
        correlation_keys=[correlation] if correlation else [], threshold_observations={"met": True},
        supporting_evidence=["threshold met"], counter_evidence=["manual review"],
    )


def _adopt(rule_id: str) -> ReasoningDisposition:
    return ReasoningDisposition.model_validate({
        "rule_id": rule_id, "disposition": {"disposition": "adopted"},
        "hypothesis_a": "support", "hypothesis_b": "counter",
        "supporting_evidence": ["evidence"], "counter_evidence": ["counter"],
        "invalidation_condition": "input changes", "actor": "lcz",
    })


def test_single_adopted_rule_cannot_replace_first_choice() -> None:
    event = _triggered("draw-kelly-parity-v1", "draw", "macau:s1")
    draft, bundle = _contract_eight_models([event])
    outlook = build_outlook_v6(draft, bundle, [_adopt(event.rule_id)])
    assert outlook.final_rankings["one_x_two"] == ["home", "draw", "away"]


def test_two_independent_adopted_rules_can_replace_first_choice() -> None:
    events = [
        _triggered("draw-kelly-parity-v1", "draw", "macau:s1"),
        _triggered("hidden-draw-away-cut-v1", "draw", "bet365:s2"),
    ]
    draft, bundle = _contract_eight_models(events)
    outlook = build_outlook_v6(draft, bundle, [_adopt(item.rule_id) for item in events])
    assert outlook.final_rankings["one_x_two"][0] == "draw"


def test_triggered_rule_on_pass_market_cannot_create_ranking() -> None:
    event = _triggered("total-goals-cross-market-v1", "under", "macau:t1", market="total_goals")
    draft, bundle = _contract_eight_models([event])
    outlook = build_outlook_v6(draft, bundle, [_adopt(event.rule_id)])
    assert "total_goals" not in outlook.final_rankings
    assert outlook.market_statuses["total_goals"] == "pass"


def test_triggered_rule_requires_disposition() -> None:
    event = _triggered("draw-kelly-parity-v1", "draw", "macau:s1")
    draft, bundle = _contract_eight_models([event])
    try:
        build_outlook_v6(draft, bundle, [])
    except ValueError as exc:
        assert "缺少人工处置" in str(exc)
    else:
        raise AssertionError("triggered rule without disposition must fail closed")
