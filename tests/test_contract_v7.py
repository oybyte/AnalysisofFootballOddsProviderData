from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import shutil

import pytest
from typer.testing import CliRunner

from odds_journal.calibration import load_calibration_config
from odds_journal.cli import app
from odds_journal.models import MatchMetadata
from odds_journal.observations import prediction_eligible_market_observations
from odds_journal.rule_engine.evaluation_v5 import (
    AnalysisDraftInputV2,
    build_outlook_v5,
    evaluate_draft_v2,
)

from .test_contract_v3 import matrix
from .test_analysis_context import factual_match
from .test_models import base_metadata


CONFIG = Path("knowledge/rule-proposals/football-analysis/1.8.0/calibration/football-analysis-v7.yml")
CUTOFF = datetime.fromisoformat("2026-08-05T17:48:00+08:00")


def _matrix_without_manual_total() -> dict:
    raw = matrix().model_dump(mode="json")
    for row in raw["rows"]:
        cell = row["market_scores"]["total_goals"]
        if cell["status"] == "assessed":
            cell["scores"] = {"over": 0.0, "under": 0.0}
    return raw


def _draft(status: str = "pass") -> AnalysisDraftInputV2:
    total = {"status": "pass", "pass_reasons": ["insufficient_exact_series"]}
    if status == "assessed":
        total = {"status": "assessed", "side": "under"}
    return AnalysisDraftInputV2.model_validate({
        "analysis_input_mode": "market_only",
        "baseline_gate": {
            "facts_status": "complete", "theoretical_positioning": "established",
            "market_relation": "aligned", "decision": "ready", "fact_refs": ["fact:market"],
        },
        "score_matrix": _matrix_without_manual_total(),
        "baseline_output": {
            "asian_line_display": "主让半球", "asian_home_line": -0.5,
            "fixed_handicap_home_line": -1, "fixed_handicap_source_type": "official",
        },
        "total_goals": total, "fact_refs": ["fact:market"],
        "hypothesis_a": "价格可能延续。", "hypothesis_b": "价格可能反转。",
    })


def _observation(provider: str, at: str, over: float, under: float, *, line: float = 2.5) -> dict:
    return {
        "observation_id": f"{provider}-{at[-8:-6]}{at[-5:-3]}", "provider_id": provider,
        "market_scope": "full_time", "quote_role": "main_line", "normalized_line": line,
        "odds_format": "hong_kong", "observed_at": at,
        "normalized_prices": {"over": over, "under": under},
    }


def _metadata() -> MatchMetadata:
    return MatchMetadata.model_validate(base_metadata() | {
        "schema_version": 2, "competition_code": "EPL", "competition": "英超", "market_snapshots": [],
    })


def test_contract_seven_rejects_manual_total_goals_scores() -> None:
    raw = _draft().model_dump(mode="json")
    raw["score_matrix"]["rows"][1]["market_scores"]["total_goals"]["scores"] = {"over": -0.5, "under": 0.5}
    with pytest.raises(ValueError, match="禁止人工总进球方向评分"):
        AnalysisDraftInputV2.model_validate(raw)


def test_contract_seven_passes_mixed_or_insufficient_series(monkeypatch, tmp_path: Path) -> None:
    from odds_journal.rule_engine import evaluation_v5

    # Only one three-node provider qualifies for under; the second provider is
    # a qualified over sequence. Either condition must prevent a direction.
    observations = [
        _observation("macau", "2026-08-04T10:00:00+08:00", 0.90, 1.10),
        _observation("macau", "2026-08-04T12:00:00+08:00", 0.95, 1.04),
        _observation("macau", "2026-08-04T14:00:00+08:00", 1.00, 1.00),
        _observation("william-hill", "2026-08-04T10:00:00+08:00", 1.10, 0.90),
        _observation("william-hill", "2026-08-04T12:00:00+08:00", 1.04, 0.95),
        _observation("william-hill", "2026-08-04T14:00:00+08:00", 1.00, 1.00),
    ]
    monkeypatch.setattr(evaluation_v5, "prediction_eligible_market_observations", lambda *args, **kwargs: observations)
    bundle = evaluate_draft_v2(
        root=tmp_path, match_id="match-v7", metadata=_metadata(), cutoff=CUTOFF,
        config=load_calibration_config(CONFIG), calibration_config_sha256="a" * 64,
        market_snapshot_sha256="b" * 64, draft=_draft("assessed"), ruleset_version="1.8.0",
    )
    assert bundle.total_goals_status == "pass"
    assert "qualified_opposite_series" in bundle.total_goals_pass_reasons
    outlook = build_outlook_v5(_draft("assessed"), bundle, [])
    assert outlook.schema_version == 5
    assert outlook.total_goals is None
    assert outlook.score_candidates == []
    assert outlook.market_statuses["total_goals"] == "pass"


