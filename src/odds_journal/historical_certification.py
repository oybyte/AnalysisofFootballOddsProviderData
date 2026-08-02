from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cases import case_events, latest_cases, rebuild_cases, write_case_directory, write_revision_manifest
from .extraction import EXTRACTION_RELATIVE
from .ledger import append_payloads, read_ledger, sha256_json


CERTIFICATION_PATH = Path("knowledge/evidence/historical-case-certification-events.jsonl")


class HistoricalMarketNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    phase: Literal["opening", "mid", "late"]
    observed_at: datetime
    provider: str = Field(min_length=1)
    market: Literal["handicap", "one_x_two", "total_goals", "kelly"]
    line: str = Field(min_length=1)
    odds_format: Literal["hong_kong", "decimal", "kelly"]
    raw_value: str = Field(min_length=1)
    source_atom_id: str = Field(min_length=1)

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("盘口节点时间必须包含时区")
        return value


class HistoricalCaseCertification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    certification_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    expected_case_revision: int = Field(ge=1)
    decision: Literal["certified", "rejected", "needs_manual_split"]
    competition_code: str | None = None
    home_team_id: str | None = None
    away_team_id: str | None = None
    kickoff_at: datetime | None = None
    result_observed_at: datetime | None = None
    prematch_atom_ids: list[str] = Field(default_factory=list)
    postmatch_atom_ids: list[str] = Field(default_factory=list)
    result_atom_ids: list[str] = Field(default_factory=list)
    market_snapshots: list[HistoricalMarketNode] = Field(default_factory=list)
    review_reason: str = Field(min_length=1)
    supersedes_certification_id: str | None = None

    @field_validator("kickoff_at", "result_observed_at")
    @classmethod
    def kickoff_timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("开赛时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_certification(self) -> "HistoricalCaseCertification":
        groups = (self.prematch_atom_ids, self.postmatch_atom_ids, self.result_atom_ids)
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("认证 atom 引用不可重复")
        if self.decision != "certified":
            return self
        if not self.kickoff_at:
            raise ValueError("认证通过必须提供开赛时间")
        if not all((self.prematch_atom_ids, self.postmatch_atom_ids, self.result_atom_ids)):
            raise ValueError("认证通过必须提供赛前、赛后与赛果 atom")
        phases = {item.phase for item in self.market_snapshots}
        if phases != {"opening", "mid", "late"}:
            raise ValueError("认证通过必须提供 opening/mid/late 盘口节点")
        if any(item.observed_at >= self.kickoff_at for item in self.market_snapshots):
            raise ValueError("认证盘口节点必须早于开赛")
        if self.result_observed_at is None or self.result_observed_at < self.kickoff_at:
            raise ValueError("认证通过必须证明赛果记录位于开赛后")
        return self

    @property
    def market_snapshot_sha256(self) -> str:
        return sha256_json([item.model_dump(mode="json") for item in self.market_snapshots])


class HistoricalCertificationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    batch_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    source_family_id: str = Field(min_length=1)
    cases: list[HistoricalCaseCertification] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def unique_case_ids(cls, value: list[HistoricalCaseCertification]) -> list[HistoricalCaseCertification]:
        case_ids = [item.case_id for item in value]
        certification_ids = [item.certification_id for item in value]
        if len(case_ids) != len(set(case_ids)) or len(certification_ids) != len(set(certification_ids)):
            raise ValueError("同一认证批次不得重复案例或认证 ID")
        return value

    @property
    def manifest_sha256(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


def certification_events(root: Path):
    return read_ledger(root / CERTIFICATION_PATH)


def latest_certifications(root: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for event in certification_events(root):
        latest[str(event.payload["case_id"])] = event.payload
    return latest


def validate_certifications(root: Path) -> dict[Path, list[str]]:
    path = root / CERTIFICATION_PATH
    errors: list[str] = []
    try:
        cases = latest_cases(root)
        for case_id, payload in latest_certifications(root).items():
            if case_id not in cases:
                errors.append(f"认证引用不存在案例：{case_id}")
                continue
            decision = payload.get("decision")
            if decision == "certified":
                case = cases[case_id]
                if not case.statistics_eligible or case.status != "approved":
                    errors.append(f"认证案例未处于 approved 统计状态：{case_id}")
    except Exception as exc:
        errors.append(str(exc))
    return {path: errors} if path.exists() else {}


def _validate_atom_ids(root: Path, source_family_id: str, atom_ids: list[str]) -> None:
    atoms: set[str] = set()
    for path in (root / "knowledge/extraction").glob("*/text-inventory.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)
                atom_id = payload.get("atom_id")
                if not isinstance(atom_id, str) or not atom_id:
                    raise ValueError(f"原子库存缺少有效 atom_id：{path}")
                atoms.add(atom_id)
    missing = [atom_id for atom_id in atom_ids if atom_id not in atoms]
    if missing:
        raise ValueError(f"认证引用不存在的 source atom：{missing[:3]}")
    foreign = [atom_id for atom_id in atom_ids if not atom_id.startswith(source_family_id)]
    if foreign:
        raise ValueError(f"认证 atom 不属于来源族 {source_family_id}：{foreign[:3]}")


def _certification_payload(
    item: HistoricalCaseCertification,
    manifest: HistoricalCertificationManifest,
    *,
    source_sha256: str,
) -> dict:
    return {
        "schema_version": 1,
        "certification_id": item.certification_id,
        "case_id": item.case_id,
        "case_revision": item.expected_case_revision + 1,
        "source_family_id": manifest.source_family_id,
        "decision": item.decision,
        "competition_code": item.competition_code,
        "home_team_id": item.home_team_id,
        "away_team_id": item.away_team_id,
        "kickoff_at": item.kickoff_at.isoformat() if item.kickoff_at else None,
        "result_observed_at": item.result_observed_at.isoformat() if item.result_observed_at else None,
        "prematch_atom_ids": item.prematch_atom_ids,
        "postmatch_atom_ids": item.postmatch_atom_ids,
        "result_atom_ids": item.result_atom_ids,
        "market_snapshots": [node.model_dump(mode="json") for node in item.market_snapshots],
        "market_snapshot_sha256": item.market_snapshot_sha256,
        "manifest_sha256": manifest.manifest_sha256,
        "source_sha256": source_sha256,
        "review_reason": item.review_reason,
        "reviewed_by": None,
        "supersedes_certification_id": item.supersedes_certification_id,
    }


def certify_historical_cases(
    root: Path,
    manifest: HistoricalCertificationManifest,
    *,
    actor: str,
    recorded_at: datetime,
) -> dict[str, int]:
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("认证记录时间必须包含时区")
    source_path = root / "knowledge/extraction" / manifest.source_family_id / "source.yml"
    if not source_path.exists():
        raise ValueError(f"来源族不存在：{manifest.source_family_id}")
    import hashlib

    source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    cases = latest_cases(root)
    existing = certification_events(root)
    existing_ids = {str(event.payload["certification_id"]): event for event in existing}
    latest_by_case = latest_certifications(root)
    case_payloads: list[dict] = []
    certification_payloads: list[dict] = []
    skipped = 0
    event_by_case = {str(event.payload["case_id"]): event for event in case_events(root)}

    for item in manifest.cases:
        current = cases.get(item.case_id)
        if current is None:
            raise ValueError(f"认证案例不存在：{item.case_id}")
        if current.case_revision != item.expected_case_revision:
            raise ValueError(f"案例 revision 已变化：{item.case_id}")
        all_atoms = [*item.prematch_atom_ids, *item.postmatch_atom_ids, *item.result_atom_ids]
        _validate_atom_ids(root, manifest.source_family_id, all_atoms)
        for node in item.market_snapshots:
            _validate_atom_ids(root, manifest.source_family_id, [node.source_atom_id])
            if node.source_atom_id not in item.prematch_atom_ids:
                raise ValueError("盘口节点必须引用赛前 atom")
        payload = _certification_payload(item, manifest, source_sha256=source_sha256)
        payload["reviewed_by"] = actor
        existing_event = existing_ids.get(item.certification_id)
        if existing_event is not None:
            if existing_event.payload != payload:
                raise ValueError(f"certification_id 已存在且内容不同：{item.certification_id}")
            skipped += 1
            continue
        previous = latest_by_case.get(item.case_id)
        if item.supersedes_certification_id:
            if previous is None or previous["certification_id"] != item.supersedes_certification_id:
                raise ValueError("supersedes_certification_id 必须指向该案例当前认证")
        elif previous is not None:
            raise ValueError("已有认证时必须显式 supersede")
        certification_payloads.append(payload)

        case_payload = current.model_dump(mode="json")
        limitations = case_payload["sections"]["limitations"].rstrip()
        limitations += (
            f"\n\n---\n\n### 历史案例再认证（{recorded_at.isoformat()}）\n\n"
            f"- 认证 ID：`{item.certification_id}`\n"
            f"- 决定：`{item.decision}`\n"
            f"- 认证清单哈希：`{manifest.manifest_sha256}`\n"
            f"- 盘口快照哈希：`{item.market_snapshot_sha256}`\n"
            f"- 说明：{item.review_reason}"
        )
        case_payload.update({
            "case_revision": current.case_revision + 1,
            "revision_effective_at": recorded_at.isoformat(),
            "chronology": "prematch_verified" if item.decision == "certified" else current.chronology,
            "completeness": "complete" if item.decision == "certified" else current.completeness,
            "statistics_eligible": item.decision == "certified",
            "status": "approved" if item.decision == "certified" else "draft",
            "sections": {**case_payload["sections"], "limitations": limitations},
            "_supersedes_event_id": event_by_case[item.case_id].event_id,
        })
        case_payloads.append(case_payload)

    if not certification_payloads:
        return {"certified": 0, "reviewed": 0, "skipped": skipped}
    from .transaction import RepositoryTransaction
    from .cases import _case_relative_path

    affected = [cases[item.case_id] for item in manifest.cases if item.certification_id not in existing_ids]
    with RepositoryTransaction(
        root,
        files=[
            root / CERTIFICATION_PATH,
            root / EXTRACTION_RELATIVE / "case-events.jsonl",
            root / "knowledge/cases/legacy/README.md",
            root / "knowledge/cases/legacy/REVISION_MANIFEST.yml",
            *(root / _case_relative_path(case) for case in affected),
        ],
        directories=[root / "knowledge/cases/legacy/_revisions"],
        operation="case-certify-historical",
    ) as transaction:
        append_payloads(
            root / CERTIFICATION_PATH,
            certification_payloads,
            recorded_at=recorded_at,
            actor=actor,
            event_id_factory=lambda value, _: f"historical-certification:{value['case_id']}:{value['certification_id']}",
        )
        append_payloads(
            root / EXTRACTION_RELATIVE / "case-events.jsonl",
            case_payloads,
            recorded_at=recorded_at,
            actor=actor,
            event_id_factory=lambda value, _: f"case:certify:{value['case_id']}:{value['case_revision']}",
        )
        rebuild_cases(root)
        write_case_directory(root)
        write_revision_manifest(root)
        transaction.commit()
    certified = sum(item.decision == "certified" for item in manifest.cases) - skipped
    return {"certified": certified, "reviewed": len(certification_payloads), "skipped": skipped}


def load_certification_manifest(path: Path) -> HistoricalCertificationManifest:
    return HistoricalCertificationManifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
