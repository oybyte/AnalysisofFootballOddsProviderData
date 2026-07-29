from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .analysis_context import ReceiptDocument, parse_receipt, validate_analysis_receipt
from .case_retrieval import parse_case_receipt, validate_case_receipt
from .indexing import build_index, document_chunks
from .ledger import atomic_write_text, canonical_json
from .markdown import MatchDocument, generic_front_matter
from .models import MatchStatus
from .rules import active_ruleset, load_ruleset, sha256_file, sha256_text
from .scenarios import parse_scenarios, scenario_hash, validate_scenario_workflow


REVIEW_RECEIPT_START = "<!-- review-retrieval:start -->"
REVIEW_RECEIPT_END = "<!-- review-retrieval:end -->"
REVIEW_CONTENT_START = "<!-- review-content:start -->"
REVIEW_CONTENT_END = "<!-- review-content:end -->"
REVIEW_RECEIPT_RE = re.compile(
    rf"{re.escape(REVIEW_RECEIPT_START)}\s*### 复盘检索回执\s*```yaml\s*(.*?)\s*```\s*{re.escape(REVIEW_RECEIPT_END)}",
    re.DOTALL,
)
REVIEW_CONTENT_RE = re.compile(
    rf"{re.escape(REVIEW_CONTENT_START)}(.*?){re.escape(REVIEW_CONTENT_END)}", re.DOTALL
)


class RulesetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ruleset_id: str
    ruleset_version: str
    ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    postmatch_only: bool
    documents: list[ReceiptDocument]


class ReviewReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    prepared_at: datetime
    prematch_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_context_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    scenario_instances_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trusted_instruction: ReceiptDocument
    locked_ruleset: RulesetSnapshot
    current_ruleset: RulesetSnapshot
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("复盘准备时间必须包含时区")
        return value


def _digest_data(receipt: ReviewReceipt | dict[str, Any]) -> dict[str, Any]:
    if isinstance(receipt, ReviewReceipt):
        data = receipt.model_dump(mode="json")
    else:
        data = json.loads(json.dumps(receipt, ensure_ascii=False, default=str))
    data.pop("prepared_at", None)
    data.pop("context_sha256", None)
    return data


def review_context_sha256(receipt: ReviewReceipt | dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_digest_data(receipt)).encode("utf-8")).hexdigest()


def parse_review_receipt(review: str, *, required: bool = False) -> ReviewReceipt | None:
    starts = review.count(REVIEW_RECEIPT_START)
    ends = review.count(REVIEW_RECEIPT_END)
    if starts == 0 and ends == 0:
        if required:
            raise ValueError("复盘章节缺少复盘检索回执")
        return None
    if starts != 1 or ends != 1:
        raise ValueError("复盘检索回执标记必须各出现一次")
    match = REVIEW_RECEIPT_RE.search(review)
    if not match:
        raise ValueError("复盘检索回执格式无效")
    return ReviewReceipt.model_validate(yaml.safe_load(match.group(1)) or {})


def parse_review_content(review: str) -> str:
    starts = review.count(REVIEW_CONTENT_START)
    ends = review.count(REVIEW_CONTENT_END)
    if starts != 1 or ends != 1:
        raise ValueError("复盘正文标记必须各出现一次")
    match = REVIEW_CONTENT_RE.search(review)
    if not match:
        raise ValueError("复盘正文标记格式无效")
    return match.group(1).strip()


def review_is_placeholder(review: str) -> bool:
    content = parse_review_content(review)
    allowed = {
        "<!-- TODO:replace-before-review -->",
        "在此记录正确判断、错误判断、遗漏信号、错误分类、规则反例和可复用教训。",
    }
    lines = {line.strip() for line in content.splitlines() if line.strip()}
    return lines.issubset(allowed)


def set_review_content(review: str, content: str) -> str:
    parse_review_content(review)
    replacement = f"{REVIEW_CONTENT_START}\n{content.strip()}\n{REVIEW_CONTENT_END}"
    return REVIEW_CONTENT_RE.sub(lambda _: replacement, review, count=1)


