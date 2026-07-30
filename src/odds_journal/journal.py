from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .aliases import AliasStore
from .ledger import atomic_write_text
from .cases import (
    CASE_SECTIONS,
    CaseMaterialStage,
    LegacyCase,
    _case_relative_path,
    _merged_evidence_refs,
    _render_stage,
    _revision_relative_path,
    case_events,
    case_from_payload,
    import_legacy_case,
    latest_cases,
    rebuild_cases,
    validate_cases,
    write_case_directory,
    write_revision_manifest,
)
from .ledger import ZERO_HASH, append_payloads, read_ledger
from .markdown import MatchDocument
from .models import HandicapResult, MarketSnapshot, MatchStatus, Result1X2
from .paths import match_files
from .services import create_match, finish_match, set_market_snapshots
from .transaction import RepositoryTransaction


JOURNAL_LEDGER = Path("knowledge/evidence/match-journal-events.jsonl")
MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENTS = 20
RESERVED_MARKER_RE = re.compile(
    r"<!--\s*(?:section|rules-retrieval|scenario-instances|case-retrieval|"
    r"analysis-content|review-content|journal-entry):[^>]*-->",
    re.IGNORECASE,
)
SCORE_RE = re.compile(r"^(\d+)-(\d+)$")


class JournalError(ValueError):
    pass


class SegmentType(StrEnum):
    PREMATCH_FACTS = "prematch_facts"
    MARKET_DATA = "market_data"
    PREMATCH_ANALYSIS = "prematch_analysis"
    PREMATCH_CONCLUSION = "prematch_conclusion"
    LIVE_UPDATE = "live_update"
    RESULT = "result"
    POSTMATCH_REVIEW = "postmatch_review"
    CORRECTION = "correction"
    UNCLASSIFIED = "unclassified"


class CaptureMode(StrEnum):
    CANONICAL_CHAT_TEXT = "canonical_chat_text"
    UPLOADED_FILE = "uploaded_file"


class UserIntent(StrEnum):
    STORE_ONLY = "store_only"
    STORE_AND_ALIGN = "store_and_align"
    REQUEST_ANALYSIS = "request_analysis"


class JournalOperation(StrEnum):
    NEW = "new"
    APPEND = "append"
    REVIEW = "review"


class FixtureCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competition_code: str | None = None
    competition: str | None = None
    home_team_id: str | None = None
    home_team: str | None = None
    away_team_id: str | None = None
    away_team: str | None = None
    kickoff_at: datetime | None = None
    timezone: str = "Asia/Shanghai"
    fixture_fingerprint: str | None = None
    match_id: str | None = None
    case_id: str | None = None

    @field_validator("kickoff_at")
    @classmethod
    def kickoff_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("kickoff_at 必须包含时区")
        return value


class JournalSegmentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    segment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    segment_type: SegmentType
    source_line_start: int = Field(ge=1)
    source_line_end: int = Field(ge=1)
    observed_at: datetime | None = None
    data_cutoff_at: datetime | None = None
    classification_confidence: float = Field(ge=0, le=1)
    ambiguity_flags: list[str] = Field(default_factory=list)
    normalized_markdown: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_at", "data_cutoff_at")
    @classmethod
    def timestamp_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("segment 时间必须包含时区")
        return value

    @model_validator(mode="after")
    def line_range_valid(self) -> "JournalSegmentV1":
        if self.source_line_end < self.source_line_start:
            raise ValueError("segment 行号范围无效")
        return self


class JournalAttachmentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    attachment_id: str
    original_filename: str
    stored_filename: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0, le=MAX_ATTACHMENT_BYTES)
    mime_type: str
    received_at: datetime
    raw_ocr_text: str | None = None
    visually_verified: bool = False
    evidence_id: str | None = None
    binding_id: str | None = None

    @field_validator("received_at")
    @classmethod
    def received_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def evidence_pair(self) -> "JournalAttachmentV1":
        if bool(self.evidence_id) != bool(self.binding_id):
            raise ValueError("evidence_id 与 binding_id 必须同时填写")
        return self


class JournalIngestRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    capture_mode: CaptureMode
    source_encoding: str | None = None
    received_at: datetime
    actor: str = Field(min_length=1)
    user_intent: UserIntent
    target_match_id: str | None = None
    fixture_candidate: FixtureCandidate | None = None
    classification_confidence: float = Field(ge=0, le=1)
    ambiguity_flags: list[str] = Field(default_factory=list)
    segments: list[JournalSegmentV1] = Field(min_length=1)

    @field_validator("received_at")
    @classmethod
    def request_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def request_consistent(self) -> "JournalIngestRequestV1":
        ids = [item.segment_id for item in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("segment_id 不得重复")
        ordered = sorted(self.segments, key=lambda item: (item.source_line_start, item.source_line_end))
        for previous, current in zip(ordered, ordered[1:]):
            if current.source_line_start <= previous.source_line_end:
                raise ValueError("segment 行号范围不得重叠")
        if self.source_encoding and self.capture_mode != CaptureMode.UPLOADED_FILE:
            raise ValueError("source_encoding 仅适用于 uploaded_file")
        return self


class JournalAlignmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str
    project_aligned_markdown: str = Field(min_length=1)
    applied_rule_ids: list[str] = Field(default_factory=list)
    excluded_rule_ids: list[str] = Field(default_factory=list)
    exclusion_reasons: dict[str, str] = Field(default_factory=dict)


class JournalAlignmentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    entry_id: str
    match_id: str
    aligned_at: datetime
    ruleset_id: str
    ruleset_version: str
    items: list[JournalAlignmentItem] = Field(min_length=1)

    @field_validator("aligned_at")
    @classmethod
    def aligned_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("aligned_at 必须包含时区")
        return value


class JournalEntryRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    entry_id: str
    deduplication_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    archive_status: Literal["archived"] = "archived"
    application_status: Literal["applied", "pending_alignment", "pending_in_target", "blocked", "not_applicable"]
    capture_mode: CaptureMode
    received_at: datetime
    actor: str
    source_path: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_path: str
    normalized_path: str
    attachments_path: str
    target_type: Literal["match", "legacy_case", "inbox"]
    target_id: str | None = None
    segment_statuses: dict[str, str]
    next_actions: list[str] = Field(default_factory=list)
    generated_prediction: Literal[False] = False


class JournalOperationResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_operation: JournalOperation
    effective_operation: JournalOperation
    entry: JournalEntryRecordV1
    created_target: bool = False
    created_alias_ids: list[str] = Field(default_factory=list)


def _safe_relative_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise JournalError(f"路径必须是项目内相对路径：{value}")
    return path


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_chat_bytes(value: bytes) -> bytes:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JournalError("canonical_chat_text 必须是 UTF-8") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def _source_bytes(path: Path, request: JournalIngestRequestV1) -> tuple[bytes, str]:
    if not path.is_file():
        raise JournalError(f"源文件不存在：{path}")
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise JournalError("源文本超过 5 MiB")
    if request.capture_mode == CaptureMode.CANONICAL_CHAT_TEXT:
        return canonical_chat_bytes(raw), "utf-8"
    encoding = request.source_encoding or "utf-8"
    try:
        raw.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise JournalError("上传文本无法按声明编码解码") from exc
    return raw, encoding


def escape_reserved_markers(value: str) -> str:
    return RESERVED_MARKER_RE.sub(lambda match: match.group(0).replace("<!--", "&lt;!--"), value)


def _normalized_text(source: bytes, encoding: str, request: JournalIngestRequestV1) -> str:
    text = source.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines()
    blocks: list[str] = []
    for segment in request.segments:
        supplied = segment.normalized_markdown.strip()
        if not supplied:
            supplied = "\n".join(lines[segment.source_line_start - 1 : segment.source_line_end]).strip()
        blocks.append(
            f"<!-- journal-segment:{segment.segment_id}:start -->\n"
            f"{supplied}\n"
            f"<!-- journal-segment:{segment.segment_id}:end -->"
        )
    return "\n\n".join(blocks).rstrip() + "\n"


def _match_by_id(root: Path, match_id: str) -> tuple[Path, MatchDocument] | None:
    found = []
    for path in match_files(root):
        document = MatchDocument.load(path)
        if document.metadata.match_id == match_id:
            found.append((path, document))
    if len(found) > 1:
        raise JournalError(f"match_id 存在多个文件：{match_id}")
    return found[0] if found else None


def _fixture_matches(document: MatchDocument, fixture: FixtureCandidate) -> bool:
    metadata = document.metadata
    return all(
        value is None or current == value
        for value, current in (
            (fixture.competition_code, metadata.competition_code),
            (fixture.home_team_id, metadata.home_team_id),
            (fixture.away_team_id, metadata.away_team_id),
            (fixture.kickoff_at, metadata.kickoff_at),
        )
    )


def _route(root: Path, request: JournalIngestRequestV1) -> tuple[str, str | None, Path | None]:
    if request.ambiguity_flags or any(item.ambiguity_flags for item in request.segments):
        return "inbox", None, None
    requested_id = request.target_match_id or (
        request.fixture_candidate.match_id if request.fixture_candidate else None
    )
    if requested_id:
        match = _match_by_id(root, requested_id)
        if match:
            return "match", requested_id, match[0]
    fixture = request.fixture_candidate
    if fixture:
        identifiable = bool(
            fixture.home_team_id and fixture.away_team_id and fixture.kickoff_at
        )
        matches = [
            (path, document)
            for path in match_files(root)
            if identifiable and _fixture_matches(document := MatchDocument.load(path), fixture)
        ]
        if len(matches) == 1:
            return "match", matches[0][1].metadata.match_id, matches[0][0]
        if len(matches) > 1:
            return "inbox", None, None
        cases = latest_cases(root)
        if fixture.case_id and fixture.case_id in cases:
            return "legacy_case", fixture.case_id, None
        candidates = [
            case.case_id
            for case in cases.values()
            if identifiable and all(
                value is None or current == value
                for value, current in (
                    (fixture.competition_code, case.competition_code),
                    (fixture.home_team_id, case.home_team_id),
                    (fixture.away_team_id, case.away_team_id),
                    (fixture.kickoff_at, case.kickoff_at),
                )
            )
        ]
        if len(candidates) == 1:
            return "legacy_case", candidates[0], None
    return "inbox", None, None


def _ensure_provisional_fixture(
    root: Path, request: JournalIngestRequestV1
) -> tuple[JournalIngestRequestV1, list[str]]:
    """Resolve explicit names or register a provisional local identity for a new fixture."""
    fixture = request.fixture_candidate
    if fixture is None:
        raise JournalError("新增比赛需要 fixture_candidate")
    aliases = AliasStore(root)
    created: list[str] = []
    values = fixture.model_dump()
    for id_key, name_key, kind, finder, exists, adder in (
        ("home_team_id", "home_team", "team", aliases.find_team_id, aliases.has_team, aliases.add_team),
        ("away_team_id", "away_team", "team", aliases.find_team_id, aliases.has_team, aliases.add_team),
        ("competition_code", "competition", "competition", aliases.find_competition_code, aliases.has_competition, aliases.add_competition),
    ):
        supplied_id = values.get(id_key)
        name = values.get(name_key)
        if supplied_id and exists(str(supplied_id)):
            continue
        if not name:
            raise JournalError(f"新增比赛缺少 {name_key}")
        resolved = finder(str(name))
        if resolved:
            values[id_key] = resolved
            continue
        provisional = AliasStore.provisional_id(kind, str(name))
        if not exists(provisional):
            adder(provisional, str(name), [])
            created.append(provisional)
        values[id_key] = provisional
    return request.model_copy(update={"fixture_candidate": FixtureCandidate.model_validate(values)}), created


def operate_journal(
    root: Path,
    *,
    operation: JournalOperation,
    source_file: Path,
    request: JournalIngestRequestV1,
    attachments: list[Path] | None = None,
) -> JournalOperationResultV1:
    """High-level new/append/review entrypoint used by desktop-agent Skills."""
    root = root.resolve()
    created_alias_ids: list[str] = []
    effective = operation
    alias_backups: dict[Path, bytes] = {}

    def restore_aliases() -> None:
        for path, original in alias_backups.items():
            atomic_write_text(path, original.decode("utf-8"))

    if operation == JournalOperation.NEW:
        aliases = AliasStore(root)
        alias_backups = {
            aliases.team_path: aliases.team_path.read_bytes(),
            aliases.competition_path: aliases.competition_path.read_bytes(),
        }
        try:
            request, created_alias_ids = _ensure_provisional_fixture(root, request)
        except Exception:
            restore_aliases()
            raise
        target_type, _, _ = _route(root, request)
        if target_type != "inbox":
            effective = JournalOperation.APPEND
    elif operation in {JournalOperation.APPEND, JournalOperation.REVIEW}:
        target_type, _, _ = _route(root, request)
        if target_type == "inbox":
            record = ingest_journal(root, source_file=source_file, request=request, attachments=attachments)
            return JournalOperationResultV1(
                requested_operation=operation, effective_operation=operation, entry=record,
                created_alias_ids=created_alias_ids,
            )

    before = _route(root, request)[0]
    try:
        record = ingest_journal(
            root,
            source_file=source_file,
            request=request,
            attachments=attachments,
            auto_apply=True,
            allow_create_match=effective == JournalOperation.NEW,
        )
    except Exception:
        restore_aliases()
        raise
    return JournalOperationResultV1(
        requested_operation=operation,
        effective_operation=effective,
        entry=record,
        created_target=before == "inbox" and record.target_type in {"match", "legacy_case"},
        created_alias_ids=created_alias_ids,
    )


def _dedupe_key(target_type: str, target_id: str | None, source_sha256: str, segments: list[JournalSegmentV1]) -> str:
    identity = target_id or target_type
    ranges = [[item.source_line_start, item.source_line_end] for item in segments]
    raw = json.dumps([identity, source_sha256, ranges], separators=(",", ":"), ensure_ascii=False)
    return _sha256_bytes(raw.encode("utf-8"))


def _event_payloads(root: Path) -> list[dict[str, Any]]:
    path = root / JOURNAL_LEDGER
    return [event.payload for event in read_ledger(path)] if path.exists() else []


def _existing_entry(root: Path, deduplication_key: str) -> JournalEntryRecordV1 | None:
    archived = [
        item for item in _event_payloads(root)
        if item.get("event_type") == "archived" and item.get("deduplication_key") == deduplication_key
    ]
    if not archived:
        return None
    return load_entry(root, str(archived[-1]["entry_id"]))


def _archive_directory(root: Path, request: JournalIngestRequestV1, entry_id: str, target_type: str, target_id: str | None) -> Path:
    stamp = request.received_at.astimezone(ZoneInfo("Asia/Shanghai"))
    leaf = f"{stamp:%Y%m%dT%H%M%S}_{entry_id}"
    if target_type == "match" and target_id:
        return root / "raw" / "matches" / target_id / "journal" / f"{stamp:%Y}" / f"{stamp:%m}" / leaf
    return root / "raw" / "journal-inbox" / f"{stamp:%Y}" / f"{stamp:%m}" / leaf


def _dump_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")


def _attachment_records(paths: list[Path], destination: Path, received_at: datetime) -> list[JournalAttachmentV1]:
    if len(paths) > MAX_ATTACHMENTS:
        raise JournalError("单次附件超过 20 个")
    records: list[JournalAttachmentV1] = []
    seen_names: set[str] = set()
    for index, source in enumerate(paths, start=1):
        if not source.is_file():
            raise JournalError(f"附件不存在：{source}")
        size = source.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise JournalError(f"附件超过 25 MiB：{source.name}")
        safe_name = re.sub(r"[^\w. -]", "_", source.name, flags=re.UNICODE).strip(". ") or f"attachment-{index}"
        if safe_name in seen_names:
            safe_name = f"{index}-{safe_name}"
        seen_names.add(safe_name)
        target = destination / "attachments" / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        records.append(JournalAttachmentV1(
            attachment_id=f"attachment-{index}",
            original_filename=source.name,
            stored_filename=f"attachments/{safe_name}",
            sha256=_sha256_bytes(source.read_bytes()),
            size=size,
            mime_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
            received_at=received_at,
        ))
    return records


def _entry_directory_from_payload(root: Path, payload: dict[str, Any]) -> Path:
    return (root / _safe_relative_path(str(payload["archive_directory"]))).resolve()


def load_entry(root: Path, entry_id: str) -> JournalEntryRecordV1:
    payloads = [item for item in _event_payloads(root) if item.get("entry_id") == entry_id]
    archived = next((item for item in payloads if item.get("event_type") == "archived"), None)
    if archived is None:
        raise JournalError(f"journal entry 不存在：{entry_id}")
    receipt = _entry_directory_from_payload(root, archived) / "receipt.yml"
    return JournalEntryRecordV1.model_validate(yaml.safe_load(receipt.read_text(encoding="utf-8")))


def _event_id(prefix: str, entry_id: str, index: int = 0) -> str:
    suffix = f":{index}" if index else ""
    return f"journal:{prefix}:{entry_id}{suffix}"


def ingest_journal(
    root: Path,
    *,
    source_file: Path,
    request: JournalIngestRequestV1,
    attachments: list[Path] | None = None,
    auto_apply: bool = False,
    allow_create_match: bool = False,
) -> JournalEntryRecordV1:
    root = root.resolve()
    processing_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    source, encoding = _source_bytes(source_file, request)
    source_text = source.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
    line_count = max(1, len(source_text.splitlines()))
    for segment in request.segments:
        if segment.source_line_end > line_count:
            raise JournalError(
                f"{segment.segment_id} 行号超出源文本范围：{segment.source_line_end}>{line_count}"
            )
    source_sha256 = _sha256_bytes(source)
    target_type, target_id, target_path = _route(root, request)
    dedupe = _dedupe_key(target_type, target_id, source_sha256, request.segments)
    existing = _existing_entry(root, dedupe)
    if existing:
        return existing

    entry_id = f"journal-{request.received_at:%Y%m%d%H%M%S}-{uuid4().hex[:10]}"
    archive = _archive_directory(root, request, entry_id, target_type, target_id)
    normalized = _normalized_text(source, encoding, request)
    high_confidence = (
        request.classification_confidence >= 0.90
        and all(item.classification_confidence >= 0.90 for item in request.segments)
        and not request.ambiguity_flags
        and all(not item.ambiguity_flags for item in request.segments)
    )
    initial_status = "not_applicable" if request.user_intent == UserIntent.STORE_ONLY else "pending_alignment"
    statuses = {item.segment_id: "archived" for item in request.segments}
    next_actions = [] if initial_status == "not_applicable" else ["检查比赛绑定并应用允许的 segment"]
    record = JournalEntryRecordV1(
        entry_id=entry_id,
        deduplication_key=dedupe,
        application_status=initial_status,
        capture_mode=request.capture_mode,
        received_at=request.received_at,
        actor=request.actor,
        source_path=(archive / "source.md").relative_to(root).as_posix(),
        source_sha256=source_sha256,
        request_path=(archive / "request.yml").relative_to(root).as_posix(),
        normalized_path=(archive / "normalized.md").relative_to(root).as_posix(),
        attachments_path=(archive / "attachments.yml").relative_to(root).as_posix(),
        target_type=target_type,
        target_id=target_id,
        segment_statuses=statuses,
        next_actions=next_actions,
    )
    ledger = root / JOURNAL_LEDGER
    with RepositoryTransaction(root, files=[ledger], directories=[archive], operation="journal-archive") as transaction:
        archive.mkdir(parents=True, exist_ok=False)
        (archive / "source.md").write_bytes(source)
        (archive / "normalized.md").write_text(normalized, encoding="utf-8", newline="\n")
        _dump_yaml(archive / "request.yml", request)
        attachment_records = _attachment_records(attachments or [], archive, request.received_at)
        _dump_yaml(archive / "attachments.yml", {"schema_version": 1, "attachments": [item.model_dump(mode="json") for item in attachment_records]})
        _dump_yaml(archive / "receipt.yml", record)
        archive_payload = {
            "event_type": "archived",
            "entry_id": entry_id,
            "deduplication_key": dedupe,
            "archive_directory": archive.relative_to(root).as_posix(),
            "source_sha256": source_sha256,
            "target_type": target_type,
            "target_id": target_id,
        }
        append_payloads(
            ledger, [archive_payload], recorded_at=processing_at, actor=request.actor,
            event_id_factory=lambda _item, index: _event_id("archived", entry_id, index),
        )
        transaction.commit()

    if auto_apply:
        if not high_confidence:
            return _update_application(root, entry_id, "pending_alignment", statuses, ["分类置信度不足或存在歧义"])
        created_target = False
        if target_type == "inbox" and allow_create_match:
            try:
                target_type, target_id, target_path = _create_target(
                    root, request, entry_id, recorded_at=processing_at
                )
                created_target = True
            except Exception as exc:
                return _update_application(
                    root, entry_id, "blocked", statuses, [str(exc)], event_type="blocked"
                )
        if created_target and target_type == "legacy_case":
            created_statuses = {
                item.segment_id: "applied"
                if item.segment_type not in {SegmentType.CORRECTION, SegmentType.UNCLASSIFIED}
                else "pending_alignment"
                for item in request.segments
            }
            pending = any(value == "pending_alignment" for value in created_statuses.values())
            return _update_application(
                root, entry_id, "pending_alignment" if pending else "applied",
                created_statuses,
                ["纠错或未分类材料仍需人工处理"] if pending else [],
                target_type="legacy_case", target_id=target_id, event_type="applied",
            )
        if target_type in {"match", "legacy_case"}:
            return apply_journal(root, entry_id=entry_id, match_path=target_path, target_case_id=target_id if target_type == "legacy_case" else None)
    return load_entry(root, entry_id)


def _complete_fixture(fixture: FixtureCandidate | None) -> bool:
    return bool(fixture and all((
        fixture.competition_code, fixture.competition, fixture.home_team_id, fixture.home_team,
        fixture.away_team_id, fixture.away_team, fixture.kickoff_at,
    )))


def _ended_bundle(request: JournalIngestRequestV1) -> bool:
    kinds = {SegmentType(item.segment_type) for item in request.segments}
    return bool({SegmentType.PREMATCH_ANALYSIS, SegmentType.RESULT, SegmentType.POSTMATCH_REVIEW} <= kinds)


def _create_target(
    root: Path,
    request: JournalIngestRequestV1,
    entry_id: str,
    *,
    recorded_at: datetime,
) -> tuple[str, str, Path | None]:
    fixture = request.fixture_candidate
    if not _complete_fixture(fixture):
        raise JournalError("自动建档要求完整赛事身份、标准 ID 和带时区开赛时间")
    assert fixture and fixture.kickoff_at
    now = recorded_at
    if fixture.kickoff_at >= now:
        with RepositoryTransaction(
            root,
            files=[],
            directories=[root / "matches", root / "assets/matches", root / "raw/matches"],
            operation="journal-create-match",
        ) as transaction:
            path = create_match(
                root, kickoff=fixture.kickoff_at, timezone=fixture.timezone,
                competition_code=str(fixture.competition_code), competition=str(fixture.competition),
                home_team_id=str(fixture.home_team_id), home_team=str(fixture.home_team),
                away_team_id=str(fixture.away_team_id), away_team=str(fixture.away_team),
                match_id=fixture.match_id, schema_version=2,
            )
            transaction.commit()
        return "match", MatchDocument.load(path).metadata.match_id, path
    if not _ended_bundle(request):
        case_id = fixture.case_id or f"legacy-{fixture.kickoff_at:%Y%m%d}-{fixture.home_team_id}-{fixture.away_team_id}"
        source_path = load_entry(root, entry_id).source_path
        stage_map = {
            SegmentType.PREMATCH_FACTS: "prematch_early",
            SegmentType.MARKET_DATA: "prematch_late",
            SegmentType.PREMATCH_ANALYSIS: "prematch_late",
            SegmentType.PREMATCH_CONCLUSION: "prematch_late",
            SegmentType.LIVE_UPDATE: "live",
            SegmentType.RESULT: "result_source",
            SegmentType.POSTMATCH_REVIEW: "postmatch_review",
        }
        sections = {name: "未提供。" for name in CASE_SECTIONS}
        stages = []
        for item in request.segments:
            kind = SegmentType(item.segment_type)
            if kind not in stage_map:
                continue
            content = item.normalized_markdown.strip() or "\n".join(
                f"- {key}: {value}" for key, value in item.payload.items()
            ) or "未提供正文。"
            stages.append({
                "material_id": f"{entry_id}-{item.segment_id}",
                "material_stage": stage_map[kind],
                "observed_at": item.observed_at,
                "observed_at_note": None if item.observed_at else "用户未提供可证实观察时间",
                "received_at": recorded_at,
                "source_path": source_path,
                "conflicts": item.ambiguity_flags,
                "content": escape_reserved_markers(content),
            })
        payload = {
            "schema_version": 3, "case_id": case_id, "case_revision": 1,
            "title": f"{fixture.home_team} vs {fixture.away_team}",
            "display_file_label": f"{fixture.kickoff_at:%Y-%m-%d}_{fixture.competition}_{fixture.home_team}_vs_{fixture.away_team}",
            "competition_code": fixture.competition_code, "home_team_id": fixture.home_team_id,
            "away_team_id": fixture.away_team_id, "kickoff_at": fixture.kickoff_at,
            "fixture_date": fixture.kickoff_at.date(),
            "fixture_fingerprint": fixture.fixture_fingerprint or f"{fixture.kickoff_at.isoformat()}|{fixture.competition_code}|{fixture.home_team_id}|{fixture.away_team_id}",
            "source_archived_at": recorded_at, "revision_effective_at": recorded_at,
            "chronology": "unknown", "completeness": "partial", "statistics_eligible": False,
            "result_known": False,
            "prematch_analysis_present": any(item.segment_type == SegmentType.PREMATCH_ANALYSIS for item in request.segments),
            "source_review_present": any(item.segment_type == SegmentType.POSTMATCH_REVIEW for item in request.segments),
            "external_result_present": False, "material_stages": stages,
            "status": "draft", "sections": sections,
        }
        case = case_from_payload(payload)
        path = import_legacy_case(root, case, actor=request.actor)
        return "legacy_case", case_id, path
    case_id = fixture.case_id or f"legacy-{fixture.kickoff_at:%Y%m%d}-{fixture.home_team_id}-{fixture.away_team_id}"
    segments = {SegmentType(item.segment_type): item for item in request.segments}
    result = segments[SegmentType.RESULT].payload
    score = str(result.get("score", ""))
    matched = SCORE_RE.fullmatch(score)
    if not matched or not result.get("source"):
        raise JournalError("LegacyCase V3 自动导入要求比分和赛果来源")
    sections = {name: "未提供。" for name in CASE_SECTIONS}
    sections["facts"] = next((item.normalized_markdown for item in request.segments if item.segment_type == SegmentType.PREMATCH_FACTS), "未单独提供赛前事实。")
    sections["market-timeline"] = next((item.normalized_markdown for item in request.segments if item.segment_type == SegmentType.MARKET_DATA), "未提供结构化盘口时间线。")
    sections["source-prematch"] = segments[SegmentType.PREMATCH_ANALYSIS].normalized_markdown
    sections["result"] = f"- 最终比分：{score}\n- 来源：{result['source']}"
    sections["source-review"] = segments[SegmentType.POSTMATCH_REVIEW].normalized_markdown
    source_path = load_entry(root, entry_id).source_path
    stage_map = {
        SegmentType.PREMATCH_FACTS: "prematch_early",
        SegmentType.MARKET_DATA: "prematch_late",
        SegmentType.PREMATCH_ANALYSIS: "prematch_late",
        SegmentType.PREMATCH_CONCLUSION: "prematch_late",
        SegmentType.LIVE_UPDATE: "live",
        SegmentType.RESULT: "result_source",
        SegmentType.POSTMATCH_REVIEW: "postmatch_review",
    }
    material_stages = [
        {
            "material_id": f"{entry_id}-{item.segment_id}",
            "material_stage": stage_map[SegmentType(item.segment_type)],
            "observed_at": item.observed_at,
            "observed_at_note": None if item.observed_at else "用户未提供可证实观察时间",
            "received_at": recorded_at,
            "source_path": source_path,
            "conflicts": item.ambiguity_flags,
            "content": escape_reserved_markers(
                item.normalized_markdown.strip()
                or "\n".join(f"- {key}: {value}" for key, value in item.payload.items())
            ),
        }
        for item in request.segments
        if SegmentType(item.segment_type) in stage_map
    ]
    payload = {
        "schema_version": 3, "case_id": case_id, "case_revision": 1,
        "title": f"{fixture.home_team} vs {fixture.away_team}",
        "display_file_label": f"{fixture.kickoff_at:%Y-%m-%d}_{fixture.competition}_{fixture.home_team}_vs_{fixture.away_team}",
        "competition_code": fixture.competition_code, "home_team_id": fixture.home_team_id,
        "away_team_id": fixture.away_team_id, "kickoff_at": fixture.kickoff_at,
        "fixture_date": fixture.kickoff_at.date(),
        "fixture_fingerprint": fixture.fixture_fingerprint or f"{fixture.kickoff_at.isoformat()}|{fixture.competition_code}|{fixture.home_team_id}|{fixture.away_team_id}",
        "source_archived_at": recorded_at, "revision_effective_at": recorded_at,
        "chronology": "mixed", "completeness": "complete", "statistics_eligible": False,
        "result_known": True, "prematch_analysis_present": True, "source_review_present": True,
        "external_result_present": False,
        "result_record": {
            "source_kind": "source_material", "home_goals": int(matched.group(1)),
            "away_goals": int(matched.group(2)), "recorded_at": recorded_at,
        },
        "material_stages": material_stages,
        "status": "draft", "sections": sections,
    }
    case = case_from_payload(payload)
    path = import_legacy_case(root, case, actor=request.actor)
    return "legacy_case", case_id, path


def _projection_block(entry: JournalEntryRecordV1, segment: JournalSegmentV1, content: str) -> str:
    observed = segment.observed_at.isoformat() if segment.observed_at else "未提供"
    cutoff = segment.data_cutoff_at.isoformat() if segment.data_cutoff_at else "未提供"
    return (
        f"<!-- journal-entry:{entry.entry_id}:{segment.segment_id}:start -->\n"
        f"### 用户材料｜{segment.segment_type}\n\n"
        f"- entry/segment：`{entry.entry_id}` / `{segment.segment_id}`\n"
        f"- 接收时间：{entry.received_at.isoformat()}\n"
        f"- 观察时间：{observed}\n"
        f"- 数据截止时间：{cutoff}\n"
        f"- 原文：`{entry.source_path}`\n"
        f"- SHA-256：`{entry.source_sha256}`\n\n"
        f"{escape_reserved_markers(content).strip()}\n"
        f"<!-- journal-entry:{entry.entry_id}:{segment.segment_id}:end -->"
    )


def _append_section(document: MatchDocument, name: str, block: str) -> None:
    if f"<!-- journal-entry:{block.split(':', 2)[1]}" in document.sections[name]:
        return
    document.replace_section(name, document.sections[name].rstrip() + "\n\n" + block + "\n")


def _append_pending_material(
    document: MatchDocument,
    entry: JournalEntryRecordV1,
    segment: JournalSegmentV1,
    reason: str,
) -> None:
    """Keep accepted same-fixture material in the Match without changing formal state."""
    marker = f"<!-- journal-entry:{entry.entry_id}:{segment.segment_id}:start -->"
    section = document.sections["postmatch-review"]
    if marker in section:
        return
    block = _projection_block(entry, segment, segment.normalized_markdown)
    label = (
        "<!-- journal-materials:start -->\n## 七、用户材料归档\n\n"
        "仅保存尚未进入正式事实、赛果或复盘流程的同场材料；该区不改变锁定赛前内容。\n"
        "<!-- journal-materials:end -->"
    )
    if "<!-- journal-materials:start -->" not in section:
        section = section.rstrip() + "\n\n" + label
    annotated = block.replace(
        f"### 用户材料｜{segment.segment_type}",
        f"### 用户材料｜{segment.segment_type}｜待应用\n\n- 原因：{reason}",
        1,
    )
    document.replace_section("postmatch-review", section.rstrip() + "\n\n" + annotated + "\n")


def _pending_in_target(
    document: MatchDocument,
    entry: JournalEntryRecordV1,
    segment: JournalSegmentV1,
    statuses: dict[str, str],
    actions: list[str],
    reason: str,
) -> None:
    _append_pending_material(document, entry, segment, reason)
    statuses[segment.segment_id] = "pending_in_target"
    actions.append(reason)


def _alignment_map(alignment: JournalAlignmentV1 | None) -> dict[str, JournalAlignmentItem]:
    return {item.segment_id: item for item in alignment.items} if alignment else {}


def _apply_match(
    root: Path,
    path: Path,
    entry: JournalEntryRecordV1,
    request: JournalIngestRequestV1,
    selected: set[str] | None,
    alignment: JournalAlignmentV1 | None,
) -> JournalEntryRecordV1:
    document = MatchDocument.load(path)
    status = MatchStatus(document.metadata.status)
    statuses: dict[str, str] = dict(entry.segment_statuses)
    next_actions: list[str] = []
    alignments = _alignment_map(alignment)
    selected_segments = [item for item in request.segments if selected is None or item.segment_id in selected]
    archived = next(
        item for item in _event_payloads(root)
        if item.get("entry_id") == entry.entry_id and item.get("event_type") == "archived"
    )
    receipt = _entry_directory_from_payload(root, archived) / "receipt.yml"
    ledger = root / JOURNAL_LEDGER
    files = [path, ledger, receipt]
    with RepositoryTransaction(root, files=files, directories=[], operation="journal-apply-match") as transaction:
        for segment in selected_segments:
            kind = SegmentType(segment.segment_type)
            content = segment.normalized_markdown
            if kind == SegmentType.PREMATCH_FACTS:
                if status not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
                    _pending_in_target(document, entry, segment, statuses, next_actions, "赛前事实只能正式应用到 draft/tracking")
                    continue
                from .analysis_context import analysis_is_placeholder, parse_receipt

                if parse_receipt(document.sections["prematch-reasoning"]) or not analysis_is_placeholder(
                    document.sections["prematch-reasoning"]
                ):
                    _pending_in_target(document, entry, segment, statuses, next_actions, "已有规则回执或实质分析；修改赛前事实前必须 analysis restart")
                    continue
                _append_section(document, "prematch-facts", _projection_block(entry, segment, content))
                statuses[segment.segment_id] = "applied"
            elif kind == SegmentType.MARKET_DATA:
                if status not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
                    _pending_in_target(document, entry, segment, statuses, next_actions, "盘口快照只能正式应用到 draft/tracking")
                    continue
                from .analysis_context import analysis_is_placeholder, parse_receipt

                if parse_receipt(document.sections["prematch-reasoning"]) or not analysis_is_placeholder(
                    document.sections["prematch-reasoning"]
                ):
                    _pending_in_target(document, entry, segment, statuses, next_actions, "已有规则回执或实质分析；修改盘口快照前必须 analysis restart")
                    continue
                snapshots = [MarketSnapshot.model_validate(item) for item in segment.payload.get("market_snapshots", [])]
                if not snapshots:
                    _pending_in_target(document, entry, segment, statuses, next_actions, f"{segment.segment_id} 缺少完整 MarketSnapshot，仅保留原文")
                    continue
                merged = {item.snapshot_id: item for item in document.metadata.market_snapshots}
                merged.update({item.snapshot_id: item for item in snapshots})
                document.metadata.market_snapshots = list(merged.values())
                _append_section(document, "prematch-facts", _projection_block(entry, segment, content))
                statuses[segment.segment_id] = "applied"
            elif kind in {SegmentType.PREMATCH_ANALYSIS, SegmentType.PREMATCH_CONCLUSION}:
                aligned = alignments.get(segment.segment_id)
                if aligned is None:
                    _pending_in_target(document, entry, segment, statuses, next_actions, "先完成 agent start、场景登记和案例检索，再提供 alignment-file")
                    continue
                from .analysis_context import parse_receipt
                from .case_retrieval import parse_case_receipt
                from .scenarios import parse_scenarios

                reasoning = document.sections["prematch-reasoning"]
                if not parse_receipt(reasoning) or not parse_case_receipt(reasoning, required=True):
                    _pending_in_target(document, entry, segment, statuses, next_actions, "规则或案例检索回执缺失")
                    continue
                parse_scenarios(reasoning, required=True)
                combined = (
                    "#### 用户原始分析\n\n" + escape_reserved_markers(content).strip()
                    + "\n\n#### 项目规则对齐分析\n\n" + escape_reserved_markers(aligned.project_aligned_markdown).strip()
                    + "\n\n> analysis-trace 仅表示本项目对齐过程，不表示原作者使用过这些规则。"
                )
                section = "prematch-reasoning" if kind == SegmentType.PREMATCH_ANALYSIS else "prematch-locked"
                _append_section(document, section, _projection_block(entry, segment, combined))
                statuses[segment.segment_id] = "applied"
            elif kind == SegmentType.LIVE_UPDATE:
                if status != MatchStatus.LOCKED:
                    _pending_in_target(document, entry, segment, statuses, next_actions, "临场更新仅在 locked 状态自动追加")
                    continue
                _append_section(document, "live-update", _projection_block(entry, segment, content))
                statuses[segment.segment_id] = "applied"
            elif kind == SegmentType.RESULT:
                if status != MatchStatus.LOCKED:
                    _pending_in_target(document, entry, segment, statuses, next_actions, "赛果仅能通过 locked -> finish 生命周期写入")
                    continue
                payload = segment.payload
                if not payload.get("score") or not payload.get("source"):
                    _pending_in_target(document, entry, segment, statuses, next_actions, "赛果缺少比分或来源")
                    continue
                document.save()
                result_1x2 = None
                handicap_result = None
                if document.metadata.schema_version == 1:
                    if not payload.get("result_1x2"):
                        statuses[segment.segment_id] = "pending_alignment"
                        next_actions.append("Match V1 赛果还需 result_1x2")
                        continue
                    result_1x2 = Result1X2(str(payload["result_1x2"]))
                    if payload.get("handicap_result"):
                        handicap_result = HandicapResult(str(payload["handicap_result"]))
                finish_match(
                    path, score=str(payload["score"]), result_1x2=result_1x2,
                    handicap_result=handicap_result,
                    recorded_at=datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0),
                    key_events=payload.get("key_events"), result_source=str(payload["source"]),
                )
                document = MatchDocument.load(path)
                status = MatchStatus.FINISHED
                statuses[segment.segment_id] = "applied"
            elif kind == SegmentType.POSTMATCH_REVIEW:
                if status == MatchStatus.FINISHED:
                    _append_pending_material(document, entry, segment, "复盘原文已保存；先执行 prepare-review，再补齐评价与场景解析")
                    statuses[segment.segment_id] = "pending_in_target"
                    next_actions.append("先执行 prepare-review；补齐评价与场景解析后执行 review")
                else:
                    _pending_in_target(document, entry, segment, statuses, next_actions, "赛后复盘需在 finished 后执行 prepare-review 并补齐评价与场景解析")
            elif kind == SegmentType.CORRECTION:
                _pending_in_target(document, entry, segment, statuses, next_actions, "纠错已归档，需按比赛状态人工 supersede/restart")
            else:
                statuses[segment.segment_id] = "not_applicable"
        document.save()
        next_actions = list(dict.fromkeys(next_actions))
        applied = any(value == "applied" for value in statuses.values())
        pending = any(value in {"pending_alignment", "pending_in_target", "blocked"} for value in statuses.values())
        application_status = (
            "pending_in_target" if any(value == "pending_in_target" for value in statuses.values()) else "pending_alignment" if pending else "applied" if applied else "not_applicable"
        )
        updated, payload, event_type, event_id, recorded_at = _application_update_parts(
            root,
            entry,
            application_status,
            statuses,
            next_actions,
            target_type="match",
            target_id=document.metadata.match_id,
            event_type="applied" if applied else "pending",
        )
        _write_application_update(
            ledger, receipt, updated, payload, event_type, event_id, recorded_at
        )
        transaction.commit()
    return updated


