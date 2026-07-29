from __future__ import annotations

import hashlib
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


class RuleMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    document_id: str
    document_type: Literal["concept", "method", "heuristic", "checklist"]
    title: str = Field(min_length=1)
    rule_version: str
    reliability: Literal["established", "supported", "experimental", "deprecated"]
    status: Literal["active", "deprecated"] = "active"
    effective_at: datetime
    evidence_level: Literal["high", "medium", "low"]
    sample_size: int = Field(ge=0)
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
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("effective_at 必须包含时区")
        return value

    @field_validator("markets", "phases", "tags")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("列表中存在重复值")
        return value

    @model_validator(mode="after")
    def reliability_boundaries(self) -> "RuleMetadata":
        if self.document_type == "heuristic" and self.reliability != "experimental":
            raise ValueError("经验规则初始可信度必须为 experimental")
        if self.reliability == "deprecated" and self.status != "deprecated":
            raise ValueError("deprecated 可信度必须配合 deprecated 状态")
        return self


class RulesetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    ruleset_id: str
    ruleset_version: str
    status: Literal["active", "superseded", "deprecated"]
    effective_at: datetime
    entry_document_id: str
    required_document_ids: list[str]
    conditional_document_ids: list[str]

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
    def timezone_required(cls, value: datetime) -> datetime:
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
        return self


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


def _ruleset_location(root: Path, ruleset_id: str, version: str) -> Path:
    return root / "knowledge" / "rulesets" / ruleset_id / version


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


def load_ruleset(root: Path, spec: str | None = None) -> Ruleset:
    ruleset_id, version = parse_ruleset_spec(root, spec)
    directory = _ruleset_location(root, ruleset_id, version)
    manifest = RulesetManifest.model_validate(_yaml_file(directory / "manifest.yml"))
    if manifest.ruleset_id != ruleset_id or manifest.ruleset_version != version:
        raise ValueError("manifest 与规则集路径不一致")

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
        if document.metadata.effective_at > manifest.effective_at:
            raise ValueError(f"manifest 生效时间早于规则文档：{item}")
    latest_required = max(documents[item].metadata.effective_at for item in manifest.required_document_ids)
    if manifest.effective_at != latest_required:
        raise ValueError("manifest effective_at 必须等于必需规则中的最晚生效时间")

    hash_order = [*manifest.required_document_ids, *sorted(manifest.conditional_document_ids)]
    manifest_hash = sha256_file(directory / "manifest.yml")
    joined = manifest_hash + "\n" + "".join(
        documents[item].content_sha256 + "\n" for item in hash_order
    )
    return Ruleset(
        directory=directory,
        manifest=manifest,
        documents=documents,
        content_sha256=hashlib.sha256(joined.encode("ascii")).hexdigest(),
    )


def validate_rules(root: Path) -> dict[Path, list[str]]:
    base = root / "knowledge" / "rulesets"
    results: dict[Path, list[str]] = {}
    seen_ids: dict[str, Path] = {}

    try:
        active = active_ruleset(root)
        active_path = base / "football-analysis" / "active.yml"
        results[active_path] = []
        ruleset = load_ruleset(root, f"{active.ruleset_id}@{active.ruleset_version}")
        if ruleset.manifest.status != "active":
            results[active_path].append("active.yml 指向的规则集不是 active 状态")
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
                previous = seen_ids.get(document.metadata.document_id)
                if previous:
                    errors.append(f"document_id 与 {previous} 重复")
                else:
                    seen_ids[document.metadata.document_id] = document.path
                for reference in document.metadata.source_refs:
                    if reference.kind == "local":
                        target = root / reference.locator.split("#", 1)[0]
                        if not target.exists():
                            errors.append(f"本地来源不存在：{reference.locator}")
                results[document.path] = errors
        except Exception as exc:
            results[manifest_path] = [str(exc)]

    for path in sorted((root / "knowledge").glob("**/*.md")):
        if base in path.parents or "sources" in path.parts:
            continue
        raw, _ = generic_front_matter(path)
        document_id = raw.get("document_id")
        if not document_id:
            continue
        previous = seen_ids.get(str(document_id))
        if previous:
            results.setdefault(path, []).append(f"document_id 与 {previous} 重复")
        else:
            seen_ids[str(document_id)] = path
            results.setdefault(path, [])
    return results