def _put_review_receipt(review: str, receipt: ReviewReceipt) -> str:
    body = yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False).rstrip()
    rendered = (
        f"{REVIEW_RECEIPT_START}\n### 复盘检索回执\n\n"
        f"```yaml\n{body}\n```\n{REVIEW_RECEIPT_END}"
    )
    current = parse_review_receipt(review)
    if current is not None:
        return REVIEW_RECEIPT_RE.sub(lambda _: rendered, review, count=1)
    position = review.find(REVIEW_CONTENT_START)
    if position < 0:
        raise ValueError("复盘章节缺少 review-content 标记")
    return f"{review[:position].rstrip()}\n\n{rendered}\n\n{review[position:]}"


def _instruction(root: Path) -> tuple[ReceiptDocument, dict[str, Any]]:
    path = root / "ai/review_prompt.md"
    metadata, body = generic_front_matter(path)
    expected = {
        "document_id": "ai-review-instruction",
        "document_type": "instruction",
        "trusted_instruction": True,
    }
    for key, expected_value in expected.items():
        if metadata.get(key) != expected_value:
            raise ValueError(f"可信复盘指令字段不匹配：{key}")
    effective_at = metadata.get("effective_at")
    if not isinstance(effective_at, datetime) or effective_at.tzinfo is None:
        raise ValueError("可信复盘指令 effective_at 必须包含时区")
    chunks = document_chunks(root, {"ai-review-instruction"}).get("ai-review-instruction", [])
    receipt = ReceiptDocument(
        document_id="ai-review-instruction",
        source_path="ai/review_prompt.md",
        effective_at=effective_at.isoformat(),
        reliability=str(metadata.get("reliability") or "established"),
        content_sha256=sha256_file(path),
        chunk_ids=[item["chunk_id"] for item in chunks],
    )
    return receipt, {"metadata": metadata, "content": body, "chunks": chunks}


def _ruleset_snapshot(root: Path, spec: str, *, postmatch_only: bool) -> tuple[RulesetSnapshot, list[dict[str, Any]]]:
    ruleset = load_ruleset(root, spec)
    ordered_ids = [
        *ruleset.manifest.required_document_ids,
        *ruleset.manifest.conditional_document_ids,
    ]
    chunks = document_chunks(
        root,
        set(ordered_ids),
        ruleset_id=ruleset.manifest.ruleset_id,
        ruleset_version=ruleset.manifest.ruleset_version,
    )
    documents = [
        ReceiptDocument(
            document_id=identity,
            rule_version=ruleset.documents[identity].metadata.rule_version,
            source_path=ruleset.documents[identity].path.relative_to(root).as_posix(),
            effective_at=ruleset.documents[identity].metadata.effective_at.isoformat(),
            reliability=ruleset.documents[identity].metadata.reliability,
            content_sha256=ruleset.documents[identity].content_sha256,
            chunk_ids=[item["chunk_id"] for item in chunks.get(identity, [])],
        )
        for identity in ordered_ids
    ]
    snapshot = RulesetSnapshot(
        ruleset_id=ruleset.manifest.ruleset_id,
        ruleset_version=ruleset.manifest.ruleset_version,
        ruleset_sha256=ruleset.content_sha256,
        postmatch_only=postmatch_only,
        documents=documents,
    )
    payload = [
        {
            **item.model_dump(mode="json"),
            "content": ruleset.documents[item.document_id].body,
            "chunks": chunks.get(item.document_id, []),
        }
        for item in documents
    ]
    return snapshot, payload