def _application_update_parts(
    root: Path,
    current: JournalEntryRecordV1,
    application_status: str,
    statuses: dict[str, str],
    next_actions: list[str],
    *,
    target_type: str | None,
    target_id: str | None,
    event_type: str,
) -> tuple[JournalEntryRecordV1, dict[str, Any], str, str, datetime]:
    updated = current.model_copy(update={
        "application_status": application_status,
        "segment_statuses": statuses,
        "next_actions": next_actions,
        "target_type": target_type or current.target_type,
        "target_id": target_id if target_id is not None else current.target_id,
    })
    ledger = root / JOURNAL_LEDGER
    payloads = _event_payloads(root)
    existing_count = sum(
        1 for item in payloads
        if item.get("entry_id") == current.entry_id and item.get("event_type") == event_type
    )
    payload = {
        "event_type": event_type,
        "entry_id": current.entry_id,
        "target_type": updated.target_type,
        "target_id": updated.target_id,
        "application_status": application_status,
        "segment_statuses": statuses,
        "next_actions": next_actions,
    }
    events = read_ledger(ledger)
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    recorded_at = max(now, events[-1].recorded_at) if events else now
    event_id = _event_id(event_type, current.entry_id, existing_count + 1)
    return updated, payload, event_type, event_id, recorded_at


