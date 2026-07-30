from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ledger import append_payloads, latest_payloads, read_ledger


EVIDENCE_LEDGER = Path("knowledge/evidence/evidence-events.jsonl")


class EvidenceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    assertion_type: Literal["kickoff", "result", "market"]
    asserted_value: dict[str, Any]
    status: Literal["active", "superseded", "rejected"] = "active"
    superseded_by_binding_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "EvidenceBinding":
        if self.status == "active" and self.superseded_by_binding_id:
            raise ValueError("active binding 不能填写 superseded_by_binding_id")
        if self.status != "active" and not self.reason:
            raise ValueError("失效 binding 必须说明原因")
        return self


class EvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    evidence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    evidence_type: Literal["kickoff_screenshot", "result_screenshot", "external_document"]
    archived_path: str
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_at: datetime
    identity_basis: str = Field(min_length=1)
    file_status: Literal["active", "unavailable", "corrupt"] = "active"
    source_basename: str | None = None
    visible_text: str | None = None
    bindings: list[EvidenceBinding]

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("证据记录时间必须包含时区")
        return value

    @model_validator(mode="after")
    def unique_bindings(self) -> "EvidenceRecord":
        identities = [item.binding_id for item in self.bindings]
        if len(identities) != len(set(identities)):
            raise ValueError("证据 binding_id 重复")
        return self


def evidence_records(root: Path) -> dict[str, EvidenceRecord]:
    events = read_ledger(root / EVIDENCE_LEDGER)
    latest = latest_payloads(events, lambda payload: str(payload["evidence_id"]))
    return {key: EvidenceRecord.model_validate(value) for key, value in latest.items()}


def active_binding(root: Path, evidence_id: str, binding_id: str, *, case_id: str) -> EvidenceBinding:
    record = evidence_records(root).get(evidence_id)
    if record is None:
        raise ValueError(f"证据不存在：{evidence_id}")
    if record.file_status != "active":
        raise ValueError(f"证据文件不可用：{evidence_id}")
    path = root / record.archived_path
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record.file_sha256:
        raise ValueError(f"证据文件缺失或哈希不一致：{evidence_id}")
    binding = next((item for item in record.bindings if item.binding_id == binding_id), None)
    if binding is None:
        raise ValueError(f"证据 binding 不存在：{binding_id}")
    if binding.case_id != case_id:
        raise ValueError(f"证据 binding 不属于案例 {case_id}：{binding_id}")
    if binding.status != "active":
        raise ValueError(f"证据 binding 已失效：{binding_id} ({binding.status})")
    return binding


