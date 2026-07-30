from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .analysis_context import analysis_is_placeholder, parse_receipt, validate_analysis_receipt
from .cases import case_events, historical_case, load_case, revision_relative_path
from .indexing import SearchResult, build_index, search_index
from .ledger import atomic_write_text, canonical_json
from .markdown import MatchDocument
from .models import MatchStatus
from .paths import match_files
from .rules import sha256_file
from .scenarios import parse_scenarios, scenario_hash


CASE_RECEIPT_START = "<!-- case-retrieval:start -->"
CASE_RECEIPT_END = "<!-- case-retrieval:end -->"
CASE_RECEIPT_RE = re.compile(
    rf"{re.escape(CASE_RECEIPT_START)}\s*### 历史案例检索回执\s*```yaml\s*(.*?)\s*```\s*{re.escape(CASE_RECEIPT_END)}",
    re.DOTALL,
)
RANKING_ALGORITHM = "metadata-bm25-v1"


class SelectedCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    case_revision: int = Field(ge=1)
    artifact_type: Literal["legacy_case", "match"]
    source_path: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_event_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    chronology: str
    completeness: str
    statistics_eligible: bool
    scenario_type_ids: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)


class CaseRetrievalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    prepared_at: datetime
    as_of: datetime
    scenario_instances_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    query: dict[str, Any]
    filters: dict[str, Any]
    ranking_algorithm: Literal["metadata-bm25-v1"] = RANKING_ALGORITHM
    eligible_corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_cases: list[SelectedCase]
    excluded_summary: dict[str, int]
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at", "as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("案例检索回执时间必须包含时区")
        return value


def _digest_data(receipt: CaseRetrievalReceipt | dict[str, Any]) -> dict[str, Any]:
    if isinstance(receipt, CaseRetrievalReceipt):
        data = receipt.model_dump(mode="json")
    else:
        data = json.loads(json.dumps(receipt, ensure_ascii=False, default=str))
    data.pop("prepared_at", None)
    data.pop("context_sha256", None)
    return data


def case_context_sha256(receipt: CaseRetrievalReceipt | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_digest_data(receipt)).encode("utf-8")).hexdigest()


def parse_case_receipt(reasoning: str, *, required: bool = False) -> CaseRetrievalReceipt | None:
    starts = reasoning.count(CASE_RECEIPT_START)
    ends = reasoning.count(CASE_RECEIPT_END)
    if starts == 0 and ends == 0:
        if required:
            raise ValueError("赛前推演缺少历史案例检索回执")
        return None
    if starts != 1 or ends != 1:
        raise ValueError("历史案例检索回执标记必须各出现一次")
    match = CASE_RECEIPT_RE.search(reasoning)
    if not match:
        raise ValueError("历史案例检索回执格式无效")
    return CaseRetrievalReceipt.model_validate(yaml.safe_load(match.group(1)) or {})


def _render_receipt(receipt: CaseRetrievalReceipt) -> str:
    body = yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False).rstrip()
    return (
        f"{CASE_RECEIPT_START}\n### 历史案例检索回执\n\n"
        f"```yaml\n{body}\n```\n{CASE_RECEIPT_END}"
    )


def set_case_receipt(reasoning: str, receipt: CaseRetrievalReceipt) -> str:
    rendered = _render_receipt(receipt)
    current = parse_case_receipt(reasoning)
    if current is not None:
        return CASE_RECEIPT_RE.sub(lambda _: rendered, reasoning, count=1)
    from .analysis_context import ANALYSIS_START

    position = reasoning.find(ANALYSIS_START)
    if position < 0:
        raise ValueError("赛前推演缺少 analysis-content 标记")
    return f"{reasoning[:position].rstrip()}\n\n{rendered}\n\n{reasoning[position:]}"


