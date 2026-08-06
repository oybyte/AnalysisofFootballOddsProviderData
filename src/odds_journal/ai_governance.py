from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ledger import append_payloads, atomic_write_text, sha256_json
from .rules import sha256_file
from .transaction import RepositoryTransaction


AI_ROOT = Path("knowledge/ai-experiments")
CONFIG_PROPOSALS = AI_ROOT / "config-proposals"
CONFIG_SNAPSHOTS = AI_ROOT / "config-snapshots"
ACTIVE_CONFIG = AI_ROOT / "active.yml"
ACTIVATION_LEDGER = AI_ROOT / "config-activation-events.jsonl"
DEACTIVATION_LEDGER = AI_ROOT / "config-deactivation-events.jsonl"
PRICING_ROOT = AI_ROOT / "provider-pricing"

PAYLOAD_FIELDS = {
    "fixture_identity", "market_features", "official_receipt", "official_evaluation",
    "official_outlook", "case_receipt", "output_schema", "rendered_prompt",
}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _now() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)


def _safe_path(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"AI 资产路径越出项目根目录：{value}") from exc
    return candidate


class EvidenceRefV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "official_analysis_receipt", "official_evaluation_bundle", "official_outlook",
        "lock_candidate_receipt", "case_receipt", "market_observation",
        "market_feature_snapshot", "fixture_fact", "rule_event",
    ]
    ref_id: str = Field(min_length=1)
    ref_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim: str = Field(min_length=1)
    effective_at: datetime

    @field_validator("effective_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("EvidenceRef effective_at 必须包含时区")
        return value


class TrustedAIAssetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    kind: Literal["prompt", "outbound_policy", "output_schema", "reasoning_profile"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PromptReferenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["facts", "rules", "cases", "prediction", "risk"]
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OutboundDataPolicyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    provider_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    network_access: Literal["deny", "allow"] = "deny"
    approved_by: str | None = None
    approved_at: datetime | None = None
    allowed_payload_fields: list[str] = Field(default_factory=list)
    response_storage: Literal["repository", "local_ignored", "hash_only"] = "hash_only"

    @model_validator(mode="after")
    def valid_policy(self) -> "OutboundDataPolicyV1":
        if set(self.allowed_payload_fields) - PAYLOAD_FIELDS:
            raise ValueError("出站策略包含未允许的 payload 字段")
        if len(self.allowed_payload_fields) != len(set(self.allowed_payload_fields)):
            raise ValueError("allowed_payload_fields 不得重复")
        if self.network_access == "allow":
            if self.approved_by != "lcz" or self.approved_at is None:
                raise ValueError("允许外部网络必须由 lcz 批准并记录时间")
            if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
                raise ValueError("approved_at 必须包含时区")
        return self


class ProviderPricingSnapshotV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    provider_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    model_id: str = Field(min_length=1)
    input_cost_per_1k: float = Field(ge=0)
    output_cost_per_1k: float = Field(ge=0)
    currency: Literal["USD"] = "USD"
    effective_at: datetime
    pricing_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("effective_at")
    @classmethod
    def pricing_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("价格快照时间必须包含时区")
        return value


class BudgetV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_total_tokens: int = Field(gt=0)
    max_total_cost: float | None = Field(default=None, ge=0)
    currency: Literal["USD"] = "USD"


class RuntimeLimitsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_timeout_seconds: int = Field(gt=0, le=600)
    max_retries_per_stage: int = Field(ge=0, le=3)


class AIExperimentConfigSnapshotV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    config_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    research_track: Literal["pilot", "confirmatory"]
    provider_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    model_id: str = Field(min_length=1)
    llm_parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    prompt_manifest: list[PromptReferenceV1] = Field(min_length=1)
    case_profile: Literal["strict_validation", "exploratory_research"]
    reasoning_profile_id: str = Field(min_length=1)
    reasoning_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_algorithm_version: str = Field(min_length=1)
    outbound_data_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_pricing_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    budget: BudgetV1
    runtime_limits: RuntimeLimitsV1
    snapshot_sha256: str = Field(default="0" * 64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_track(self) -> "AIExperimentConfigSnapshotV1":
        if self.research_track == "confirmatory" and self.case_profile != "strict_validation":
            raise ValueError("confirmatory 必须使用 strict_validation 案例 profile")
        stages = [item.stage for item in self.prompt_manifest]
        if len(stages) != len(set(stages)):
            raise ValueError("Prompt stage 不得重复")
        return self


class AIExperimentConfigActivationEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["ai_config_activated"] = "ai_config_activated"
    config_id: str
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str
    revision: int = Field(ge=1)
    approved_by: Literal["lcz"]
    activated_at: datetime


class AIExperimentConfigDeactivationEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["ai_config_deactivated"] = "ai_config_deactivated"
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: Literal["lcz"]
    deactivated_at: datetime
    reason: str = Field(min_length=1)


class ActiveAIConfigV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    status: Literal["active", "inactive"]
    config_id: str
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_path: str
    revision: int = Field(ge=1)
    updated_at: datetime


class LLMProvider(Protocol):
    provider_id: str

    def run(self, *, model_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class FakeProvider:
    provider_id = "fake-offline"

    def run(self, *, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "model_id": model_id,
            "payload_sha256": _hash(payload),
            "response": {"status": "fake", "markets": {}},
            "input_tokens": 0,
            "output_tokens": 0,
        }


def config_digest(config: AIExperimentConfigSnapshotV1, assets: list[TrustedAIAssetV1]) -> str:
    body = config.model_dump(mode="json")
    body["snapshot_sha256"] = "0" * 64
    return _hash({"config": body, "assets": [item.model_dump(mode="json") for item in sorted(assets, key=lambda item: item.path)]})


def _load_manifest_assets(root: Path) -> list[TrustedAIAssetV1]:
    from .desktop_agents import load_manifest

    return [TrustedAIAssetV1.model_validate(item.model_dump(mode="json")) for item in load_manifest(root).trusted_ai_assets]


def _validate_assets(root: Path, config: AIExperimentConfigSnapshotV1) -> tuple[list[TrustedAIAssetV1], OutboundDataPolicyV1]:
    assets = _load_manifest_assets(root)
    by_path = {item.path: item for item in assets}
    prompt_paths = {item.path for item in config.prompt_manifest}
    if len(prompt_paths) != len(config.prompt_manifest):
        raise ValueError("Prompt 路径不可重复")
    selected: list[TrustedAIAssetV1] = []
    for prompt in config.prompt_manifest:
        asset = by_path.get(prompt.path)
        if asset is None or asset.kind != "prompt" or asset.content_sha256 != prompt.sha256:
            raise ValueError(f"Prompt 不在受信 AI 资产清单中：{prompt.path}")
        if not _safe_path(root, prompt.path).is_file() or sha256_file(_safe_path(root, prompt.path)) != prompt.sha256:
            raise ValueError(f"Prompt 文件哈希不一致：{prompt.path}")
        selected.append(asset)
    special = [item for item in assets if item.content_sha256 in {config.reasoning_profile_sha256, config.output_schema_sha256, config.outbound_data_policy_sha256}]
    if len(special) != 3 or {item.kind for item in special} != {"reasoning_profile", "output_schema", "outbound_policy"}:
        raise ValueError("配置引用的推理 profile、输出 Schema 或出站策略不在受信清单中")
    for item in special:
        if not _safe_path(root, item.path).is_file() or sha256_file(_safe_path(root, item.path)) != item.content_sha256:
            raise ValueError(f"AI 资产哈希不一致：{item.path}")
    policy_asset = next(item for item in special if item.kind == "outbound_policy")
    policy = OutboundDataPolicyV1.model_validate(yaml.safe_load(_safe_path(root, policy_asset.path).read_text(encoding="utf-8")) or {})
    if policy.provider_id != config.provider_id:
        raise ValueError("出站策略 provider 与配置不一致")
    return [*selected, *special], policy


def validate_config(root: Path, config_path: Path) -> AIExperimentConfigSnapshotV1:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("AI 配置顶层必须为对象")
    forbidden = {"prompt", "instructions", "system_prompt", "tool"} & set(raw)
    if forbidden:
        raise ValueError("AI 配置不得内嵌 Prompt 或可执行指令：" + ", ".join(sorted(forbidden)))
    config = AIExperimentConfigSnapshotV1.model_validate(raw)
    assets, policy = _validate_assets(root, config)
    digest = config_digest(config, assets)
    if config.snapshot_sha256 not in {"0" * 64, digest}:
        raise ValueError("配置 snapshot_sha256 与内容不一致")
    if policy.network_access == "allow" and config.provider_pricing_snapshot_sha256 is None:
        raise ValueError("外部 provider 必须冻结价格快照")
    return config.model_copy(update={"snapshot_sha256": digest})


def _next_revision(root: Path, config_id: str) -> int:
    if not (root / ACTIVATION_LEDGER).exists():
        return 1
    from .ledger import read_ledger

    return 1 + max((int(event.payload.get("revision", 0)) for event in read_ledger(root / ACTIVATION_LEDGER) if event.payload.get("config_id") == config_id), default=0)


def activate_config(root: Path, config_path: Path, *, approved_by: str) -> ActiveAIConfigV1:
    if approved_by != "lcz":
        raise ValueError("AI 配置只能由 lcz 激活")
    config = validate_config(root, config_path)
    assets, _ = _validate_assets(root, config)
    target = root / CONFIG_SNAPSHOTS / config.snapshot_sha256
    active_path = root / ACTIVE_CONFIG
    if active_path.is_file():
        existing = ActiveAIConfigV1.model_validate(yaml.safe_load(active_path.read_text(encoding="utf-8")) or {})
        if existing.status == "active" and existing.snapshot_sha256 == config.snapshot_sha256:
            return existing
    revision = _next_revision(root, config.config_id)
    now = _now()
    active = ActiveAIConfigV1(
        status="active", config_id=config.config_id, snapshot_sha256=config.snapshot_sha256,
        snapshot_path=target.relative_to(root).as_posix(), revision=revision, updated_at=now,
    )
    with RepositoryTransaction(root, files=[active_path, root / ACTIVATION_LEDGER], directories=[target], operation="activate-ai-config") as transaction:
        if not target.exists():
            target.mkdir(parents=True)
            atomic_write_text(target / "config.yml", yaml.safe_dump(config.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
            copied = []
            for asset in sorted(assets, key=lambda item: item.path):
                source = _safe_path(root, asset.path)
                destination = target / "assets" / asset.path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
                copied.append({"path": asset.path, "kind": asset.kind, "sha256": asset.content_sha256})
            atomic_write_text(target / "manifest.yml", yaml.safe_dump({"schema_version": 1, "snapshot_sha256": config.snapshot_sha256, "assets": copied}, allow_unicode=True, sort_keys=False))
        else:
            stored = AIExperimentConfigSnapshotV1.model_validate(
                yaml.safe_load((target / "config.yml").read_text(encoding="utf-8")) or {}
            )
            manifest = yaml.safe_load((target / "manifest.yml").read_text(encoding="utf-8")) or {}
            if stored.snapshot_sha256 != config.snapshot_sha256 or manifest.get("snapshot_sha256") != config.snapshot_sha256:
                raise ValueError("已存在 AI 配置快照内容不一致")
            for asset in assets:
                copied_asset = target / "assets" / asset.path
                if not copied_asset.is_file() or sha256_file(copied_asset) != asset.content_sha256:
                    raise ValueError(f"已存在 AI 配置快照资产不一致：{asset.path}")
        atomic_write_text(active_path, yaml.safe_dump(active.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        event = AIExperimentConfigActivationEventV1(config_id=config.config_id, snapshot_sha256=config.snapshot_sha256, snapshot_path=active.snapshot_path, revision=revision, approved_by="lcz", activated_at=now)
        append_payloads(root / ACTIVATION_LEDGER, [event.model_dump(mode="json")], recorded_at=now, actor="lcz", event_id_factory=lambda item, _: f"ai-config:activate:{item['snapshot_sha256']}:{item['revision']}")
        transaction.commit()
    return active


def deactivate_config(root: Path, *, approved_by: str, reason: str) -> ActiveAIConfigV1:
    if approved_by != "lcz" or not reason.strip():
        raise ValueError("停用 AI 配置必须由 lcz 提供原因")
    active_path = root / ACTIVE_CONFIG
    if not active_path.is_file():
        raise ValueError("没有活动 AI 配置")
    active = ActiveAIConfigV1.model_validate(yaml.safe_load(active_path.read_text(encoding="utf-8")) or {})
    now = _now()
    inactive = active.model_copy(update={"status": "inactive", "updated_at": now})
    with RepositoryTransaction(root, files=[active_path, root / DEACTIVATION_LEDGER], directories=[], operation="deactivate-ai-config") as transaction:
        atomic_write_text(active_path, yaml.safe_dump(inactive.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        event = AIExperimentConfigDeactivationEventV1(snapshot_sha256=active.snapshot_sha256, approved_by="lcz", deactivated_at=now, reason=reason.strip())
        append_payloads(root / DEACTIVATION_LEDGER, [event.model_dump(mode="json")], recorded_at=now, actor="lcz", event_id_factory=lambda item, _: f"ai-config:deactivate:{item['snapshot_sha256']}")
        transaction.commit()
    return inactive


def active_config(root: Path) -> ActiveAIConfigV1 | None:
    path = root / ACTIVE_CONFIG
    if not path.is_file():
        return None
    item = ActiveAIConfigV1.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if item.status != "active":
        return None
    snapshot = _safe_path(root, item.snapshot_path)
    if not (snapshot / "config.yml").is_file():
        raise ValueError("活动 AI 配置快照缺失")
    return item


def sandbox_run(root: Path, config_path: Path, fixture_path: Path) -> dict[str, Any]:
    if "tests" not in fixture_path.resolve().parts or "fixtures" not in fixture_path.resolve().parts:
        raise ValueError("sandbox 只接受 tests/fixtures 下的合成夹具")
    fixture = yaml.safe_load(fixture_path.read_text(encoding="utf-8")) or {}
    if not isinstance(fixture, dict) or fixture.get("synthetic") is not True:
        raise ValueError("sandbox 夹具必须声明 synthetic: true")
    config = validate_config(root, config_path)
    if config.provider_id != "fake-offline":
        raise ValueError("sandbox 只允许 fake-offline provider")
    with tempfile.TemporaryDirectory(prefix="odds-journal-ai-sandbox-"):
        response = FakeProvider().run(model_id=config.model_id, payload={"fixture_identity": fixture.get("fixture", {}), "rendered_prompt": "sandbox"})
    return {"schema_version": 1, "status": "completed", "provider_id": "fake-offline", "response_sha256": _hash(response)}
