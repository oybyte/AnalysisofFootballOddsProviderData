from __future__ import annotations

from pathlib import Path
import shutil

import pytest
import yaml

from odds_journal.ai_governance import active_config, activate_config, sandbox_run, validate_config


REPOSITORY = Path(__file__).resolve().parents[1]


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    shutil.copytree(REPOSITORY / "ai", root / "ai")
    return root


def _config(root: Path) -> Path:
    manifest = yaml.safe_load((root / "ai/desktop-agent-manifest.yml").read_text(encoding="utf-8"))
    assets = {item["path"]: item["content_sha256"] for item in manifest["trusted_ai_assets"]}
    payload = {
        "config_id": "fake-pilot", "research_track": "pilot", "provider_id": "fake-offline", "model_id": "fixture-v1",
        "prompt_manifest": [
            {"stage": stage, "path": path, "sha256": assets[path]}
            for stage, path in (
                ("facts", "ai/ai-experiment-prompts/v1/stage1_facts.md"),
                ("rules", "ai/ai-experiment-prompts/v1/stage2_rules.md"),
                ("cases", "ai/ai-experiment-prompts/v1/stage3_cases.md"),
                ("prediction", "ai/ai-experiment-prompts/v1/stage4_prediction.md"),
                ("risk", "ai/ai-experiment-prompts/v1/stage5_risk.md"),
            )
        ],
        "case_profile": "exploratory_research", "reasoning_profile_id": "research-v1",
        "reasoning_profile_sha256": assets["ai/ai-experiment-profiles/v1.yml"],
        "output_schema_sha256": assets["ai/ai-experiment-schemas/outlook-v1.json"],
        "evaluation_algorithm_version": "v1",
        "outbound_data_policy_sha256": assets["ai/ai-experiment-policies/fake-offline.yml"],
        "budget": {"max_total_tokens": 100, "max_total_cost": 0, "currency": "USD"},
        "runtime_limits": {"stage_timeout_seconds": 5, "max_retries_per_stage": 0},
    }
    path = root / "config.yml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path


def test_config_activation_copies_hash_pinned_assets(tmp_path: Path) -> None:
    root = _root(tmp_path)
    config = _config(root)
    checked = validate_config(root, config)
    active = activate_config(root, config, approved_by="lcz")
    assert active.snapshot_sha256 == checked.snapshot_sha256
    assert active_config(root) == active
    assert (root / active.snapshot_path / "assets/ai/ai-experiment-prompts/v1/stage1_facts.md").is_file()
    assert activate_config(root, config, approved_by="lcz").revision == active.revision


def test_sandbox_rejects_real_and_accepts_synthetic_fixture(tmp_path: Path) -> None:
    root = _root(tmp_path)
    config = _config(root)
    fixture = root / "tests/fixtures/ai/sample.yml"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("synthetic: true\nfixture: {id: demo}\n", encoding="utf-8")
    assert sandbox_run(root, config, fixture)["status"] == "completed"
    real = root / "matches/demo.yml"
    real.parent.mkdir()
    real.write_text("synthetic: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tests/fixtures"):
        sandbox_run(root, config, real)