def _write_application_update(
    ledger: Path,
    receipt: Path,
    updated: JournalEntryRecordV1,
    payload: dict[str, Any],
    event_type: str,
    event_id: str,
    recorded_at: datetime,
) -> None:
    _dump_yaml(receipt, updated)
    append_payloads(
        ledger,
        [payload],
        recorded_at=recorded_at,
        actor=updated.actor,
        event_id_factory=lambda _item, _index: event_id,
    )


def _update_application(
    root: Path,
    entry_id: str,
    application_status: str,
    statuses: dict[str, str],
    next_actions: list[str],
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    event_type: str = "pending",
) -> JournalEntryRecordV1:
    current = load_entry(root, entry_id)
    archived = next(item for item in _event_payloads(root) if item.get("entry_id") == entry_id and item.get("event_type") == "archived")
    directory = _entry_directory_from_payload(root, archived)
    ledger = root / JOURNAL_LEDGER
    receipt = directory / "receipt.yml"
    updated, payload, event_type, event_id, recorded_at = _application_update_parts(
        root,
        current,
        application_status,
        statuses,
        next_actions,
        target_type=target_type,
        target_id=target_id,
        event_type=event_type,
    )
    with RepositoryTransaction(root, files=[ledger, receipt], directories=[], operation="journal-update") as transaction:
        _write_application_update(
            ledger, receipt, updated, payload, event_type, event_id, recorded_at
        )
        transaction.commit()
    return updated


