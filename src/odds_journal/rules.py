from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .markdown import generic_front_matter


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
DOCUMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]+$")
RULESET_SPEC_RE = re.compile(r"^([a-z0-9][a-z0-9-]+)@(\d+\.\d+\.\d+)$")


def canonical_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"


def sha256_text(text: str) -> str:
    return hashlib.sha256(canonical_text(text).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_text(path.read_text(encoding="utf-8"))


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["local", "external"]
    locator: str = Field(min_length=1)
    anchor: str | None = None
    title: str | None = None
    accessed_at: datetime | None = None
    summary: str | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> "SourceReference":
        if self.kind == "external" and not self.locator.startswith(("https://", "http://")):
            raise ValueError("external 来源必须使用 HTTP(S) URL")
        if self.kind == "external" and self.accessed_at is None:
            raise ValueError("external 来源必须记录 accessed_at")
        return self


class EvidenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: datetime
    eligible_independent_cases: int = Field(ge=0)
    support: int = Field(ge=0)
    counterexample: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation_study_id: str | None = None
    baseline_rate: float | None = Field(default=None, ge=0, le=1)
    point_estimate: float | None = Field(default=None, ge=0, le=1)
    wilson_95_lower: float | None = Field(default=None, ge=0, le=1)
    diversity_confirmed: bool | None = None

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evidence_snapshot.as_of 必须包含时区")
        return value


class RuleMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2, 3, 4]
    document_id: str
    document_type: Literal["concept", "method", "heuristic", "checklist"]
    title: str = Field(min_length=1)
    rule_version: str
    reliability: Literal["established", "supported", "experimental", "deprecated"]
    status: Literal["active", "deprecated"] = "active"
    effective_at: datetime | None
    evidence_level: Literal["high", "medium", "low"]
    sample_size: int | None = Field(default=None, ge=0)
    evidence_snapshot: EvidenceSnapshot | None = None
    source_atom_ids: list[str] = Field(default_factory=list)
    evidence_provenance: Literal["linked", "gap"] = "linked"
    scenario_type_ids: list[str] = Field(default_factory=list)
    promotion_reviewed_by: str | None = None
    markets: list[Literal["all", "one_x_two", "handicap", "total_goals", "pass"]]
    phases: list[Literal["prematch", "live", "postmatch"]]
    tags: list[str] = Field(default_factory=list)
    source_refs: list[SourceReference] = Field(default_factory=list)
    index: bool = True

    @field_validator("document_id")
    @classmethod
    def valid_document_id(cls, value: str) -> str:
        if not DOCUMENT_ID_RE.fullmatch(value):
            raise ValueError("document_id 必须是小写字母、数字和连字符")
        return value

    @field_validator("rule_version")
    @classmethod
    def valid_rule_version(cls, value: str) -> str:
        if not SEMVER_RE.fullmatch(value):
            raise ValueError("rule_version 必须使用语义版本，例如 1.0.0")
        return value

    @field_validator("effective_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("effective_at 必须包含时区")
        return value

    @field_validator("markets", "phases", "tags", "source_atom_ids", "scenario_type_ids")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("列表中存在重复值")
        return value

    @model_validator(mode="after")
    def reliability_boundaries(self) -> "RuleMetadata":
        if self.schema_version == 1:
            if self.sample_size is None:
                raise ValueError("schema_version=1 必须填写 sample_size")
            if self.evidence_snapshot is not None or self.source_atom_ids or self.scenario_type_ids:
                raise ValueError("schema_version=1 不支持证据快照和原子引用")
        else:
            if self.evidence_snapshot is None:
                raise ValueError("schema_version=2/3/4 必须填写 evidence_snapshot")
            if self.sample_size is not None:
                raise ValueError("schema_version=2 使用 evidence_snapshot，不填写 sample_size")
        if self.document_type == "heuristic" and self.reliability == "established":
            raise ValueError("经验规则不能标记为 established")
        if self.document_type == "heuristic" and self.reliability == "supported":
            if self.schema_version == 1:
                raise ValueError("schema_version=1 的经验规则必须为 experimental")
            if not self.evidence_snapshot or self.evidence_snapshot.eligible_independent_cases < 30:
                raise ValueError("经验规则晋级 supported 至少需要 30 个合格独立案例")
            if not self.promotion_reviewed_by:
                raise ValueError("经验规则晋级 supported 必须记录人工审核人")
            if self.schema_version in {3, 4}:
                snapshot = self.evidence_snapshot
                assert snapshot is not None
                if not snapshot.validation_study_id:
                    raise ValueError("schema_version=3 经验规则晋级必须引用冻结验证研究")
                if snapshot.baseline_rate is None or snapshot.point_estimate is None:
                    raise ValueError("经验规则晋级必须记录基线和点估计")
                if snapshot.wilson_95_lower is None or snapshot.diversity_confirmed is not True:
                    raise ValueError("经验规则晋级必须通过 Wilson 下界和样本多样性门禁")
                if snapshot.point_estimate < snapshot.baseline_rate + 0.05:
                    raise ValueError("经验规则点估计必须至少高于基线 5 个百分点")
                if snapshot.wilson_95_lower < snapshot.baseline_rate:
                    raise ValueError("经验规则 Wilson 95% 下界不得低于基线")
        if self.reliability == "deprecated" and self.status != "deprecated":
            raise ValueError("deprecated 可信度必须配合 deprecated 状态")
        if self.evidence_provenance == "gap":
            if self.source_atom_ids or self.reliability != "experimental" or self.promotion_reviewed_by:
                raise ValueError("证据缺口规则只能是未晋级 experimental，且不得伪造来源原子")
        elif self.schema_version == 4 and not self.source_atom_ids:
            raise ValueError("schema_version=4 的 linked 规则必须引用 source atom")
        return self


class RulesetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2, 3, 4, 5, 6]
    ruleset_id: str
    ruleset_version: str
    status: Literal["active", "superseded", "deprecated"] | None = None
    publication_status: Literal["published", "deprecated", "proposal"] | None = None
    effective_at: datetime | None
    entry_document_id: str
    required_document_ids: list[str]
    conditional_document_ids: list[str]
    source_family_ids: list[str] = Field(default_factory=list)
    source_coverage_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    weight_model_id: str | None = None
    market_data_contract_version: int | None = Field(default=None, ge=1)
    analysis_receipt_schema_version: int | None = Field(default=None, ge=1)
    review_receipt_schema_version: int | None = Field(default=None, ge=1)
    index_schema_version: int | None = Field(default=None, ge=1)
    retrieval_contract_version: int | None = Field(default=None, ge=1)
    calibration_contract_version: int | None = Field(default=None, ge=1)
    calibration_config_path: str | None = None
    calibration_config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proposal_prepared_at: datetime | None = None

    @field_validator("ruleset_id", "entry_document_id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not DOCUMENT_ID_RE.fullmatch(value):
            raise ValueError("ID 必须是小写字母、数字和连字符")
        return value

    @field_validator("ruleset_version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        if not SEMVER_RE.fullmatch(value):
            raise ValueError("ruleset_version 必须使用语义版本")
        return value

    @field_validator("effective_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("effective_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def unique_documents(self) -> "RulesetManifest":
        values = [*self.required_document_ids, *self.conditional_document_ids]
        if len(values) != len(set(values)):
            raise ValueError("manifest 文档 ID 存在重复")
        if self.entry_document_id not in self.required_document_ids:
            raise ValueError("entry_document_id 必须属于 required_document_ids")
        if self.schema_version == 1:
            if self.status is None:
                raise ValueError("schema_version=1 必须填写 status")
            if any((self.publication_status, self.source_coverage_sha256, self.evidence_snapshot_sha256)):
                raise ValueError("schema_version=1 不支持发布快照字段")
        else:
            if self.status is not None:
                raise ValueError("schema_version=2 的活动状态仅由 active.yml 决定")
            if self.publication_status is None:
                raise ValueError("schema_version=2 必须填写 publication_status")
            if self.publication_status == "proposal" and self.effective_at is not None:
                raise ValueError("提案规则集 effective_at 必须为空")
            if self.publication_status == "proposal" and self.proposal_prepared_at is None:
                raise ValueError("提案规则集必须记录 proposal_prepared_at")
            if self.publication_status != "proposal" and self.proposal_prepared_at is not None:
                raise ValueError("已发布规则集不得保留 proposal_prepared_at")
            if self.publication_status != "proposal" and self.effective_at is None:
                raise ValueError("已发布规则集必须填写 effective_at")
            if not self.source_coverage_sha256 or not self.evidence_snapshot_sha256:
                raise ValueError("schema_version=2/3 必须绑定覆盖报告和证据快照")
            contract_values = (
                self.weight_model_id,
                self.market_data_contract_version,
                self.analysis_receipt_schema_version,
                self.review_receipt_schema_version,
                self.index_schema_version,
                self.retrieval_contract_version,
            )
            if self.schema_version == 2 and any(value is not None for value in contract_values):
                raise ValueError("schema_version=2 不支持分析契约版本字段")
            if self.schema_version in {3, 4, 5, 6} and any(value is None for value in contract_values):
                raise ValueError("schema_version=3/4/5/6 必须固定全部分析契约版本")
            calibration_values = (
                self.calibration_contract_version,
                self.calibration_config_path,
                self.calibration_config_sha256,
            )
            if self.schema_version < 4 and any(value is not None for value in calibration_values):
                raise ValueError("schema_version=1/2/3 不支持校准契约字段")
            if self.schema_version in {4, 5, 6}:
                if any(value is None for value in calibration_values):
                    raise ValueError("schema_version=4/5/6 必须固定校准契约、配置路径和配置哈希")
                allowed_contracts = {1, 2, 3} if self.schema_version == 4 else {4} if self.schema_version == 5 else {5}
                if self.calibration_contract_version not in allowed_contracts:
                    raise ValueError("manifest schema 与 calibration contract 组合不受支持")
                expected_receipt = 6 if self.calibration_contract_version in {4, 5} else 5 if self.calibration_contract_version == 3 else 4
                if self.analysis_receipt_schema_version != expected_receipt:
                    raise ValueError(f"manifest contract {self.calibration_contract_version} 必须使用 AnalysisReceipt schema {expected_receipt}")
                config_path = Path(str(self.calibration_config_path))
                if config_path.is_absolute() or ".." in config_path.parts:
                    raise ValueError("校准配置必须使用规则集目录内的相对路径")
                if config_path.suffix not in {".yml", ".yaml"}:
                    raise ValueError("校准配置必须是 YAML 文件")
        return self

    @property
    def published(self) -> bool:
        if self.schema_version == 1:
            return self.status == "active"
        return self.publication_status == "published"


class ActiveRuleset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    ruleset_id: str
    ruleset_version: str

    @field_validator("ruleset_id")
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not DOCUMENT_ID_RE.fullmatch(value):
            raise ValueError("ruleset_id 格式无效")
        return value

    @field_validator("ruleset_version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        if not SEMVER_RE.fullmatch(value):
            raise ValueError("ruleset_version 格式无效")
        return value


@dataclass(frozen=True)
class RuleDocument:
    path: Path
    metadata: RuleMetadata
    body: str
    content_sha256: str


@dataclass(frozen=True)
class Ruleset:
    directory: Path
    manifest: RulesetManifest
    documents: dict[str, RuleDocument]
    content_sha256: str
    calibration_config: dict | None = None
    origin: Literal["published", "proposal"] = "published"

    @property
    def required(self) -> list[RuleDocument]:
        return [self.documents[item] for item in self.manifest.required_document_ids]

    @property
    def conditional(self) -> list[RuleDocument]:
        return [self.documents[item] for item in self.manifest.conditional_document_ids]


def _yaml_file(path: Path) -> dict:
    if not path.exists():
        raise ValueError(f"文件不存在：{path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _ruleset_location(root: Path, ruleset_id: str, version: str, *, proposal: bool = False) -> Path:
    base = "rule-proposals" if proposal else "rulesets"
    return root / "knowledge" / base / ruleset_id / version


def active_ruleset(root: Path) -> ActiveRuleset:
    path = root / "knowledge" / "rulesets" / "football-analysis" / "active.yml"
    return ActiveRuleset.model_validate(_yaml_file(path))


def parse_ruleset_spec(root: Path, spec: str | None) -> tuple[str, str]:
    if spec is None:
        active = active_ruleset(root)
        return active.ruleset_id, active.ruleset_version
    match = RULESET_SPEC_RE.fullmatch(spec)
    if not match:
        raise ValueError("规则集必须使用 ID@VERSION，例如 football-analysis@1.0.0")
    return match.group(1), match.group(2)


def load_ruleset(root: Path, spec: str | None = None, *, allow_proposal: bool = False) -> Ruleset:
    ruleset_id, version = parse_ruleset_spec(root, spec)
    directory = _ruleset_location(root, ruleset_id, version, proposal=allow_proposal)
    manifest = RulesetManifest.model_validate(_yaml_file(directory / "manifest.yml"))
    if manifest.ruleset_id != ruleset_id or manifest.ruleset_version != version:
        raise ValueError("manifest 与规则集路径不一致")
    if allow_proposal != (manifest.publication_status == "proposal"):
        raise ValueError("规则集来源与 --proposal 声明不一致")

    documents: dict[str, RuleDocument] = {}
    for path in sorted(directory.glob("**/*.md")):
        raw, body = generic_front_matter(path)
        metadata = RuleMetadata.model_validate(raw)
        if metadata.document_id in documents:
            raise ValueError(f"规则集内 document_id 重复：{metadata.document_id}")
        documents[metadata.document_id] = RuleDocument(
            path=path,
            metadata=metadata,
            body=body,
            content_sha256=sha256_file(path),
        )

    listed = [*manifest.required_document_ids, *manifest.conditional_document_ids]
    missing = [item for item in listed if item not in documents]
    extra = [item for item in documents if item not in listed]
    if missing:
        raise ValueError(f"manifest 缺少对应规则文件：{', '.join(missing)}")
    if extra:
        raise ValueError(f"规则文件未登记到 manifest：{', '.join(extra)}")
    for item in listed:
        document = documents[item]
        if document.metadata.rule_version != version:
            raise ValueError(f"{item} 的 rule_version 与规则集版本不一致")
        if document.metadata.status != "active":
            raise ValueError(f"活动规则集包含非 active 文档：{item}")
        if document.metadata.effective_at is None and not allow_proposal:
            raise ValueError(f"已发布规则缺少 effective_at：{item}")
        if not allow_proposal and document.metadata.effective_at > manifest.effective_at:
            raise ValueError(f"manifest 生效时间早于规则文档：{item}")
    if not allow_proposal:
        latest_required = max(
            documents[item].metadata.effective_at for item in manifest.required_document_ids
        )
        if manifest.effective_at != latest_required:
            raise ValueError("manifest effective_at 必须等于必需规则中的最晚生效时间")

    calibration_config = None
    calibration_hashes: list[str] = []
    if manifest.schema_version in {4, 5, 6}:
        config_path = directory / str(manifest.calibration_config_path)
        resolved = config_path.resolve()
        if directory.resolve() not in resolved.parents:
            raise ValueError("校准配置路径越出规则集目录")
        if not config_path.is_file():
            raise ValueError(f"校准配置不存在：{manifest.calibration_config_path}")
        actual_hash = sha256_file(config_path)
        if actual_hash != manifest.calibration_config_sha256:
            raise ValueError("校准配置哈希与 manifest 不一致")
        calibration_config = _yaml_file(config_path)
        if manifest.calibration_contract_version == 5:
            from .experiments import ExperimentCalibrationConfig

            ExperimentCalibrationConfig.model_validate(calibration_config)
        else:
            from .calibration import CalibrationConfig

            CalibrationConfig.model_validate(calibration_config)
        calibration_hashes.append(actual_hash)

    hash_order = [*manifest.required_document_ids, *sorted(manifest.conditional_document_ids)]
    manifest_hash = sha256_file(directory / "manifest.yml")
    joined = manifest_hash + "\n" + "".join(
        documents[item].content_sha256 + "\n" for item in hash_order
    ) + "".join(value + "\n" for value in calibration_hashes)
    return Ruleset(
        directory=directory,
        manifest=manifest,
        documents=documents,
        content_sha256=hashlib.sha256(joined.encode("ascii")).hexdigest(),
        calibration_config=calibration_config,
        origin="proposal" if allow_proposal else "published",
    )


def validate_rules(root: Path) -> dict[Path, list[str]]:
    base = root / "knowledge" / "rulesets"
    results: dict[Path, list[str]] = {}
    published_rule_ids: dict[str, list[Path]] = {}
    known_source_atom_ids = _known_source_atom_ids(root)

    try:
        active = active_ruleset(root)
        active_path = base / "football-analysis" / "active.yml"
        results[active_path] = []
        ruleset = load_ruleset(root, f"{active.ruleset_id}@{active.ruleset_version}")
        if not ruleset.manifest.published:
            results[active_path].append("active.yml 指向的规则集不是 published 状态")
    except Exception as exc:
        results[base / "football-analysis" / "active.yml"] = [str(exc)]

    for manifest_path in sorted(base.glob("*/*/manifest.yml")):
        version_dir = manifest_path.parent
        try:
            manifest = RulesetManifest.model_validate(_yaml_file(manifest_path))
            ruleset = load_ruleset(root, f"{manifest.ruleset_id}@{manifest.ruleset_version}")
            results.setdefault(manifest_path, [])
            for document in ruleset.documents.values():
                errors: list[str] = []
                published_rule_ids.setdefault(document.metadata.document_id, []).append(document.path)
                for reference in document.metadata.source_refs:
                    if reference.kind == "local":
                        target = root / reference.locator.split("#", 1)[0]
                        if not target.exists():
                            errors.append(f"本地来源不存在：{reference.locator}")
                if document.metadata.schema_version == 2:
                    missing_atoms = sorted(
                        set(document.metadata.source_atom_ids) - known_source_atom_ids
                    )
                    if missing_atoms:
                        errors.append(f"规则引用不存在的 source atom：{', '.join(missing_atoms[:5])}")
                results[document.path] = errors
        except Exception as exc:
            results[manifest_path] = [str(exc)]

    for path in sorted((root / "knowledge").glob("**/*.md")):
        if (
            base in path.parents
            or "sources" in path.parts
            or "rule-proposals" in path.parts
            or "rule-experiments" in path.parts
        ):
            continue
        raw, _ = generic_front_matter(path)
        document_id = raw.get("document_id")
        if not document_id:
            continue
        previous_rules = published_rule_ids.get(str(document_id), [])
        if previous_rules:
            results.setdefault(path, []).append(f"document_id 与版本化规则 {previous_rules[0]} 重复")
        results.setdefault(path, [])
    experiment_active_path = root / "knowledge/rule-experiments/football-analysis/active.yml"
    if experiment_active_path.exists():
        try:
            from .experiments import active_experiment

            active_experiment(root)
            results[experiment_active_path] = []
        except Exception as exc:
            results[experiment_active_path] = [str(exc)]
    return results


def _known_source_atom_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    extraction_root = root / "knowledge" / "extraction"
    for path in extraction_root.glob("*/text-inventory.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            try:
                atom_id = json.loads(line).get("atom_id")
                if atom_id:
                    ids.add(str(atom_id))
            except Exception:
                continue
    return ids
