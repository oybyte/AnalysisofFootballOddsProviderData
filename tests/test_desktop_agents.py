from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import os

import pytest
import yaml
import odds_journal.desktop_agents as desktop_agents

from odds_journal.desktop_agents import (
    CertificationResult,
    DesktopManifest,
    TraeCNLoadValidation,
    _select_registry_candidate,
    _copy_file_atomic,
    changes,
    configure_product,
    load_local_state,
    load_manifest,
    sync_agents,
    _copy_tree_atomic,
    _validate_skill_target,
)


REPOSITORY = Path(__file__).resolve().parents[1]


def test_manifest_v3_is_single_source_of_product_versions() -> None:
    manifest = load_manifest(REPOSITORY)
    assert manifest.schema_version == 3
    assert manifest.release_channel == "experimental"
    assert manifest.cli.package == "odds-journal"
    assert manifest.supported_contracts.case_receipt_schema_versions == [1, 2, 3]
    assert manifest.supported_contracts.experiment_analysis_receipt_versions == [1, 2, 3, 4]
    assert manifest.supported_contracts.experiment_advisory_receipt_versions == [1]
    assert {item.product_id for item in manifest.products} == {
        "codex-desktop",
        "trae-cn",
        "workbuddy",
        "teloswork",
    }
    trae = next(item for item in manifest.products if item.product_id == "trae-cn")
    assert trae.adapter == "project-instructions"
    assert trae.required_target == "instruction-target"
    assert trae.certification_mode == "manual"
    assert "3.3.84" in trae.tested_versions
    assert {item.kind for item in manifest.trusted_ai_assets} == {
        "prompt", "outbound_policy", "output_schema", "reasoning_profile",
    }


