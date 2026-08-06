from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odds_journal.ai_governance import activate_config
from odds_journal.ai_research import (
    AIExperimentStudyV1,
    evaluate,
    register_study,
    run,
)
from odds_journal.models import AnalysisOutlook, MatchStatus

from .test_ai_governance import _config, _root


def _setup_locked_match(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, SimpleNamespace, SimpleNamespace]:
    import odds_journal.ai_research as research

    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    metadata = SimpleNamespace(
        match_id="ai-test-match",
        status=MatchStatus.LOCKED,
        locked_at=now - timedelta(minutes=5),
        kickoff_at=now + timedelta(hours=2),
        score=None,
        result_source=None,
        result_recorded_at=None,
    )
    document = SimpleNamespace(metadata=metadata, sections={"prematch-reasoning": ""})
    candidate = SimpleNamespace(
        receipt_id="lock-ai-test", receipt_sha256="a" * 64,
        data_cutoff_at=now - timedelta(minutes=10),
    )
    official = {
        "analysis_receipt_sha256": "b" * 64,
        "analysis_outlook_sha256": "c" * 64,
        "case_receipt_sha256": "d" * 64,
        "lock_candidate_sha256": "a" * 64,
        "prematch_content_sha256": "e" * 64,
        "official_evaluation_bundle_sha256": "f" * 64,
        "case_context_sha256": "1" * 64,
    }
    monkeypatch.setattr(research.MatchDocument, "load", lambda _: document)
    monkeypatch.setattr(research, "_official_inputs", lambda *_: (candidate, official, {"cases": SimpleNamespace(selected_cases=[])}))
    monkeypatch.setattr(research, "market_feature_snapshot", lambda *_: {"feature_snapshot_sha256": "f" * 64, "observation_set_sha256": "2" * 64})
    path = root / "matches" / "ai-test.md"
    path.parent.mkdir(parents=True)
    path.write_text("formal-match-is-untouched\n", encoding="utf-8")
    return path, metadata, document


def test_diagnostic_run_is_sealed_and_never_changes_formal_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    activate_config(root, _config(root), approved_by="lcz")
    path, _, _ = _setup_locked_match(monkeypatch, root)

    target, receipt = run(root, path, role="diagnostic", nonce="fixture")

    assert receipt.run_role == "diagnostic"
    assert (target / "receipt.yml").is_file()
    assert (target / "bundle.yml").is_file()
    assert (target / "run-manifest.yml").is_file()
    assert path.read_text(encoding="utf-8") == "formal-match-is-untouched\n"
    assert run(root, path, role="diagnostic", nonce="fixture")[0] == target


def test_run_rejects_kickoff_passed_and_tampered_snapshot_asset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    active = activate_config(root, _config(root), approved_by="lcz")
    path, metadata, _ = _setup_locked_match(monkeypatch, root)
    metadata.kickoff_at = datetime.now(ZoneInfo("Asia/Shanghai")) - timedelta(seconds=1)
    with pytest.raises(ValueError, match="开赛"):
        run(root, path, role="diagnostic", nonce="late")
    metadata.kickoff_at = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(hours=2)
    asset = root / active.snapshot_path / "assets/ai/ai-experiment-prompts/v1/stage1_facts.md"
    asset.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="资产哈希"):
        run(root, path, role="diagnostic", nonce="tampered")


def test_primary_rejects_pilot_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    active = activate_config(root, _config(root), approved_by="lcz")
    path, _, _ = _setup_locked_match(monkeypatch, root)
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    study = AIExperimentStudyV1(
        study_id="pilot-study", config_snapshot_sha256=active.snapshot_sha256, registered_by="lcz", registered_at=now,
        official_baseline_schema_sha256=research_schema_hash(), stopping_conditions=["fixture"], study_sha256="0" * 64,
    )
    register_study(root, study)
    with pytest.raises(ValueError, match="confirmatory"):
        run(root, path, role="primary", study_id="pilot-study")


def test_primary_requires_confirmatory_study_and_claim_is_unique(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    config = _config(root)
    import yaml

    raw = yaml.safe_load(config.read_text(encoding="utf-8"))
    raw["config_id"] = "fake-confirmatory"
    raw["research_track"] = "confirmatory"
    raw["case_profile"] = "strict_validation"
    config.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    active = activate_config(root, config, approved_by="lcz")
    path, _, _ = _setup_locked_match(monkeypatch, root)
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    study = AIExperimentStudyV1(
        study_id="fixture-study", config_snapshot_sha256=active.snapshot_sha256, registered_by="lcz", registered_at=now,
        official_baseline_schema_sha256=research_schema_hash(), stopping_conditions=["fixture"], study_sha256="0" * 64,
    )
    register_study(root, study)

    _, receipt = run(root, path, role="primary", study_id="fixture-study")
    assert receipt.run_role == "primary"
    assert run(root, path, role="primary", study_id="fixture-study")[1] == receipt
    replacement = AIExperimentStudyV1(
        study_id="replacement-study", config_snapshot_sha256=active.snapshot_sha256, registered_by="lcz", registered_at=now,
        official_baseline_schema_sha256=research_schema_hash(), stopping_conditions=["fixture"], study_sha256="0" * 64,
    )
    register_study(root, replacement)
    with pytest.raises(ValueError, match="Primary claim"):
        run(root, path, role="primary", study_id="replacement-study")


def test_stage_failure_is_sealed_and_does_not_release_primary_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    activate_config(root, _config(root), approved_by="lcz")
    path, _, _ = _setup_locked_match(monkeypatch, root)
    import odds_journal.ai_research as research

    monkeypatch.setattr(research, "_compile_stages", lambda **_: (_ for _ in ()).throw(RuntimeError("fake failure")))
    target, _ = run(root, path, role="diagnostic", nonce="failure")
    assert "failed" in (target / "run-manifest.yml").read_text(encoding="utf-8")
    assert path.read_text(encoding="utf-8") == "formal-match-is-untouched\n"


def test_outcome_is_independent_and_not_evaluated_without_ai_outlook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    activate_config(root, _config(root), approved_by="lcz")
    path, metadata, _ = _setup_locked_match(monkeypatch, root)
    _, receipt = run(root, path, role="diagnostic", nonce="outcome")
    metadata.status = MatchStatus.FINISHED
    metadata.score = "1-0"
    metadata.result_source = "fixture-result"
    metadata.result_recorded_at = datetime.now(ZoneInfo("Asia/Shanghai"))
    target, outcome = evaluate(root, path, receipt.receipt_id)
    assert target.is_file()
    assert outcome.status == "not_evaluated"
    assert outcome.markets == {}
    assert path.read_text(encoding="utf-8") == "formal-match-is-untouched\n"


def test_sealed_run_tampering_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    activate_config(root, _config(root), approved_by="lcz")
    path, _, _ = _setup_locked_match(monkeypatch, root)
    target, _ = run(root, path, role="diagnostic", nonce="sealed")
    (target / "bundle.yml").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="封存文件哈希"):
        run(root, path, role="diagnostic", nonce="sealed")


def research_schema_hash() -> str:
    from odds_journal.ledger import sha256_json

    return sha256_json(AnalysisOutlook.model_json_schema())
