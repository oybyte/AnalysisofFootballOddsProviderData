from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .agent_workflow import analysis_report_text, validate_analysis_draft
from .analysis_context import parse_receipt
from .case_retrieval import parse_case_receipt
from .ledger import append_payloads, read_ledger, sha256_json
from .markdown import MatchDocument, PREMATCH_SECTIONS, has_substantive_content
from .models import (
    AnalysisDataMode,
    AnalysisOutlook,
    MARKET_SELECTIONS,
    MatchStatus,
    PrimaryMarket,
    Selection,
)
from .rules import sha256_text
from .scenarios import parse_scenarios
from .services import ServiceError, finish_match, lock_match
from .transaction import RepositoryTransaction


LIFECYCLE_LEDGER = Path("knowledge/evidence/match-lifecycle-events.jsonl")
LOCK_CANDIDATE_DIR = Path("raw/matches")
JOURNAL_ENTRY_RE = re.compile(r"<!-- journal-entry:([^:>]+):")


class LifecycleActionStatus(StrEnum):
    APPLIED = "applied"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class LifecycleAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["audit_lock", "finish", "prepare_review"]
    status: LifecycleActionStatus
    reason: str | None = None


class LockCandidateReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    schema_version: Literal[1, 2] = 1
    receipt_id: str = Field(pattern=r"^lock-[a-z0-9-]+$")
    match_id: str
    prepared_at: datetime
    data_cutoff_at: datetime
    kickoff_at: datetime
    primary_market: PrimaryMarket
    primary_selection: Selection
    secondary_selection: Selection | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    analysis_data_mode: AnalysisDataMode
    prematch_facts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prematch_reasoning_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prematch_locked_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prematch_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_outlook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_entry_ids: list[str] = Field(default_factory=list)
    outlook_path: str
    outlook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_report_path: str | None = None
    analysis_report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    calibration_config_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at", "data_cutoff_at", "kickoff_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("锁定候选时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> "LockCandidateReceiptV1":
        if self.prepared_at > self.kickoff_at or self.data_cutoff_at > self.kickoff_at:
            raise ValueError("锁定候选必须在开赛前形成")
        market = PrimaryMarket(self.primary_market)
        selection = Selection(self.primary_selection)
        if selection not in MARKET_SELECTIONS[market]:
            raise ValueError("主选方向不适用于主市场")
        if self.secondary_selection and Selection(self.secondary_selection) not in MARKET_SELECTIONS[market]:
            raise ValueError("次选方向不适用于主市场")
        mode = AnalysisDataMode(self.analysis_data_mode)
        if mode == AnalysisDataMode.DEGRADED and self.confidence is not None and self.confidence > 0.69:
            raise ValueError("degraded 锁定候选置信度不得超过 0.69")
        if market == PrimaryMarket.PASS:
            if selection != Selection.PASS or self.confidence is not None:
                raise ValueError("pass 锁定候选必须使用 pass 且不填写置信度")
        elif self.confidence is None:
            raise ValueError("非 pass 锁定候选必须填写置信度")
        frozen = (
            self.analysis_report_path,
            self.analysis_report_sha256,
            self.calibration_config_sha256,
        )
        if self.schema_version == 1 and any(value is not None for value in frozen):
            raise ValueError("锁定候选 V1 不支持规范报告和校准配置哈希")
        if self.schema_version == 2 and any(value is None for value in frozen):
            raise ValueError("锁定候选 V2 必须冻结规范报告和校准配置哈希")
        return self


def _receipt_hash(payload: dict) -> str:
    clean = dict(payload)
    clean.pop("receipt_sha256", None)
    if clean.get("schema_version", 1) == 1:
        clean.pop("analysis_report_path", None)
        clean.pop("analysis_report_sha256", None)
        clean.pop("calibration_config_sha256", None)
    return sha256_json(clean)


def _section_hash(document: MatchDocument, name: str) -> str:
    return sha256_text(document.sections[name])


def _outlook_model_hash(outlook: AnalysisOutlook) -> str:
    payload = outlook.model_dump(mode="json")
    if outlook.schema_version == 1:
        payload.pop("schema_version", None)
        payload.pop("competition_profile", None)
        payload.pop("calibration_contract_version", None)
        payload.pop("calibration_events", None)
        payload.pop("calibration_summary", None)
    return sha256_json(payload)


def _relative_file(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ServiceError("锁定候选文件必须位于项目内") from exc


def candidate_path(root: Path, receipt: LockCandidateReceiptV1) -> Path:
    return root / LOCK_CANDIDATE_DIR / receipt.match_id / "lock-candidates" / f"{receipt.receipt_id}.yml"


def load_lock_candidate(path: Path) -> LockCandidateReceiptV1:
    receipt = LockCandidateReceiptV1.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if receipt.receipt_sha256 != _receipt_hash(receipt.model_dump(mode="json")):
        raise ServiceError("锁定候选回执哈希无效")
    return receipt


def latest_lock_candidate(root: Path, match_id: str) -> tuple[Path, LockCandidateReceiptV1] | None:
    directory = root / LOCK_CANDIDATE_DIR / match_id / "lock-candidates"
    candidates = sorted(directory.glob("lock-*.yml")) if directory.exists() else []
    if not candidates:
        return None
    loaded = [(path, load_lock_candidate(path)) for path in candidates]
    ledger = root / LIFECYCLE_LEDGER
    if ledger.exists():
        prepared = [
            event.payload for event in read_ledger(ledger)
            if event.payload.get("event_type") == "lock_candidate_prepared"
            and event.payload.get("match_id") == match_id
        ]
        if prepared:
            latest_id = prepared[-1].get("receipt_id")
            for candidate in loaded:
                if candidate[1].receipt_id == latest_id:
                    return candidate
    return max(loaded, key=lambda item: (item[1].prepared_at, item[0].name))


def prepare_lock_candidate(
    root: Path,
    path: Path,
    *,
    market: PrimaryMarket,
    selection: Selection,
    secondary: Selection | None,
    confidence: float | None,
    outlook_path: Path,
    actor: str,
) -> tuple[Path, LockCandidateReceiptV1]:
    root = root.resolve()
    document = MatchDocument.load(path)
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if now > document.metadata.kickoff_at:
        raise ServiceError("比赛已开赛，禁止生成锁定候选回执")
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ServiceError("只有 draft/tracking 可以生成锁定候选回执")
    analysis_receipt = parse_receipt(document.sections["prematch-reasoning"])
    if analysis_receipt and analysis_receipt.schema_version in {5, 6} and analysis_receipt.ruleset_origin == "proposal":
        raise ServiceError("提案规则集只能离线分析，禁止生成锁定候选回执")
    outlook = AnalysisOutlook.model_validate(yaml.safe_load(outlook_path.read_text(encoding="utf-8")) or {})
    errors = validate_analysis_draft(root, document, outlook=outlook, require_current=True)
    for name in PREMATCH_SECTIONS:
        if "TODO:replace-before-lock" in document.sections[name]:
            errors.append(f"锁定章节仍包含待填写标记：{name}")
        if not has_substantive_content(document.sections[name]):
            errors.append(f"锁定章节缺少有效内容：{name}")
    if errors:
        raise ServiceError("；".join(dict.fromkeys(errors)))
    scenarios = parse_scenarios(document.sections["prematch-reasoning"], required=True)
    case_receipt = parse_case_receipt(document.sections["prematch-reasoning"], required=True)
    assert analysis_receipt is not None and scenarios is not None and case_receipt is not None
    source_ids = sorted(set(JOURNAL_ENTRY_RE.findall("".join(document.sections[name] for name in PREMATCH_SECTIONS))))
    outlook_relative = _relative_file(root, outlook_path)
    report_path = root / LOCK_CANDIDATE_DIR / document.metadata.match_id / "analysis-report.md"
    receipt_schema = 2 if analysis_receipt.schema_version == 4 else 1
    if receipt_schema == 2 and not report_path.is_file():
        raise ServiceError("缺少规范分析报告；请先运行 agent render-draft")
    if receipt_schema == 2 and report_path.read_text(encoding="utf-8") != analysis_report_text(
        document, analysis_receipt
    ):
        raise ServiceError("规范分析报告与当前 Metadata 或分析正文不一致；请重新 render-draft")
    raw = {
        "schema_version": receipt_schema,
        "receipt_id": f"lock-{now:%Y%m%d%H%M%S}-{uuid4().hex[:12]}",
        "match_id": document.metadata.match_id,
        "prepared_at": now,
        "data_cutoff_at": analysis_receipt.as_of,
        "kickoff_at": document.metadata.kickoff_at,
        "primary_market": market,
        "primary_selection": selection,
        "secondary_selection": secondary,
        "confidence": confidence,
        "analysis_data_mode": outlook.data_mode,
        "prematch_facts_sha256": _section_hash(document, "prematch-facts"),
        "prematch_reasoning_sha256": _section_hash(document, "prematch-reasoning"),
        "prematch_locked_sha256": _section_hash(document, "prematch-locked"),
        "prematch_content_sha256": document.prematch_hash(),
        "analysis_outlook_sha256": _outlook_model_hash(outlook),
        "analysis_receipt_sha256": sha256_json(analysis_receipt.model_dump(mode="json")),
        "scenario_receipt_sha256": sha256_json(scenarios.model_dump(mode="json")),
        "case_receipt_sha256": sha256_json(case_receipt.model_dump(mode="json")),
        "source_entry_ids": source_ids,
        "outlook_path": outlook_relative,
        "outlook_sha256": hashlib.sha256((root / outlook_relative).read_bytes()).hexdigest(),
        "receipt_sha256": "0" * 64,
    }
    if receipt_schema == 2:
        raw.update(
            {
                "analysis_report_path": report_path.relative_to(root).as_posix(),
                "analysis_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                "calibration_config_sha256": analysis_receipt.calibration_config_sha256,
            }
        )
    provisional = LockCandidateReceiptV1.model_validate(raw)
    raw = provisional.model_dump(mode="json")
    raw["receipt_sha256"] = _receipt_hash(raw)
    receipt = LockCandidateReceiptV1.model_validate(raw)
    target = candidate_path(root, receipt)
    ledger = root / LIFECYCLE_LEDGER
    previous = latest_lock_candidate(root, document.metadata.match_id)
    with RepositoryTransaction(root, files=[target, ledger], directories=[], operation="prepare-lock-candidate") as transaction:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
        payloads = []
        if previous is not None:
            _, previous_receipt = previous
            payloads.append({
                "event_type": "lock_candidate_superseded",
                "match_id": receipt.match_id,
                "receipt_id": previous_receipt.receipt_id,
                "superseded_by_receipt_id": receipt.receipt_id,
            })
        payloads.append(
            {"event_type": "lock_candidate_prepared", "match_id": receipt.match_id, "receipt_id": receipt.receipt_id, "receipt_path": target.relative_to(root).as_posix(), "receipt_sha256": receipt.receipt_sha256, "effective_at": receipt.data_cutoff_at.isoformat()}
        )
        append_payloads(
            ledger,
            payloads,
            recorded_at=now,
            actor=actor,
            event_id_factory=lambda item, _: f"lifecycle:{item['event_type']}:{item['receipt_id']}:{receipt.receipt_id}",
        )
        transaction.commit()
    return target, receipt


def validate_lock_candidate(
    root: Path,
    path: Path,
    candidate: LockCandidateReceiptV1,
    *,
    require_current: bool,
) -> tuple[MatchDocument, AnalysisOutlook]:
    document = MatchDocument.load(path)
    errors: list[str] = []
    analysis_receipt = None
    if candidate.match_id != document.metadata.match_id:
        errors.append("锁定候选 match_id 与比赛不一致")
    latest = latest_lock_candidate(root, document.metadata.match_id)
    if latest is None or latest[1].receipt_id != candidate.receipt_id:
        errors.append("锁定候选不是该比赛的最新有效回执")
    expected = {
        "prematch_facts_sha256": _section_hash(document, "prematch-facts"),
        "prematch_reasoning_sha256": _section_hash(document, "prematch-reasoning"),
        "prematch_locked_sha256": _section_hash(document, "prematch-locked"),
        "prematch_content_sha256": document.prematch_hash(),
    }
    for field, actual in expected.items():
        if getattr(candidate, field) != actual:
            errors.append(f"锁定候选与当前赛前内容不一致：{field}")
    try:
        analysis_receipt = parse_receipt(document.sections["prematch-reasoning"])
        scenarios = parse_scenarios(document.sections["prematch-reasoning"], required=True)
        case_receipt = parse_case_receipt(document.sections["prematch-reasoning"], required=True)
        if analysis_receipt is None:
            errors.append("当前比赛缺少分析回执")
        else:
            if sha256_json(analysis_receipt.model_dump(mode="json")) != candidate.analysis_receipt_sha256:
                errors.append("分析回执与锁定候选不一致")
        if scenarios is not None and sha256_json(scenarios.model_dump(mode="json")) != candidate.scenario_receipt_sha256:
            errors.append("场景回执与锁定候选不一致")
        if case_receipt is not None and sha256_json(case_receipt.model_dump(mode="json")) != candidate.case_receipt_sha256:
            errors.append("案例回执与锁定候选不一致")
    except Exception as exc:
        errors.append(str(exc))
    lifecycle_events = read_ledger(root / LIFECYCLE_LEDGER)
    prepared_event = next(
        (
            event
            for event in lifecycle_events
            if event.payload.get("event_type") == "lock_candidate_prepared"
            and event.payload.get("receipt_id") == candidate.receipt_id
        ),
        None,
    )
    if prepared_event is None or prepared_event.payload.get("receipt_sha256") != candidate.receipt_sha256:
        errors.append("锁定候选缺少有效的赛前准备事件")
    outlook_file = root / candidate.outlook_path
    if not outlook_file.is_file() or hashlib.sha256(outlook_file.read_bytes()).hexdigest() != candidate.outlook_sha256:
        errors.append("锁定候选 Outlook 文件缺失或哈希变化")
        outlook = None
    else:
        outlook = AnalysisOutlook.model_validate(yaml.safe_load(outlook_file.read_text(encoding="utf-8")) or {})
        if _outlook_model_hash(outlook) != candidate.analysis_outlook_sha256:
            errors.append("锁定候选 Outlook 结构哈希变化")
    if outlook is not None:
        errors.extend(validate_analysis_draft(root, document, outlook=outlook, require_current=require_current))
    if candidate.schema_version == 2:
        report_file = root / str(candidate.analysis_report_path)
        if (
            not report_file.is_file()
            or hashlib.sha256(report_file.read_bytes()).hexdigest()
            != candidate.analysis_report_sha256
        ):
            errors.append("锁定候选规范分析报告缺失或哈希变化")
        if analysis_receipt and (
            candidate.calibration_config_sha256
            != analysis_receipt.calibration_config_sha256
        ):
            errors.append("锁定候选校准配置哈希与分析回执不一致")
    if errors:
        raise ServiceError("；".join(dict.fromkeys(errors)))
    assert outlook is not None
    return document, outlook


def lock_from_candidate(
    root: Path,
    path: Path,
    candidate_file: Path,
    *,
    actor: str,
    audit_late: bool = False,
    trigger_entry_id: str | None = None,
) -> MatchDocument:
    candidate = load_lock_candidate(candidate_file)
    document, outlook = validate_lock_candidate(root, path, candidate, require_current=not audit_late)
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if audit_late and now <= document.metadata.kickoff_at:
        raise ServiceError("开赛前应执行普通锁定，不得使用审计补锁")
    if not audit_late and now > document.metadata.kickoff_at:
        raise ServiceError("比赛已开赛；普通锁定已关闭")
    event_type = "audit_locked" if audit_late else "prematch_locked"
    ledger = root / LIFECYCLE_LEDGER
    with RepositoryTransaction(root, files=[path, ledger], directories=[], operation=event_type) as transaction:
        locked = lock_match(
            path,
            at=candidate.data_cutoff_at,
            market=PrimaryMarket(candidate.primary_market),
            selection=Selection(candidate.primary_selection),
            secondary=Selection(candidate.secondary_selection) if candidate.secondary_selection else None,
            confidence=candidate.confidence,
            analysis_outlook=outlook,
            require_current=not audit_late,
        )
        append_payloads(
            ledger,
            [{"event_type": event_type, "match_id": candidate.match_id, "effective_at": candidate.data_cutoff_at.isoformat(), "trigger_entry_id": trigger_entry_id, "lock_candidate_receipt_id": candidate.receipt_id, "prematch_lock_sha256": locked.metadata.prematch_lock_sha256}],
            recorded_at=now,
            actor=actor,
            event_id_factory=lambda item, _: f"lifecycle:{event_type}:{candidate.receipt_id}",
        )
        transaction.commit()
    return locked


def audit_lock_and_finish(
    root: Path,
    path: Path,
    candidate_file: Path,
    *,
    trigger_entry_id: str,
    actor: str,
    score: str,
    source: str,
    key_events: str | None,
) -> MatchDocument:
    if not re.fullmatch(r"\d+-\d+", score) or not source.strip():
        raise ServiceError("审计补锁前必须提供唯一全场比分和赛果来源")
    candidate = load_lock_candidate(candidate_file)
    document, outlook = validate_lock_candidate(root, path, candidate, require_current=False)
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if now <= document.metadata.kickoff_at:
        raise ServiceError("开赛前不得使用审计补锁")
    ledger = root / LIFECYCLE_LEDGER
    with RepositoryTransaction(root, files=[path, ledger], directories=[], operation="audit-lock-and-finish") as transaction:
        locked = lock_match(
            path,
            at=candidate.data_cutoff_at,
            market=PrimaryMarket(candidate.primary_market),
            selection=Selection(candidate.primary_selection),
            secondary=Selection(candidate.secondary_selection) if candidate.secondary_selection else None,
            confidence=candidate.confidence,
            analysis_outlook=outlook,
            require_current=False,
        )
        finished = finish_match(
            path,
            score=score,
            result_1x2=None,
            handicap_result=None,
            recorded_at=now,
            key_events=key_events,
            result_source=source,
        )
        append_payloads(
            ledger,
            [
                {"event_type": "audit_locked", "match_id": candidate.match_id, "effective_at": candidate.data_cutoff_at.isoformat(), "trigger_entry_id": trigger_entry_id, "lock_candidate_receipt_id": candidate.receipt_id, "prematch_lock_sha256": locked.metadata.prematch_lock_sha256},
                {"event_type": "result_recorded", "match_id": candidate.match_id, "trigger_entry_id": trigger_entry_id, "score": score, "source": source},
            ],
            recorded_at=now,
            actor=actor,
            event_id_factory=lambda item, index: f"lifecycle:{item['event_type']}:{candidate.receipt_id}:{index}",
        )
        transaction.commit()
    return finished


def append_lifecycle_event(
    root: Path,
    *,
    event_type: str,
    match_id: str,
    recorded_at: datetime,
    actor: str,
    payload: dict,
    event_suffix: str,
) -> None:
    ledger = root / LIFECYCLE_LEDGER
    append_payloads(
        ledger,
        [{"event_type": event_type, "match_id": match_id, **payload}],
        recorded_at=recorded_at,
        actor=actor,
        event_id_factory=lambda item, _: f"lifecycle:{event_type}:{event_suffix}",
    )


def finish_locked_with_event(
    root: Path,
    path: Path,
    *,
    trigger_entry_id: str,
    actor: str,
    score: str,
    source: str,
    key_events: str | None,
) -> MatchDocument:
    document = MatchDocument.load(path)
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    ledger = root / LIFECYCLE_LEDGER
    with RepositoryTransaction(root, files=[path, ledger], directories=[], operation="finish-from-review") as transaction:
        finished = finish_match(
            path,
            score=score,
            result_1x2=None,
            handicap_result=None,
            recorded_at=now,
            key_events=key_events,
            result_source=source,
        )
        append_lifecycle_event(
            root,
            event_type="result_recorded",
            match_id=document.metadata.match_id,
            recorded_at=now,
            actor=actor,
            payload={"trigger_entry_id": trigger_entry_id, "score": score, "source": source},
            event_suffix=trigger_entry_id,
        )
        transaction.commit()
    return finished


def validate_lifecycle(root: Path) -> dict[Path, list[str]]:
    ledger = root / LIFECYCLE_LEDGER
    errors: list[str] = []
    try:
        events = read_ledger(ledger)
        for event in events:
            payload = event.payload
            if payload.get("event_type") == "lock_candidate_prepared":
                path = root / str(payload.get("receipt_path", ""))
                if not path.is_file():
                    errors.append(f"锁定候选回执缺失：{path}")
                    continue
                receipt = load_lock_candidate(path)
                if receipt.receipt_sha256 != payload.get("receipt_sha256"):
                    errors.append(f"锁定候选事件哈希不一致：{receipt.receipt_id}")
    except Exception as exc:
        errors.append(str(exc))
    return {ledger: errors}
