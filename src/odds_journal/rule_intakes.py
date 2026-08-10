from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ledger import append_payloads, atomic_write_text, read_ledger, sha256_json
from .rules import sha256_file


INTAKE_LEDGER = Path("knowledge/rule-intakes/events.jsonl")
ATOM_LEDGER = Path("knowledge/rule-intakes/atoms.jsonl")
DISPOSITION_LEDGER = Path("knowledge/rule-intakes/dispositions.jsonl")
RULE_BUILD_NAME = "rule-build.yml"
RULE_CONSOLIDATIONS_NAME = "rule-consolidations.yml"


class RuleIntakeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    intake_id: str = Field(pattern=r"^intake-[a-f0-9]{16}$")
    source_path: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    received_at: datetime
    trust_status: Literal["untrusted_source_intake"] = "untrusted_source_intake"
    import_status: Literal["ingested", "duplicate"] = "ingested"


class RuleAtomV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    atom_id: str = Field(pattern=r"^rule-atom-[a-f0-9]{24}$")
    intake_id: str = Field(pattern=r"^intake-[a-f0-9]{16}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_line_start: int = Field(ge=1)
    source_line_end: int = Field(ge=1)
    statement: str = Field(min_length=1)
    rule_domain: Literal["handicap", "one_x_two", "total_goals", "score", "cross_market", "live"]
    timing: Literal["prematch", "live", "postmatch"]
    classification: Literal[
        "duplicate", "supplement", "conflict", "invalid", "deferred",
        "advisory_candidate", "research_only",
    ]
    reasons: list[str] = Field(default_factory=list)
    supersedes_atom_ids: list[str] = Field(default_factory=list)
    atom_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_lines(self) -> "RuleAtomV1":
        if self.source_line_end < self.source_line_start:
            raise ValueError("source_line_end 不得早于 source_line_start")
        return self


class RuleDispositionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    atom_id: str = Field(pattern=r"^rule-atom-[a-f0-9]{24}$")
    disposition: Literal[
        "duplicate", "supplement", "conflict", "invalid", "deferred",
        "advisory_candidate", "research_only", "promoted_to_prediction", "retired",
    ]
    existing_rule_ids: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    actor: Literal["system", "lcz"]
    reason: str = Field(min_length=1)
    recorded_at: datetime


class RuleEvaluatorV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "threshold_series", "cross_market_relation", "structured_fact",
        "manual_review", "postmatch_only", "legacy_contract5",
    ]
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def strict_config(self) -> "RuleEvaluatorV1":
        allowed: dict[str, set[str]] = {
            "threshold_series": {"provider_ids", "market", "line", "price_key", "operator", "threshold", "minimum_exact_nodes", "odds_format"},
            "cross_market_relation": {"left_market", "right_market", "lineage_key", "window_minutes", "operator", "threshold"},
            "structured_fact": {"fact_type", "allowed_sources", "effective_before"},
            "manual_review": {"question"},
            "postmatch_only": {"outcome_measure"},
            "legacy_contract5": {"legacy_rule_id"},
        }
        unknown = set(self.config) - allowed[self.kind]
        if unknown:
            raise ValueError(f"{self.kind} 包含不支持配置：{sorted(unknown)}")
        if self.kind == "threshold_series":
            required = {"market", "price_key", "operator", "threshold", "minimum_exact_nodes"}
            if required - set(self.config):
                raise ValueError("threshold_series 缺少严格比较配置")
        if self.kind == "legacy_contract5" and not self.config.get("legacy_rule_id"):
            raise ValueError("legacy_contract5 必须声明 legacy_rule_id")
        return self