def validate_evidence_registry(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        records = evidence_records(root)
    except Exception as exc:
        return [str(exc)]
    binding_ids: dict[str, str] = {}
    for record in records.values():
        path = root / record.archived_path
        if not path.is_file():
            errors.append(f"证据文件不存在：{record.evidence_id} -> {record.archived_path}")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != record.file_sha256:
            errors.append(f"证据文件哈希不一致：{record.evidence_id}")
        for binding in record.bindings:
            previous = binding_ids.get(binding.binding_id)
            if previous and previous != record.evidence_id:
                errors.append(f"binding_id 跨证据重复：{binding.binding_id}")
            binding_ids[binding.binding_id] = record.evidence_id
            if binding.superseded_by_binding_id and binding.superseded_by_binding_id == binding.binding_id:
                errors.append(f"binding 不能 supersede 自身：{binding.binding_id}")
    for record in records.values():
        for binding in record.bindings:
            if binding.superseded_by_binding_id and binding.superseded_by_binding_id not in binding_ids:
                errors.append(
                    f"replacement binding 不存在：{binding.binding_id} -> {binding.superseded_by_binding_id}"
                )
    return errors


def _binding_id(evidence_id: str, case_id: str, assertion_type: str) -> str:
    return f"{evidence_id}:{case_id}:{assertion_type}"


def _manifest_records(root: Path) -> list[EvidenceRecord]:
    output: list[EvidenceRecord] = []
    for manifest_path in sorted((root / "knowledge/evidence").glob("**/MANIFEST.yml")):
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        for raw in manifest.get("records", []):
            evidence_id = str(raw["evidence_id"])
            bindings: list[EvidenceBinding] = []
            if raw.get("identified_matches"):
                for match in raw["identified_matches"]:
                    case_id = str(match["case_id"])
                    bindings.append(EvidenceBinding(
                        binding_id=_binding_id(evidence_id, case_id, "kickoff"),
                        case_id=case_id,
                        assertion_type="kickoff",
                        asserted_value={"kickoff_at": str(match["kickoff_at"])},
                    ))
                evidence_type = "kickoff_screenshot"
            else:
                for case_id in raw.get("case_ids", []):
                    bindings.append(EvidenceBinding(
                        binding_id=_binding_id(evidence_id, str(case_id), "result"),
                        case_id=str(case_id),
                        assertion_type="result",
                        asserted_value={"visible_text": str(raw.get("visible_text") or "")},
                    ))
                evidence_type = "result_screenshot"
            output.append(EvidenceRecord(
                evidence_id=evidence_id,
                evidence_type=evidence_type,
                archived_path=str(raw["archived_path"]),
                file_sha256=str(raw["sha256"]),
                recorded_at=raw["recorded_at"],
                identity_basis=str(raw["identity_basis"]),
                source_basename=raw.get("source_basename"),
                visible_text=raw.get("visible_text"),
                bindings=bindings,
            ))
    return output


def migrate_evidence_manifests(root: Path, *, dry_run: bool = False) -> dict[str, int]:
    records = sorted(_manifest_records(root), key=lambda item: (item.recorded_at, item.evidence_id))
    result = {"records": len(records), "bindings": sum(len(item.bindings) for item in records), "corrections": 1}
    if dry_run:
        return result
    path = root / EVIDENCE_LEDGER
    for record in records:
        append_payloads(
            path,
            [record.model_dump(mode="json")],
            recorded_at=record.recorded_at,
            actor="manifest-migration",
            event_id_factory=lambda item, _: f"evidence:{item['evidence_id']}:import",
        )
    current = evidence_records(root)["user-kickoff-20260730-05"]
    bindings = []
    for binding in current.bindings:
        if binding.case_id == "legacy-seoul-ulsan" and binding.assertion_type == "kickoff":
            binding = binding.model_copy(update={
                "status": "rejected",
                "reason": "后续赛程截图确认该案例实际开赛时间为 2026-07-26T18:30:00+08:00",
                "superseded_by_binding_id": _binding_id(
                    "user-kickoff-20260730-07", "legacy-seoul-ulsan", "kickoff"
                ),
            })
        bindings.append(binding)
    corrected = current.model_copy(update={"bindings": bindings})
    source_event = next(
        event for event in read_ledger(path)
        if event.payload.get("evidence_id") == current.evidence_id
    )
    payload = corrected.model_dump(mode="json")
    payload["_supersedes_event_id"] = source_event.event_id
    append_payloads(
        path,
        [payload],
        recorded_at=datetime.fromisoformat("2026-07-30T10:15:00+08:00"),
        actor="manifest-migration",
        event_id_factory=lambda item, _: "evidence:user-kickoff-20260730-05:reject-binding",
    )
    errors = validate_evidence_registry(root)
    if errors:
        raise ValueError("；".join(errors))
    return result


def register_evidence(root: Path, record: EvidenceRecord, *, actor: str) -> None:
    path = root / record.archived_path
    if not path.is_file():
        raise ValueError(f"证据文件不存在：{record.archived_path}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record.file_sha256:
        raise ValueError(f"证据文件哈希不一致：{record.evidence_id}")
    append_payloads(
        root / EVIDENCE_LEDGER,
        [record.model_dump(mode="json")],
        recorded_at=record.recorded_at,
        actor=actor,
        event_id_factory=lambda item, _: f"evidence:{item['evidence_id']}:register",
    )


def change_binding_status(
    root: Path,
    *,
    evidence_id: str,
    binding_id: str,
    status: Literal["superseded", "rejected"],
    reason: str,
    recorded_at: datetime,
    actor: str,
    replacement_binding_id: str | None = None,
) -> None:
    ledger = root / EVIDENCE_LEDGER
    events = read_ledger(ledger)
    relevant = [event for event in events if event.payload.get("evidence_id") == evidence_id]
    if not relevant:
        raise ValueError(f"证据不存在：{evidence_id}")
    current_event = relevant[-1]
    record = EvidenceRecord.model_validate(current_event.payload)
    found = False
    bindings: list[EvidenceBinding] = []
    for binding in record.bindings:
        if binding.binding_id == binding_id:
            found = True
            binding = binding.model_copy(update={
                "status": status,
                "reason": reason,
                "superseded_by_binding_id": replacement_binding_id,
            })
        bindings.append(binding)
    if not found:
        raise ValueError(f"证据 binding 不存在：{binding_id}")
    payload = record.model_copy(update={"bindings": bindings}).model_dump(mode="json")
    payload["_supersedes_event_id"] = current_event.event_id
    append_payloads(
        ledger,
        [payload],
        recorded_at=recorded_at,
        actor=actor,
        event_id_factory=lambda item, _: f"evidence:{evidence_id}:{status}:{len(relevant) + 1}",
    )
