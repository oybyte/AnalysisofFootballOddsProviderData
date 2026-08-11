from __future__ import annotations

"""Append-only, offline AI research runs.

This module deliberately has no dependency on the formal analysis writer.  It can
read a frozen official lock, but never writes a Match document or formal receipt.
"""

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ai_governance import AIExperimentConfigSnapshotV1, EvidenceRefV1, OutboundDataPolicyV1, active_config
from .analysis_context import parse_receipt
from .case_retrieval import parse_case_receipt
from .ledger import append_payloads, atomic_write_text, sha256_json
from .lock_lifecycle import LockCandidateReceiptV1, latest_lock_candidate
from .markdown import MatchDocument
from .models import AnalysisOutlook, MatchStatus
from .observations import market_feature_snapshot
from .rules import sha256_file
from .transaction import RepositoryTransaction


AI_ROOT = Path("knowledge/ai-experiments")
STUDIES = AI_ROOT / "study-events.jsonl"
PRIMARY = AI_ROOT / "primary-claim-events.jsonl"
OUTCOMES = AI_ROOT / "outcome-events.jsonl"
FAILURES = AI_ROOT / "run-failure-events.jsonl"
DISPOSITIONS = AI_ROOT / "disposition-events.jsonl"


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"YAML 顶层必须为对象：{path}")
    return raw


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("AI 研究文件必须位于项目目录") from exc
    return resolved


class AIExperimentStudyV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    study_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    config_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    registered_by: Literal["lcz"]
    registered_at: datetime
    sample_relation: Literal["out_of_sample"] = "out_of_sample"
    required_capability_profile: list[str] = Field(default_factory=list)
    eligible_match_ids: list[str] = Field(default_factory=list)
    official_baseline_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stopping_conditions: list[str] = Field(min_length=1)
    status: Literal["registered", "closed", "superseded"] = "registered"
    study_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("registered_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Study 登记时间必须包含时区")
        return value

    @model_validator(mode="after")
    def valid_study(self) -> "AIExperimentStudyV1":
        if len(self.eligible_match_ids) != len(set(self.eligible_match_ids)):
            raise ValueError("Study eligible_match_ids 不得重复")
        return self


class AIExperimentStageEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["facts", "rules", "cases", "prediction", "risk"]
    status: Literal["completed", "unavailable", "failed", "no_case_comparison"]
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    model_response_id: str | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float = Field(ge=0)
    retries: int = Field(ge=0)
    reason: str | None = None


class AIExperimentBundleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str
    match_id: str
    official_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stages: list[AIExperimentStageEventV1] = Field(min_length=5, max_length=5)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def stages_once(self) -> "AIExperimentBundleV1":
        expected = {"facts", "rules", "cases", "prediction", "risk"}
        if {item.stage for item in self.stages} != expected:
            raise ValueError("AI Bundle 必须恰有五个阶段")
        return self


