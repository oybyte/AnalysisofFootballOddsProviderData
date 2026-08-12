"""Study 台账适配器。

实现统一 KnowledgeStudyLedgerEventV1 的追加式 JSONL 台账：
- 幂等：相同 idempotency_key + 相同 payload 返回既有 event
- 冲突拒绝：相同 key、不同内容拒绝；event_id 重复且内容不同拒绝
- JSONL 损坏 fail closed：任一行不可解析、哈希错误或 supersedes 链断裂时报错
- 状态重建：当前 Study、Primary、Outcome 状态仅从 ledger 重建
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..domain.studies import (
    KnowledgeStudyLedgerEventV1,
    StudyEventType,
    StudyState,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _payload_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _event_sha256(event_data: dict[str, Any]) -> str:
    data = json.loads(json.dumps(event_data, ensure_ascii=False, default=str))
    data.pop("event_sha256", None)
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


class LedgerCorruptionError(Exception):
    """台账损坏错误，fail closed。"""


class IdempotencyConflictError(Exception):
    """幂等键冲突：相同 key、不同内容。"""


class StudyLedger:
    """Study 台账适配器。

    台账目录固定为 knowledge/knowledge-studies/，包含：
    study-events.jsonl / primary-claim-events.jsonl / exposure-events.jsonl
    outcome-events.jsonl / failure-events.jsonl / ai-advisory-events.jsonl
    """

    LEDGER_FILES = {
        StudyEventType.STUDY_REGISTERED: "study-events.jsonl",
        StudyEventType.PRIMARY_CLAIMED: "primary-claim-events.jsonl",
        StudyEventType.EXPOSED: "exposure-events.jsonl",
        StudyEventType.OUTCOME_RECORDED: "outcome-events.jsonl",
        StudyEventType.FAILURE_RECORDED: "failure-events.jsonl",
        StudyEventType.AI_ADVISORY_RECORDED: "ai-advisory-events.jsonl",
    }

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._studies_dir = self._root / "knowledge" / "knowledge-studies"

    @property
    def studies_dir(self) -> Path:
        return self._studies_dir

    def _ledger_path(self, event_type: StudyEventType) -> Path:
        filename = self.LEDGER_FILES[event_type]
        return self._studies_dir / filename

    def _parse_line(self, line: str, file_path: Path, line_no: int) -> dict[str, Any]:
        line = line.strip()
        if not line:
            raise LedgerCorruptionError(f"{file_path}:{line_no}: 空行")
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerCorruptionError(f"{file_path}:{line_no}: JSON 不可解析：{exc}") from exc
        if not isinstance(data, dict):
            raise LedgerCorruptionError(f"{file_path}:{line_no}: 非对象行")
        return data

    def _read_ledger(self, path: Path) -> list[KnowledgeStudyLedgerEventV1]:
        if not path.is_file():
            return []
        events: list[KnowledgeStudyLedgerEventV1] = []
        for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            data = self._parse_line(raw_line, path, line_no)
            # 哈希校验
            expected_sha = data.get("event_sha256")
            if not isinstance(expected_sha, str) or len(expected_sha) != 64:
                raise LedgerCorruptionError(f"{path}:{line_no}: event_sha256 缺失或格式错误")
            recomputed = _event_sha256(data)
            if recomputed != expected_sha:
                raise LedgerCorruptionError(f"{path}:{line_no}: event_sha256 不匹配")
            # payload 哈希校验
            payload = data.get("payload", {})
            expected_payload_sha = data.get("payload_sha256")
            if not isinstance(expected_payload_sha, str) or len(expected_payload_sha) != 64:
                raise LedgerCorruptionError(f"{path}:{line_no}: payload_sha256 缺失或格式错误")
            if _payload_sha256(payload) != expected_payload_sha:
                raise LedgerCorruptionError(f"{path}:{line_no}: payload_sha256 不匹配")
            try:
                events.append(KnowledgeStudyLedgerEventV1.model_validate(data))
            except Exception as exc:
                raise LedgerCorruptionError(f"{path}:{line_no}: 事件校验失败：{exc}") from exc
        return events

    def _read_all_events(self) -> list[KnowledgeStudyLedgerEventV1]:
        events: list[KnowledgeStudyLedgerEventV1] = []
        for event_type in self.LEDGER_FILES:
            path = self._ledger_path(event_type)
            events.extend(self._read_ledger(path))
        events.sort(key=lambda e: e.recorded_at)
        return events

    def append(
        self,
        event_type: StudyEventType,
        event_id: str,
        aggregate_id: str,
        idempotency_key: str,
        recorded_at: Any,
        payload: dict[str, Any],
        supersedes_event_id: str | None = None,
    ) -> KnowledgeStudyLedgerEventV1:
        """追加事件到台账。

        幂等：相同 idempotency_key + 相同 payload 返回既有 event。
        冲突：相同 key、不同内容拒绝；event_id 重复且内容不同拒绝。
        """
        path = self._ledger_path(event_type)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 检查幂等
        existing_events = self._read_ledger(path)
        for existing in existing_events:
            if existing.idempotency_key == idempotency_key:
                if existing.payload_sha256 != _payload_sha256(payload):
                    raise IdempotencyConflictError(
                        f"幂等键冲突：{idempotency_key} 已存在不同内容"
                    )
                return existing
            if existing.event_id == event_id and existing.event_sha256 != _event_sha256(
                {
                    "schema_version": 1,
                    "event_id": event_id,
                    "event_type": event_type.value,
                    "aggregate_id": aggregate_id,
                    "idempotency_key": idempotency_key,
                    "recorded_at": recorded_at.isoformat() if hasattr(recorded_at, "isoformat") else recorded_at,
                    "payload": payload,
                    "payload_sha256": _payload_sha256(payload),
                    "supersedes_event_id": supersedes_event_id,
                }
            ):
                raise IdempotencyConflictError(
                    f"event_id 冲突：{event_id} 已存在不同内容"
                )

        # supersedes 链校验
        if supersedes_event_id is not None:
            all_events = self._read_all_events()
            if not any(e.event_id == supersedes_event_id for e in all_events):
                raise LedgerCorruptionError(
                    f"supersedes 链断裂：{supersedes_event_id} 不存在"
                )

        event_data = {
            "schema_version": 1,
            "event_id": event_id,
            "event_type": event_type.value,
            "aggregate_id": aggregate_id,
            "idempotency_key": idempotency_key,
            "recorded_at": recorded_at.isoformat() if hasattr(recorded_at, "isoformat") else str(recorded_at),
            "payload": payload,
            "payload_sha256": _payload_sha256(payload),
            "supersedes_event_id": supersedes_event_id,
            "event_sha256": "0" * 64,
        }
        event_data["event_sha256"] = _event_sha256(event_data)
        event = KnowledgeStudyLedgerEventV1.model_validate(event_data)
        # 直接追加 JSONL（不使用 append_payloads，因为本台账使用独立事件格式）
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
        return event

    def rebuild_study_state(self, study_id: str) -> dict[str, Any]:
        """从台账重建 Study 状态。

        当前 Study、Primary、Outcome 状态仅从 ledger 重建，不依赖目录扫描。
        """
        events = self._read_all_events()
        study_events = [e for e in events if e.aggregate_id.startswith(study_id) or e.payload.get("study_id") == study_id]

        if not study_events:
            return {"study_id": study_id, "state": StudyState.REGISTERED.value, "exists": False}

        state = StudyState.REGISTERED
        primary_claims: dict[str, dict[str, Any]] = {}
        exposures: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        ai_advisories: list[dict[str, Any]] = []
        study_registered = False

        # 追踪被 supersede 的 outcome
        superseded_outcome_ids: set[str] = set()

        for event in study_events:
            payload = event.payload
            if event.event_type == StudyEventType.STUDY_REGISTERED:
                study_registered = True
            elif event.event_type == StudyEventType.PRIMARY_CLAIMED:
                if state == StudyState.REGISTERED or state == StudyState.BASELINE_READY:
                    state = StudyState.PRIMARY_SEALED
                match_key = f"{payload.get('study_id')}:{payload.get('match_id')}:{payload.get('snapshot_sha256')}"
                primary_claims[match_key] = {**payload, "event_id": event.event_id}
            elif event.event_type == StudyEventType.EXPOSED:
                if state == StudyState.PRIMARY_SEALED:
                    state = StudyState.EXPOSED
                exposures.append({**payload, "event_id": event.event_id})
            elif event.event_type == StudyEventType.OUTCOME_RECORDED:
                if state in (StudyState.PRIMARY_SEALED, StudyState.EXPOSED, StudyState.OFFICIAL_LOCKED):
                    state = StudyState.COMPLETED
                if event.supersedes_event_id:
                    superseded_outcome_ids.add(event.supersedes_event_id)
                outcomes.append({**payload, "event_id": event.event_id})
            elif event.event_type == StudyEventType.FAILURE_RECORDED:
                failures.append({**payload, "event_id": event.event_id})
            elif event.event_type == StudyEventType.AI_ADVISORY_RECORDED:
                ai_advisories.append({**payload, "event_id": event.event_id})

        # 评估状态：有未被 supersede 的 outcome
        valid_outcomes = [o for o in outcomes if o["event_id"] not in superseded_outcome_ids]
        if valid_outcomes and state == StudyState.COMPLETED:
            state = StudyState.EVALUATED

        return {
            "study_id": study_id,
            "exists": study_registered,
            "state": state.value,
            "primary_claims": primary_claims,
            "exposures": exposures,
            "outcomes": outcomes,
            "valid_outcomes": valid_outcomes,
            "superseded_outcome_ids": sorted(superseded_outcome_ids),
            "failures": failures,
            "ai_advisories": ai_advisories,
        }

    def list_studies(self) -> list[str]:
        """列出所有已注册 Study ID。"""
        path = self._ledger_path(StudyEventType.STUDY_REGISTERED)
        events = self._read_ledger(path)
        study_ids: list[str] = []
        seen: set[str] = set()
        for event in events:
            study_id = event.payload.get("study_id")
            if study_id and study_id not in seen:
                seen.add(study_id)
                study_ids.append(study_id)
        return study_ids

    def get_primary_claims(self, study_id: str) -> list[dict[str, Any]]:
        """获取 Study 的所有 Primary Claim。"""
        path = self._ledger_path(StudyEventType.PRIMARY_CLAIMED)
        events = self._read_ledger(path)
        return [
            {**e.payload, "event_id": e.event_id}
            for e in events
            if e.payload.get("study_id") == study_id
        ]

    def get_outcomes(self, study_id: str) -> list[dict[str, Any]]:
        """获取 Study 的所有 Outcome（含被 supersede 的）。"""
        path = self._ledger_path(StudyEventType.OUTCOME_RECORDED)
        events = self._read_ledger(path)
        return [
            {**e.payload, "event_id": e.event_id, "supersedes": e.supersedes_event_id}
            for e in events
            if e.payload.get("study_id") == study_id
        ]

    def get_valid_outcomes(self, study_id: str) -> list[dict[str, Any]]:
        """获取未被 supersede 的 Outcome。"""
        outcomes = self.get_outcomes(study_id)
        # superseded 集合收集被 supersede 的 event_id（即 supersedes 字段指向的 id）
        superseded = {o["supersedes"] for o in outcomes if o.get("supersedes")}
        return [o for o in outcomes if o["event_id"] not in superseded]

    def has_primary_claim(self, study_id: str, match_id: str, snapshot_sha256: str) -> bool:
        """检查是否已存在 Primary Claim。"""
        claims = self.get_primary_claims(study_id)
        return any(
            c.get("match_id") == match_id and c.get("snapshot_sha256") == snapshot_sha256
            for c in claims
        )