def _apply_legacy_case(
    root: Path,
    *,
    case_id: str,
    entry: JournalEntryRecordV1,
    request: JournalIngestRequestV1,
    selected: set[str] | None,
) -> JournalEntryRecordV1:
    case = latest_cases(root).get(case_id)
    if case is None:
        raise JournalError(f"历史案例不存在：{case_id}")
    stage_map = {
        SegmentType.PREMATCH_FACTS: "prematch_early",
        SegmentType.MARKET_DATA: "prematch_late",
        SegmentType.PREMATCH_ANALYSIS: "prematch_late",
        SegmentType.PREMATCH_CONCLUSION: "prematch_late",
        SegmentType.LIVE_UPDATE: "live",
        SegmentType.RESULT: "result_source",
        SegmentType.POSTMATCH_REVIEW: "postmatch_review",
    }
    statuses = dict(entry.segment_statuses)
    actions: list[str] = []
    stages: list[CaseMaterialStage] = []
    case_ledger = root / "knowledge/extraction/doubao-2026-07-28/case-events.jsonl"
    existing_case_events = read_ledger(case_ledger)
    case_recorded_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    if existing_case_events:
        case_recorded_at = max(case_recorded_at, existing_case_events[-1].recorded_at)
    for item in request.segments:
        if selected is not None and item.segment_id not in selected:
            continue
        kind = SegmentType(item.segment_type)
        if kind not in stage_map:
            statuses[item.segment_id] = "pending_alignment"
            actions.append(f"{item.segment_id} 需要人工确定纠错或未分类材料的落点")
            continue
        content = item.normalized_markdown.strip()
        if kind == SegmentType.RESULT and item.payload:
            content = content or "\n".join(f"- {key}: {value}" for key, value in item.payload.items())
        stages.append(CaseMaterialStage(
            material_id=f"{entry.entry_id}-{item.segment_id}",
            material_stage=stage_map[kind],
            received_at=case_recorded_at,
            observed_at=item.observed_at,
            observed_at_note=None if item.observed_at else "用户未提供可证实观察时间",
            source_path=entry.source_path,
            content=escape_reserved_markers(content),
            conflicts=item.ambiguity_flags,
        ))
        statuses[item.segment_id] = "applied"

    payload = case.model_dump(mode="json")
    if stages:
        sections = dict(payload["sections"])
        for stage in stages:
            section = {
                "prematch_early": "source-prematch",
                "prematch_late": "source-prematch",
                "live": "source-live",
                "result_source": "result",
                "postmatch_review": "source-review",
            }[stage.material_stage]
            sections[section] = f"{sections[section].rstrip()}\n\n---\n\n{_render_stage(stage)}"
        payload.update({
            "case_revision": case.case_revision + 1,
            "revision_effective_at": case_recorded_at.isoformat(),
            "sections": sections,
            "material_stages": [
                *payload["material_stages"],
                *(stage.model_dump(mode="json") for stage in stages),
            ],
            "prematch_analysis_present": case.prematch_analysis_present
            or any(stage.material_stage.startswith("prematch") for stage in stages),
            "source_review_present": case.source_review_present
            or any(stage.material_stage == "postmatch_review" for stage in stages),
            "evidence_refs": _merged_evidence_refs(
                case.evidence_refs,
                [reference for stage in stages for reference in stage.evidence_refs],
            ),
        })
    candidate = case_from_payload(payload)
    payload = candidate.model_dump(mode="json")
    applied = bool(stages)
    pending = any(value in {"pending_alignment", "blocked"} for value in statuses.values())
    application_status = "pending_alignment" if pending else "applied" if applied else "not_applicable"
    updated, journal_payload, event_type, event_id, journal_recorded_at = _application_update_parts(
        root,
        entry,
        application_status,
        statuses,
        actions,
        target_type="legacy_case",
        target_id=case_id,
        event_type="applied" if applied else "pending",
    )
    archived = next(
        item for item in _event_payloads(root)
        if item.get("entry_id") == entry.entry_id and item.get("event_type") == "archived"
    )
    receipt = _entry_directory_from_payload(root, archived) / "receipt.yml"
    journal_ledger = root / JOURNAL_LEDGER
    files = [journal_ledger, receipt]
    if stages:
        latest_event = next(
            event for event in reversed(case_events(root)) if event.payload.get("case_id") == case_id
        )
        payload["_supersedes_event_id"] = latest_event.event_id
        files.extend([
            case_ledger,
            root / _case_relative_path(case),
            root / _revision_relative_path(candidate),
            root / "knowledge/cases/legacy/README.md",
            root / "knowledge/cases/legacy/REVISION_MANIFEST.yml",
        ])
    with RepositoryTransaction(
        root,
        files=files,
        directories=[root / "knowledge/cases/legacy/_revisions"] if stages else [],
        operation="journal-apply-legacy-case",
    ) as transaction:
        if stages:
            append_payloads(
                case_ledger,
                [payload],
                recorded_at=case_recorded_at,
                actor=request.actor,
                event_id_factory=lambda item, _: (
                    f"case:journal:{item['case_id']}:{item['case_revision']}"
                ),
            )
            rebuild_cases(root)
            write_case_directory(root)
            write_revision_manifest(root)
            errors = [error for values in validate_cases(root).values() for error in values]
            if errors:
                raise JournalError("案例 journal 应用校验失败：" + "；".join(errors[:10]))
        _write_application_update(
            journal_ledger,
            receipt,
            updated,
            journal_payload,
            event_type,
            event_id,
            journal_recorded_at,
        )
        transaction.commit()
    return updated