class AIExperimentOutlookV1(BaseModel):
    """Research-only structure; it is intentionally not an AnalysisOutlook."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str
    match_id: str
    market_statuses: dict[Literal["one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score"], Literal["assessed", "pass"]]
    predictions: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[EvidenceRefV1] = Field(default_factory=list)
    outlook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def valid_assessments(self) -> "AIExperimentOutlookV1":
        expected = {"one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score"}
        if set(self.market_statuses) != expected:
            raise ValueError("AI Outlook 必须声明五个市场状态")
        assessed = {market for market, status in self.market_statuses.items() if status == "assessed"}
        if set(self.predictions) - assessed:
            raise ValueError("AI Outlook 不得为 pass 市场写入预测")
        for market in assessed:
            evidence = [item for item in self.evidence_refs if item.claim.startswith(f"{market}:")]
            claims = {item.claim.split(":", 2)[1] for item in evidence if ":" in item.claim}
            if not {"support", "counter"}.issubset(claims):
                raise ValueError(f"AI Outlook assessed 市场缺少支持或反证 EvidenceRef：{market}")
        return self


class AIExperimentPrimaryClaimEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    receipt_id: str
    study_id: str
    config_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claimed_at: datetime

    @field_validator("claimed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Primary claim 时间必须包含时区")
        return value


class AIExperimentReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str = Field(pattern=r"^ai-[a-z0-9-]+$")
    match_id: str
    study_id: str | None = None
    run_role: Literal["diagnostic", "primary"]
    config_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lock_candidate_receipt_id: str
    lock_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_evaluation_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: datetime
    locked_at: datetime
    kickoff_at: datetime
    sealed_at: datetime
    status: Literal["sealed", "failed", "stale"]
    capability_profile: list[str] = Field(default_factory=list)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of", "locked_at", "kickoff_at", "sealed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AI Receipt 时间必须包含时区")
        return value

    @model_validator(mode="after")
    def chronological(self) -> "AIExperimentReceiptV1":
        if self.as_of > self.locked_at or self.locked_at >= self.kickoff_at or self.sealed_at >= self.kickoff_at:
            raise ValueError("AI Receipt 必须使用开赛前已锁定的正式输入")
        return self


class AIExperimentRunManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    receipt_id: str
    status: Literal["sealed", "failed", "stale"]
    files: dict[str, str] = Field(min_length=2)
    failure_reason: str | None = None
    run_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AIExperimentOutcomeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    outcome_id: str = Field(pattern=r"^ai-outcome-[a-z0-9-]+$")
    receipt_id: str
    match_id: str
    result_score: str
    result_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["not_evaluated", "evaluated"]
    eligible_for_study: bool
    exclusion_reasons: list[str] = Field(default_factory=list)
    markets: dict[str, Literal["correct", "incorrect", "not_evaluated"]]
    outcome_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AIExperimentDispositionEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    outcome_id: str
    disposition: Literal["support", "counterexample", "ambiguous", "not_applicable"]
    reason: str = Field(min_length=3)
    counter_evidence: list[EvidenceRefV1] = Field(default_factory=list)
    actor: Literal["lcz"]
    recorded_at: datetime
    disposition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("AI 人工处置时间必须包含时区")
        return value


def _digest(model: BaseModel, field: str) -> str:
    raw = model.model_dump(mode="json")
    raw[field] = "0" * 64
    return _hash(raw)


def _load_active_config(root: Path) -> tuple[Any, AIExperimentConfigSnapshotV1]:
    active = active_config(root)
    if active is None:
        raise ValueError("没有活动 AI 配置")
    snapshot = _inside(root, root / active.snapshot_path)
    config_path = snapshot / "config.yml"
    if not config_path.is_file():
        raise ValueError("活动 AI 配置快照缺失")
    config = AIExperimentConfigSnapshotV1.model_validate(_yaml(config_path))
    if config.snapshot_sha256 != active.snapshot_sha256:
        raise ValueError("活动 AI 配置与快照哈希不一致")
    manifest = _yaml(snapshot / "manifest.yml")
    if manifest.get("snapshot_sha256") != active.snapshot_sha256:
        raise ValueError("活动 AI 配置快照 Manifest 不一致")
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise ValueError("活动 AI 配置快照资产清单无效")
    for item in assets:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("sha256"), str):
            raise ValueError("活动 AI 配置快照资产条目无效")
        asset = (snapshot / "assets" / item["path"]).resolve()
        try:
            asset.relative_to((snapshot / "assets").resolve())
        except ValueError as exc:
            raise ValueError("活动 AI 配置快照资产路径越界") from exc
        if not asset.is_file() or sha256_file(asset) != item["sha256"]:
            raise ValueError(f"活动 AI 配置快照资产哈希不一致：{item['path']}")
    return active, config


def _study(root: Path, study_id: str) -> AIExperimentStudyV1:
    events = read_studies(root)
    found = [item for item in events if item.study_id == study_id]
    if not found:
        raise ValueError("Primary 需要已登记 Study")
    study = found[-1]
    if study.status != "registered":
        raise ValueError("Study 不是可用状态")
    if study.study_sha256 != _digest(study, "study_sha256"):
        raise ValueError("Study 哈希无效")
    return study


def read_studies(root: Path) -> list[AIExperimentStudyV1]:
    from .ledger import read_ledger

    ledger = root / STUDIES
    return [AIExperimentStudyV1.model_validate(event.payload) for event in read_ledger(ledger)] if ledger.exists() else []


def _primary_claims(root: Path) -> list[dict[str, Any]]:
    from .ledger import read_ledger

    ledger = root / PRIMARY
    return [event.payload for event in read_ledger(ledger)] if ledger.exists() else []


def register_study(root: Path, study: AIExperimentStudyV1) -> AIExperimentStudyV1:
    if study.registered_by != "lcz":
        raise ValueError("Study 只能由 lcz 登记")
    if study.study_sha256 not in {"0" * 64, _digest(study, "study_sha256")}:
        raise ValueError("Study 哈希与内容不一致")
    sealed = study.model_copy(update={"study_sha256": _digest(study, "study_sha256")})
    if any(item.study_id == sealed.study_id for item in read_studies(root)):
        raise ValueError("Study 已存在；变更必须登记新的 Study")
    append_payloads(
        root / STUDIES, [sealed.model_dump(mode="json")], recorded_at=sealed.registered_at, actor="lcz",
        event_id_factory=lambda item, _: f"ai-study:{item['study_id']}",
    )
    return sealed


def _official_inputs(root: Path, document: MatchDocument) -> tuple[LockCandidateReceiptV1, dict[str, Any], dict[str, Any]]:
    metadata = document.metadata
    if MatchStatus(metadata.status) not in {MatchStatus.LOCKED, MatchStatus.FINISHED, MatchStatus.REVIEWED}:
        raise ValueError("AI 实验仅接受已正式锁定比赛")
    if not metadata.locked_at or metadata.locked_at >= metadata.kickoff_at:
        raise ValueError("正式锁定时间无效")
    candidate_pair = latest_lock_candidate(root, metadata.match_id)
    if candidate_pair is None:
        raise ValueError("缺少已冻结 LockCandidateReceipt")
    _, candidate = candidate_pair
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    cases = parse_case_receipt(document.sections["prematch-reasoning"], required=True)
    if receipt is None:
        raise ValueError("缺少正式 AnalysisReceipt")
    if sha256_json(receipt.model_dump(mode="json")) != candidate.analysis_receipt_sha256:
        raise ValueError("正式 AnalysisReceipt 与 LockCandidate 不一致")
    if sha256_json(cases.model_dump(mode="json")) != candidate.case_receipt_sha256:
        raise ValueError("CaseReceipt 与 LockCandidate 不一致")
    outlook_path = _inside(root, root / candidate.outlook_path)
    if not outlook_path.is_file() or _file_hash(outlook_path) != candidate.outlook_sha256:
        raise ValueError("正式 Outlook 文件缺失或哈希不一致")
    outlook = AnalysisOutlook.model_validate(_yaml(outlook_path))
    if outlook.evaluation_bundle_sha256 is None:
        raise ValueError("正式 Outlook 缺少 EvaluationBundle 引用")
    evaluation_path = root / "raw" / "matches" / metadata.match_id / f"rule-evaluation-{outlook.evaluation_bundle_sha256}.yml"
    evaluation = _yaml(evaluation_path) if evaluation_path.is_file() else None
    if not evaluation or evaluation.get("bundle_sha256") != outlook.evaluation_bundle_sha256:
        raise ValueError("正式 EvaluationBundle 缺失或哈希不一致")
    input_data = {
        "analysis_receipt_sha256": candidate.analysis_receipt_sha256,
        "analysis_outlook_sha256": candidate.analysis_outlook_sha256,
        "case_receipt_sha256": candidate.case_receipt_sha256,
        "lock_candidate_sha256": candidate.receipt_sha256,
        "prematch_content_sha256": candidate.prematch_content_sha256,
        "official_evaluation_bundle_sha256": outlook.evaluation_bundle_sha256,
        "case_context_sha256": cases.context_sha256,
    }
    return candidate, input_data, {"receipt": receipt, "cases": cases, "outlook": outlook, "evaluation": evaluation}


def _run_directory(root: Path, match_id: str, receipt_id: str) -> Path:
    return root / "raw" / "matches" / match_id / "ai-experiments" / receipt_id


def _verify_sealed_run(base: Path, receipt: AIExperimentReceiptV1) -> AIExperimentRunManifestV1:
    manifest = AIExperimentRunManifestV1.model_validate(_yaml(base / "run-manifest.yml"))
    if receipt.receipt_sha256 != _digest(receipt, "receipt_sha256") or manifest.run_manifest_sha256 != _digest(manifest, "run_manifest_sha256"):
        raise ValueError("AI 封存产物哈希无效")
    if manifest.receipt_id != receipt.receipt_id or {"receipt.yml", "bundle.yml"} - set(manifest.files):
        raise ValueError("AI RunManifest 缺少必要封存文件")
    for relative, digest in manifest.files.items():
        candidate = (base / relative).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError as exc:
            raise ValueError("AI RunManifest 文件路径越界") from exc
        if not candidate.is_file() or _file_hash(candidate) != digest:
            raise ValueError(f"AI 封存文件哈希不一致：{relative}")
    bundle = AIExperimentBundleV1.model_validate(_yaml(base / "bundle.yml"))
    if bundle.receipt_id != receipt.receipt_id or bundle.bundle_sha256 != _digest(bundle, "bundle_sha256"):
        raise ValueError("AI Bundle 哈希无效")
    return manifest


def _load_ai_outlook(base: Path, receipt: AIExperimentReceiptV1) -> AIExperimentOutlookV1 | None:
    path = base / "outlook.yml"
    if not path.is_file():
        return None
    outlook = AIExperimentOutlookV1.model_validate(_yaml(path))
    if outlook.receipt_id != receipt.receipt_id or outlook.match_id != receipt.match_id or outlook.outlook_sha256 != _digest(outlook, "outlook_sha256"):
        raise ValueError("AI Outlook 哈希无效")
    return outlook


def _market_outcome(outlook: AIExperimentOutlookV1, metadata: Any) -> dict[str, Literal["correct", "incorrect", "not_evaluated"]]:
    result: dict[str, Literal["correct", "incorrect", "not_evaluated"]] = {}
    for market, status in outlook.market_statuses.items():
        if status == "pass":
            result[market] = "not_evaluated"
            continue
        prediction = outlook.predictions.get(market)
        if not isinstance(prediction, dict):
            result[market] = "not_evaluated"
        elif market == "one_x_two":
            result[market] = "correct" if prediction.get("selection") == str(metadata.result_1x2) else "incorrect"
        elif market == "asian_handicap":
            result[market] = "correct" if prediction.get("selection") == str(metadata.handicap_result) else "incorrect"
        elif market == "total_goals":
            lower, upper = prediction.get("minimum"), prediction.get("maximum")
            result[market] = "correct" if isinstance(lower, int) and isinstance(upper, int) and lower <= int(metadata.total_goals) <= upper else "incorrect"
        elif market == "score":
            candidates = prediction.get("candidates")
            result[market] = "correct" if isinstance(candidates, list) and metadata.score in candidates else "incorrect"
        else:
            result[market] = "not_evaluated"
    return result


def _existing_primary(root: Path, match_id: str) -> dict[str, Any] | None:
    claims = [item for item in _primary_claims(root) if item.get("match_id") == match_id]
    return claims[-1] if claims else None


def _load_provider_policy(root: Path, policy_sha256: str) -> OutboundDataPolicyV1:
    """Load and verify an outbound data policy from the active config snapshot."""
    active = active_config(root)
    if active is None:
        raise ValueError("没有活动 AI 配置")
    snapshot = _inside(root, root / active.snapshot_path)
    assets_dir = snapshot / "assets"
    for asset_path in assets_dir.rglob("*.yml"):
        if sha256_file(asset_path) == policy_sha256:
            raw = yaml.safe_load(asset_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError("出站策略文件格式无效")
            policy = OutboundDataPolicyV1.model_validate(raw)
            if policy.network_access == "allow" and (policy.approved_by != "lcz" or policy.approved_at is None):
                raise ValueError("出站策略 network_access: allow 需要 lcz 审批")
            return policy
    raise ValueError("出站策略不在活动 AI 配置快照中")


def _validate_run_config(root: Path, config: AIExperimentConfigSnapshotV1) -> None:
    expected = {"facts", "rules", "cases", "prediction", "risk"}
    if {item.stage for item in config.prompt_manifest} != expected:
        raise ValueError("AI 运行配置必须冻结五个阶段的 Prompt")
    from .llm_provider import PROVIDER_REGISTRY
    if config.provider_id not in PROVIDER_REGISTRY:
        raise ValueError(f"未知 AI provider：{config.provider_id}")
    if config.provider_id != "fake-offline":
        policy = _load_provider_policy(root, config.outbound_data_policy_sha256)
        if policy.network_access != "allow":
            raise ValueError("真实 provider 需要出站策略 network_access: allow")


def _compile_stages(
    *, root: Path, active: Any, config: AIExperimentConfigSnapshotV1, official: dict[str, Any],
    cases: Any, feature: dict[str, Any], receipt: Any, outlook: Any, evaluation: dict[str, Any] | None,
    metadata: Any,
) -> list[AIExperimentStageEventV1]:
    from .llm_provider import get_provider
    provider = get_provider(config.provider_id)
    snapshot = _inside(root, root / active.snapshot_path)
    prompts_by_stage: dict[str, str] = {}
    for prompt_ref in config.prompt_manifest:
        prompt_path = snapshot / "assets" / prompt_ref.path
        if not prompt_path.is_file() or sha256_file(prompt_path) != prompt_ref.sha256:
            raise ValueError(f"Prompt 文件哈希不一致：{prompt_ref.path}")
        prompts_by_stage[prompt_ref.stage] = prompt_path.read_text(encoding="utf-8")
    fixture_identity = {
        "match_id": feature.get("match_id", ""),
        "home_team": getattr(metadata, "home_team", "") or "",
        "away_team": getattr(metadata, "away_team", "") or "",
        "competition": getattr(metadata, "competition", "") or "",
        "kickoff_at": str(metadata.kickoff_at) if getattr(metadata, "kickoff_at", None) else "",
    }
    market_data = {
        "series": feature.get("series", []),
        "phase_only_series": feature.get("phase_only_series", []),
        "provider_direction_matrix": feature.get("provider_direction_matrix", []),
    }
    rules_data = evaluation if evaluation else {}
    cases_data = {
        "selected_cases": [case.model_dump(mode="json") if hasattr(case, "model_dump") else case for case in (cases.selected_cases or [])],
    }
    outlook_data = outlook.model_dump(mode="json") if outlook else {}
    staged_inputs: dict[str, dict[str, Any]] = {
        "facts": {"fixture_identity": fixture_identity, "market_features": market_data},
        "rules": {"official_receipt": {"ruleset_id": getattr(receipt, "ruleset_id", ""), "competition_profile": getattr(receipt, "competition_profile", "global")}, "rule_evaluation": rules_data},
        "cases": {"case_receipt": cases_data, "untrusted_case_data": "no_case_comparison" if not cases.selected_cases else "escaped"},
        "prediction": {"output_schema_sha256": config.output_schema_sha256, "official_outlook": outlook_data},
        "risk": {"market_features": market_data, "official_outlook": outlook_data, "late_60m_observations": feature.get("late_60m_observation_ids", []), "excluded_observations": feature.get("excluded_observations", []), "anomalies": feature.get("conflicts", [])},
    }
    stage_outputs: dict[str, dict[str, Any]] = {}
    events: list[AIExperimentStageEventV1] = []
    stage_order = ("facts", "rules", "cases", "prediction", "risk")
    for idx, stage in enumerate(stage_order):
        if idx > 0 and config.provider_id != "fake-offline":
            time.sleep(10)
        payload = dict(staged_inputs[stage])
        if stage in ("prediction", "risk"):
            payload["stage_facts_output"] = stage_outputs.get("facts", {})
            payload["stage_rules_output"] = stage_outputs.get("rules", {})
            payload["stage_cases_output"] = stage_outputs.get("cases", {})
        status: Literal["completed", "unavailable", "failed", "no_case_comparison"] = "no_case_comparison" if stage == "cases" and not cases.selected_cases else "completed"
        system_prompt = prompts_by_stage.get(stage)
        response = provider.run(model_id=config.model_id, payload=payload, system_prompt=system_prompt)
        stage_outputs[stage] = response.get("response", response)
        events.append(AIExperimentStageEventV1(
            stage=stage, status=status, input_sha256=_hash(payload), response_sha256=_hash(response),
            model_response_id=None, input_tokens=int(response.get("input_tokens", 0)), output_tokens=int(response.get("output_tokens", 0)),
            cost=0, retries=0, reason=None,
        ))
    return events


def run(root: Path, path: Path, *, role: Literal["diagnostic", "primary"], study_id: str | None = None, nonce: str | None = None) -> tuple[Path, AIExperimentReceiptV1]:
    root = root.resolve()
    document = MatchDocument.load(_inside(root, path))
    metadata = document.metadata
    now = _now()
    if metadata.score or now >= metadata.kickoff_at:
        raise ValueError("开赛或赛果后禁止启动 AI 运行")
    active, config = _load_active_config(root)
    _validate_run_config(root, config)
    candidate, official, context = _official_inputs(root, document)
    if role == "primary":
        if config.research_track != "confirmatory" or not study_id:
            raise ValueError("Primary 需要 confirmatory 配置和 Study")
        study = _study(root, study_id)
        if study.config_snapshot_sha256 != active.snapshot_sha256:
            raise ValueError("Study 与活动 AI 配置快照不一致")
        if study.official_baseline_schema_sha256 != _hash(AnalysisOutlook.model_json_schema()):
            raise ValueError("Study 未冻结当前正式 Outlook schema")
        if study.eligible_match_ids and metadata.match_id not in study.eligible_match_ids:
            raise ValueError("比赛不在 Study 冻结 cohort")
        if not set(study.required_capability_profile).issubset({"fake-offline"}):
            raise ValueError("Study 所需 capability 当前不可用")
    elif study_id is not None:
        raise ValueError("diagnostic 不得占用 Study")
    else:
        study = None
    identity = [metadata.match_id, candidate.receipt_sha256, active.snapshot_sha256, role, study_id]
    if role == "diagnostic":
        identity.append(nonce or uuid4().hex)
    receipt_id = "ai-" + _hash(identity)[:24]
    target = _run_directory(root, metadata.match_id, receipt_id)
    if target.exists():
        receipt = AIExperimentReceiptV1.model_validate(_yaml(target / "receipt.yml"))
        _verify_sealed_run(target, receipt)
        return target, receipt
    prior = _existing_primary(root, metadata.match_id) if role == "primary" else None
    if prior is not None:
        raise ValueError("该比赛已有 Primary claim，禁止更换模型、配置或 Receipt")
    feature = market_feature_snapshot(root, metadata.match_id, candidate.data_cutoff_at)
    receipt_raw = {
        "receipt_id": receipt_id, "match_id": metadata.match_id, "study_id": study_id, "run_role": role,
        "config_snapshot_sha256": active.snapshot_sha256, "lock_candidate_receipt_id": candidate.receipt_id,
        "lock_candidate_sha256": candidate.receipt_sha256, "official_input_sha256": _hash(official),
        "official_evaluation_bundle_sha256": official["official_evaluation_bundle_sha256"],
        "case_context_sha256": official["case_context_sha256"], "observation_set_sha256": feature["observation_set_sha256"],
        "as_of": candidate.data_cutoff_at, "locked_at": metadata.locked_at, "kickoff_at": metadata.kickoff_at,
        "sealed_at": now, "status": "sealed", "capability_profile": ["fake-offline"], "receipt_sha256": "0" * 64,
    }
    provisional = AIExperimentReceiptV1.model_validate(receipt_raw)
    receipt = provisional.model_copy(update={"receipt_sha256": _digest(provisional, "receipt_sha256")})
    try:
        with RepositoryTransaction(root, files=[root / PRIMARY, root / FAILURES], directories=[target], operation="run-ai-experiment") as transaction:
            target.mkdir(parents=True)
            atomic_write_text(target / "receipt.yml", yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
            if role == "primary":
                claim = AIExperimentPrimaryClaimEventV1(
                    match_id=metadata.match_id, receipt_id=receipt.receipt_id, study_id=study_id or "",
                    config_snapshot_sha256=active.snapshot_sha256, claimed_at=now,
                )
                append_payloads(
                    root / PRIMARY, [claim.model_dump(mode="json")],
                    recorded_at=now, actor="system", event_id_factory=lambda item, _: f"ai-primary:{item['match_id']}",
                )
            failure_reason: str | None = None
            try:
                stages = _compile_stages(root=root, active=active, config=config, official=official, cases=context["cases"], feature=feature, receipt=context["receipt"], outlook=context["outlook"], evaluation=context["evaluation"], metadata=metadata)
            except Exception as exc:
                failure_reason = f"provider_or_stage_failure:{exc}"
                stages = [
                    AIExperimentStageEventV1(
                        stage=stage, status="failed" if stage == "prediction" else "unavailable",
                        input_sha256=_hash({"receipt_id": receipt.receipt_id, "stage": stage}), response_sha256=None,
                        model_response_id=None, input_tokens=0, output_tokens=0, cost=0, retries=0,
                        reason=failure_reason,
                    )
                    for stage in ("facts", "rules", "cases", "prediction", "risk")
                ]
            bundle_raw = {"receipt_id": receipt.receipt_id, "match_id": metadata.match_id, "official_input_sha256": receipt.official_input_sha256, "feature_snapshot_sha256": feature["feature_snapshot_sha256"], "stages": [item.model_dump(mode="json") for item in stages], "bundle_sha256": "0" * 64}
            bundle = AIExperimentBundleV1.model_validate(bundle_raw)
            bundle = bundle.model_copy(update={"bundle_sha256": _digest(bundle, "bundle_sha256")})
            atomic_write_text(target / "bundle.yml", yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
            manifest_raw = {"receipt_id": receipt.receipt_id, "status": "failed" if failure_reason else "sealed", "files": {"receipt.yml": _file_hash(target / "receipt.yml"), "bundle.yml": _file_hash(target / "bundle.yml")}, "failure_reason": failure_reason, "run_manifest_sha256": "0" * 64}
            manifest = AIExperimentRunManifestV1.model_validate(manifest_raw)
            manifest = manifest.model_copy(update={"run_manifest_sha256": _digest(manifest, "run_manifest_sha256")})
            atomic_write_text(target / "run-manifest.yml", yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
            if failure_reason:
                append_payloads(
                    root / FAILURES, [{"receipt_id": receipt_id, "match_id": metadata.match_id, "reason": failure_reason, "occurred_at": now.isoformat()}],
                    recorded_at=now, actor="system", event_id_factory=lambda item, _: f"ai-run-failure:{item['receipt_id']}",
                )
            transaction.commit()
    except Exception as exc:
        raise
    return target, receipt


def evaluate(root: Path, path: Path, receipt_id: str) -> tuple[Path, AIExperimentOutcomeV1]:
    root = root.resolve()
    document = MatchDocument.load(_inside(root, path))
    metadata = document.metadata
    if MatchStatus(metadata.status) not in {MatchStatus.FINISHED, MatchStatus.REVIEWED, MatchStatus.HISTORICAL_FINISHED}:
        raise ValueError("AI Outcome 仅接受已完赛比赛")
    if not metadata.score or not metadata.result_source:
        raise ValueError("AI Outcome 需要确认赛果与来源")
    base = _run_directory(root, metadata.match_id, receipt_id)
    receipt = AIExperimentReceiptV1.model_validate(_yaml(base / "receipt.yml"))
    manifest = _verify_sealed_run(base, receipt)
    if receipt.match_id != metadata.match_id or manifest.receipt_id != receipt_id:
        raise ValueError("AI 运行与比赛不一致")
    outcome_id = f"ai-outcome-{receipt_id.removeprefix('ai-')}"
    target = root / "raw" / "matches" / metadata.match_id / "ai-experiment-outcomes" / f"{outcome_id}.yml"
    result_hash = _hash({"score": metadata.score, "result_source": metadata.result_source, "recorded_at": metadata.result_recorded_at})
    reasons: list[str] = []
    try:
        candidate, official, _ = _official_inputs(root, document)
        if candidate.receipt_sha256 != receipt.lock_candidate_sha256 or _hash(official) != receipt.official_input_sha256:
            reasons.append("stale_formal_input")
    except Exception:
        reasons.append("stale_or_unverifiable_formal_input")
    outlook = _load_ai_outlook(base, receipt)
    if receipt.run_role != "primary" or not receipt.study_id:
        reasons.append("not_primary")
    elif receipt.sealed_at >= receipt.kickoff_at or receipt.status != "sealed" or manifest.status != "sealed":
        reasons.append("run_not_eligible")
    else:
        try:
            study = _study(root, receipt.study_id)
            if study.config_snapshot_sha256 != receipt.config_snapshot_sha256 or study.sample_relation != "out_of_sample":
                reasons.append("study_not_eligible")
        except Exception:
            reasons.append("study_unavailable")
    if outlook is None:
        reasons.append("no_ai_outlook")
    markets = _market_outcome(outlook, metadata) if outlook else {}
    evaluated = bool(outlook and any(value != "not_evaluated" for value in markets.values()))
    raw = {"outcome_id": outcome_id, "receipt_id": receipt_id, "match_id": metadata.match_id, "result_score": metadata.score, "result_source_sha256": result_hash, "status": "evaluated" if evaluated else "not_evaluated", "eligible_for_study": not reasons and evaluated, "exclusion_reasons": sorted(set(reasons)), "markets": markets, "outcome_sha256": "0" * 64}
    outcome = AIExperimentOutcomeV1.model_validate(raw)
    outcome = outcome.model_copy(update={"outcome_sha256": _digest(outcome, "outcome_sha256")})
    if target.exists():
        existing = AIExperimentOutcomeV1.model_validate(_yaml(target))
        if existing.model_dump(mode="json") != outcome.model_dump(mode="json"):
            raise ValueError("AI Outcome 已存在且内容不同")
        return target, existing
    with RepositoryTransaction(root, files=[root / OUTCOMES, target], directories=[], operation="evaluate-ai-experiment") as transaction:
        atomic_write_text(target, yaml.safe_dump(outcome.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        append_payloads(root / OUTCOMES, [outcome.model_dump(mode="json")], recorded_at=_now(), actor="system", event_id_factory=lambda item, _: f"ai-outcome:{item['outcome_id']}")
        transaction.commit()
    return target, outcome


def status(root: Path) -> dict[str, Any]:
    return {"schema_version": 1, "studies": [item.model_dump(mode="json") for item in read_studies(root)], "primary_claims": len(_primary_claims(root))}


def _outcome_payloads(root: Path) -> list[dict[str, Any]]:
    from .ledger import read_ledger

    return [event.payload for event in read_ledger(root / OUTCOMES)] if (root / OUTCOMES).exists() else []


def dispose(root: Path, disposition: AIExperimentDispositionEventV1) -> AIExperimentDispositionEventV1:
    if disposition.actor != "lcz":
        raise ValueError("AI Outcome 只能由 lcz 人工处置")
    if disposition.outcome_id not in {item.get("outcome_id") for item in _outcome_payloads(root)}:
        raise ValueError("只能处置已封存的 AI Outcome")
    if disposition.disposition in {"support", "counterexample"} and not disposition.counter_evidence:
        raise ValueError("support/counterexample 必须附带反证或支持 EvidenceRef")
    if disposition.disposition_sha256 not in {"0" * 64, _digest(disposition, "disposition_sha256")}:
        raise ValueError("AI 处置哈希与内容不一致")
    sealed = disposition.model_copy(update={"disposition_sha256": _digest(disposition, "disposition_sha256")})
    append_payloads(
        root / DISPOSITIONS, [sealed.model_dump(mode="json")], recorded_at=sealed.recorded_at, actor="lcz",
        event_id_factory=lambda item, _: f"ai-disposition:{item['outcome_id']}:{item['disposition_sha256'][:16]}",
    )
    return sealed


def report(root: Path, study_id: str | None = None) -> tuple[Path, dict[str, Any]]:
    """Create a research-only descriptive report; it is never a formal metric."""
    from .ledger import read_ledger

    studies = read_studies(root)
    selected = [item for item in studies if study_id is None or item.study_id == study_id]
    if study_id and not selected:
        raise ValueError("Study 不存在")
    claims = _primary_claims(root)
    outcomes = _outcome_payloads(root)
    dispositions = [event.payload for event in read_ledger(root / DISPOSITIONS)] if (root / DISPOSITIONS).exists() else []
    runs: list[dict[str, Any]] = []
    for claim in claims:
        if selected and claim.get("study_id") not in {item.study_id for item in selected}:
            continue
        receipt_path = _run_directory(root, claim["match_id"], claim["receipt_id"]) / "receipt.yml"
        manifest_path = receipt_path.parent / "run-manifest.yml"
        if receipt_path.is_file() and manifest_path.is_file():
            runs.append({"receipt": _yaml(receipt_path), "manifest": _yaml(manifest_path)})
    eligible = [item for item in outcomes if item.get("eligible_for_study") is True and (not selected or any(run["receipt"].get("receipt_id") == item.get("receipt_id") for run in runs))]
    market_counts: dict[str, dict[str, int]] = {}
    for outcome in eligible:
        for market, value in outcome.get("markets", {}).items():
            bucket = market_counts.setdefault(market, {"correct": 0, "incorrect": 0, "not_evaluated": 0})
            bucket[value] = bucket.get(value, 0) + 1
    payload = {
        "schema_version": 1,
        "scope": "ai_research_only",
        "study_ids": [item.study_id for item in selected],
        "primary_runs": len(runs),
        "sealed_runs": sum(item["manifest"].get("status") == "sealed" for item in runs),
        "failed_runs": sum(item["manifest"].get("status") == "failed" for item in runs),
        "eligible_outcomes": len(eligible),
        "market_outcomes": market_counts,
        "manual_dispositions": {kind: sum(item.get("disposition") == kind for item in dispositions) for kind in ("support", "counterexample", "ambiguous", "not_applicable")},
        "exclusions": {reason: sum(reason in item.get("exclusion_reasons", []) for item in outcomes) for reason in sorted({reason for item in outcomes for reason in item.get("exclusion_reasons", [])})},
    }
    label = study_id or "all"
    target = root / "reports" / "ai-experiments" / label / "report.json"
    atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return target, payload


def export_research_evidence(root: Path, study_id: str) -> tuple[Path, dict[str, Any]]:
    """Export untrusted research hypotheses; it deliberately does not create RuleSpecs."""
    study = _study(root, study_id)
    claims = [item for item in _primary_claims(root) if item.get("study_id") == study_id]
    outcome_ids = {item.get("receipt_id"): item.get("outcome_id") for item in _outcome_payloads(root)}
    payload = {
        "schema_version": 1,
        "trust_status": "untrusted_ai_research_evidence",
        "study_id": study.study_id,
        "study_sha256": study.study_sha256,
        "primary_receipt_ids": [item.get("receipt_id") for item in claims],
        "outcome_ids": [outcome_ids[item.get("receipt_id")] for item in claims if item.get("receipt_id") in outcome_ids],
        "next_step": "人工撰写文本规则后使用 rules intake ingest；本文件不得直接编译或激活规则",
    }
    target = root / "knowledge" / "ai-experiments" / "research-exports" / f"{study_id}.yml"
    if target.exists():
        existing = _yaml(target)
        if existing != payload:
            raise ValueError("研究证据导出已存在且内容不同；请创建新的 Study")
        return target, payload
    atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    return target, payload