def test_manifest_schema_1_remains_read_compatible(tmp_path: Path) -> None:
    (tmp_path / "ai").mkdir()
    old = yaml.safe_load(
        (REPOSITORY / "ai/desktop-agent-manifest.yml").read_text(encoding="utf-8")
    )
    converted = {
        "schema_version": 1,
        "manifest_id": old["manifest_id"],
        "workflow_version": "1.0.0",
        "cli_package": old["cli"]["package"],
        "cli_version": old["cli"]["version"],
        "active_ruleset": "football-analysis@1.1.0",
        "trusted_instructions": old["trusted_instructions"],
        "products": [
            {
                "product_id": item["product_id"],
                "display_name": item["display_name"],
                "minimum_version": item["minimum_version"],
                "tested_version": item["tested_versions"][0]
                if item["tested_versions"]
                else None,
                "adapter": item["adapter"],
            }
            for item in old["products"]
        ],
        "platform_certification": old["platform_certification"],
    }
    (tmp_path / "ai/desktop-agent-manifest.yml").write_text(
        yaml.safe_dump(converted, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    assert load_manifest(tmp_path).schema_version == 2


def test_configure_records_only_local_absolute_paths(tmp_path: Path) -> None:
    shutil.copytree(REPOSITORY / "ai", tmp_path / "ai")
    root = tmp_path / "workbuddy-skills"
    payload = configure_product(tmp_path, "workbuddy", root)
    state = load_local_state(tmp_path)
    assert Path(payload["skill_root"]).is_absolute()
    assert state.products["workbuddy"].installed_skill_path == str(
        root.resolve() / "football-odds-journal"
    )
    assert not (tmp_path / "integrations/desktop-agent-release.yml").exists()


def test_trae_cn_configuration_requires_external_instruction_target(tmp_path: Path) -> None:
    shutil.copytree(REPOSITORY / "ai", tmp_path / "ai")
    installation = tmp_path.parent / "Trae CN"
    installation.mkdir(exist_ok=True)
    target = tmp_path.parent / "trae-cn-project" / "PROJECT_INSTRUCTIONS.md"
    target.parent.mkdir(exist_ok=True)
    payload = configure_product(
        tmp_path,
        "trae-cn",
        installation_path=installation,
        instruction_target=target,
    )
    assert payload["installation_path"] == str(installation.resolve())
    assert payload["instruction_target"] == str(target.resolve())
    assert payload["load_validation_path"] is None


def test_registry_selection_prefers_existing_highest_version_and_rejects_ties(tmp_path: Path) -> None:
    first = tmp_path / "one.exe"
    second = tmp_path / "two.exe"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    selected, status = _select_registry_candidate([
        {"display_name": "Trae CN (User)", "version": "3.3.84", "executable": str(first)},
        {"display_name": "Trae CN (User)", "version": "3.3.85", "executable": str(second)},
    ])
    assert status == "selected"
    assert selected and selected["executable"] == str(second)
    selected, status = _select_registry_candidate([
        {"display_name": "Trae CN", "version": "3.3.85", "executable": str(first)},
        {"display_name": "Trae CN", "version": "3.3.85", "executable": str(second)},
    ])
    assert selected is None
    assert status == "ambiguous_installation"


def test_trae_cn_load_validation_requires_all_client_checks() -> None:
    payload = {
        "product_version": "3.3.84",
        "platform": "windows",
        "workflow_version": "1.12.0",
        "tested_at": "2026-08-06T12:00:00+08:00",
        "tester": "lcz",
        "repo_commit": "a" * 40,
        "manifest_sha256": "a" * 64,
        "instruction_source_sha256": "b" * 64,
        "installation_path": "C:/Trae CN",
        "instruction_target": "C:/Projects/PROJECT_INSTRUCTIONS.md",
        "refresh_steps": ["first_open", "reopen", "refresh_after_change"],
        "evidence_sha256": ["c" * 64],
        "checks": [{"scenario_id": "instruction-loaded", "status": "passed"}],
        "status": "passed",
    }
    with pytest.raises(ValueError, match="全部唯一检查项"):
        TraeCNLoadValidation.model_validate(payload)


def test_telos_import_has_explicit_intermediate_state(tmp_path: Path) -> None:
    shutil.copytree(REPOSITORY / "ai", tmp_path / "ai")
    package = tmp_path / "dist/football-odds-journal.skill"
    package.parent.mkdir()
    package.write_bytes(b"test-package")
    payload = configure_product(
        tmp_path,
        "teloswork",
        None,
        confirm_import=True,
        imported_version="3.7.8",
    )
    assert payload["import_state"] == "imported_unverified"
    assert load_local_state(tmp_path).products["teloswork"].imported_version == "3.7.8"


def test_certification_pass_requires_all_five_unique_scenarios() -> None:
    base = {
        "schema_version": 1,
        "product_id": "workbuddy",
        "product_version": "5.3.5",
        "platform": "windows",
        "workflow_version": "1.1.0",
        "tested_at": datetime.fromisoformat("2026-07-30T12:00:00+08:00"),
        "tester": "lcz",
        "repo_commit": "a" * 40,
        "manifest_sha256": "a" * 64,
        "skill_sha256": "b" * 64,
        "instruction_sha256": {},
        "status": "passed",
        "checks": [{"scenario_id": "extraction-only", "status": "passed"}],
    }
    with pytest.raises(ValueError, match="对应 workflow"):
        CertificationResult.model_validate(base)


def test_teloswork_pass_requires_import_confirmation() -> None:
    checks = [
        {"scenario_id": item, "status": "passed"}
        for item in (
            "extraction-only",
            "governed-analysis",
            "degraded-or-pass",
            "failed-gate",
            "postmatch-review",
        )
    ]
    payload = {
        "schema_version": 1,
        "product_id": "teloswork",
        "product_version": "3.7.8",
        "platform": "windows",
        "workflow_version": "1.1.0",
        "tested_at": "2026-07-30T12:00:00+08:00",
        "tester": "lcz",
        "repo_commit": "a" * 40,
        "manifest_sha256": "a" * 64,
        "skill_sha256": "b" * 64,
        "instruction_sha256": {},
        "checks": checks,
        "status": "passed",
        "telos_import_confirmed": False,
    }
    with pytest.raises(ValueError, match="telosWork"):
        CertificationResult.model_validate(payload)


def test_workflow_1_10_certification_remains_read_compatible() -> None:
    checks = [
        {"scenario_id": item, "status": "passed"}
        for item in desktop_agents.HISTORICAL_CERTIFICATION_SCENARIOS["1.10.0"]
    ]
    result = CertificationResult.model_validate({
        "schema_version": 1,
        "product_id": "workbuddy",
        "product_version": "5.3.5",
        "platform": "windows",
        "workflow_version": "1.10.0",
        "tested_at": "2026-08-05T12:00:00+08:00",
        "tester": "lcz",
        "repo_commit": "a" * 40,
        "manifest_sha256": "a" * 64,
        "skill_sha256": "b" * 64,
        "instruction_sha256": {},
        "checks": checks,
        "status": "passed",
    })
    assert result.workflow_version == "1.10.0"


def test_sync_accepts_legacy_lcz_flags_but_rejects_other_approvers() -> None:
    with pytest.raises(ValueError, match="仅接受 lcz"):
        sync_agents(REPOSITORY, approved_by="agent", confirm_sync=True)


def test_automated_certification_requires_immutable_report() -> None:
    payload = {
        "product_id": "codex-desktop",
        "product_version": "current-session",
        "platform": "windows",
        "workflow_version": "1.12.0",
        "tested_at": "2026-08-05T12:00:00+08:00",
        "tester": "repository-automation",
        "repo_commit": "a" * 40,
        "manifest_sha256": "a" * 64,
        "skill_sha256": "b" * 64,
        "instruction_sha256": {},
        "certification_method": "automated",
        "checks": [{"scenario_id": item, "status": "passed"} for item in desktop_agents._required_certification_scenarios(REPOSITORY, "1.12.0")],
        "status": "passed",
    }
    with pytest.raises(ValueError, match="自动认证必须绑定"):
        CertificationResult.model_validate(payload)


def test_sync_rejects_broad_or_repository_skill_target() -> None:
    with pytest.raises(ValueError, match="不得位于项目仓库内"):
        _validate_skill_target(REPOSITORY, REPOSITORY / "football-odds-journal")
    with pytest.raises(ValueError, match="绝对"):
        _validate_skill_target(REPOSITORY, Path("football-odds-journal"))


def test_skill_copy_stages_on_the_target_volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "current.txt").write_text("new", encoding="utf-8")
    target = tmp_path / "external" / "football-odds-journal"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = tmp_path / "repository-transaction"
    calls: list[tuple[Path, Path]] = []
    original_replace = os.replace

    def track_replace(source_path: str | bytes | os.PathLike[str] | os.PathLike[bytes], target_path: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> None:
        calls.append((Path(source_path), Path(target_path)))
        original_replace(source_path, target_path)

    monkeypatch.setattr("odds_journal.desktop_agents.os.replace", track_replace)
    _copy_tree_atomic(source, target, transaction)

    assert (target / "current.txt").read_text(encoding="utf-8") == "new"
    assert not (target / "old.txt").exists()
    assert (transaction / "backups" / target.name / "old.txt").exists()
    assert calls
    assert all(source_path.parent == target_path.parent for source_path, target_path in calls)


def test_skill_copy_restores_target_when_activation_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "current.txt").write_text("new", encoding="utf-8")
    target = tmp_path / "external" / "football-odds-journal"
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old", encoding="utf-8")
    transaction = tmp_path / "repository-transaction"
    original_replace = os.replace
    attempts = 0

    def fail_activation(source_path: str | bytes | os.PathLike[str] | os.PathLike[bytes], target_path: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise OSError("simulated activation failure")
        original_replace(source_path, target_path)

    monkeypatch.setattr("odds_journal.desktop_agents.os.replace", fail_activation)
    with pytest.raises(OSError, match="simulated activation failure"):
        _copy_tree_atomic(source, target, transaction)

    assert (target / "old.txt").read_text(encoding="utf-8") == "old"
    assert not (target / "current.txt").exists()


def test_trae_cn_instruction_copy_is_atomic_and_hash_checked(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    source = root / "PROJECT_INSTRUCTIONS.md"
    source.write_text("new instructions", encoding="utf-8")
    target = tmp_path / "external" / "PROJECT_INSTRUCTIONS.md"
    target.parent.mkdir()
    target.write_text("old instructions", encoding="utf-8")
    transaction = root / ".odds-journal" / "agent-sync-backups" / "transaction"
    transaction.mkdir(parents=True)
    _copy_file_atomic(root, source, target, transaction)
    assert target.read_text(encoding="utf-8") == "new instructions"
    assert (transaction / "backups" / target.name).read_text(encoding="utf-8") == "old instructions"


def test_changes_detects_workflow_fingerprint_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = desktop_agents.current_fingerprints(REPOSITORY)
    changed = {**current, "skill_sha256": "f" * 64}
    monkeypatch.setattr(desktop_agents, "current_fingerprints", lambda root: changed)

    payload = changes(REPOSITORY)
    assert payload["dominant_classification"] == "workflow_breaking"
    assert any(item["kind"] == "workflow_breaking" for item in payload["reasons"])
