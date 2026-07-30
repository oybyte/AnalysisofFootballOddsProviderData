from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ZERO_HASH = "0" * 64
EVENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]+$")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


class LedgerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    event_id: str
    recorded_at: datetime
    actor: str = Field(min_length=1)
    previous_event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supersedes_event_id: str | None = None
    payload: dict[str, Any]
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        if not EVENT_ID_RE.fullmatch(value):
            raise ValueError("event_id 只能包含小写字母、数字和 ._:-")
        return value

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at 必须包含时区")
        return value


def event_hash_data(event: LedgerEvent | dict[str, Any]) -> dict[str, Any]:
    if isinstance(event, LedgerEvent):
        data = event.model_dump(mode="json")
    else:
        data = json.loads(json.dumps(event, ensure_ascii=False, default=str))
    data.pop("event_sha256", None)
    return data


def calculate_event_sha256(event: LedgerEvent | dict[str, Any]) -> str:
    return sha256_json(event_hash_data(event))


def read_ledger(path: Path) -> list[LedgerEvent]:
    if not path.exists():
        return []
    events: list[LedgerEvent] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            events.append(LedgerEvent.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"{path}:{line_number} 事件格式无效：{exc}") from exc
    errors = validate_ledger_events(events)
    if errors:
        raise ValueError("；".join(errors))
    return events


def validate_ledger_events(events: list[LedgerEvent]) -> list[str]:
    errors: list[str] = []
    expected_previous = ZERO_HASH
    seen: set[str] = set()
    for index, event in enumerate(events, start=1):
        if event.event_id in seen:
            errors.append(f"第 {index} 条 event_id 重复：{event.event_id}")
        if event.previous_event_sha256 != expected_previous:
            errors.append(f"第 {index} 条 previous_event_sha256 断链")
        actual = calculate_event_sha256(event)
        if event.event_sha256 != actual:
            errors.append(f"第 {index} 条 event_sha256 无效：{event.event_id}")
        if event.supersedes_event_id and event.supersedes_event_id not in seen:
            errors.append(f"第 {index} 条 supersedes_event_id 不存在或位于未来")
        seen.add(event.event_id)
        expected_previous = event.event_sha256
    return errors


def make_event(
    *,
    event_id: str,
    recorded_at: datetime,
    actor: str,
    previous_event_sha256: str,
    payload: dict[str, Any],
    supersedes_event_id: str | None = None,
) -> LedgerEvent:
    raw = {
        "schema_version": 1,
        "event_id": event_id,
        "recorded_at": recorded_at,
        "actor": actor,
        "previous_event_sha256": previous_event_sha256,
        "supersedes_event_id": supersedes_event_id,
        "payload": payload,
        "event_sha256": ZERO_HASH,
    }
    event = LedgerEvent.model_validate(raw)
    return event.model_copy(update={"event_sha256": calculate_event_sha256(event)})


def append_payloads(
    path: Path,
    payloads: list[dict[str, Any]],
    *,
    recorded_at: datetime,
    actor: str,
    event_id_factory: Callable[[dict[str, Any], int], str],
) -> list[LedgerEvent]:
    current_bytes = path.read_bytes() if path.exists() else b""
    events = read_ledger(path)
    by_id = {event.event_id: event for event in events}
    previous = events[-1].event_sha256 if events else ZERO_HASH
    created: list[LedgerEvent] = []
    for index, payload in enumerate(payloads):
        event_id = event_id_factory(payload, index)
        supersedes = payload.pop("_supersedes_event_id", None)
        existing = by_id.get(event_id)
        if existing:
            if existing.payload != payload:
                raise ValueError(f"event_id 已存在且内容不同：{event_id}")
            continue
        if events and recorded_at < events[-1].recorded_at:
            raise ValueError(f"recorded_at 早于台账最后事件：{path}")
        if supersedes and supersedes in by_id and recorded_at < by_id[supersedes].recorded_at:
            raise ValueError(f"recorded_at 早于被替代事件：{supersedes}")
        event = make_event(
            event_id=event_id,
            recorded_at=recorded_at,
            actor=actor,
            previous_event_sha256=previous,
            supersedes_event_id=supersedes,
            payload=payload,
        )
        events.append(event)
        created.append(event)
        by_id[event_id] = event
        previous = event.event_sha256
    if not created:
        return []
    if path.exists() and path.read_bytes() != current_bytes:
        raise ValueError(f"写入前台账已变化：{path}")
    text = "".join(canonical_json(event.model_dump(mode="json")) + "\n" for event in events)
    atomic_write_text(path, text)
    return created


def latest_payloads(
    events: list[LedgerEvent], key: Callable[[dict[str, Any]], str]
) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        latest[key(event.payload)] = event.payload
    return latest
