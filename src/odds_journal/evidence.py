from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .cases import latest_cases
from .ledger import append_payloads, atomic_write_text, read_ledger
from .markdown import MatchDocument
from .models import MatchStatus
from .paths import match_files
from .rules import load_ruleset


EVIDENCE_PATH = Path("knowledge/evidence/rule-evidence.jsonl")


class EvidencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    rule_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    observed_ruleset_version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    rule_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    proposal_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    case_type: Literal["match", "legacy_case"]
    case_id: str
    case_cluster_id: str
    scenario_instance_id: str | None = None
    market: Literal["one_x_two", "handicap", "total_goals", "pass"]
    target_definition: str = Field(min_length=1)
    baseline_definition: str = Field(min_length=1)
    relation: Literal["support", "counterexample", "ambiguous", "not_applicable"]
    eligibility: Literal["eligible", "ineligible"]
    ineligibility_reasons: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_payload(self) -> "EvidencePayload":
        if not self.observed_ruleset_version and not self.proposal_sha256:
            raise ValueError("证据必须引用已发布规则版本或规则提案")
        if self.observed_ruleset_version and not self.rule_content_sha256:
            raise ValueError("已发布规则证据必须记录规则内容哈希")
        if self.eligibility == "ineligible" and not self.ineligibility_reasons:
            raise ValueError("ineligible 证据必须说明原因")
        if self.eligibility == "eligible" and self.relation in {"ambiguous", "not_applicable"}:
            raise ValueError("ambiguous/not_applicable 不能计为 eligible")
        return self


def append_evidence(root: Path, payload: EvidencePayload, *, recorded_at: datetime) -> None:
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("证据记录时间必须包含时区")
    if payload.case_type == "match":
        matches = {
            MatchDocument.load(path).metadata.match_id: MatchDocument.load(path)
            for path in match_files(root)
        }
        document = matches.get(payload.case_id)
        if document is None:
            raise ValueError(f"比赛不存在：{payload.case_id}")
        if MatchStatus(document.metadata.status) != MatchStatus.REVIEWED:
            raise ValueError("正式证据只能引用 reviewed 比赛")
    else:
        case = latest_cases(root).get(payload.case_id)
        if case is None:
            raise ValueError(f"历史案例不存在：{payload.case_id}")
        if payload.eligibility == "eligible" and not case.statistics_eligible:
            raise ValueError("该历史案例不能进入合格证据分母")
    if payload.observed_ruleset_version:
        ruleset = load_ruleset(root, f"football-analysis@{payload.observed_ruleset_version}")
        document = ruleset.documents.get(payload.rule_id)
        if document is None:
            raise ValueError(f"规则不存在：{payload.rule_id}")
        if document.content_sha256 != payload.rule_content_sha256:
            raise ValueError("证据引用的规则哈希不一致")
    append_payloads(
        root / EVIDENCE_PATH,
        [payload.model_dump(mode="json")],
        recorded_at=recorded_at,
        actor=payload.reviewed_by,
        event_id_factory=lambda item, index: f"evidence:{payload.evidence_id}",
    )


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float | None:
    if total == 0:
        return None
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def _rule_document_type(root: Path, rule_id: str, items: list[EvidencePayload]) -> str | None:
    versions = [item.observed_ruleset_version for item in items if item.observed_ruleset_version]
    for version in versions:
        try:
            ruleset = load_ruleset(root, f"football-analysis@{version}")
            if rule_id in ruleset.documents:
                return ruleset.documents[rule_id].metadata.document_type
        except Exception:
            continue
    try:
        ruleset = load_ruleset(root)
        if rule_id in ruleset.documents:
            return ruleset.documents[rule_id].metadata.document_type
    except Exception:
        pass
    return None


def _pending_evidence(root: Path, active: list) -> list[dict]:
    from .scenarios import parse_resolutions

    linked: set[str] = set()
    for event in active:
        scenario_id = EvidencePayload.model_validate(event.payload).scenario_instance_id
        if scenario_id:
            linked.add(scenario_id)
    pending: list[dict] = []
    for path in match_files(root):
        document = MatchDocument.load(path)
        resolutions = parse_resolutions(document.sections["postmatch-review"])
        if not resolutions:
            continue
        for item in resolutions.resolutions:
            reason = None
            if item.evidence_disposition == "defer":
                reason = "defer"
            elif (
                item.evidence_disposition == "link_after_review"
                and MatchStatus(document.metadata.status) == MatchStatus.REVIEWED
                and item.scenario_instance_id not in linked
            ):
                reason = "awaiting_link"
            if reason:
                pending.append(
                    {
                        "match_id": document.metadata.match_id,
                        "match_status": str(document.metadata.status),
                        "scenario_instance_id": item.scenario_instance_id,
                        "evidence_disposition": item.evidence_disposition,
                        "pending_reason": reason,
                        "review_note": item.review_note,
                        "source_path": path.relative_to(root).as_posix(),
                    }
                )
    return pending


