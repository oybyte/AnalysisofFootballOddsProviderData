from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from importlib import metadata as importlib_metadata
import json
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml

from .indexing import INDEX_SCHEMA_VERSION, current_source_fingerprint, index_metadata
from .rules import active_ruleset, load_ruleset, sha256_file, validate_rules


LOCAL_STATE = Path(".odds-journal/desktop-agent-local.yml")
RELEASE_STATE = Path("integrations/desktop-agent-release.yml")
MANIFEST_PATH = Path("ai/desktop-agent-manifest.yml")
SKILL_PATH = Path("integrations/skills/football-odds-journal/SKILL.md")
CERTIFICATION_ROOT = Path("integrations/certification/results")
CERTIFICATION_AUTOMATION_ROOT = Path("integrations/certification/automation")
LOAD_VALIDATION_ROOT = Path("integrations/certification/load-validations")
ZERO_HASH = "0" * 64
CLASSIFICATION_PRIORITY = {
    "no_change": 0,
    "data_only": 1,
    "rules_compatible": 2,
    "product_upgrade": 3,
    "workflow_breaking": 4,
}
HISTORICAL_CERTIFICATION_SCENARIOS = {
    "1.0.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass",
        "failed-gate", "postmatch-review",
    },
    "1.1.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass",
        "failed-gate", "postmatch-review",
    },
    "1.2.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass",
        "failed-gate", "postmatch-review", "long-text-storage",
    },
    "1.3.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass",
        "failed-gate", "postmatch-review", "long-text-storage",
    },
    "1.4.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass",
        "failed-gate", "postmatch-review", "long-text-storage",
    },
    "1.5.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass",
        "failed-gate", "postmatch-review", "long-text-storage",
    },
    "1.6.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass",
        "failed-gate", "postmatch-review", "long-text-storage",
        "historical-result-completion",
    },
    "1.7.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass", "failed-gate",
        "postmatch-review", "long-text-storage", "historical-result-completion",
        "low-stability-calibration",
    },
    "1.8.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass", "failed-gate",
        "postmatch-review", "long-text-storage", "historical-result-completion",
        "low-stability-calibration",
    },
    "1.9.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass", "failed-gate",
        "postmatch-review", "long-text-storage", "historical-result-completion",
        "low-stability-calibration", "normalized-market-bundle",
    },
    "1.10.0": {
        "extraction-only", "governed-analysis", "degraded-or-pass", "failed-gate",
        "postmatch-review", "long-text-storage", "historical-result-completion",
        "low-stability-calibration", "normalized-market-bundle",
        "incremental-market-monitoring",
    },
}


