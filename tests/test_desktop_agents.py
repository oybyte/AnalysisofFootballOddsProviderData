from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil

import pytest
import yaml

from odds_journal.desktop_agents import (
    CertificationResult,
    DesktopManifest,
    changes,
    configure_product,
    load_local_state,
    load_manifest,
    sync_agents,
    _validate_skill_target,
)


REPOSITORY = Path(__file__).resolve().parents[1]


def test_manifest_v2_is_single_source_of_product_versions() -> None:
    manifest = load_manifest(REPOSITORY)
    assert manifest.schema_version == 2
    assert manifest.release_channel == "experimental"
    assert manifest.cli.package == "odds-journal"
    assert manifest.supported_contracts.case_receipt_schema_versions == [1, 2, 3]
    assert {item.product_id for item in manifest.products} == {
        "codex-desktop",
        "trae-work",
        "workbuddy",
        "teloswork",
    }
    assert "3.3.80" in next(
        item for item in manifest.products if item.product_id == "trae-work"
    ).tested_versions


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


def test_sync_requires_explicit_lcz_confirmation() -> None:
    with pytest.raises(ValueError, match="approved-by lcz"):
        sync_agents(REPOSITORY, approved_by="agent", confirm_sync=True)
    with pytest.raises(ValueError, match="approved-by lcz"):
        sync_agents(REPOSITORY, approved_by="lcz", confirm_sync=False)


def test_sync_rejects_broad_or_repository_skill_target() -> None:
    with pytest.raises(ValueError, match="不得位于项目仓库内"):
        _validate_skill_target(REPOSITORY, REPOSITORY / "football-odds-journal")
    with pytest.raises(ValueError, match="绝对"):
        _validate_skill_target(REPOSITORY, Path("football-odds-journal"))


def test_migrated_baseline_detects_workflow_change() -> None:
    payload = changes(REPOSITORY)
    assert payload["dominant_classification"] == "workflow_breaking"
    assert any(item["kind"] == "workflow_breaking" for item in payload["reasons"])