def build_evidence_report(root: Path) -> tuple[Path, Path, dict]:
    events = read_ledger(root / EVIDENCE_PATH)
    superseded = {event.supersedes_event_id for event in events if event.supersedes_event_id}
    active = [event for event in events if event.event_id not in superseded]
    grouped: dict[str, list[EvidencePayload]] = defaultdict(list)
    for event in active:
        payload = EvidencePayload.model_validate(event.payload)
        grouped[payload.rule_id].append(payload)
    rules: dict[str, dict] = {}
    for rule_id, items in sorted(grouped.items()):
        relation_counts = Counter(item.relation for item in items)
        eligible = [item for item in items if item.eligibility == "eligible"]
        clusters = {item.case_cluster_id for item in eligible}
        eligible_by_cluster: dict[str, list[EvidencePayload]] = defaultdict(list)
        for item in eligible:
            eligible_by_cluster[item.case_cluster_id].append(item)
        supporting_clusters = sum(
            any(item.relation == "support" for item in values)
            and not any(item.relation == "counterexample" for item in values)
            for values in eligible_by_cluster.values()
        )
        point_estimate = supporting_clusters / len(clusters) if clusters else None
        wilson_lower = _wilson_lower(supporting_clusters, len(clusters))
        document_type = _rule_document_type(root, rule_id, items)
        promotion_gate = None
        if document_type == "heuristic":
            promotion_gate = {
                "minimum_30_independent_cases": len(clusters) >= 30,
                "league_season_or_time_window_diversity": "manual_review_required",
                "comparison_baseline_defined": "manual_review_required",
                "point_estimate_five_points_above_baseline": "not_evaluable_without_structured_baseline",
                "wilson_95_lower_not_below_baseline": "not_evaluable_without_structured_baseline",
                "human_approval": False,
                "promotion_candidate": False,
            }
        rules[rule_id] = {
            "document_type": document_type,
            "evaluation_mode": (
                "official_definition"
                if document_type == "concept"
                else "process_execution"
                if document_type in {"method", "checklist"}
                else "predefined_outcome_vs_baseline"
                if document_type == "heuristic"
                else "unknown"
            ),
            "events": len(items),
            "relations": dict(relation_counts),
            "eligible_events": len(eligible),
            "eligible_independent_cases": len(clusters),
            "supporting_independent_cases": supporting_clusters,
            "point_estimate": point_estimate,
            "wilson_95_lower": wilson_lower,
            "deferred_or_ineligible": len(items) - len(eligible),
            "promotion_gate": promotion_gate,
        }
    pending = _pending_evidence(root, active)
    payload = {
        "schema_version": 1,
        "ledger_events": len(events),
        "active_events": len(active),
        "rules": rules,
        "pending_evidence": pending,
    }
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    json_path = reports / "规则证据报告.json"
    markdown_path = reports / "规则证据报告.md"
    atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# 规则证据报告",
        "",
        f"- 台账事件：{len(events)}",
        f"- 当前有效事件：{len(active)}",
        f"- 待处理证据：{len(pending)}",
        "",
    ]
    for rule_id, record in rules.items():
        lines.extend(
            [
                f"## {rule_id}",
                "",
                f"- 事件数：{record['events']}",
                f"- 评估方式：{record['evaluation_mode']}",
                f"- 合格独立案例：{record['eligible_independent_cases']}",
                f"- 支持独立案例：{record['supporting_independent_cases']}",
                f"- 点估计：{record['point_estimate'] if record['point_estimate'] is not None else '样本不足'}",
                f"- 95% Wilson 下界：{record['wilson_95_lower'] if record['wilson_95_lower'] is not None else '样本不足'}",
                f"- 关系分布：{record['relations']}",
                f"- 晋级门禁：{record['promotion_gate'] if record['promotion_gate'] is not None else '不适用'}",
                "",
            ]
        )
    if pending:
        lines.extend(["## 待处理证据", ""])
        for item in pending:
            lines.append(
                f"- {item['match_id']} / {item['scenario_instance_id']} / "
                f"{item['pending_reason']}：{item['review_note']}"
            )
        lines.append("")
    atomic_write_text(markdown_path, "\n".join(lines).rstrip() + "\n")
    return markdown_path, json_path, payload


def validate_evidence(root: Path) -> dict[Path, list[str]]:
    path = root / EVIDENCE_PATH
    errors: list[str] = []
    try:
        for event in read_ledger(path):
            EvidencePayload.model_validate(event.payload)
    except Exception as exc:
        errors.append(str(exc))
    return {path: errors}