def prepare_review_context(
    root: Path, path: Path, *, prepared_at: datetime
) -> tuple[Path, dict[str, Any], ReviewReceipt]:
    document = MatchDocument.load(path)
    original_match_bytes = path.read_bytes()
    if MatchStatus(document.metadata.status) != MatchStatus.FINISHED:
        raise ValueError("只有 finished 比赛可以准备复盘上下文")
    if not review_is_placeholder(document.sections["postmatch-review"]):
        raise ValueError("复盘正文已包含实质内容；准备复盘必须先于正文")
    if prepared_at.tzinfo is None or prepared_at.utcoffset() is None:
        raise ValueError("复盘准备时间必须包含时区")
    if document.metadata.result_recorded_at and prepared_at < document.metadata.result_recorded_at:
        raise ValueError("复盘准备时间不得早于赛果记录时间")
    analysis = parse_receipt(document.sections["prematch-reasoning"])
    if analysis is None:
        raise ValueError("比赛缺少赛前规则回执")
    errors = validate_analysis_receipt(root, document)
    if analysis.schema_version == 2:
        errors.extend(validate_case_receipt(root, document, require_current=False))
        errors.extend(validate_scenario_workflow(document, require_v2=True))
    if document.metadata.prematch_lock_sha256 != document.prematch_hash():
        errors.append("赛前锁定内容已变化")
    if errors:
        raise ValueError("；".join(dict.fromkeys(errors)))

    build_index(root)
    trusted, trusted_payload = _instruction(root)
    if datetime.fromisoformat(trusted.effective_at) > prepared_at:
        raise ValueError("可信复盘指令在准备时间尚未生效")
    locked_snapshot, locked_payload = _ruleset_snapshot(
        root,
        f"{analysis.ruleset_id}@{analysis.ruleset_version}",
        postmatch_only=False,
    )
    active = active_ruleset(root)
    current_snapshot, current_payload = _ruleset_snapshot(
        root,
        f"{active.ruleset_id}@{active.ruleset_version}",
        postmatch_only=True,
    )
    current_ruleset = load_ruleset(root, f"{active.ruleset_id}@{active.ruleset_version}")
    if current_ruleset.manifest.effective_at > prepared_at:
        raise ValueError("当前规则集在复盘准备时间尚未生效")
    case_receipt = parse_case_receipt(document.sections["prematch-reasoning"])
    scenarios = parse_scenarios(document.sections["prematch-reasoning"])
    data = {
        "schema_version": 1,
        "match_id": document.metadata.match_id,
        "prepared_at": prepared_at,
        "prematch_lock_sha256": document.metadata.prematch_lock_sha256,
        "analysis_context_sha256": analysis.context_sha256,
        "case_context_sha256": case_receipt.context_sha256 if case_receipt else None,
        "scenario_instances_sha256": scenario_hash(scenarios) if scenarios else None,
        "result_sha256": sha256_text(document.sections["result"]),
        "trusted_instruction": trusted,
        "locked_ruleset": locked_snapshot,
        "current_ruleset": current_snapshot,
        "context_sha256": "0" * 64,
    }
    draft = ReviewReceipt.model_validate(data)
    receipt = draft.model_copy(update={"context_sha256": review_context_sha256(draft)})
    payload = {
        **receipt.model_dump(mode="json"),
        "trusted_instruction_content": trusted_payload,
        "locked_ruleset_documents": locked_payload,
        "current_ruleset_documents": current_payload,
    }
    payload = json.loads(
        json.dumps(
            payload,
            ensure_ascii=False,
            default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value),
        )
    )
    context_path = root / "data/review-context" / f"{document.metadata.match_id}.json"
    previous_context = context_path.read_bytes() if context_path.exists() else None
    review = _put_review_receipt(document.sections["postmatch-review"], receipt)
    if analysis.schema_version == 2:
        from .scenarios import ResolutionCollection, parse_resolutions, set_resolution_collection

        if parse_resolutions(review) is None:
            review = set_resolution_collection(review, ResolutionCollection())
    if path.read_bytes() != original_match_bytes:
        raise ValueError("生成复盘上下文期间比赛文件已变化，未写入回执")
    try:
        atomic_write_text(context_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        document.replace_section("postmatch-review", review)
        document.save()
    except Exception:
        if previous_context is None:
            context_path.unlink(missing_ok=True)
        else:
            rollback = context_path.with_suffix(".json.rollback")
            rollback.write_bytes(previous_context)
            rollback.replace(context_path)
        raise
    return context_path, payload, receipt


def _verify_ruleset_snapshot(root: Path, snapshot: RulesetSnapshot) -> list[str]:
    errors: list[str] = []
    try:
        ruleset = load_ruleset(root, f"{snapshot.ruleset_id}@{snapshot.ruleset_version}")
        if snapshot.ruleset_sha256 != ruleset.content_sha256:
            errors.append(f"复盘回执规则集哈希不一致：{snapshot.ruleset_version}")
        expected_ids = [
            *ruleset.manifest.required_document_ids,
            *ruleset.manifest.conditional_document_ids,
        ]
        actual_ids = [item.document_id for item in snapshot.documents]
        if actual_ids != expected_ids:
            errors.append(f"复盘回执规则文档列表不一致：{snapshot.ruleset_version}")
        build_index(root)
        chunks = document_chunks(
            root,
            set(expected_ids),
            ruleset_id=ruleset.manifest.ruleset_id,
            ruleset_version=ruleset.manifest.ruleset_version,
        )
        for item in snapshot.documents:
            rule = ruleset.documents.get(item.document_id)
            if not rule:
                errors.append(f"复盘回执规则文档不存在：{item.document_id}")
                continue
            if rule.content_sha256 != item.content_sha256:
                errors.append(f"复盘回执规则文档不一致：{item.document_id}")
            if item.rule_version != rule.metadata.rule_version:
                errors.append(f"复盘回执规则版本不一致：{item.document_id}")
            if item.source_path != rule.path.relative_to(root).as_posix():
                errors.append(f"复盘回执规则路径不一致：{item.document_id}")
            if item.effective_at != rule.metadata.effective_at.isoformat():
                errors.append(f"复盘回执规则生效时间不一致：{item.document_id}")
            if item.reliability != rule.metadata.reliability:
                errors.append(f"复盘回执规则可信度不一致：{item.document_id}")
            expected_chunks = [chunk["chunk_id"] for chunk in chunks.get(item.document_id, [])]
            if item.chunk_ids != expected_chunks:
                errors.append(f"复盘回执规则片段不一致：{item.document_id}")
    except Exception as exc:
        errors.append(str(exc))
    return errors


def validate_review_receipt(root: Path, document: MatchDocument) -> list[str]:
    errors: list[str] = []
    try:
        receipt = parse_review_receipt(document.sections["postmatch-review"], required=True)
        assert receipt is not None
        analysis = parse_receipt(document.sections["prematch-reasoning"])
        if analysis is None:
            errors.append("复盘回执缺少对应赛前规则回执")
        else:
            if receipt.analysis_context_sha256 != analysis.context_sha256:
                errors.append("复盘回执引用的赛前上下文不一致")
        case_receipt = parse_case_receipt(document.sections["prematch-reasoning"])
        expected_case_hash = case_receipt.context_sha256 if case_receipt else None
        if receipt.case_context_sha256 != expected_case_hash:
            errors.append("复盘回执引用的案例上下文不一致")
        scenarios = parse_scenarios(document.sections["prematch-reasoning"])
        expected_scenario_hash = scenario_hash(scenarios) if scenarios else None
        if receipt.scenario_instances_sha256 != expected_scenario_hash:
            errors.append("复盘回执引用的场景不一致")
        if receipt.match_id != document.metadata.match_id:
            errors.append("复盘回执 match_id 与比赛不一致")
        if receipt.prematch_lock_sha256 != document.metadata.prematch_lock_sha256:
            errors.append("复盘回执引用的锁定哈希不一致")
        if receipt.result_sha256 != sha256_text(document.sections["result"]):
            errors.append("赛果正文在复盘准备后发生变化")
        if receipt.context_sha256 != review_context_sha256(receipt):
            errors.append("复盘检索上下文哈希无效")
        current_instruction, _ = _instruction(root)
        if receipt.trusted_instruction != current_instruction:
            errors.append("可信复盘指令已变化")
        if receipt.locked_ruleset.postmatch_only:
            errors.append("锁定规则集不能标记为 postmatch_only")
        if not receipt.current_ruleset.postmatch_only:
            errors.append("当前规则集必须标记为 postmatch_only")
        errors.extend(_verify_ruleset_snapshot(root, receipt.locked_ruleset))
        errors.extend(_verify_ruleset_snapshot(root, receipt.current_ruleset))
    except Exception as exc:
        errors.append(str(exc))
    return errors