def _eligible_artifacts(root: Path, as_of: datetime, exclude_match_id: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    legacy_root = root / "knowledge/cases/legacy"
    event_hashes = {str(event.payload.get("case_id")): event.event_sha256 for event in case_events(root)}
    for path in sorted(legacy_root.glob("**/*.md")) if legacy_root.exists() else []:
        if "_revisions" in path.parts or path.name == "README.md":
            continue
        case = load_case(path)
        if case.source_effective_at > as_of:
            continue
        revision = root / revision_relative_path(case.case_id, case.case_revision)
        version_path = revision if revision.exists() else path
        relative = version_path.relative_to(root).as_posix()
        output[f"legacy_case:{case.case_id}:{case.case_revision}"] = {
            "case_id": case.case_id,
            "case_revision": case.case_revision,
            "artifact_type": "legacy_case",
            "source_path": relative,
            "content_sha256": sha256_file(version_path),
            "case_event_sha256": event_hashes.get(case.case_id),
            "chronology": case.chronology,
            "completeness": case.completeness,
            "statistics_eligible": case.statistics_eligible,
            "scenario_type_ids": sorted(case.scenario_instance_ids),
        }
    for path in match_files(root):
        document = MatchDocument.load(path)
        if document.metadata.match_id == exclude_match_id:
            continue
        if MatchStatus(document.metadata.status) != MatchStatus.REVIEWED:
            continue
        if not document.metadata.reviewed_at or document.metadata.reviewed_at > as_of:
            continue
        relative = path.relative_to(root).as_posix()
        output[f"match:{document.metadata.match_id}:1"] = {
            "case_id": document.metadata.match_id,
            "case_revision": 1,
            "artifact_type": "match",
            "source_path": relative,
        "content_sha256": sha256_file(path),
            "case_event_sha256": None,
            "chronology": "prematch_verified",
            "completeness": str(document.metadata.record_integrity),
            "statistics_eligible": True,
            "scenario_type_ids": [],
        }
    return output


def eligible_corpus_fingerprint(artifacts: dict[str, dict[str, Any]]) -> str:
    rows = [
        f"{identity}|{record['source_path']}|{record['content_sha256']}"
        for identity, record in sorted(artifacts.items())
    ]
    return hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def _query(document: MatchDocument, scenario_terms: list[str]) -> str:
    return " ".join(
        " ".join(
            [
                document.metadata.competition,
                document.metadata.home_team,
                document.metadata.away_team,
                *document.metadata.tags,
                *scenario_terms,
            ]
        ).split()
    )


def _rank_cases(
    root: Path,
    document: MatchDocument,
    *,
    query: str,
    as_of: datetime,
    artifacts: dict[str, dict[str, Any]],
    limit: int,
) -> list[SelectedCase]:
    if not artifacts:
        return []
    results: list[SearchResult] = []
    for artifact_type in ("legacy_case", "match"):
        results.extend(
            search_index(
                root,
                query,
                as_of=as_of,
                exclude_match_id=document.metadata.match_id,
                artifact_type=artifact_type,
                limit=100,
            )
        )
    reliability_order = {"established": 0, "supported": 1, "experimental": 2}
    results.sort(key=lambda item: (reliability_order.get(item.reliability, 3), item.score, item.chunk_id))
    grouped: dict[str, list[SearchResult]] = {}
    for result in results:
        case_id = result.case_id or result.match_id
        revision = result.case_revision or 1
        identity = f"{result.artifact_type}:{case_id}:{revision}"
        if identity in artifacts:
            grouped.setdefault(identity, []).append(result)
    selected: list[SelectedCase] = []
    for identity, chunks in grouped.items():
        record = artifacts[identity]
        selected.append(
            SelectedCase(
                **record,
                chunk_ids=list(dict.fromkeys(item.chunk_id for item in chunks)),
            )
        )
        if len(selected) >= limit:
            break
    return selected


def _build_receipt(
    root: Path,
    document: MatchDocument,
    *,
    prepared_at: datetime,
    as_of: datetime,
    query: str,
    limit: int,
) -> CaseRetrievalReceipt:
    scenarios = parse_scenarios(document.sections["prematch-reasoning"], required=True)
    assert scenarios is not None
    artifacts = _eligible_artifacts(root, as_of, document.metadata.match_id)
    selected = _rank_cases(
        root, document, query=query, as_of=as_of, artifacts=artifacts, limit=limit
    )
    selected_ids = {f"{item.artifact_type}:{item.case_id}:{item.case_revision}" for item in selected}
    data = {
        "schema_version": 1,
        "match_id": document.metadata.match_id,
        "prepared_at": prepared_at,
        "as_of": as_of,
        "scenario_instances_sha256": scenario_hash(scenarios),
        "query": {"terms": query},
        "filters": {
            "artifact_types": ["legacy_case", "match"],
            "historical_match_status": "reviewed",
            "exclude_match_id": document.metadata.match_id,
            "as_of": as_of.isoformat(),
            "limit": limit,
        },
        "ranking_algorithm": RANKING_ALGORITHM,
        "eligible_corpus_fingerprint": eligible_corpus_fingerprint(artifacts),
        "selected_cases": selected,
        "excluded_summary": {
            "eligible_artifacts": len(artifacts),
            "not_selected": len(set(artifacts) - selected_ids),
        },
        "context_sha256": "0" * 64,
    }
    draft = CaseRetrievalReceipt.model_validate(data)
    return draft.model_copy(update={"context_sha256": case_context_sha256(draft)})


def retrieve_cases(
    root: Path,
    path: Path,
    *,
    prepared_at: datetime,
    limit: int = 10,
) -> tuple[Path, dict[str, Any], CaseRetrievalReceipt]:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ValueError("只有 draft/tracking 比赛可以检索赛前案例")
    if not analysis_is_placeholder(document.sections["prematch-reasoning"]):
        raise ValueError("案例检索必须在撰写实质分析之前完成")
    rules = parse_receipt(document.sections["prematch-reasoning"])
    if rules is None or rules.schema_version != 2:
        raise ValueError("案例检索要求 v2 规则回执")
    rule_errors = validate_analysis_receipt(root, document, require_current=True)
    if rule_errors:
        raise ValueError("；".join(rule_errors))
    scenarios = parse_scenarios(document.sections["prematch-reasoning"], required=True)
    assert scenarios is not None
    scenario_terms: list[str] = []
    for item in scenarios.instances:
        scenario_terms.extend([item.scenario_type_id, *item.observed_facts])
    if not scenario_terms:
        scenario_terms.append(scenarios.no_scenario_reason or "无明确场景")
    query = _query(document, scenario_terms)
    build_index(root)
    receipt = _build_receipt(
        root,
        document,
        prepared_at=prepared_at,
        as_of=rules.as_of,
        query=query,
        limit=limit,
    )
    payload = receipt.model_dump(mode="json")
    payload["selected_case_contents"] = [
        {
            **item.model_dump(mode="json"),
            "content": (root / item.source_path).read_text(encoding="utf-8"),
        }
        for item in receipt.selected_cases
    ]
    context_path = root / "data/case-context" / f"{document.metadata.match_id}.json"
    atomic_write_text(context_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    document.replace_section(
        "prematch-reasoning",
        set_case_receipt(document.sections["prematch-reasoning"], receipt),
    )
    document.save()
    return context_path, payload, receipt


def validate_case_receipt(
    root: Path,
    document: MatchDocument,
    *,
    require_current: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        rules = parse_receipt(document.sections["prematch-reasoning"])
        if rules is None or rules.schema_version != 2:
            return []
        receipt = parse_case_receipt(document.sections["prematch-reasoning"], required=True)
        scenarios = parse_scenarios(document.sections["prematch-reasoning"], required=True)
        assert receipt is not None and scenarios is not None
        if receipt.match_id != document.metadata.match_id:
            errors.append("案例回执 match_id 与比赛不一致")
        if receipt.as_of != rules.as_of:
            errors.append("案例回执与规则回执的 as_of 不一致")
        if receipt.scenario_instances_sha256 != scenario_hash(scenarios):
            errors.append("场景实例已变化，需要重新检索案例")
        if receipt.context_sha256 != case_context_sha256(receipt):
            errors.append("案例检索上下文哈希无效")
        for item in receipt.selected_cases:
            path = root / item.source_path
            resolved = path
            if not path.exists() or sha256_file(path) != item.content_sha256:
                if item.artifact_type == "legacy_case":
                    resolved = historical_case(root, item.case_id, item.case_revision, item.content_sha256)
                if resolved is None:
                    errors.append(f"案例回执内容哈希不一致：{item.case_id}")
                    continue
            if item.artifact_type == "legacy_case":
                case = load_case(resolved)
                if (case.case_id, case.case_revision) != (item.case_id, item.case_revision):
                    errors.append(f"案例版本不一致：{item.case_id}")
        if require_current:
            current_artifacts = _eligible_artifacts(
                root, receipt.as_of, document.metadata.match_id
            )
            current_fingerprint = eligible_corpus_fingerprint(current_artifacts)
            if receipt.eligible_corpus_fingerprint != current_fingerprint:
                errors.append("合格案例语料已变化，需要重新检索")
    except Exception as exc:
        errors.append(str(exc))
    return errors