def test_contract_seven_requires_same_line_for_provider_confirmation(monkeypatch, tmp_path: Path) -> None:
    from odds_journal.rule_engine import evaluation_v5

    observations = [
        _observation("macau", "2026-08-04T10:00:00+08:00", 1.10, 0.90),
        _observation("macau", "2026-08-04T12:00:00+08:00", 1.04, 0.95),
        _observation("macau", "2026-08-04T14:00:00+08:00", 1.00, 1.00),
        _observation("william-hill", "2026-08-04T10:00:00+08:00", 1.10, 0.90, line=3.5),
        _observation("william-hill", "2026-08-04T12:00:00+08:00", 1.04, 0.95, line=3.5),
        _observation("william-hill", "2026-08-04T14:00:00+08:00", 1.00, 1.00, line=3.5),
    ]
    monkeypatch.setattr(evaluation_v5, "prediction_eligible_market_observations", lambda *args, **kwargs: observations)
    bundle = evaluate_draft_v2(
        root=tmp_path, match_id="match-v7", metadata=_metadata(), cutoff=CUTOFF,
        config=load_calibration_config(CONFIG), calibration_config_sha256="a" * 64,
        market_snapshot_sha256="b" * 64, draft=_draft("assessed"), ruleset_version="1.8.0",
    )
    assert bundle.total_goals_status == "pass"
    assert "insufficient_independent_exact_series" in bundle.total_goals_pass_reasons


def test_contract_seven_builds_a_whole_analysis_pass(monkeypatch, tmp_path: Path) -> None:
    from odds_journal.rule_engine import evaluation_v5

    monkeypatch.setattr(evaluation_v5, "prediction_eligible_market_observations", lambda *args, **kwargs: [])
    raw = _draft().model_dump(mode="json")
    raw["baseline_gate"].update({
        "facts_status": "conflicted", "decision": "pass", "reasons": ["facts_conflicted"],
    })
    draft = AnalysisDraftInputV2.model_validate(raw)
    bundle = evaluate_draft_v2(
        root=tmp_path, match_id="match-v7", metadata=_metadata(), cutoff=CUTOFF,
        config=load_calibration_config(CONFIG), calibration_config_sha256="a" * 64,
        market_snapshot_sha256="b" * 64, draft=draft, ruleset_version="1.8.0",
    )
    outlook = build_outlook_v5(draft, bundle, [])
    assert outlook.data_mode == "pass"
    assert set(outlook.market_statuses.values()) == {"pass"}


def test_exact_observation_must_be_received_by_analysis_cutoff(monkeypatch, tmp_path: Path) -> None:
    from odds_journal import observations

    item = {
        "match_id": "match-v7", "market": "total_goals", "availability_status": "available",
        "time_precision": "exact", "prediction_eligible": True, "observation_id": "late-import",
        "observed_at": "2026-08-05T10:00:00+08:00", "received_at": "2026-08-05T12:00:00+08:00",
    }
    monkeypatch.setattr(observations, "_active_observations", lambda root: [item])
    monkeypatch.setattr(observations, "_conflict_index", lambda active, resolutions: ({}, {}))
    monkeypatch.setattr(observations, "_conflict_resolutions", lambda root: [])
    assert prediction_eligible_market_observations(
        tmp_path, match_id="match-v7", market="total_goals",
        cutoff=datetime.fromisoformat("2026-08-05T11:00:00+08:00"),
    ) == []


def test_contract_seven_proposal_start_returns_v7(project_root: Path, monkeypatch) -> None:
    repository = Path(__file__).resolve().parents[1]
    proposal_root = project_root / "knowledge" / "rule-proposals" / "football-analysis"
    proposal_root.mkdir(parents=True)
    shutil.copytree(repository / "knowledge" / "rule-proposals" / "football-analysis" / "1.8.0", proposal_root / "1.8.0")
    path = factual_match(project_root)
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(app, [
        "agent", "start", str(path), "--ruleset", "football-analysis@1.8.0", "--proposal",
        "--as-of", "2026-07-30T17:30:00+08:00", "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["analysis_receipt_schema_version"] == 7
    assert payload["analysis_outlook_schema_version"] == 5
    assert payload["calibration_contract_version"] == 7