class RuleSpecV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    rule_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    rule_revision: int = Field(ge=1)
    track: Literal["advisory", "prediction_experiment", "research_only"]
    effect: Literal["advisory", "total_goals_pool", "score_pool", "outcome_risk_pool", "handicap_signal"]
    official_effect: Literal["none"] = "none"
    market_scope: Literal["handicap", "one_x_two", "total_goals", "score", "cross_market", "live", "none"]
    applies_to_profiles: list[str] = Field(min_length=1)
    source_atoms: list[str] = Field(default_factory=list)
    evaluator: RuleEvaluatorV1
    required_inputs: list[str] = Field(default_factory=list)
    time_gate: Literal["prematch", "live", "postmatch"]
    failure_mode: Literal["insufficient_data", "not_applicable"]
    thresholds: dict[str, float] = Field(default_factory=dict)
    counter_evidence_requirements: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    precedence: dict[str, Any] = Field(default_factory=lambda: {"override_mode": "none", "supersedes_rule_ids": [], "override_scope": "none"})

    @model_validator(mode="after")
    def enforce_track_boundary(self) -> "RuleSpecV1":
        if self.track == "advisory" and self.effect != "advisory":
            raise ValueError("advisory 规则只能使用 advisory 影响面")
        if self.track == "advisory" and self.evaluator.kind != "manual_review":
            raise ValueError("advisory 规则只能使用 manual_review")
        if self.track == "research_only" and (
            self.evaluator.kind != "postmatch_only" or self.time_gate != "postmatch"
        ):
            raise ValueError("research_only 规则只能使用 postmatch_only 并限于赛后")
        if self.track != "advisory" and self.effect == "advisory":
            raise ValueError("非 advisory 规则不能使用 advisory 影响面")
        if self.track != "prediction_experiment" and self.precedence.get("override_mode") != "none":
            raise ValueError("只有 prediction_experiment 可以声明覆盖")
        if self.track == "prediction_experiment" and self.evaluator.kind in {"manual_review", "postmatch_only"}:
            raise ValueError("预测实验必须使用可赛前冻结的求值器")
        return self


class RuleBuildEntryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_id: str
    atom_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    disposition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class RuleConsolidationV1(BaseModel):
    """A reviewed replacement that binds several intake atoms to one RuleSpec."""

    model_config = ConfigDict(extra="forbid")

    consolidation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    rule_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    source_atoms: list[str] = Field(min_length=1)
    superseded_rule_ids: list[str] = Field(default_factory=list)
    rule_spec: RuleSpecV1
    merge_reason: str = Field(min_length=1)
    consolidation_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_consolidation(self) -> "RuleConsolidationV1":
        if self.rule_spec.rule_id != self.rule_id:
            raise ValueError("合并规则 ID 必须与 RuleSpec 一致")
        if self.rule_spec.source_atoms != self.source_atoms:
            raise ValueError("合并 RuleSpec 必须绑定全部 source atom")
        raw = self.model_dump(mode="json")
        raw["consolidation_sha256"] = "0" * 64
        if self.consolidation_sha256 != sha256_json(raw):
            raise ValueError("合并声明内容哈希无效")
        return self


class RuleConsolidationManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    proposal_version: Literal["1.7.0"] = "1.7.0"
    consolidations: list[RuleConsolidationV1] = Field(default_factory=list)
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_manifest_hash(self) -> "RuleConsolidationManifestV1":
        raw = self.model_dump(mode="json")
        raw["manifest_sha256"] = "0" * 64
        if self.manifest_sha256 != sha256_json(raw):
            raise ValueError("规则合并清单内容哈希无效")
        if len({item.consolidation_id for item in self.consolidations}) != len(self.consolidations):
            raise ValueError("规则合并清单存在重复 ID")
        if len({item.rule_id for item in self.consolidations}) != len(self.consolidations):
            raise ValueError("规则合并清单存在重复 RuleSpec")
        return self


class RuleBuildManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    proposal_version: Literal["1.7.0"] = "1.7.0"
    compiler_version: str = "rule-intake-compiler-v1"
    source_intakes: list[dict[str, str]]
    selected_atoms: list[RuleBuildEntryV1]
    generated_rule_specs: list[dict[str, str]]
    duplicate_and_conflict_resolutions: list[dict[str, Any]] = Field(default_factory=list)
    consolidation_manifest_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    consolidation_resolutions: list[dict[str, Any]] = Field(default_factory=list)
    build_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_build_hash(self) -> "RuleBuildManifestV1":
        raw = self.model_dump(mode="json")
        # Existing revision 1/2 manifests predate consolidation fields. Their canonical
        # digest intentionally excludes defaults that were not serialized on disk.
        if self.compiler_version == "rule-intake-compiler-v1":
            raw.pop("consolidation_manifest_sha256", None)
            raw.pop("consolidation_resolutions", None)
        if self.build_sha256 != _build_hash(raw):
            raise ValueError("rule-build.yml build_sha256 无效")
        return self


def _now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)


def _relative(root: Path, path: Path) -> str:
    resolved = path.resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError("intake 文件必须位于仓库内")
    return resolved.relative_to(root.resolve()).as_posix()


def _latest(path: Path, key: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in read_ledger(path):
        result[str(event.payload[key])] = event.payload
    return result


def ingest_intake(root: Path, source: Path, *, actor: str = "system") -> RuleIntakeV1:
    source_path = _relative(root, source)
    digest = sha256_file(source)
    existing = _latest(root / INTAKE_LEDGER, "intake_id")
    identity = f"intake-{digest[:16]}"
    if identity in existing:
        return RuleIntakeV1.model_validate({**existing[identity], "import_status": "duplicate"})
    payload = RuleIntakeV1(
        intake_id=identity, source_path=source_path, source_sha256=digest, received_at=_now()
    ).model_dump(mode="json")
    append_payloads(root / INTAKE_LEDGER, [payload], recorded_at=_now(), actor=actor,
                    event_id_factory=lambda item, _: f"rule-intake:{item['intake_id']}")
    return RuleIntakeV1.model_validate(payload)


def _classify(statement: str) -> tuple[str, str, list[str]]:
    compact = re.sub(r"\s+", "", statement).lower()
    domain = "total_goals" if any(value in compact for value in ("大小球", "总进球", "大球", "小球")) else "handicap" if any(value in compact for value in ("让球", "亚盘", "水位")) else "one_x_two" if any(value in compact for value in ("欧赔", "凯利", "主胜", "平局", "客胜")) else "cross_market"
    timing = "postmatch" if any(value in compact for value in ("赛后", "复盘", "完赛")) else "live" if any(value in compact for value in ("前20分钟", "赛中", "早进球")) else "prematch"
    if any(value in compact for value in ("内幕", "必发资金", "交易量", "散户资金", "机构主动控赔")):
        return domain, timing, ["research_only", "依赖当前不存在或不可验证的资金/意图事实"]
    if any(value in compact for value in ("100%", "固定概率", "必然命中", "直接改变第一顺位")):
        return domain, timing, ["invalid", "包含不可审计的确定性或越权结论"]
    if timing == "postmatch":
        return domain, timing, ["research_only", "赛后条款不能进入赛前实验"]
    return domain, timing, ["advisory_candidate", "自动进入提示实验候选；仍须 lcz 激活"]


def _semantic_groups(lines: list[str]) -> list[tuple[int, int, str]]:
    """Skip metadata/governance and preserve meaningful user-rule paragraphs and line ranges."""
    in_front_matter = False
    front_matter_delimiters = 0
    in_governance = False
    groups: list[tuple[int, int, str]] = []
    start: int | None = None
    values: list[str] = []

    def flush(end: int) -> None:
        nonlocal start, values
        if values:
            groups.append((start or end, end, "\n".join(values)))
        start, values = None, []

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped == "---" and front_matter_delimiters < 2:
            flush(number - 1)
            in_front_matter = not in_front_matter
            front_matter_delimiters += 1
            continue
        if in_front_matter:
            continue
        if stripped.startswith("#"):
            flush(number - 1)
            in_governance = stripped.lstrip("#").strip() in {"治理状态", "Governance"}
            continue
        if in_governance:
            continue
        normalized_label = stripped.replace("*", "").strip()
        if normalized_label.startswith(("规则名称：", "归属：")):
            flush(number - 1)
            continue
        if re.fullmatch(r"(?:\d+\.\s+)?\*{2}.+?\*{2}(?:（.*）)?", stripped):
            flush(number - 1)
            continue
        if normalized_label.endswith(("：", ":")) and normalized_label[:-1].strip():
            # Markdown bold labels such as "**规则内容**：" carry no proposition.
            flush(number - 1)
            continue
        if stripped:
            start = number if start is None else start
            values.append(stripped)
        else:
            flush(number - 1)
    flush(len(lines))
    return groups


def atomize_intake(root: Path, intake_id: str, *, actor: str = "system") -> list[RuleAtomV1]:
    intakes = _latest(root / INTAKE_LEDGER, "intake_id")
    if intake_id not in intakes:
        raise ValueError(f"不存在 intake：{intake_id}")
    intake = RuleIntakeV1.model_validate(intakes[intake_id])
    source = root / intake.source_path
    if not source.is_file() or sha256_file(source) != intake.source_sha256:
        raise ValueError("intake 原文不存在或哈希已变化")
    lines = source.read_text(encoding="utf-8").splitlines()
    groups = _semantic_groups(lines)
    atoms: list[RuleAtomV1] = []
    for start, end, statement in groups:
        domain, timing, verdict = _classify(statement)
        classification, reason = verdict
        atom_id = "rule-atom-" + hashlib.sha256(f"{intake_id}|{start}|{end}|{statement}".encode("utf-8")).hexdigest()[:24]
        raw = {
            "atom_id": atom_id, "intake_id": intake_id, "source_sha256": intake.source_sha256,
            "source_line_start": start, "source_line_end": end, "statement": statement,
            "rule_domain": domain, "timing": timing, "classification": classification,
            "reasons": [reason], "supersedes_atom_ids": [], "atom_sha256": "0" * 64,
        }
        raw["atom_sha256"] = sha256_json({key: value for key, value in raw.items() if key != "atom_sha256"})
        atom = RuleAtomV1.model_validate(raw)
        atoms.append(atom)
    existing_atoms = _latest(root / ATOM_LEDGER, "atom_id")
    new_atoms = [item for item in atoms if item.atom_id not in existing_atoms]
    append_payloads(root / ATOM_LEDGER, [item.model_dump(mode="json") for item in new_atoms], recorded_at=_now(), actor=actor,
                    event_id_factory=lambda item, _: f"rule-atom:{item['atom_id']}")
    existing_dispositions = {
        (str(event.payload.get("atom_id")), str(event.payload.get("disposition")))
        for event in read_ledger(root / DISPOSITION_LEDGER)
    }
    dispositions = [RuleDispositionV1(
        atom_id=item.atom_id, disposition=item.classification, actor="system", reason=item.reasons[0], recorded_at=_now()
    ).model_dump(mode="json") for item in new_atoms
        if (item.atom_id, item.classification) not in existing_dispositions]
    append_payloads(root / DISPOSITION_LEDGER, dispositions, recorded_at=_now(), actor=actor,
                    event_id_factory=lambda item, _: f"rule-disposition:{item['atom_id']}:{item['disposition']}")
    return atoms


def _disposition_hash(root: Path, atom_id: str) -> str:
    records = [event.payload for event in read_ledger(root / DISPOSITION_LEDGER) if event.payload.get("atom_id") == atom_id]
    return sha256_json(records)


def _build_hash(payload: dict[str, Any]) -> str:
    raw = dict(payload)
    raw["build_sha256"] = "0" * 64
    return sha256_json(raw)


def _sync_contract6_build_hash(proposal: Path, build_path: Path) -> None:
    manifest_path = proposal / "manifest.yml"
    if not manifest_path.is_file():
        return
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if manifest.get("calibration_contract_version") != 6:
        return
    config_relative = Path(str(manifest.get("calibration_config_path") or ""))
    config_path = (proposal / config_relative).resolve()
    if proposal.resolve() not in config_path.parents or not config_path.is_file():
        raise ValueError("Contract 6 校准配置不存在或超出提案目录")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if config.get("schema_version") != 6 or config.get("rule_build_path") != RULE_BUILD_NAME:
        raise ValueError("Contract 6 规则编译清单配置无效")
    config["rule_build_sha256"] = sha256_file(build_path)
    atomic_write_text(config_path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    manifest["calibration_config_sha256"] = sha256_file(config_path)
    atomic_write_text(manifest_path, yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))


def _load_consolidations(proposal: Path) -> RuleConsolidationManifestV1 | None:
    path = proposal / RULE_CONSOLIDATIONS_NAME
    if not path.is_file():
        return None
    return RuleConsolidationManifestV1.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _latest_dispositions(root: Path) -> dict[str, RuleDispositionV1]:
    return {
        atom_id: RuleDispositionV1.model_validate(payload)
        for atom_id, payload in _latest(root / DISPOSITION_LEDGER, "atom_id").items()
    }


def scaffold_intake_rules(root: Path, intake_id: str, proposal_version: str = "1.7.0") -> Path:
    """Reconcile every included intake, rather than only incrementally adding one atom."""
    if proposal_version != "1.7.0":
        raise ValueError("通用 Intake 流水线首版仅支持 1.7.0")
    requested_atoms = [RuleAtomV1.model_validate(event.payload) for event in read_ledger(root / ATOM_LEDGER)
                       if event.payload.get("intake_id") == intake_id]
    if not requested_atoms:
        raise ValueError("intake 尚未原子化；请先执行 rules intake inspect")
    proposal = root / "knowledge/rule-proposals/football-analysis" / proposal_version
    if not proposal.is_dir():
        raise ValueError("1.7.0 proposal 不存在")
    specs_dir = proposal / "rule-specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    target = proposal / RULE_BUILD_NAME
    existing_build: dict[str, Any] = {}
    if target.exists():
        existing_build = RuleBuildManifestV1.model_validate(
            yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        ).model_dump(mode="json")

    intake_records = _latest(root / INTAKE_LEDGER, "intake_id")
    source_intake_ids = {str(item["intake_id"]) for item in existing_build.get("source_intakes", [])}
    source_intake_ids.add(intake_id)
    consolidations = _load_consolidations(proposal)
    consolidation_items = consolidations.consolidations if consolidations else []
    atom_payloads = {event.payload.get("atom_id"): event.payload for event in read_ledger(root / ATOM_LEDGER)}
    for atom_id in {atom for item in consolidation_items for atom in item.source_atoms}:
        payload = atom_payloads.get(atom_id)
        if payload is None:
            raise ValueError(f"合并声明引用不存在 atom：{atom_id}")
        source_intake_ids.add(str(payload["intake_id"]))
    all_atoms = [RuleAtomV1.model_validate(payload) for payload in atom_payloads.values()
                 if payload.get("intake_id") in source_intake_ids]
    latest_dispositions = _latest_dispositions(root)
    consolidated_atoms = {atom_id for item in consolidation_items for atom_id in item.source_atoms}
    superseded_rule_ids = {rule_id for item in consolidation_items for rule_id in item.superseded_rule_ids}
    known_atoms = {atom.atom_id: atom for atom in all_atoms}
    selected: dict[str, RuleBuildEntryV1] = {}
    specs: dict[str, dict[str, str]] = {}

    for atom in all_atoms:
        rule_id = f"advisory-intake-{atom.atom_id[-12:]}"
        disposition = latest_dispositions.get(atom.atom_id)
        effective = disposition.disposition if disposition else atom.classification
        if effective != "advisory_candidate" or atom.atom_id in consolidated_atoms or rule_id in superseded_rule_ids:
            continue
        spec = RuleSpecV1(
            rule_id=rule_id, rule_revision=1, track="advisory", effect="advisory",
            market_scope=atom.rule_domain, applies_to_profiles=["global"], source_atoms=[atom.atom_id],
            evaluator=RuleEvaluatorV1(kind="manual_review", config={"question": atom.statement}),
            required_inputs=["human_review"], time_gate=atom.timing,
            failure_mode="insufficient_data", invalidation_conditions=["缺少赛前可追溯输入"],
        )
        spec_path = specs_dir / f"{rule_id}.yml"
        atomic_write_text(spec_path, yaml.safe_dump(spec.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        selected[atom.atom_id] = RuleBuildEntryV1(
            atom_id=atom.atom_id, atom_sha256=atom.atom_sha256,
            disposition_sha256=_disposition_hash(root, atom.atom_id),
        )
        specs[rule_id] = {"rule_id": rule_id, "rule_spec_sha256": sha256_file(spec_path)}

    resolutions: list[dict[str, Any]] = []
    for item in consolidation_items:
        for atom_id in item.source_atoms:
            atom = known_atoms.get(atom_id)
            disposition = latest_dispositions.get(atom_id)
            if atom is None or disposition is None:
                raise ValueError(f"合并声明引用不存在或未处置的 atom：{atom_id}")
            if disposition.disposition not in {"advisory_candidate", "research_only"}:
                raise ValueError(f"合并声明引用不可选 atom：{atom_id}")
            selected[atom_id] = RuleBuildEntryV1(
                atom_id=atom_id, atom_sha256=atom.atom_sha256,
                disposition_sha256=_disposition_hash(root, atom_id),
            )
        spec_path = specs_dir / f"{item.rule_id}.yml"
        atomic_write_text(spec_path, yaml.safe_dump(item.rule_spec.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        specs[item.rule_id] = {"rule_id": item.rule_id, "rule_spec_sha256": sha256_file(spec_path)}
        resolutions.append({
            "consolidation_id": item.consolidation_id, "rule_id": item.rule_id,
            "source_atoms": item.source_atoms, "superseded_rule_ids": item.superseded_rule_ids,
            "consolidation_sha256": item.consolidation_sha256,
        })

    generated_ids = set(specs)
    for spec_path in specs_dir.glob("advisory-intake-*.yml"):
        if spec_path.stem not in generated_ids:
            spec_path.unlink()
    source_intakes = [
        {"intake_id": identifier, "source_sha256": RuleIntakeV1.model_validate(intake_records[identifier]).source_sha256}
        for identifier in sorted(source_intake_ids)
    ]
    raw = {
        "schema_version": 1, "proposal_version": proposal_version, "compiler_version": "rule-intake-compiler-v2",
        "source_intakes": source_intakes,
        "selected_atoms": [selected[key].model_dump(mode="json") for key in sorted(selected)],
        "generated_rule_specs": [specs[key] for key in sorted(specs)],
        "duplicate_and_conflict_resolutions": existing_build.get("duplicate_and_conflict_resolutions", []),
        "consolidation_manifest_sha256": consolidations.manifest_sha256 if consolidations else None,
        "consolidation_resolutions": resolutions,
        "build_sha256": "0" * 64,
    }
    raw["build_sha256"] = _build_hash(raw)
    build = RuleBuildManifestV1.model_validate(raw)
    atomic_write_text(target, yaml.safe_dump(build.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    _sync_contract6_build_hash(proposal, target)
    return target


def _latest_disposition(root: Path, atom_id: str) -> RuleDispositionV1:
    entries = [RuleDispositionV1.model_validate(event.payload) for event in read_ledger(root / DISPOSITION_LEDGER)
               if event.payload.get("atom_id") == atom_id]
    if not entries:
        raise ValueError(f"原子尚无处置记录：{atom_id}")
    return entries[-1]


def set_atom_disposition(
    root: Path,
    atom_id: str,
    disposition: Literal["duplicate", "supplement", "conflict", "invalid", "deferred", "advisory_candidate", "research_only", "promoted_to_prediction", "retired"],
    *,
    reason: str,
    existing_rule_ids: list[str] | None = None,
    missing_inputs: list[str] | None = None,
    conflict_ids: list[str] | None = None,
    actor: str = "lcz",
) -> RuleDispositionV1:
    if atom_id not in _latest(root / ATOM_LEDGER, "atom_id"):
        raise ValueError(f"不存在原子：{atom_id}")
    fields = {
        "atom_id": atom_id,
        "disposition": disposition,
        "existing_rule_ids": existing_rule_ids or [],
        "conflict_ids": conflict_ids or [],
        "missing_inputs": missing_inputs or [],
        "actor": actor,
        "reason": reason,
    }
    current = _latest_disposition(root, atom_id)
    if all(getattr(current, key) == value for key, value in fields.items()):
        return current
    payload = RuleDispositionV1(**fields, recorded_at=_now()).model_dump(mode="json")
    append_payloads(root / DISPOSITION_LEDGER, [payload], recorded_at=_now(), actor=actor,
                    event_id_factory=lambda item, _: f"rule-disposition:{item['atom_id']}:{item['disposition']}:{sha256_json(item)[:12]}")
    return RuleDispositionV1.model_validate(payload)


def set_rule_disposition(root: Path, rule_id: str, disposition: Literal["promoted_to_prediction", "deferred", "retired"], *, reason: str, actor: str = "lcz") -> RuleDispositionV1:
    proposal = root / "knowledge/rule-proposals/football-analysis/1.7.0"
    spec_path = proposal / "rule-specs" / f"{rule_id}.yml"
    if not spec_path.exists():
        raise ValueError(f"不存在由 intake 生成的规则：{rule_id}")
    spec = RuleSpecV1.model_validate(yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {})
    if not spec.source_atoms:
        raise ValueError("规则未绑定 source atom")
    atom_id = spec.source_atoms[0]
    if disposition == "promoted_to_prediction":
        if spec.track != "advisory":
            raise ValueError("只能从 advisory 候选晋级预测实验")
        raise ValueError("晋级预测实验必须在新的 proposal revision 中补齐预测输出、反证和测试夹具")
    records = [
        set_atom_disposition(root, source_atom, disposition, reason=reason,
                             existing_rule_ids=[rule_id], actor=actor)
        for source_atom in spec.source_atoms
    ]
    return records[0]


def consolidate_intake_rules(root: Path, proposal_version: str = "1.7.0") -> Path:
    proposal = root / "knowledge/rule-proposals/football-analysis" / proposal_version
    consolidations = _load_consolidations(proposal)
    if consolidations is None or not consolidations.consolidations:
        raise ValueError("缺少非空 rule-consolidations.yml")
    atoms = {event.payload.get("atom_id"): event.payload for event in read_ledger(root / ATOM_LEDGER)}
    referenced = {atom_id for item in consolidations.consolidations for atom_id in item.source_atoms}
    missing = sorted(atom_id for atom_id in referenced if atom_id not in atoms)
    if missing:
        raise ValueError("规则合并清单引用不存在 atom：" + ", ".join(missing))
    # Any referenced intake starts the complete reconciliation, which retains all prior proposal intakes.
    first_intake = str(atoms[sorted(referenced)[0]]["intake_id"])
    return scaffold_intake_rules(root, first_intake, proposal_version)


def intake_status(root: Path) -> dict[str, Any]:
    intakes = _latest(root / INTAKE_LEDGER, "intake_id")
    atoms = [RuleAtomV1.model_validate(event.payload) for event in read_ledger(root / ATOM_LEDGER)]
    counts: dict[str, int] = {}
    for atom in atoms:
        counts[atom.classification] = counts.get(atom.classification, 0) + 1
    return {"schema_version": 1, "intakes": len(intakes), "atoms": len(atoms), "classifications": counts}