def _version_tuple(value: str | None) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(r"\d+", value or "")[:4])


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256_bytes(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def _tree_sha256(path: Path) -> str:
    """Hash managed Skill content without trusting file timestamps or pycache."""
    entries: list[tuple[str, str]] = []
    for item in sorted(path.rglob("*")):
        if item.is_file() and "__pycache__" not in item.parts:
            entries.append((item.relative_to(path).as_posix(), sha256_file(item)))
    return _sha256_bytes(_canonical_json(entries))


def _yaml_read(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"YAML 顶层必须是对象：{path}")
    return value


def _atomic_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


class CliContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package: str
    version: str
    python: str = ">=3.11,<3.12"
    wrapper_windows: str
    wrapper_posix: str


class SupportedContracts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_schema_versions: list[int]
    ruleset_manifest_schema_versions: list[int]
    analysis_receipt_schema_versions: list[int]
    case_receipt_schema_versions: list[int]
    index_schema_versions: list[int]
    journal_ingest_schema_versions: list[int] = Field(default_factory=list)
    lock_candidate_receipt_schema_versions: list[int] = Field(default_factory=list)
    analysis_outlook_schema_versions: list[int] = Field(default_factory=list)
    calibration_contract_versions: list[int] = Field(default_factory=list)
    experiment_analysis_receipt_versions: list[int] = Field(default_factory=list)
    experiment_outlook_versions: list[int] = Field(default_factory=list)
    experiment_prediction_receipt_versions: list[int] = Field(default_factory=list)
    experiment_outcome_versions: list[int] = Field(default_factory=list)
    experiment_advisory_bundle_versions: list[int] = Field(default_factory=list)
    experiment_advisory_disposition_versions: list[int] = Field(default_factory=list)
    experiment_advisory_receipt_versions: list[int] = Field(default_factory=list)
    experiment_advisory_outcome_versions: list[int] = Field(default_factory=list)
    live_experiment_receipt_versions: list[int] = Field(default_factory=list)
    market_archive_comparison_versions: list[int] = Field(default_factory=list)
    prematch_risk_watchlist_versions: list[int] = Field(default_factory=list)


class TrustedInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    document_id: str
    scope: str
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class TrustedAIAsset(BaseModel):
    """A hash-pinned AI runtime asset, distinct from an agent instruction."""

    model_config = ConfigDict(extra="forbid")

    path: str
    kind: Literal["prompt", "outbound_policy", "output_schema", "reasoning_profile"]
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProductDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # `windows_registry_names` is retained only for schema-1 manifest migration.
    # Current manifests must use exact or prefix matching to avoid TRAE-family
    # products being misidentified as one another.
    windows_registry_names: list[str] = Field(default_factory=list)
    display_name_exact: list[str] = Field(default_factory=list)
    display_name_prefix: list[str] = Field(default_factory=list)


class DesktopProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    display_name: str
    minimum_version: str | None = None
    tested_versions: list[str] = Field(default_factory=list)
    adapter: Literal[
        "agents-md-and-skill", "agents-md", "skill", "packaged-skill",
        "project-instructions",
    ]
    instruction_mode: Literal["none", "repository-root", "external-project-file"] = "none"
    sync_mode: Literal["none", "skill-tree", "atomic-file", "package"] = "none"
    certification_mode: Literal["automated", "manual", "none"] = "manual"
    required_target: Literal["none", "skill-root", "instruction-target", "package"] = "none"
    requires_manual_import: bool = False
    detection: ProductDetection = Field(default_factory=ProductDetection)


class AutomationPolicy(BaseModel):
    """Narrowly scoped approval for repository-owned desktop automation."""

    model_config = ConfigDict(extra="forbid")

    workflow_breaking_sync: Literal["automatic"]
    certify_products: list[Literal["codex-desktop"]] = Field(default_factory=list)
    commit_generated_artifacts: Literal[True]


class DesktopManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2, 3] = 2
    manifest_id: str
    workflow_version: str
    release_channel: Literal["experimental", "stable"] = "experimental"
    cli: CliContract
    supported_contracts: SupportedContracts
    trusted_instructions: list[TrustedInstruction]
    trusted_ai_assets: list[TrustedAIAsset] = Field(default_factory=list)
    products: list[DesktopProduct]
    platform_certification: dict[str, str]
    automation_policy: AutomationPolicy | None = None

    @field_validator("products")
    @classmethod
    def products_unique(cls, values: list[DesktopProduct]) -> list[DesktopProduct]:
        ids = [item.product_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("桌面产品 product_id 不得重复")
        return values


def load_manifest(root: Path) -> DesktopManifest:
    raw = _yaml_read(root / MANIFEST_PATH)
    if raw.get("schema_version") == 1:
        raw = {
            "schema_version": 2,
            "manifest_id": raw["manifest_id"],
            "workflow_version": raw["workflow_version"],
            "release_channel": "experimental",
            "cli": {
                "package": raw["cli_package"],
                "version": raw["cli_version"],
                "python": ">=3.11,<3.12",
                "wrapper_windows": "scripts/odds-journal.ps1",
                "wrapper_posix": "scripts/odds-journal.sh",
            },
            "supported_contracts": {
                "match_schema_versions": [1, 2],
                "ruleset_manifest_schema_versions": [1, 2],
                "analysis_receipt_schema_versions": [1, 2, 3],
                "case_receipt_schema_versions": [1],
                "index_schema_versions": [2, 3, 4, 5],
                "journal_ingest_schema_versions": [],
                "lock_candidate_receipt_schema_versions": [],
            },
            "trusted_instructions": raw["trusted_instructions"],
            "trusted_ai_assets": [],
            "products": [
                {
                    "product_id": item["product_id"],
                    "display_name": item["display_name"],
                    "minimum_version": item.get("minimum_version"),
                    "tested_versions": [item["tested_version"]]
                    if item.get("tested_version")
                    else [],
                    "adapter": item["adapter"],
                    "instruction_mode": "repository-root" if item["adapter"] == "agents-md" else "none",
                    "sync_mode": "skill-tree" if item["adapter"] in {"skill", "agents-md-and-skill"} else "none",
                    "certification_mode": "automated" if item["product_id"] == "codex-desktop" else "manual",
                    "required_target": "skill-root" if item["adapter"] in {"skill", "agents-md-and-skill"} else "none",
                    "requires_manual_import": item["adapter"] == "packaged-skill",
                    "detection": {"display_name_exact": [item["display_name"]]},
                }
                for item in raw["products"]
            ],
            "platform_certification": raw.get("platform_certification", {}),
        }
    return DesktopManifest.model_validate(raw)


class ProductLocalState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_root: str | None = None
    installed_skill_path: str | None = None
    package_path: str | None = None
    installation_path: str | None = None
    instruction_target: str | None = None
    load_validation_path: str | None = None
    import_state: Literal[
        "not_built", "package_ready", "imported_unverified", "certified"
    ] | None = None
    imported_version: str | None = None
    updated_at: datetime | None = None


class DesktopLocalState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    products: dict[str, ProductLocalState] = Field(default_factory=dict)
    last_sync_transaction_id: str | None = None


class ReleaseObserved(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ruleset: str
    ruleset_manifest_schema_version: int
    index_schema_version: int
    source_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class ReleaseApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str | None = None
    approved_at: datetime | None = None


class DesktopReleaseState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2] = 2
    release_channel: Literal["experimental", "stable"]
    workflow_version: str
    repo_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    governance_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    instruction_sha256: dict[str, str]
    agent_runtime_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed: ReleaseObserved
    product_versions: dict[str, str | None]
    synchronized_targets: list[str]
    adapter_states: dict[str, dict[str, str]] = Field(default_factory=dict)
    approval: ReleaseApproval
    baseline_kind: Literal["migrated", "approved-sync"]
    transaction_id: str | None = None

    @field_validator("instruction_sha256")
    @classmethod
    def hashes_valid(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in values.values()):
            raise ValueError("instruction_sha256 包含无效哈希")
        return values

    @model_validator(mode="after")
    def valid_approval(self) -> "DesktopReleaseState":
        if self.baseline_kind == "approved-sync" and (
            not self.approval.approved_by or self.approval.approved_at is None or not self.transaction_id
        ):
            raise ValueError("approved-sync 必须记录批准人、批准时间和事务 ID")
        if len(self.synchronized_targets) != len(set(self.synchronized_targets)):
            raise ValueError("synchronized_targets 不得重复")
        return self


TRAE_CN_LOAD_CHECKS = {
    "instruction-loaded",
    "chinese-instructions-intact",
    "cli-gate-runnable",
    "agent-start-failure-blocks-analysis",
    "experiment-isolation",
    "restart-and-refresh-persist",
}


class TraeCNLoadValidation(BaseModel):
    """Human evidence that Trae CN actually loads the managed instruction file."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    product_id: Literal["trae-cn"] = "trae-cn"
    product_version: str
    platform: Literal["windows"]
    workflow_version: str
    tested_at: datetime
    tester: str
    repo_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    instruction_source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    installation_path: str
    instruction_target: str
    refresh_steps: list[Literal["first_open", "reopen", "refresh_after_change"]]
    evidence_sha256: list[str] = Field(min_length=1)
    checks: list["CertificationCheck"]
    status: Literal["passed", "failed"]

    @field_validator("tested_at")
    @classmethod
    def tested_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("tested_at 必须包含时区")
        return value

    @field_validator("evidence_sha256")
    @classmethod
    def evidence_hashes_valid(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in values):
            raise ValueError("evidence_sha256 必须是唯一的 SHA-256 哈希")
        return values

    @model_validator(mode="after")
    def complete_load_suite(self) -> "TraeCNLoadValidation":
        check_ids = [item.scenario_id for item in self.checks]
        if self.status != "passed":
            return self
        if set(self.refresh_steps) != {"first_open", "reopen", "refresh_after_change"}:
            raise ValueError("Trae CN 载入验证必须覆盖首次打开、重开和刷新")
        if len(check_ids) != len(set(check_ids)) or set(check_ids) != TRAE_CN_LOAD_CHECKS:
            raise ValueError("Trae CN 载入验证必须包含全部唯一检查项")
        if any(item.status != "passed" for item in self.checks):
            raise ValueError("Trae CN 通过的载入验证不得包含失败检查项")
        return self


def load_local_state(root: Path) -> DesktopLocalState:
    path = root / LOCAL_STATE
    return DesktopLocalState.model_validate(_yaml_read(path)) if path.exists() else DesktopLocalState()


def save_local_state(root: Path, state: DesktopLocalState) -> None:
    _atomic_yaml(root / LOCAL_STATE, state.model_dump(mode="json", exclude_none=True))


def load_release_state(root: Path) -> DesktopReleaseState:
    return DesktopReleaseState.model_validate(_yaml_read(root / RELEASE_STATE))


def configure_product(
    root: Path,
    product_id: str,
    skill_root: Path | None = None,
    *,
    installation_path: Path | None = None,
    instruction_target: Path | None = None,
    confirm_import: bool = False,
    imported_version: str | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(root)
    product = next((item for item in manifest.products if item.product_id == product_id), None)
    if product is None:
        raise ValueError(f"未知桌面产品：{product_id}")
    if product.adapter in {"skill", "agents-md-and-skill"} and skill_root is None:
        existing = load_local_state(root).products.get(product_id)
        if not existing or not existing.skill_root:
            raise ValueError(f"{product.display_name} 必须提供 --skill-root")
    if product.required_target == "instruction-target" and instruction_target is None:
        existing = load_local_state(root).products.get(product_id)
        if not existing or not existing.instruction_target:
            raise ValueError(f"{product.display_name} 必须提供 --instruction-target")
    if product.adapter == "project-instructions" and installation_path is None:
        existing = load_local_state(root).products.get(product_id)
        if not existing or not existing.installation_path:
            raise ValueError(f"{product.display_name} 必须提供 --installation-path")
    if confirm_import and product_id != "teloswork":
        raise ValueError("--confirm-import 仅用于 telosWork")
    if confirm_import and not imported_version:
        raise ValueError("确认 telosWork 导入时必须提供 --imported-version")
    state = load_local_state(root)
    current = state.products.get(product_id, ProductLocalState())
    if skill_root is not None:
        resolved = skill_root.expanduser().resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        current.skill_root = str(resolved)
        current.installed_skill_path = str(resolved / "football-odds-journal")
    if installation_path is not None:
        resolved_installation = installation_path.expanduser().resolve()
        if not resolved_installation.is_absolute() or not resolved_installation.exists():
            raise ValueError("安装路径必须是存在的绝对路径")
        if root.resolve() == resolved_installation or root.resolve() in resolved_installation.parents:
            raise ValueError("安装路径不得位于项目仓库内")
        current.installation_path = str(resolved_installation)
    if instruction_target is not None:
        target = _validate_instruction_target(root, instruction_target)
        current.instruction_target = str(target)
        # A target change invalidates the previous client-side loading proof.
        current.load_validation_path = None
    if confirm_import:
        package = Path(current.package_path) if current.package_path else root / "dist/football-odds-journal.skill"
        if not package.exists():
            raise ValueError("telosWork Skill 包不存在，不能确认导入")
        current.package_path = str(package.resolve())
        current.import_state = "imported_unverified"
        current.imported_version = imported_version
    current.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    state.products[product_id] = current
    save_local_state(root, state)
    return {"schema_version": 1, "product_id": product_id, **current.model_dump(mode="json")}


def _registry_name_matches(detection: ProductDetection, display_name: str) -> bool:
    name = display_name.casefold()
    exact = [item.casefold() for item in detection.display_name_exact]
    prefixes = [item.casefold() for item in detection.display_name_prefix]
    legacy = [item.casefold() for item in detection.windows_registry_names]
    return name in exact or any(name.startswith(item) for item in prefixes) or name in legacy


def _select_registry_candidate(
    candidates: list[dict[str, str]],
    configured_installation: str | None = None,
) -> tuple[dict[str, str] | None, str]:
    if not candidates:
        return None, "not_installed"
    configured = Path(configured_installation).resolve() if configured_installation else None
    if configured is not None:
        matching = [
            item for item in candidates
            if item["executable"]
            and (Path(item["executable"]).resolve() == configured or Path(item["executable"]).resolve().parent == configured)
        ]
        if not matching:
            return None, "configured_installation_not_found"
        candidates = matching
    usable = [item for item in candidates if item["executable"] and Path(item["executable"]).is_file()]
    ranked = usable or candidates
    highest = max(_version_tuple(item["version"]) for item in ranked)
    best = [item for item in ranked if _version_tuple(item["version"]) == highest]
    paths = {item["executable"] for item in best if item["executable"]}
    if len(paths) > 1 and configured is None:
        return None, "ambiguous_installation"
    return best[0], "selected" if usable else "registry_only"


def _registry_products(
    manifest: DesktopManifest,
    state: DesktopLocalState | None = None,
) -> dict[str, dict[str, Any]]:
    result = {
        item.product_id: {
            "display_name": item.display_name,
            "minimum_version": item.minimum_version,
            "tested_versions": item.tested_versions,
            "adapter": item.adapter,
            "instruction_mode": item.instruction_mode,
            "sync_mode": item.sync_mode,
            "certification_mode": item.certification_mode,
            "required_target": item.required_target,
            "installed": item.product_id == "codex-desktop",
            "version": "current-session" if item.product_id == "codex-desktop" else None,
        }
        for item in manifest.products
    }
    if platform.system() != "Windows":
        return result
    try:
        import winreg

        roots = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        candidates: dict[str, list[dict[str, str]]] = {item.product_id: [] for item in manifest.products}
        for hive, key_path in roots:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        with winreg.OpenKey(key, winreg.EnumKey(key, index)) as child:
                            try:
                                name = str(winreg.QueryValueEx(child, "DisplayName")[0])
                            except OSError:
                                continue
                            for product in manifest.products:
                                if _registry_name_matches(product.detection, name):
                                    try:
                                        version = str(winreg.QueryValueEx(child, "DisplayVersion")[0])
                                    except OSError:
                                        version = "unknown"
                                    try:
                                        executable = str(winreg.QueryValueEx(child, "DisplayIcon")[0]).split(",", 1)[0].strip('"')
                                    except OSError:
                                        executable = ""
                                    candidates[product.product_id].append({
                                        "display_name": name,
                                        "version": version,
                                        "executable": executable,
                                    })
            except OSError:
                continue
    except ImportError:
        pass
    for product in manifest.products:
        if product.product_id == "codex-desktop":
            continue
        configured = state.products.get(product.product_id) if state else None
        selected, selection_status = _select_registry_candidate(
            candidates.get(product.product_id, []) if "candidates" in locals() else [],
            configured.installation_path if configured else None,
        )
        result[product.product_id]["installation_status"] = selection_status
        result[product.product_id]["installation_candidates"] = len(candidates.get(product.product_id, [])) if "candidates" in locals() else 0
        if selected:
            result[product.product_id].update(
                installed=True,
                version=selected["version"],
                executable=selected["executable"],
            )
    return result


def _workbuddy_target(root: Path, state: DesktopLocalState) -> Path:
    configured = state.products.get("workbuddy")
    if configured and configured.installed_skill_path:
        return Path(configured.installed_skill_path)
    candidates = [
        Path.home() / ".workbuddy/skills/football-odds-journal",
        Path.home() / ".codebuddy/skills/football-odds-journal",
    ]
    identified = [path for path in candidates if (path / "SKILL.md").exists()]
    if len(identified) == 1:
        return identified[0]
    if len(identified) > 1:
        raise ValueError(
            "WorkBuddy 存在多个同名 Skill，必须运行 agent configure --product workbuddy --skill-root PATH"
        )
    raise ValueError(
        "无法确定 WorkBuddy Skill 目录，请运行 agent configure --product workbuddy --skill-root PATH"
    )


def _skill_target_for_product(
    root: Path,
    state: DesktopLocalState,
    product: DesktopProduct,
) -> Path:
    if product.adapter == "agents-md-and-skill":
        configured = state.products.get(product.product_id)
        return (
            Path(configured.installed_skill_path)
            if configured and configured.installed_skill_path
            else Path.home() / ".codex/skills/football-odds-journal"
        )
    if product.adapter == "skill":
        return _workbuddy_target(root, state)
    raise ValueError(f"{product.display_name} 不使用 Skill 树适配器")


def _adapter_status(root: Path, state: DesktopLocalState) -> dict[str, dict[str, Any]]:
    manifest = load_manifest(root)
    registry = _registry_products(manifest, state)
    source = root / SKILL_PATH
    source_hash = sha256_file(source) if source.exists() else None
    adapters: dict[str, dict[str, Any]] = {}
    for product in manifest.products:
        if product.sync_mode == "skill-tree":
            try:
                target = _skill_target_for_product(root, state, product)
                installed = target / "SKILL.md"
                adapters[product.product_id] = {
                    "status": "synchronized" if installed.exists() and sha256_file(installed) == source_hash else "pending_configuration",
                    "path": str(target),
                    "installed": installed.exists(),
                    "matches_repository": installed.exists() and sha256_file(installed) == source_hash,
                }
            except ValueError as exc:
                adapters[product.product_id] = {
                    "status": "pending_configuration", "path": None,
                    "installed": False, "matches_repository": False, "error": str(exc),
                }
        elif product.sync_mode == "atomic-file":
            target_state = state.products.get(product.product_id, ProductLocalState())
            validation_status, reason, _ = _load_validation_state(
                root, state, registry[product.product_id].get("version"),
            )
            source_path = _trae_cn_instruction_source(root)
            target = Path(target_state.instruction_target) if target_state.instruction_target else None
            matches = bool(target and target.exists() and source_path.exists() and sha256_file(target) == sha256_file(source_path))
            adapters[product.product_id] = {
                "status": "synchronized" if validation_status == "verified" and matches else validation_status,
                "path": str(target) if target else None,
                "instruction_source": str(source_path),
                "installed": bool(registry[product.product_id].get("installed")),
                "matches_repository": matches,
                "load_validation_status": validation_status,
                "error": reason,
            }
        elif product.sync_mode == "package":
            local = state.products.get(product.product_id, ProductLocalState())
            package = Path(local.package_path) if local.package_path else root / "dist/football-odds-journal.skill"
            adapters[product.product_id] = {
                "status": "package_ready" if package.exists() else "not_applicable",
                "package_path": str(package),
                "package_ready": package.exists(),
                "import_state": local.import_state or ("package_ready" if package.exists() else "not_built"),
                "manual_import_required": product.requires_manual_import,
            }
        else:
            adapters[product.product_id] = {"status": "not_applicable"}
    return adapters


def doctor(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    try:
        manifest = load_manifest(root)
        checks["manifest"] = {"schema_version": manifest.schema_version, "ok": True}
    except Exception as exc:
        return {"schema_version": 2, "ok": False, "platform": platform.system().lower(), "checks": {}, "errors": [str(exc)], "warnings": []}
    python_ok = sys.version_info[:2] == (3, 11)
    checks["python"] = {"version": platform.python_version(), "ok": python_ok}
    if not python_ok:
        errors.append("必须使用 Python 3.11")
    venv_python = root / ".venv" / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    checks["venv"] = {"path": str(venv_python), "ok": venv_python.exists()}
    if not venv_python.exists():
        errors.append("项目虚拟环境不存在")
    try:
        package_version = importlib_metadata.version(manifest.cli.package)
    except importlib_metadata.PackageNotFoundError:
        package_version = "not-installed"
    cli_ok = package_version == manifest.cli.version
    checks["cli"] = {"version": package_version, "expected": manifest.cli.version, "ok": cli_ok}
    if not cli_ok:
        errors.append("桌面智能体 manifest 的 CLI 版本与当前包不一致")
    try:
        active = active_ruleset(root)
        ruleset = load_ruleset(root, f"{active.ruleset_id}@{active.ruleset_version}")
        rule_errors = [error for values in validate_rules(root).values() for error in values]
        supported = ruleset.manifest.schema_version in manifest.supported_contracts.ruleset_manifest_schema_versions
        checks["ruleset"] = {
            "id": active.ruleset_id,
            "version": active.ruleset_version,
            "manifest_schema_version": ruleset.manifest.schema_version,
            "sha256": ruleset.content_sha256,
            "supported": supported,
            "ok": not rule_errors and supported,
        }
        errors.extend(rule_errors)
        if not supported:
            errors.append("活动规则集契约不受桌面智能体 manifest 支持")
    except Exception as exc:
        checks["ruleset"] = {"ok": False, "error": str(exc)}
        errors.append(str(exc))
    instruction_checks = []
    for item in manifest.trusted_instructions:
        try:
            path = root / item.path
            raw = path.read_text(encoding="utf-8")
            front = yaml.safe_load(raw.split("---", 2)[1]) or {}
            digest = sha256_file(path)
            ok = front.get("document_id") == item.document_id and front.get("document_type") == "instruction" and front.get("trusted_instruction") is True and digest == item.content_sha256
        except Exception:
            digest, ok = None, False
        instruction_checks.append({"path": item.path, "sha256": digest, "ok": ok})
        if not ok:
            errors.append(f"可信指令清单或哈希不匹配：{item.path}")
    checks["trusted_instructions"] = instruction_checks
    asset_checks = []
    for item in manifest.trusted_ai_assets:
        try:
            path = (root / item.path).resolve()
            path.relative_to(root.resolve())
            digest = sha256_file(path)
            ok = path.is_file() and digest == item.content_sha256
        except Exception:
            digest, ok = None, False
        asset_checks.append({"path": item.path, "kind": item.kind, "sha256": digest, "ok": ok})
        if not ok:
            errors.append(f"受信 AI 资产清单或哈希不匹配：{item.path}")
    checks["trusted_ai_assets"] = asset_checks
    metadata = index_metadata(root)
    expected = current_source_fingerprint(root)
    index_ok = metadata.get("schema_version") == str(INDEX_SCHEMA_VERSION) and metadata.get("source_fingerprint") == expected
    checks["index"] = {"metadata": metadata, "expected_source_fingerprint": expected, "ok": index_ok}
    if not index_ok:
        warnings.append("检索索引缺失或版本过期，请运行 build-index")
    state = load_local_state(root)
    products = _registry_products(manifest, state)
    for product_id, item in products.items():
        installed = bool(item.get("installed"))
        version = item.get("version")
        minimum_ok = item["minimum_version"] is None or _version_tuple(version) >= _version_tuple(item["minimum_version"])
        ambiguous = item.get("installation_status") == "ambiguous_installation"
        item["ok"] = installed and minimum_ok and not ambiguous
        item["version_in_test_matrix"] = bool(version in item["tested_versions"])
        if platform.system() == "Windows" and not item["ok"]:
            warnings.append(f"{item['display_name']} 未安装或低于最低版本")
        elif installed and not item["version_in_test_matrix"]:
            warnings.append(f"{item['display_name']} 当前版本 {version} 不在版本测试矩阵中")
        if ambiguous:
            warnings.append(f"{item['display_name']} 存在多个同版本有效安装，请运行 agent configure --product {product_id} --installation-path PATH")
    checks["products"] = products
    adapters = _adapter_status(root, state)
    checks["adapters"] = adapters
    for product in manifest.products:
        adapter = adapters[product.product_id]
        if product.sync_mode == "skill-tree" and not adapter.get("matches_repository"):
            warnings.append(f"{product.product_id} Skill 未同步或无法唯一定位")
        if product.sync_mode == "atomic-file" and adapter["status"] != "synchronized":
            warnings.append(f"{product.display_name} 当前状态：{adapter['status']}" + (f"（{adapter['error']}）" if adapter.get("error") else ""))
        if product.sync_mode == "package" and adapter["import_state"] != "certified":
            warnings.append(f"{product.display_name} 当前状态：{adapter['import_state']}")
    git = _git_state(root)
    checks["git"] = git
    if not git["available"]:
        warnings.append("未找到 Git")
    return {"schema_version": 2, "ok": not errors, "platform": platform.system().lower(), "checks": checks, "errors": list(dict.fromkeys(errors)), "warnings": list(dict.fromkeys(warnings))}


def _git_state(root: Path) -> dict[str, Any]:
    if not shutil.which("git"):
        return {"available": False, "dirty": None, "commit": None}
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    return {"available": True, "dirty": bool(status.stdout.strip()), "commit": commit.stdout.strip() if commit.returncode == 0 else None}


def current_fingerprints(root: Path) -> dict[str, Any]:
    manifest = load_manifest(root)
    active = active_ruleset(root)
    ruleset = load_ruleset(root, f"{active.ruleset_id}@{active.ruleset_version}")
    instructions = {item.path: sha256_file(root / item.path) for item in manifest.trusted_instructions}
    instructions.update({item.path: sha256_file(root / item.path) for item in manifest.trusted_ai_assets})
    runtime_files = (
        "src/odds_journal/cli.py",
        "src/odds_journal/desktop_agents.py",
        "src/odds_journal/agent_workflow.py",
        "scripts/odds-journal.ps1",
        "scripts/odds-journal.sh",
        "integrations/trae-cn/PROJECT_INSTRUCTIONS.md",
    )
    return {
        "workflow_version": manifest.workflow_version,
        "manifest_sha256": sha256_file(root / MANIFEST_PATH),
        "skill_sha256": sha256_file(root / SKILL_PATH),
        "governance_sha256": sha256_file(root / "AGENTS.md"),
        "instruction_sha256": instructions,
        "agent_runtime_sha256": _sha256_bytes(_canonical_json([
            (path, sha256_file(root / path)) for path in runtime_files
        ])),
        "ruleset": f"{active.ruleset_id}@{active.ruleset_version}",
        "ruleset_manifest_schema_version": ruleset.manifest.schema_version,
        "index_schema_version": INDEX_SCHEMA_VERSION,
        "source_fingerprint": current_source_fingerprint(root),
    }


def changes(root: Path) -> dict[str, Any]:
    release_path = root / RELEASE_STATE
    current = current_fingerprints(root)
    products = _registry_products(load_manifest(root), load_local_state(root))
    reasons: list[dict[str, str]] = []
    kinds: list[str] = []
    if not release_path.exists():
        kinds.append("workflow_breaking")
        reasons.append({"kind": "workflow_breaking", "reason": "缺少桌面智能体发布基线"})
        baseline: dict[str, Any] = {}
    else:
        baseline = load_release_state(root).model_dump(mode="json")
        for key in ("workflow_version", "manifest_sha256", "skill_sha256", "governance_sha256", "instruction_sha256", "agent_runtime_sha256"):
            if baseline.get(key) != current.get(key):
                kinds.append("workflow_breaking")
                reasons.append({"kind": "workflow_breaking", "reason": f"{key} 已变化"})
        observed = baseline.get("observed", {})
        if observed.get("ruleset") != current["ruleset"]:
            if current["ruleset_manifest_schema_version"] in load_manifest(root).supported_contracts.ruleset_manifest_schema_versions:
                kinds.append("rules_compatible")
                reasons.append({"kind": "rules_compatible", "reason": "活动规则集发生兼容更新"})
            else:
                kinds.append("workflow_breaking")
                reasons.append({"kind": "workflow_breaking", "reason": "活动规则集契约不兼容"})
        if observed.get("source_fingerprint") != current["source_fingerprint"]:
            kinds.append("data_only")
            reasons.append({"kind": "data_only", "reason": "索引语料指纹发生变化"})
        baseline_versions = baseline.get("product_versions", {})
        for product_id, item in products.items():
            version = item.get("version")
            if version and baseline_versions.get(product_id) not in (None, version):
                kinds.append("product_upgrade")
                reasons.append({"kind": "product_upgrade", "reason": f"{product_id} 版本由 {baseline_versions[product_id]} 变为 {version}"})
    unique = set(kinds)
    if not unique:
        classification = "no_change"
    elif len(unique) > 1:
        classification = "mixed"
    else:
        classification = next(iter(unique))
    dominant = max(unique, key=lambda item: CLASSIFICATION_PRIORITY[item]) if unique else "no_change"
    actions = {
        "no_change": [],
        "data_only": ["运行 build-index；无需同步 Skill"],
        "rules_compatible": ["运行规则校验和 build-index；无需重装 Skill"],
        "product_upgrade": ["仅重新认证升级的产品"],
        "workflow_breaking": ["直接运行 agent sync；将自动同步四端、认证 Codex Desktop 并提交受限产物"],
    }[dominant]
    return {"schema_version": 1, "classification": classification, "dominant_classification": dominant, "reasons": reasons, "required_actions": actions, "current": current, "baseline": baseline}


@contextmanager
def _exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
    except FileExistsError as exc:
        raise ValueError("已有桌面智能体同步事务正在运行") from exc
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _run_checked(root: Path, command: list[str]) -> None:
    result = subprocess.run(command, cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    if result.returncode:
        detail = (result.stdout + "\n" + result.stderr).strip()
        raise ValueError(f"同步预检失败：{' '.join(command)}\n{detail[-3000:]}")


def _copy_tree_atomic(source: Path, target: Path, transaction: Path) -> None:
    # os.replace cannot move a directory across Windows volumes.  Keep the
    # auditable backup in the repository transaction, but stage beside target.
    target.parent.mkdir(parents=True, exist_ok=True)
    token = f"{transaction.name}-{uuid4().hex[:8]}"
    staged = target.parent / f".{target.name}.sync-stage-{token}"
    displaced = target.parent / f".{target.name}.sync-backup-{token}"
    shutil.copytree(source, staged)
    moved_target = False
    if target.exists():
        backup = transaction / "backups" / target.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, backup)
        os.replace(target, displaced)
        moved_target = True
    try:
        os.replace(staged, target)
    except Exception:
        if moved_target and displaced.exists():
            os.replace(displaced, target)
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    if displaced.exists():
        shutil.rmtree(displaced)


def _copy_file_atomic(root: Path, source: Path, target: Path, transaction: Path) -> None:
    target = _validate_instruction_target(root, target)
    token = f"{transaction.name}-{uuid4().hex[:8]}"
    staged = target.parent / f".{target.name}.sync-stage-{token}"
    displaced = target.parent / f".{target.name}.sync-backup-{token}"
    backup = transaction / "backups" / target.name
    if target.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup)
    else:
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.with_suffix(backup.suffix + ".missing").write_text("missing\n", encoding="utf-8")
    shutil.copy2(source, staged)
    moved_target = False
    if target.exists():
        os.replace(target, displaced)
        moved_target = True
    try:
        os.replace(staged, target)
        if sha256_file(target) != sha256_file(source):
            raise ValueError("Trae CN 指令同步后的内容哈希不匹配")
    except Exception:
        if target.exists():
            target.unlink()
        if moved_target and displaced.exists():
            os.replace(displaced, target)
        raise
    finally:
        staged.unlink(missing_ok=True)
    displaced.unlink(missing_ok=True)


def _validate_skill_source(root: Path) -> None:
    path = root / SKILL_PATH
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n") or raw.count("---") < 2:
        raise ValueError("Skill 缺少 YAML Front Matter")
    metadata = yaml.safe_load(raw.split("---", 2)[1]) or {}
    if metadata.get("name") != "football-odds-journal":
        raise ValueError("Skill name 必须是 football-odds-journal")
    if not str(metadata.get("description", "")).strip():
        raise ValueError("Skill description 不能为空")


def _validate_skill_target(root: Path, target: Path) -> None:
    resolved = target.expanduser().resolve()
    if not target.is_absolute() or resolved.name != "football-odds-journal":
        raise ValueError(f"Skill 目标必须是绝对的 football-odds-journal 目录：{target}")
    if resolved == root.resolve() or root.resolve() in resolved.parents:
        raise ValueError(f"Skill 目标不得位于项目仓库内：{target}")
    if len(resolved.parts) < 4:
        raise ValueError(f"Skill 目标路径过宽，拒绝同步：{target}")


def _validate_instruction_target(root: Path, target: Path) -> Path:
    resolved = target.expanduser().resolve()
    forbidden_names = {".ssh", "credentials", "credential", "secrets", "secret", "tokens", "token"}
    if not target.is_absolute() or resolved == root.resolve() or root.resolve() in resolved.parents:
        raise ValueError("Trae CN 指令目标必须是仓库外的绝对文件路径")
    if resolved == Path.home().resolve() or len(resolved.parts) < 4:
        raise ValueError(f"Trae CN 指令目标路径过宽，拒绝同步：{target}")
    if resolved.name.casefold() in forbidden_names or any(part.casefold() in forbidden_names for part in resolved.parts):
        raise ValueError("Trae CN 指令目标不得位于凭据或令牌目录")
    if resolved.suffix.casefold() not in {".md", ".txt"}:
        raise ValueError("Trae CN 指令目标必须是 .md 或 .txt 文件")
    if not resolved.parent.exists() or not resolved.parent.is_dir():
        raise ValueError("Trae CN 指令目标的父目录必须已存在")
    return resolved


def _trae_cn_instruction_source(root: Path) -> Path:
    return root / "integrations/trae-cn/PROJECT_INSTRUCTIONS.md"


def _load_validation_state(
    root: Path,
    state: DesktopLocalState,
    product_version: str | None,
) -> tuple[str, str | None, TraeCNLoadValidation | None]:
    local = state.products.get("trae-cn")
    if not local or not local.instruction_target or not local.installation_path:
        return "pending_configuration", "缺少安装路径或指令目标配置", None
    if not local.load_validation_path:
        return "pending_manual_validation", "尚未记录真实 Trae CN 载入验证", None
    path = root / local.load_validation_path
    try:
        validation = TraeCNLoadValidation.model_validate(_yaml_read(path))
    except Exception as exc:
        return "pending_manual_validation", f"载入验证记录无效：{exc}", None
    current = current_fingerprints(root)
    if (
        validation.status != "passed"
        or validation.product_version != product_version
        or validation.workflow_version != current["workflow_version"]
        or validation.repo_commit != _git_state(root)["commit"]
        or validation.manifest_sha256 != current["manifest_sha256"]
        or validation.instruction_source_sha256 != sha256_file(_trae_cn_instruction_source(root))
        or Path(validation.installation_path).resolve() != Path(local.installation_path).resolve()
        or Path(validation.instruction_target).resolve() != Path(local.instruction_target).resolve()
    ):
        return "pending_manual_validation", "载入验证与当前版本、仓库或本机配置不一致", None
    return "verified", None, validation


def _backup_repo_path(path: Path, backup: Path) -> None:
    if path.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, backup)
        else:
            shutil.copy2(path, backup)
    else:
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.with_suffix(backup.suffix + ".missing").write_text("missing\n", encoding="utf-8")


def _restore_repo_path(path: Path, backup: Path) -> None:
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    if backup.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup.is_dir():
            shutil.copytree(backup, path)
        else:
            shutil.copy2(backup, path)


def _commit_generated_sync(root: Path) -> str:
    allowed = (
        "integrations/desktop-agent-release.yml",
        "integrations/certification/results/codex-desktop/",
        "integrations/certification/automation/codex-desktop/",
    )
    _run_checked(root, ["git", "add", "--", *allowed])
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=root, text=True, encoding="utf-8", capture_output=True, check=False)
    paths = [item.replace("\\", "/") for item in staged.stdout.splitlines() if item]
    if not paths or any(not any(item == value.rstrip("/") or item.startswith(value) for value in allowed) for item in paths):
        subprocess.run(["git", "restore", "--staged", "--", *allowed], cwd=root, check=False, capture_output=True)
        raise ValueError("自动提交只允许同步基线和 Codex 自动认证产物")
    try:
        _run_checked(root, ["git", "commit", "-m", "同步桌面代理并认证Codex"])
    except Exception:
        subprocess.run(["git", "restore", "--staged", "--", *allowed], cwd=root, check=False, capture_output=True)
        raise
    return _git_state(root)["commit"]


def sync_agents(root: Path, *, approved_by: str | None = None, confirm_sync: bool = False) -> dict[str, Any]:
    if approved_by not in (None, "lcz"):
        raise ValueError("已废弃的 --approved-by 仅接受 lcz")
    lock_path = root / ".odds-journal/agent-sync.lock"
    with _exclusive_lock(lock_path):
        git = _git_state(root)
        if not git["available"] or git["dirty"] or not git["commit"]:
            raise ValueError("同步要求有效提交且 Git 工作树干净")
        manifest = load_manifest(root)
        policy = manifest.automation_policy
        if not policy or policy.workflow_breaking_sync != "automatic" or not policy.commit_generated_artifacts:
            raise ValueError("manifest 未启用自动同步与受限自动提交策略")
        classification = changes(root)["dominant_classification"]
        state = load_local_state(root)
        registry = _registry_products(manifest, state)
        verified_pending_target = False
        for product in manifest.products:
            if product.sync_mode != "atomic-file":
                continue
            validation_status, _, _ = _load_validation_state(
                root, state, registry[product.product_id].get("version"),
            )
            local = state.products.get(product.product_id, ProductLocalState())
            target = Path(local.instruction_target) if local.instruction_target else None
            source = _trae_cn_instruction_source(root)
            target_matches = bool(target and target.exists() and source.exists() and sha256_file(target) == sha256_file(source))
            verified_pending_target = verified_pending_target or (validation_status == "verified" and not target_matches)
        if classification != "workflow_breaking" and not verified_pending_target:
            raise ValueError(f"agent sync 仅处理 workflow_breaking 或已验证的待同步项目指令；当前为 {classification}")
        report = doctor(root)
        if not report["ok"]:
            raise ValueError("agent doctor 未通过：" + "；".join(report["errors"]))
        _run_checked(root, [sys.executable, "-m", "odds_journal", "schemas", "check"])
        _run_checked(root, [sys.executable, "-m", "odds_journal", "validate", "--all"])
        _run_checked(root, [sys.executable, "-m", "pytest", "--basetemp=.odds-journal/pytest-sync"])
        _validate_skill_source(root)
        tree_targets: dict[str, Path] = {}
        for product in manifest.products:
            if product.sync_mode == "skill-tree":
                tree_targets[product.product_id] = _skill_target_for_product(root, state, product)
        for target in tree_targets.values():
            _validate_skill_target(root, target)
        transaction_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        transaction = root / ".odds-journal/agent-sync-backups" / transaction_id
        transaction.mkdir(parents=True)
        completed: list[str] = []
        adapter_states: dict[str, dict[str, str]] = {}
        target_existed = {product_id: target.exists() for product_id, target in tree_targets.items()}
        trae_target: Path | None = None
        trae_was_written = False
        trae_product = next((item for item in manifest.products if item.adapter == "project-instructions"), None)
        if trae_product is not None:
            validation_status, validation_reason, _ = _load_validation_state(
                root, state, registry[trae_product.product_id].get("version"),
            )
            if validation_status == "verified":
                configured = state.products.get(trae_product.product_id, ProductLocalState())
                trae_target = _validate_instruction_target(root, Path(configured.instruction_target or ""))
                adapter_states[trae_product.product_id] = {"status": "pending_configuration", "reason": "已验证，待同步"}
            else:
                adapter_states[trae_product.product_id] = {
                    "status": validation_status,
                    "reason": validation_reason or "等待人工完成真实客户端载入验证",
                }
        package_product = next((item for item in manifest.products if item.sync_mode == "package"), None)
        if package_product is None:
            raise ValueError("manifest 缺少打包 Skill 适配器")
        dist = root / "dist"
        package = dist / "football-odds-journal.skill"
        package_backup = transaction / "teloswork-package.skill"
        if package.exists():
            package_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(package, package_backup)
        local_state_path = root / LOCAL_STATE
        release_state_path = root / RELEASE_STATE
        local_state_backup = transaction / "desktop-agent-local.yml"
        release_state_backup = transaction / "desktop-agent-release.yml"
        if local_state_path.exists():
            shutil.copy2(local_state_path, local_state_backup)
        if release_state_path.exists():
            shutil.copy2(release_state_path, release_state_backup)
        generated_backup = transaction / "generated"
        _backup_repo_path(release_state_path, generated_backup / "desktop-agent-release.yml")
        _backup_repo_path(root / CERTIFICATION_ROOT / "codex-desktop", generated_backup / "certification-results")
        _backup_repo_path(root / CERTIFICATION_AUTOMATION_ROOT / "codex-desktop", generated_backup / "certification-automation")
        try:
            for product_id, target in tree_targets.items():
                _copy_tree_atomic(root / "integrations/skills/football-odds-journal", target, transaction / product_id)
                completed.append(product_id)
                adapter_states[product_id] = {"status": "synchronized"}
            if trae_product is not None and trae_target is not None:
                _copy_file_atomic(root, _trae_cn_instruction_source(root), trae_target, transaction / trae_product.product_id)
                completed.append(trae_product.product_id)
                trae_was_written = True
                adapter_states[trae_product.product_id] = {"status": "synchronized"}
            dist.mkdir(parents=True, exist_ok=True)
            temporary = dist / f".{transaction_id}.zip"
            shutil.make_archive(str(temporary.with_suffix("")), "zip", root / "integrations/skills/football-odds-journal")
            os.replace(temporary, package)
            package_state = state.products.get(package_product.product_id, ProductLocalState())
            package_state.package_path = str(package.resolve())
            package_state.import_state = "package_ready"
            package_state.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
            state.products[package_product.product_id] = package_state
            adapter_states[package_product.product_id] = {"status": "package_ready"}
            state.last_sync_transaction_id = transaction_id
            fingerprints = current_fingerprints(root)
            products = _registry_products(manifest, state)
            release = DesktopReleaseState.model_validate({
                "schema_version": 2,
                "release_channel": manifest.release_channel,
                "workflow_version": manifest.workflow_version,
                "repo_commit": git["commit"],
                **{key: fingerprints[key] for key in ("manifest_sha256", "skill_sha256", "governance_sha256", "instruction_sha256", "agent_runtime_sha256")},
                "observed": {
                    "ruleset": fingerprints["ruleset"],
                    "ruleset_manifest_schema_version": fingerprints["ruleset_manifest_schema_version"],
                    "index_schema_version": fingerprints["index_schema_version"],
                    "source_fingerprint": fingerprints["source_fingerprint"],
                },
                "product_versions": {key: value.get("version") for key, value in products.items()},
                "synchronized_targets": completed + [f"{package_product.product_id}-package"],
                "adapter_states": adapter_states,
                "approval": {"approved_by": "manifest-automation-policy", "approved_at": datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat()},
                "baseline_kind": "approved-sync",
                "transaction_id": transaction_id,
            })
            save_local_state(root, state)
            _atomic_yaml(release_state_path, release.model_dump(mode="json", exclude_none=True))
            certification_path, automation_report = _auto_certify_codex_desktop(root, transaction)
            commit = _commit_generated_sync(root)
        except Exception:
            for product_id, target in tree_targets.items():
                backup = transaction / product_id / "backups" / target.name
                if backup.exists():
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(backup, target)
                elif product_id in completed and not target_existed[product_id] and target.exists():
                    shutil.rmtree(target)
            if trae_was_written and trae_target is not None:
                backup = transaction / (trae_product.product_id if trae_product else "trae-cn") / "backups" / trae_target.name
                if trae_target.exists():
                    trae_target.unlink()
                if backup.exists():
                    shutil.copy2(backup, trae_target)
            if package_backup.exists():
                package.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(package_backup, package)
            elif package.exists():
                package.unlink()
            for state_path, backup in (
                (local_state_path, local_state_backup),
                (release_state_path, release_state_backup),
            ):
                if backup.exists():
                    shutil.copy2(backup, state_path)
                elif state_path.exists():
                    state_path.unlink()
            _restore_repo_path(release_state_path, generated_backup / "desktop-agent-release.yml")
            _restore_repo_path(root / CERTIFICATION_ROOT / "codex-desktop", generated_backup / "certification-results")
            _restore_repo_path(root / CERTIFICATION_AUTOMATION_ROOT / "codex-desktop", generated_backup / "certification-automation")
            raise
        return {"schema_version": 1, "transaction_id": transaction_id, "synchronized_targets": release.synchronized_targets, "adapter_states": release.adapter_states, "teloswork_state": "package_ready", "certification_result": str(certification_path.relative_to(root)), "automation_report": str(automation_report.relative_to(root)), "git_commit_created": True, "git_commit": commit}


class CertificationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    status: Literal["passed", "failed"]
    notes: str | None = None


TraeCNLoadValidation.model_rebuild()


class CertificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    product_id: str
    product_version: str
    platform: str
    workflow_version: str
    tested_at: datetime
    tester: str
    repo_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    skill_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    instruction_sha256: dict[str, str]
    certification_method: Literal["manual", "automated"] = "manual"
    automation_run_id: str | None = None
    automation_report_path: str | None = None
    automation_report_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    telos_import_confirmed: bool | None = None
    checks: list[CertificationCheck]
    status: Literal["passed", "failed"]

    @field_validator("tested_at")
    @classmethod
    def tested_at_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("tested_at 必须包含时区")
        return value

    @field_validator("instruction_sha256")
    @classmethod
    def instruction_hashes_valid(cls, values: dict[str, str]) -> dict[str, str]:
        if any(not re.fullmatch(r"[a-f0-9]{64}", value) for value in values.values()):
            raise ValueError("instruction_sha256 包含无效哈希")
        return values

    @model_validator(mode="after")
    def complete_suite(self) -> "CertificationResult":
        ids = [item.scenario_id for item in self.checks]
        valid = len(ids) == len(set(ids)) and all(item.status == "passed" for item in self.checks)
        historical = HISTORICAL_CERTIFICATION_SCENARIOS.get(self.workflow_version)
        if historical is not None:
            valid = valid and set(ids) == historical
        elif self.workflow_version == "1.2.0":
            # Exact IDs are loaded from scenarios.yml by record_certification.
            valid = valid and len(ids) == 6
        if self.product_id == "teloswork":
            valid = valid and self.telos_import_confirmed is True
        if self.status == "passed" and not valid:
            raise ValueError("认证 passed 必须包含对应 workflow 的唯一且全部通过场景；telosWork 还需确认导入")
        automated_fields = (
            self.automation_run_id,
            self.automation_report_path,
            self.automation_report_sha256,
        )
        if self.certification_method == "automated" and not all(automated_fields):
            raise ValueError("自动认证必须绑定运行 ID、报告路径和报告哈希")
        if self.certification_method == "manual" and any(automated_fields):
            raise ValueError("人工认证不得填写自动化运行字段")
        return self


def _required_certification_scenarios(root: Path, workflow_version: str) -> set[str]:
    suite = _yaml_read(root / "integrations/certification/scenarios.yml")
    if suite.get("workflow_version") == workflow_version:
        values = suite.get("required_scenario_ids") or []
        if not values or len(values) != len(set(values)):
            raise ValueError("认证 suite 的 required_scenario_ids 缺失或重复")
        return {str(item) for item in values}
    if workflow_version not in HISTORICAL_CERTIFICATION_SCENARIOS:
        raise ValueError(f"没有 workflow {workflow_version} 的认证 suite")
    return HISTORICAL_CERTIFICATION_SCENARIOS[workflow_version]


def _record_certification_result(root: Path, result: CertificationResult) -> Path:
    required = _required_certification_scenarios(root, result.workflow_version)
    actual = {item.scenario_id for item in result.checks}
    if actual != required:
        raise ValueError(
            "认证场景与 workflow suite 不一致："
            f"缺少 {sorted(required - actual)}，多出 {sorted(actual - required)}"
        )
    manifest = load_manifest(root)
    product = next((item for item in manifest.products if item.product_id == result.product_id), None)
    if product is None:
        raise ValueError(f"manifest 未声明产品：{result.product_id}")
    if result.product_id == "teloswork" and result.status == "passed":
        telos = load_local_state(root).products.get("teloswork")
        if not telos or telos.import_state != "imported_unverified":
            raise ValueError("telosWork 必须先确认导入并处于 imported_unverified")
        if telos.imported_version != result.product_version:
            raise ValueError("telosWork 导入版本与认证结果版本不一致")
    if result.product_id == "trae-cn" and result.status == "passed":
        validation_status, validation_reason, _ = _load_validation_state(
            root,
            load_local_state(root),
            result.product_version,
        )
        if validation_status != "verified":
            raise ValueError("Trae CN 必须先完成当前真实客户端载入验证：" + (validation_reason or validation_status))
    current = current_fingerprints(root)
    git = _git_state(root)
    expected = {
        "workflow_version": current["workflow_version"],
        "repo_commit": git["commit"],
        "manifest_sha256": current["manifest_sha256"],
        "skill_sha256": current["skill_sha256"],
        "instruction_sha256": current["instruction_sha256"],
    }
    for key, value in expected.items():
        if getattr(result, key) != value:
            raise ValueError(f"认证结果与当前仓库绑定不一致：{key}")
    suffix = ""
    if result.certification_method == "automated":
        suffix = f"-{result.manifest_sha256[:12]}-{result.automation_run_id}"
    name = f"{result.platform}-{result.product_version}-{result.workflow_version}{suffix}.yml".replace("/", "-")
    target = root / CERTIFICATION_ROOT / result.product_id / name
    if target.exists():
        raise ValueError(f"认证结果已存在且不可覆盖：{target}")
    _atomic_yaml(target, result.model_dump(mode="json", exclude_none=True))
    if result.product_id == "teloswork" and result.status == "passed":
        state = load_local_state(root)
        telos = state.products.get("teloswork", ProductLocalState())
        telos.import_state = "certified"
        telos.imported_version = result.product_version
        telos.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
        state.products["teloswork"] = telos
        save_local_state(root, state)
    return target


def record_certification(root: Path, result_file: Path) -> Path:
    return _record_certification_result(
        root, CertificationResult.model_validate(_yaml_read(result_file))
    )


def record_trae_cn_load_validation(root: Path, result_file: Path) -> Path:
    """Persist a hash-bound manual loading verification without copying evidence."""
    TraeCNLoadValidation.model_rebuild()
    result = TraeCNLoadValidation.model_validate(_yaml_read(result_file))
    manifest = load_manifest(root)
    product = next((item for item in manifest.products if item.product_id == "trae-cn"), None)
    if product is None:
        raise ValueError("manifest 未声明 trae-cn")
    state = load_local_state(root)
    local = state.products.get("trae-cn")
    if not local or not local.installation_path or not local.instruction_target:
        raise ValueError("Trae CN 必须先使用 agent configure 保存安装路径和指令目标")
    target = _validate_instruction_target(root, Path(local.instruction_target))
    registry = _registry_products(manifest, state)
    current = current_fingerprints(root)
    expected = {
        "product_version": registry["trae-cn"].get("version"),
        "workflow_version": current["workflow_version"],
        "repo_commit": _git_state(root)["commit"],
        "manifest_sha256": current["manifest_sha256"],
        "instruction_source_sha256": sha256_file(_trae_cn_instruction_source(root)),
        "installation_path": str(Path(local.installation_path).resolve()),
        "instruction_target": str(target),
    }
    for key, value in expected.items():
        if getattr(result, key) != value:
            raise ValueError(f"Trae CN 载入验证与当前本机或仓库绑定不一致：{key}")
    name = (
        f"{result.platform}-{result.product_version}-{result.workflow_version}-"
        f"{result.manifest_sha256[:12]}.yml"
    ).replace("/", "-")
    target_path = root / LOAD_VALIDATION_ROOT / "trae-cn" / name
    if target_path.exists():
        existing = TraeCNLoadValidation.model_validate(_yaml_read(target_path))
        if existing.model_dump(mode="json") != result.model_dump(mode="json"):
            raise ValueError(f"Trae CN 载入验证已存在且内容不同：{target_path}")
    else:
        _atomic_yaml(target_path, result.model_dump(mode="json"))
    local.load_validation_path = target_path.relative_to(root).as_posix()
    local.updated_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    state.products["trae-cn"] = local
    save_local_state(root, state)
    return target_path


def _auto_certify_codex_desktop(root: Path, transaction: Path) -> tuple[Path, Path]:
    """Run the repository-owned Codex suite and persist a hash-bound result."""
    manifest = load_manifest(root)
    policy = manifest.automation_policy
    if not policy or "codex-desktop" not in policy.certify_products:
        raise ValueError("manifest 未授权 Codex Desktop 自动认证")
    state = load_local_state(root)
    installed = state.products.get("codex-desktop")
    expected = (root / "integrations/skills/football-odds-journal").resolve()
    actual = Path(installed.installed_skill_path).resolve() if installed and installed.installed_skill_path else (Path.home() / ".codex/skills/football-odds-journal").resolve()
    if not actual.exists() or _tree_sha256(actual) != _tree_sha256(expected):
        raise ValueError("Codex Desktop 已安装 Skill 与仓库受管 Skill 不一致")
    required = sorted(_required_certification_scenarios(root, manifest.workflow_version))
    run_id = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
    command = [sys.executable, "-m", "pytest", "-q", "tests/test_codex_desktop_certification.py", f"--basetemp={transaction / 'pytest-codex-certification'}"]
    started = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    completed = subprocess.run(command, cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    ended = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    fingerprints = current_fingerprints(root)
    report = {
        "schema_version": 1,
        "run_id": run_id,
        "product_id": "codex-desktop",
        "certification_method": "automated",
        "repo_commit": _git_state(root)["commit"],
        "workflow_version": manifest.workflow_version,
        "manifest_sha256": fingerprints["manifest_sha256"],
        "skill_sha256": fingerprints["skill_sha256"],
        "instruction_sha256": fingerprints["instruction_sha256"],
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "command": command,
        "exit_code": completed.returncode,
        "scenario_ids": required,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    report_path = root / CERTIFICATION_AUTOMATION_ROOT / "codex-desktop" / f"{manifest.workflow_version}-{fingerprints['manifest_sha256'][:12]}-{run_id}.yml"
    _atomic_yaml(report_path, report)
    report_hash = sha256_file(report_path)
    if completed.returncode:
        raise ValueError(f"Codex Desktop 自动认证失败：{report_path}")
    product = next(item for item in manifest.products if item.product_id == "codex-desktop")
    result = CertificationResult.model_validate({
        "product_id": "codex-desktop",
        "product_version": _registry_products(manifest, load_local_state(root))["codex-desktop"].get("version") or "current-session",
        "platform": platform.system().lower(),
        "workflow_version": manifest.workflow_version,
        "tested_at": ended,
        "tester": "repository-automation",
        "repo_commit": _git_state(root)["commit"],
        "manifest_sha256": fingerprints["manifest_sha256"],
        "skill_sha256": fingerprints["skill_sha256"],
        "instruction_sha256": fingerprints["instruction_sha256"],
        "certification_method": "automated",
        "automation_run_id": run_id,
        "automation_report_path": report_path.relative_to(root).as_posix(),
        "automation_report_sha256": report_hash,
        "checks": [{"scenario_id": scenario_id, "status": "passed", "notes": f"automation:{run_id}"} for scenario_id in required],
        "status": "passed",
    })
    return _record_certification_result(root, result), report_path


def auto_certify_codex_desktop(root: Path) -> dict[str, Any]:
    """Diagnostic/retry entrypoint; sync remains the committing transaction."""
    git = _git_state(root)
    if not git["available"] or git["dirty"] or not git["commit"]:
        raise ValueError("自动认证要求有效提交且 Git 工作树干净")
    with _exclusive_lock(root / ".odds-journal/agent-sync.lock"):
        transaction = root / ".odds-journal/agent-sync-backups" / (
            "certify-" + datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        )
        transaction.mkdir(parents=True)
        result, report = _auto_certify_codex_desktop(root, transaction)
    return {"schema_version": 1, "product_id": "codex-desktop", "certification_result": str(result.relative_to(root)), "automation_report": str(report.relative_to(root))}


def certification_status(root: Path, *, product_id: str | None = None) -> dict[str, Any]:
    manifest = load_manifest(root)
    current = current_fingerprints(root)
    state = load_local_state(root)
    products = _registry_products(manifest, state)
    adapters = _adapter_status(root, state)
    rows: list[dict[str, Any]] = []
    for product in manifest.products:
        if product_id and product.product_id != product_id:
            continue
        current_version = products[product.product_id].get("version")
        candidates = sorted((root / CERTIFICATION_ROOT / product.product_id).glob("*.yml")) if (root / CERTIFICATION_ROOT / product.product_id).exists() else []
        matching: CertificationResult | None = None
        for path in reversed(candidates):
            try:
                item = CertificationResult.model_validate(_yaml_read(path))
            except Exception:
                continue
            if item.product_version == current_version and item.platform == platform.system().lower():
                matching = item
                break
        reasons: list[str] = []
        if matching is None:
            reasons.append("没有当前产品版本的认证结果")
        else:
            for key in ("workflow_version", "manifest_sha256", "skill_sha256", "instruction_sha256"):
                if getattr(matching, key) != current[key]:
                    reasons.append(f"{key} 已变化")
            if matching.status != "passed":
                reasons.append("认证场景未全部通过")
        if product.adapter == "project-instructions":
            adapter = adapters[product.product_id]
            if adapter["load_validation_status"] != "verified":
                reasons.append("Trae CN 真实客户端载入验证缺失或已过期")
            if adapter["status"] != "synchronized":
                reasons.append("Trae CN 受管项目指令尚未同步")
        rows.append({
            "product_id": product.product_id,
            "current_version": current_version,
            "status": "passed" if matching and not reasons else "expired",
            "certification_method": matching.certification_method if matching and not reasons else None,
            "reasons": reasons,
        })
    if product_id and not rows:
        raise ValueError(f"manifest 未声明产品：{product_id}")
    return {"schema_version": 1, "workflow_version": manifest.workflow_version, "products": rows, "all_passed": all(item["status"] == "passed" for item in rows)}
