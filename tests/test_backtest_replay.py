from __future__ import annotations

from pathlib import Path

import yaml
import pytest

from odds_journal.backtest import (
    BacktestLabelManifestV1,
    BacktestDatasetManifestV1,
    BacktestFixtureEligibilityV1,
    BacktestMarketEligibilityV1,
    BacktestPredictionManifestV1,
    DeterministicReplayPredictionV1,
    _finalize,
    evaluate,
    replay,
)


def _prediction(*, market: str, decision: dict, selection: str = "home_handicap") -> DeterministicReplayPredictionV1:
    return _finalize(DeterministicReplayPredictionV1, {
        "match_id": "fixture-a", "fixture_fingerprint": "fixture-cluster-a", "market": market,
        "phase": "late", "as_of": "2026-08-01T10:00:00+08:00", "status": "assessed",
        "selection": selection, "frozen_decision": decision,
    }, "prediction_sha256")


def _evaluate(tmp_path: Path, predictions: list[DeterministicReplayPredictionV1], score: str) -> list[dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    prediction_manifest = _finalize(BacktestPredictionManifestV1, {
        "dataset_manifest_sha256": "a" * 64,
        "predictions": [item.model_dump(mode="json") for item in predictions],
    }, "prediction_manifest_sha256")
    prediction_path = tmp_path / "prediction-manifest.yml"
    prediction_path.write_text(yaml.safe_dump(prediction_manifest.model_dump(mode="json"), allow_unicode=True), encoding="utf-8")
    labels = _finalize(BacktestLabelManifestV1, {
        "prediction_manifest_sha256": prediction_manifest.prediction_manifest_sha256,
        "labels": [{"match_id": "fixture-a", "score": score, "status": "available"}],
    }, "label_manifest_sha256")
    label_path = tmp_path / "label-manifest.yml"
    label_path.write_text(yaml.safe_dump(labels.model_dump(mode="json"), allow_unicode=True), encoding="utf-8")
    _, outcome = evaluate(prediction_path, label_path)
    return outcome.outcomes


def test_replay_settles_quarter_handicap_and_total_score_markets(tmp_path: Path) -> None:
    rows = _evaluate(tmp_path, [
        _prediction(market="asian_handicap", decision={"home_line": -0.25}),
        _prediction(market="total_goals", selection="range", decision={"minimum": 2, "maximum": 3}),
        _prediction(market="score", selection="candidates", decision={"candidates": ["2-1", "1-1"]}),
    ], "2-1")
    assert [item["outcome"] for item in rows] == ["full_win", "correct", "correct"]


def test_replay_settles_all_asian_outcome_classes(tmp_path: Path) -> None:
    expected = {
        ("2-0", -0.25): "full_win", ("0-0", 0.25): "half_win",
        ("0-0", 0.0): "push", ("0-0", -0.25): "half_loss", ("0-1", -0.25): "full_loss",
    }
    for (score, line), outcome in expected.items():
        rows = _evaluate(tmp_path / (score + str(line)).replace("-", "_"), [_prediction(market="asian_handicap", decision={"home_line": line})], score)
        assert rows[0]["outcome"] == outcome


def test_replay_fails_closed_to_pass_without_complete_frozen_inputs(tmp_path: Path) -> None:
    fixture = BacktestFixtureEligibilityV1(
        match_id="fixture-a", fixture_fingerprint="fixture-cluster-a", kickoff_at="2026-08-01T12:00:00+08:00",
        status="partial", reasons=["missing_complete_frozen_replay_inputs"],
        markets=[BacktestMarketEligibilityV1(
            market="european_odds", phase="late", as_of="2026-08-01T11:55:00+08:00", status="eligible",
        )],
    )
    manifest = _finalize(BacktestDatasetManifestV1, {
        "backtest_id": "frozen-input-gate", "mode": "historical_reproduction", "ruleset": "football-analysis@1.8.0",
        "ruleset_sha256": "a" * 64, "fixtures": [fixture.model_dump(mode="json")],
    }, "manifest_sha256")
    path = tmp_path / "dataset-manifest.yml"
    path.write_text(yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True), encoding="utf-8")
    _, prediction_manifest = replay(tmp_path, path)
    assert prediction_manifest.predictions[0].status == "pass"
    # Exact retry is idempotent, but a pre-existing divergent stage is immutable.
    assert replay(tmp_path, path)[1] == prediction_manifest
    (tmp_path / "prediction-manifest.yml").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="已封存"):
        replay(tmp_path, path)