def apply_journal(
    root: Path,
    *,
    entry_id: str,
    match_path: Path | None = None,
    target_case_id: str | None = None,
    segment_ids: list[str] | None = None,
    alignment: JournalAlignmentV1 | None = None,
) -> JournalEntryRecordV1:
    entry = load_entry(root, entry_id)
    request = JournalIngestRequestV1.model_validate(yaml.safe_load((root / entry.request_path).read_text(encoding="utf-8")))
    selected = set(segment_ids) if segment_ids else None
    try:
        if match_path is not None:
            document = MatchDocument.load(match_path)
            if entry.target_id and document.metadata.match_id != entry.target_id:
                raise JournalError("entry 与目标比赛不匹配，请先执行 journal resolve")
            if alignment and (alignment.entry_id != entry_id or alignment.match_id != document.metadata.match_id):
                raise JournalError("alignment 与 entry 或目标比赛不匹配")
            return _apply_match(root, match_path, entry, request, selected, alignment)
        elif target_case_id:
            return _apply_legacy_case(
                root,
                case_id=target_case_id,
                entry=entry,
                request=request,
                selected=selected,
            )
        else:
            raise JournalError("必须提供 Match 路径或 LegacyCase ID")
    except Exception as exc:
        statuses = dict(entry.segment_statuses)
        return _update_application(root, entry_id, "blocked", statuses, [str(exc)], event_type="blocked")


