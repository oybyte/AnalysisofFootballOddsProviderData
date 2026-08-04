from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import json
import shutil

import pytest
import yaml
from typer.testing import CliRunner

from odds_journal.cli import app
from odds_journal.experiments import (
    ExperimentCalibrationConfig,
    _directory_hash,
    evaluate_experiment_rules,
    experiment_feature_snapshot,
)
from odds_journal.models import MarketSnapshot
from odds_journal.markdown import MatchDocument
from odds_journal.observations import MatchDataBundleV1, ingest_bundle
from .test_analysis_context import factual_match
from .test_contract_v4 import _publish_contract_four


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "knowledge/rule-proposals/football-analysis/1.6.0/calibration/football-analysis-v5.yml"


def load_config() -> ExperimentCalibrationConfig:
    return ExperimentCalibrationConfig.model_validate(yaml.safe_load(CONFIG.read_text(encoding="utf-8")))


def snapshot(identity: str, *, line: float, over: float, under: float, phase: str, captured_at: datetime) -> MarketSnapshot:
    return MarketSnapshot.model_validate(
        {
            "snapshot_id": identity,
            "market": "total_goals",
            "phase": phase,
            "captured_at": captured_at,
            "provider_id": "macau",
            "source_ref": f"source:{identity}",
            "odds_format": "hong_kong",
            "raw_values": {"line": str(line), "over_water": str(over), "under_water": str(under)},
            "normalized_values": {"line": line, "over_water": over, "under_water": under},
        }
    )


def test_contract5_profiles_and_rule_inventory() -> None:
    config = load_config()
    assert len(config.rules) == 12
    assert config.profile_chain_for("competition-u-388f03e8f4") == ["global", "low-goal", "nordic-low-heat"]
    assert config.profile_chain_for("KOR-K1") == ["global", "low-goal", "korea-low-goal"]
    assert config.profile_chain_for("UNKNOWN") == ["global"]


def test_same_line_threshold_and_external_override_are_audited() -> None:
    config = load_config()
    kickoff = datetime.fromisoformat("2026-08-04T20:00:00+08:00")
    metadata = SimpleNamespace(
        kickoff_at=kickoff,
        tags=[],
        market_snapshots=[
            snapshot("tg-open", line=2.5, over=0.90, under=0.90, phase="opening", captured_at=kickoff - timedelta(hours=5)),
            snapshot("tg-mid", line=2.5, over=0.82, under=0.98, phase="mid", captured_at=kickoff - timedelta(hours=2)),
            snapshot("tg-late", line=2.5, over=0.75, under=1.05, phase="late", captured_at=kickoff - timedelta(minutes=70)),
        ],
    )
    features = experiment_feature_snapshot(metadata, kickoff - timedelta(minutes=60))
    events = {item.rule_id: item for item in evaluate_experiment_rules(config, "UNKNOWN", features)}
    assert events["tg-same-line-water-defense-v1"].status == "triggered"
    assert events["tg-same-line-water-defense-v1"].signal_direction == "over"


def test_line_drop_override_only_when_complete_trigger() -> None:
    config = load_config()
    features = {
        "total_series": [
            {"provider": "macau", "market": "total_goals", "odds_format": "hong_kong", "line": 2.5, "snapshot_ids": ["a"], "captured_at": ["2026-08-04T12:00:00+08:00"], "values": {"over_water": [0.81], "under_water": [1.01]}, "changes": {"over_water": None, "under_water": None}, "three_nodes": False},
            {"provider": "macau", "market": "total_goals", "odds_format": "hong_kong", "line": 2.0, "snapshot_ids": ["b"], "captured_at": ["2026-08-04T18:00:00+08:00"], "values": {"over_water": [0.84], "under_water": [0.96]}, "changes": {"over_water": None, "under_water": None}, "three_nodes": False},
        ],
        "asian_series": [],
        "euro_series": [],
        "kelly_series": [],
        "tags": [],
        "kickoff_at": "2026-08-04T20:00:00+08:00",
        "cutoff": "2026-08-04T19:00:00+08:00",
        "fund_flow_status": "unknown",
        "causal_attribution": "unverified",
    }
    event = {item.rule_id: item for item in evaluate_experiment_rules(config, "UNKNOWN", features)}[
        "tg-line-drop-over-price-divergence-v1"
    ]
    assert event.status == "triggered"
    assert event.suppressed_external_rule_ids == ["legacy-total-line-drop-interpretation"]