def resolve_journal(root: Path, entry_id: str, match_path: Path) -> JournalEntryRecordV1:
    entry = load_entry(root, entry_id)
    document = MatchDocument.load(match_path)
    return _update_application(
        root, entry_id, "pending_alignment", entry.segment_statuses,
        ["绑定已确认，可执行 journal apply"], target_type="match",
        target_id=document.metadata.match_id, event_type="bound",
    )


def journal_status(root: Path, *, entry_id: str | None = None, match_path: Path | None = None) -> list[JournalEntryRecordV1]:
    ids: list[str] = []
    match_id = MatchDocument.load(match_path).metadata.match_id if match_path else None
    for payload in _event_payloads(root):
        if payload.get("event_type") != "archived":
            continue
        if entry_id and payload.get("entry_id") != entry_id:
            continue
        ids.append(str(payload["entry_id"]))
    records = [load_entry(root, item) for item in ids]
    return [item for item in records if not match_id or item.target_id == match_id]


def validate_journal(root: Path) -> dict[Path, list[str]]:
    ledger = root / JOURNAL_LEDGER
    errors: list[str] = []
    try:
        events = read_ledger(ledger)
    except Exception as exc:
        return {ledger: [str(exc)]}
    archived_ids: set[str] = set()
    for event in events:
        payload = event.payload
        entry_id = str(payload.get("entry_id", ""))
        if payload.get("event_type") == "archived":
            archived_ids.add(entry_id)
            try:
                directory = _entry_directory_from_payload(root, payload)
                record = load_entry(root, entry_id)
                source = root / record.source_path
                if not source.is_file() or _sha256_bytes(source.read_bytes()) != record.source_sha256:
                    errors.append(f"{entry_id} 原文缺失或哈希变化")
                for relative in (record.request_path, record.normalized_path, record.attachments_path):
                    if not (root / _safe_relative_path(relative)).is_file():
                        errors.append(f"{entry_id} 归档文件缺失：{relative}")
                attachment_manifest = yaml.safe_load(
                    (root / record.attachments_path).read_text(encoding="utf-8")
                ) or {}
                for raw_attachment in attachment_manifest.get("attachments", []):
                    attachment = JournalAttachmentV1.model_validate(raw_attachment)
                    attachment_path = directory / _safe_relative_path(attachment.stored_filename)
                    if not attachment_path.is_file():
                        errors.append(f"{entry_id} 附件缺失：{attachment.stored_filename}")
                    elif _sha256_bytes(attachment_path.read_bytes()) != attachment.sha256:
                        errors.append(f"{entry_id} 附件哈希变化：{attachment.stored_filename}")
                if directory != (root / Path(record.source_path).parent).resolve():
                    errors.append(f"{entry_id} archive_directory 与 receipt 不一致")
            except Exception as exc:
                errors.append(f"{entry_id}：{exc}")
        elif entry_id not in archived_ids:
            errors.append(f"{event.event_id} 引用尚未归档的 entry")
    return {ledger: errors}


def journal_json(record: JournalEntryRecordV1) -> str:
    return json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2)