def test_override_cycle_is_rejected() -> None:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    first, second = raw["rules"][0], raw["rules"][1]
    first.update(supersedes_rule_ids=[second["rule_id"]], override_mode="replace", override_scope="total_goals")
    second.update(supersedes_rule_ids=[first["rule_id"]], override_mode="replace", override_scope="total_goals")
    with pytest.raises(ValueError, match="循环"):
        ExperimentCalibrationConfig.model_validate(raw)


def test_activation_metadata_does_not_change_snapshot_content_hash(tmp_path: Path) -> None:
    (tmp_path / "manifest.yml").write_text("schema_version: 6\n", encoding="utf-8")
    before = _directory_hash(tmp_path)
    (tmp_path / "EXPERIMENT-ACTIVATION.yml").write_text("status: active\n", encoding="utf-8")
    assert _directory_hash(tmp_path) == before


def test_agent_start_pins_active_experiment_without_changing_official_ruleset(project_root, monkeypatch) -> None:
    _publish_contract_four(project_root, monkeypatch)
    shutil.copytree(
        ROOT / "knowledge/rule-experiments",
        project_root / "knowledge/rule-experiments",
    )
    path = factual_match(project_root)
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(
        app,
        ["agent", "start", str(path), "--as-of", "2026-07-30T17:30:00+08:00", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ruleset"] == "football-analysis@1.5.0"
    assert payload["experiment"]["active"] is True
    assert payload["experiment"]["ruleset"] == "football-analysis@1.6.0"
    assert payload["experiment"]["experiment_revision"] == 2


def test_agent_start_freezes_normalized_observations_in_experiment_receipt_v2(project_root, monkeypatch) -> None:
    _publish_contract_four(project_root, monkeypatch)
    shutil.copytree(
        ROOT / "knowledge/rule-experiments",
        project_root / "knowledge/rule-experiments",
    )
    path = factual_match(project_root)
    metadata = MatchDocument.load(path).metadata
    bundle = MatchDataBundleV1.model_validate({
        "schema_version": 1,
        "bundle_id": "experiment-observation-freeze",
        "fixture": {
            "competition_code": metadata.competition_code,
            "competition": metadata.competition,
            "home_team": metadata.home_team,
            "away_team": metadata.away_team,
            "kickoff_at": metadata.kickoff_at.isoformat(),
            "timezone": metadata.timezone,
        },
        "market_data": {
            "source_kind": "user_confirmed_text",
            "capture_batch_id": "experiment-observation-freeze",
            "total_goals_summary": [{
                "provider_id": "macau",
                "provider_name": "澳*",
                "opening": {"over": "0.81", "line": "2.5", "under": "1.01"},
                "current": {"over": "0.84", "line": "2", "under": "0.96"},
            }],
        },
    })
    ingest_bundle(
        project_root,
        bundle,
        match_path=path,
        received_at=datetime.fromisoformat("2026-07-30T17:20:00+08:00"),
    )
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(
        app,
        ["agent", "start", str(path), "--as-of", "2026-07-30T17:30:00+08:00", "--json"],
    )
    assert result.exit_code == 0, result.output
    receipt = yaml.safe_load(
        (project_root / "raw" / "matches" / metadata.match_id / "experiment-analysis-receipt.yml").read_text(encoding="utf-8")
    )
    assert receipt["schema_version"] == 2
    assert len(receipt["observation_set_sha256"]) == 64
    assert len(receipt["market_feature_snapshot_sha256"]) == 64
