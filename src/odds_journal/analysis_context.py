from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import model_validator

from .aliases import AliasStore
from .indexing import (
    INDEX_SCHEMA_VERSION,
    build_index,
    document_chunks,
    index_metadata,
    legacy_chunks,
    search_index,
)
from .markdown import MatchDocument, generic_front_matter
from .models import MatchStatus, PrimaryMarket
from .rules import (
    RuleDocument,
    Ruleset,
    active_ruleset,
    load_ruleset,
    sha256_file,
    sha256_text,
    validate_rules,
)


RECEIPT_START = "<!-- rules-retrieval:start -->"
RECEIPT_END = "<!-- rules-retrieval:end -->"
ANALYSIS_START = "<!-- analysis-content:start -->"
ANALYSIS_END = "<!-- analysis-content:end -->"
RECEIPT_RE = re.compile(
    rf"{re.escape(RECEIPT_START)}\s*### 规则检索回执\s*```yaml\s*(.*?)\s*```\s*{re.escape(RECEIPT_END)}",
    re.DOTALL,
)
ANALYSIS_RE = re.compile(
    rf"{re.escape(ANALYSIS_START)}(.*?){re.escape(ANALYSIS_END)}",
    re.DOTALL,
)
DEFAULT_MARKETS = ["one_x_two", "handicap", "total_goals"]
MARKET_LABELS = {
    "one_x_two": "胜平负 欧赔 主胜 平局 客胜",
    "handicap": "亚洲让球 盘口 升盘 降盘 水位 阻盘 诱盘",
    "total_goals": "大小球 总进球 大球 小球 比分",
}


class ReceiptDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    rule_version: str | None = None
    source_path: str
    effective_at: str
    reliability: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_ids: list[str]


class ExcludedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    reason: Literal["future_effective", "market_mismatch", "no_keyword_match", "limit"]


class AnalysisReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2]
    match_id: str
    prepared_at: datetime
    as_of: datetime
    ruleset_id: str
    ruleset_version: str
    ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    markets: list[Literal["one_x_two", "handicap", "total_goals"]]
    query: dict[str, str]
    filters: dict[str, str]
    index_schema_version: Literal[2, 3, 4]
    chunker_version: Literal[1, 2] | None = None
    prematch_facts_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    retrieval_contract_version: Literal[2, 3] | None = None
    trusted_instruction: ReceiptDocument
    required_documents: list[ReceiptDocument]
    conditional_documents: list[ReceiptDocument]
    excluded_documents: list[ExcludedDocument]
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prepared_at", "as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("检索回执时间必须包含时区")
        return value

    @field_validator("markets")
    @classmethod
    def markets_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("markets 存在重复值")
        return value

    @model_validator(mode="after")
    def version_contract(self) -> "AnalysisReceipt":
        if self.schema_version == 1:
            if self.index_schema_version != 2:
                raise ValueError("schema_version=1 必须使用 index schema 2")
            if any((self.chunker_version, self.prematch_facts_sha256, self.retrieval_contract_version)):
                raise ValueError("schema_version=1 不支持 v2 检索字段")
        else:
            if self.index_schema_version not in {3, 4} or self.chunker_version != 2:
                raise ValueError("schema_version=2 必须使用 index schema 3/4 和 chunker 2")
            expected_contract = 2 if self.index_schema_version == 3 else 3
            if not self.prematch_facts_sha256 or self.retrieval_contract_version != expected_contract:
                raise ValueError("schema_version=2 缺少事实哈希或检索契约版本")
        return self


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _receipt_digest_data(receipt: AnalysisReceipt | dict[str, Any]) -> dict[str, Any]:
    if isinstance(receipt, AnalysisReceipt):
        data = receipt.model_dump(mode="json")
    else:
        data = json.loads(json.dumps(receipt, ensure_ascii=False, default=str))
    data.pop("prepared_at", None)
    data.pop("context_sha256", None)
    return data


def context_sha256(receipt: AnalysisReceipt | dict[str, Any]) -> str:
    payload = _canonical_json(_receipt_digest_data(receipt)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_receipt(reasoning: str) -> AnalysisReceipt | None:
    starts = reasoning.count(RECEIPT_START)
    ends = reasoning.count(RECEIPT_END)
    if starts == 0 and ends == 0:
        return None
    if starts != 1 or ends != 1:
        raise ValueError("规则检索回执标记必须各出现一次")
    match = RECEIPT_RE.search(reasoning)
    if not match:
        raise ValueError("规则检索回执格式无效")
    return AnalysisReceipt.model_validate(yaml.safe_load(match.group(1)) or {})


def parse_analysis_content(reasoning: str) -> str:
    starts = reasoning.count(ANALYSIS_START)
    ends = reasoning.count(ANALYSIS_END)
    if starts != 1 or ends != 1:
        raise ValueError("赛前分析正文标记必须各出现一次")
    match = ANALYSIS_RE.search(reasoning)
    if not match:
        raise ValueError("赛前分析正文标记格式无效")
    return match.group(1).strip()


def analysis_is_placeholder(reasoning: str) -> bool:
    content = parse_analysis_content(reasoning)
    allowed = {
        "<!-- TODO:replace-before-lock -->",
        "在完成规则检索后填写缺失信息、理论盘口、双向假设、证据、反证和规则引用。",
        "在完成规则、场景和案例检索后填写缺失信息、理论盘口、双向假设、证据、反证和规则引用。",
        "本次仅完成截图数据提取与归档，尚未进行赛前推演或预测。",
    }
    lines = {line.strip() for line in content.splitlines() if line.strip()}
    return lines.issubset(allowed)


def set_analysis_content(reasoning: str, content: str) -> str:
    parse_analysis_content(reasoning)
    replacement = f"{ANALYSIS_START}\n{content.strip()}\n{ANALYSIS_END}"
    return ANALYSIS_RE.sub(lambda _: replacement, reasoning, count=1)


def _render_receipt(receipt: AnalysisReceipt) -> str:
    raw = receipt.model_dump(mode="json")
    yaml_text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False).rstrip()
    return f"{RECEIPT_START}\n### 规则检索回执\n\n```yaml\n{yaml_text}\n```\n{RECEIPT_END}"


def _put_receipt(reasoning: str, receipt: AnalysisReceipt) -> str:
    rendered = _render_receipt(receipt)
    current = parse_receipt(reasoning)
    if current is not None:
        return RECEIPT_RE.sub(lambda _: rendered, reasoning, count=1)
    analysis_position = reasoning.find(ANALYSIS_START)
    if analysis_position < 0:
        raise ValueError("赛前推演缺少分析正文标记")
    return f"{reasoning[:analysis_position].rstrip()}\n\n{rendered}\n\n{reasoning[analysis_position:]}"


def _receipt_document(root: Path, document: RuleDocument, chunks: list[dict[str, str]]) -> ReceiptDocument:
    return ReceiptDocument(
        document_id=document.metadata.document_id,
        rule_version=document.metadata.rule_version,
        source_path=document.path.relative_to(root).as_posix(),
        effective_at=document.metadata.effective_at.isoformat(),
        reliability=document.metadata.reliability,
        content_sha256=document.content_sha256,
        chunk_ids=[item["chunk_id"] for item in chunks],
    )


def _instruction_document(root: Path, chunks: list[dict[str, str]]) -> tuple[ReceiptDocument, dict[str, Any]]:
    path = root / "ai" / "analysis_prompt.md"
    metadata, body = generic_front_matter(path)
    expected = {
        "document_id": "ai-analysis-instruction",
        "document_type": "instruction",
        "trusted_instruction": True,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"可信分析指令字段不匹配：{key}")
    effective_at = metadata.get("effective_at")
    if not isinstance(effective_at, datetime) or effective_at.tzinfo is None:
        raise ValueError("可信分析指令 effective_at 必须包含时区")
    receipt = ReceiptDocument(
        document_id="ai-analysis-instruction",
        source_path="ai/analysis_prompt.md",
        effective_at=effective_at.isoformat(),
        reliability=str(metadata.get("reliability") or "established"),
        content_sha256=sha256_file(path),
        chunk_ids=[item["chunk_id"] for item in chunks],
    )
    return receipt, {"metadata": metadata, "content": body}


def _markets(values: list[PrimaryMarket | str] | None) -> list[str]:
    if not values:
        return list(DEFAULT_MARKETS)
    output: list[str] = []
    for value in values:
        market = value.value if isinstance(value, PrimaryMarket) else str(value)
        if market == "pass":
            continue
        if market not in DEFAULT_MARKETS:
            raise ValueError(f"prepare-analysis 不支持市场：{market}")
        if market not in output:
            output.append(market)
    return output


def _rule_payload(root: Path, document: RuleDocument, chunks: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "document_id": document.metadata.document_id,
        "rule_version": document.metadata.rule_version,
        "title": document.metadata.title,
        "document_type": document.metadata.document_type,
        "reliability": document.metadata.reliability,
        "effective_at": document.metadata.effective_at.isoformat(),
        "markets": document.metadata.markets,
        "phases": document.metadata.phases,
        "source_path": document.path.relative_to(root).as_posix(),
        "content_sha256": document.content_sha256,
        "chunks": chunks,
        "content": document.body,
    }


def prepare_analysis_context(
    root: Path,
    path: Path,
    *,
    prepared_at: datetime,
    as_of: datetime,
    ruleset_spec: str | None = None,
    markets: list[PrimaryMarket | str] | None = None,
    limit_rules: int = 20,
) -> tuple[Path, dict[str, Any], AnalysisReceipt]:
    document = MatchDocument.load(path)
    original_match_bytes = path.read_bytes()
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ValueError("只有 draft/tracking 比赛可以准备分析上下文")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of 必须包含时区")
    if as_of > document.metadata.kickoff_at:
        raise ValueError("as_of 不得晚于比赛开赛时间")
    if prepared_at.tzinfo is None or prepared_at.utcoffset() is None:
        raise ValueError("prepared_at 必须包含时区")
    if not analysis_is_placeholder(document.sections["prematch-reasoning"]):
        raise ValueError("赛前推演已包含实质分析；首次规则准备必须发生在分析之前")

    reasoning_for_write = document.sections["prematch-reasoning"]
    existing_receipt = parse_receipt(reasoning_for_write)
    if existing_receipt is not None:
        from .case_retrieval import CASE_RECEIPT_RE, parse_case_receipt
        from .scenarios import parse_scenarios

        existing_cases = parse_case_receipt(reasoning_for_write)
        existing_scenarios = parse_scenarios(reasoning_for_write)
        facts_changed = bool(
            existing_receipt.schema_version == 2
            and existing_receipt.prematch_facts_sha256
            != sha256_text(document.sections["prematch-facts"])
        )
        if existing_cases is not None and not facts_changed:
            raise ValueError("已有历史案例回执；重新准备前请执行 analysis restart")
        if existing_scenarios and any(item.as_of != as_of for item in existing_scenarios.instances):
            raise ValueError("场景截止时间与新的 as_of 不一致；请执行 analysis restart 后重建场景")
        if facts_changed and existing_cases is not None:
            reasoning_for_write = CASE_RECEIPT_RE.sub("", reasoning_for_write, count=1)

        # Validate the current facts independently from a receipt that is about to be replaced.
        validation_reasoning = RECEIPT_RE.sub("", reasoning_for_write, count=1)
        validation_document = MatchDocument(
            path=document.path,
            metadata=document.metadata,
            body=document.body,
            prefix=document.prefix,
            sections=dict(document.sections),
        )
        validation_document.replace_section("prematch-reasoning", validation_reasoning)
    else:
        validation_document = document

    from .validation import validate_document

    validation_errors = validate_document(validation_document, AliasStore(root))
    if validation_errors:
        raise ValueError("；".join(validation_errors))
    rule_errors = [error for errors in validate_rules(root).values() for error in errors]
    if rule_errors:
        raise ValueError("规则集校验失败：" + "；".join(rule_errors))

    selected_markets = _markets(markets)
    ruleset = load_ruleset(root, ruleset_spec)
    if ruleset.manifest.effective_at > as_of:
        raise ValueError("规则集在 as_of 时尚未生效")
    future_required = [
        item.metadata.document_id for item in ruleset.required if item.metadata.effective_at > as_of
    ]
    if future_required:
        raise ValueError("必需规则在 as_of 时尚未生效：" + ", ".join(future_required))

    build_index(root)
    all_ids = {item.metadata.document_id for item in ruleset.documents.values()}
    rule_chunks = document_chunks(
        root,
        all_ids,
        ruleset_id=ruleset.manifest.ruleset_id,
        ruleset_version=ruleset.manifest.ruleset_version,
    )
    missing_chunks = [item for item in all_ids if not rule_chunks.get(item)]
    if missing_chunks:
        raise ValueError("索引缺少规则文档：" + ", ".join(sorted(missing_chunks)))
    instruction_chunks = document_chunks(root, {"ai-analysis-instruction"})["ai-analysis-instruction"]
    trusted_receipt, trusted_payload = _instruction_document(root, instruction_chunks)
    if datetime.fromisoformat(trusted_receipt.effective_at) > as_of:
        raise ValueError("可信分析指令在 as_of 时尚未生效")

    facts = document.sections["prematch-facts"][:2000]
    query_terms = " ".join(
        [
            document.metadata.competition,
            document.metadata.home_team,
            document.metadata.away_team,
            *document.metadata.tags,
            *(MARKET_LABELS[item] for item in selected_markets),
            facts,
        ]
    )
    conditional_ids = set(ruleset.manifest.conditional_document_ids)
    eligible_ids: set[str] = set()
    excluded: list[ExcludedDocument] = []
    for rule in ruleset.conditional:
        if not selected_markets:
            excluded.append(ExcludedDocument(document_id=rule.metadata.document_id, reason="market_mismatch"))
        elif rule.metadata.effective_at > as_of:
            excluded.append(ExcludedDocument(document_id=rule.metadata.document_id, reason="future_effective"))
        elif "all" not in rule.metadata.markets and not set(selected_markets) & set(rule.metadata.markets):
            excluded.append(ExcludedDocument(document_id=rule.metadata.document_id, reason="market_mismatch"))
        else:
            eligible_ids.add(rule.metadata.document_id)

    results = search_index(
        root,
        query_terms,
        as_of=as_of,
        limit=100,
        document_ids=eligible_ids,
        ruleset_id=ruleset.manifest.ruleset_id,
        ruleset_version=ruleset.manifest.ruleset_version,
    )
    ranked_ids: list[str] = []
    for result in results:
        if result.document_id not in ranked_ids:
            ranked_ids.append(result.document_id)
    selected_ids = ranked_ids[: max(0, limit_rules)]
    for item in sorted(eligible_ids - set(ranked_ids)):
        excluded.append(ExcludedDocument(document_id=item, reason="no_keyword_match"))
    for item in ranked_ids[max(0, limit_rules) :]:
        excluded.append(ExcludedDocument(document_id=item, reason="limit"))

    required_receipts = [
        _receipt_document(root, rule, rule_chunks[rule.metadata.document_id]) for rule in ruleset.required
    ]
    conditional_receipts = [
        _receipt_document(root, ruleset.documents[item], rule_chunks[item]) for item in selected_ids
    ]
    query = {"terms": " ".join(query_terms.split())}
    filters = {
        "as_of": as_of.isoformat(),
        "ruleset": f"{ruleset.manifest.ruleset_id}@{ruleset.manifest.ruleset_version}",
        "candidate_scope": "manifest-conditional-only",
    }
    receipt_schema_version = 1 if ruleset.manifest.schema_version == 1 else 2
    receipt_data = {
        "schema_version": receipt_schema_version,
        "match_id": document.metadata.match_id,
        "prepared_at": prepared_at,
        "as_of": as_of,
        "ruleset_id": ruleset.manifest.ruleset_id,
        "ruleset_version": ruleset.manifest.ruleset_version,
        "ruleset_sha256": ruleset.content_sha256,
        "markets": selected_markets,
        "query": query,
        "filters": filters,
        "index_schema_version": 2 if receipt_schema_version == 1 else INDEX_SCHEMA_VERSION,
        "trusted_instruction": trusted_receipt,
        "required_documents": required_receipts,
        "conditional_documents": conditional_receipts,
        "excluded_documents": sorted(excluded, key=lambda item: item.document_id),
        "context_sha256": "0" * 64,
    }
    if receipt_schema_version == 2:
        receipt_data.update(
            {
                "chunker_version": 2,
                "prematch_facts_sha256": sha256_text(document.sections["prematch-facts"]),
                "retrieval_contract_version": 3 if INDEX_SCHEMA_VERSION == 4 else 2,
            }
        )
    draft_receipt = AnalysisReceipt.model_validate(receipt_data)
    receipt = draft_receipt.model_copy(update={"context_sha256": context_sha256(draft_receipt)})
    metadata = index_metadata(root)
    payload = {
        "schema_version": 1,
        "match_id": document.metadata.match_id,
        "generated_at": prepared_at.isoformat(),
        "as_of": as_of.isoformat(),
        "markets": selected_markets,
        "ruleset": {
            "id": ruleset.manifest.ruleset_id,
            "version": ruleset.manifest.ruleset_version,
            "sha256": ruleset.content_sha256,
        },
        "trusted_instruction": {
            **trusted_payload,
            **trusted_receipt.model_dump(mode="json"),
            "chunks": instruction_chunks,
        },
        "required_rules": [
            _rule_payload(root, rule, rule_chunks[rule.metadata.document_id]) for rule in ruleset.required
        ],
        "conditional_rules": [
            _rule_payload(root, ruleset.documents[item], rule_chunks[item]) for item in selected_ids
        ],
        "excluded_rules": [item.model_dump(mode="json") for item in receipt.excluded_documents],
        "query": query,
        "filters": filters,
        "index": {
            "schema_version": int(metadata["schema_version"]),
            "build_version": int(metadata["build_version"]),
            "source_fingerprint": metadata["source_fingerprint"],
        },
        "next_case_queries": [
            f"{document.metadata.competition} {document.metadata.home_team} {document.metadata.away_team}",
            " ".join(document.metadata.tags),
        ],
        "context_sha256": receipt.context_sha256,
    }
    payload = json.loads(
        json.dumps(
            payload,
            ensure_ascii=False,
            default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value),
        )
    )

    context_path = root / "data" / "analysis-context" / f"{document.metadata.match_id}.json"
    previous_context = context_path.read_bytes() if context_path.exists() else None
    context_path.parent.mkdir(parents=True, exist_ok=True)
    if path.read_bytes() != original_match_bytes:
        raise ValueError("生成分析上下文期间比赛文件已变化，未写入回执")
    try:
        temporary = context_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        temporary.replace(context_path)
        reasoning = _put_receipt(reasoning_for_write, receipt)
        document.replace_section("prematch-reasoning", reasoning)
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


def _verify_receipt_documents(root: Path, ruleset: Ruleset, receipt: AnalysisReceipt) -> list[str]:
    errors: list[str] = []
    required_ids = [item.document_id for item in receipt.required_documents]
    if required_ids != ruleset.manifest.required_document_ids:
        errors.append("回执必需规则与 manifest 不一致")
    conditional_ids = {item.document_id for item in receipt.conditional_documents}
    if not conditional_ids.issubset(set(ruleset.manifest.conditional_document_ids)):
        errors.append("回执包含 manifest 之外的条件规则")
    excluded_ids = {item.document_id for item in receipt.excluded_documents}
    if len(excluded_ids) != len(receipt.excluded_documents):
        errors.append("回执排除规则存在重复")
    if conditional_ids & excluded_ids:
        errors.append("同一条件规则同时出现在采用和排除列表")
    if conditional_ids | excluded_ids != set(ruleset.manifest.conditional_document_ids):
        errors.append("回执没有覆盖全部 manifest 条件规则")
    if receipt.schema_version == 1:
        indexed = {
            item.metadata.document_id: legacy_chunks(
                item.path.relative_to(root).as_posix(), item.metadata.document_type, item.body
            )
            for item in ruleset.documents.values()
        }
    else:
        build_index(root)
        indexed = document_chunks(
            root,
            {item.document_id for item in [*receipt.required_documents, *receipt.conditional_documents]},
            ruleset_id=ruleset.manifest.ruleset_id,
            ruleset_version=ruleset.manifest.ruleset_version,
        )
    for item in [*receipt.required_documents, *receipt.conditional_documents]:
        document = ruleset.documents.get(item.document_id)
        if document is None:
            errors.append(f"回执规则不存在：{item.document_id}")
            continue
        if item.rule_version != document.metadata.rule_version:
            errors.append(f"规则版本不一致：{item.document_id}")
        if item.content_sha256 != document.content_sha256:
            errors.append(f"规则内容哈希不一致：{item.document_id}")
        if item.source_path != document.path.relative_to(root).as_posix():
            errors.append(f"规则来源路径不一致：{item.document_id}")
        if item.effective_at != document.metadata.effective_at.isoformat():
            errors.append(f"规则生效时间不一致：{item.document_id}")
        if item.reliability != document.metadata.reliability:
            errors.append(f"规则可信度不一致：{item.document_id}")
        current_chunks = [chunk["chunk_id"] for chunk in indexed.get(item.document_id, [])]
        if item.chunk_ids != current_chunks:
            errors.append(f"规则片段列表不一致：{item.document_id}")
    if receipt.schema_version == 1:
        instruction_path = root / "ai/analysis_prompt.md"
        instruction_metadata, instruction_body = generic_front_matter(instruction_path)
        instruction_chunks = legacy_chunks(
            instruction_path.relative_to(root).as_posix(), "instruction", instruction_body
        )
    else:
        instruction_chunks = document_chunks(root, {"ai-analysis-instruction"}).get(
            "ai-analysis-instruction", []
        )
    try:
        current_instruction, _ = _instruction_document(root, instruction_chunks)
        if receipt.trusted_instruction != current_instruction:
            errors.append("可信分析指令元数据、内容或片段不一致")
    except Exception as exc:
        errors.append(str(exc))
    return errors


def validate_analysis_receipt(
    root: Path,
    document: MatchDocument,
    *,
    lock_at: datetime | None = None,
    market: PrimaryMarket | str | None = None,
    require_current: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        receipt = parse_receipt(document.sections["prematch-reasoning"])
        if receipt is None:
            return ["赛前推演缺少规则检索回执"]
        parse_analysis_content(document.sections["prematch-reasoning"])
        if receipt.match_id != document.metadata.match_id:
            errors.append("规则回执 match_id 与比赛不一致")
        if receipt.context_sha256 != context_sha256(receipt):
            errors.append("规则回执上下文哈希无效")
        if receipt.schema_version == 2:
            current_facts_hash = sha256_text(document.sections["prematch-facts"])
            if receipt.prematch_facts_sha256 != current_facts_hash:
                errors.append("赛前事实已变化，规则回执需要重新准备")
        ruleset = load_ruleset(root, f"{receipt.ruleset_id}@{receipt.ruleset_version}")
        if receipt.ruleset_sha256 != ruleset.content_sha256:
            errors.append("规则集内容哈希不一致")
        if ruleset.manifest.effective_at > receipt.as_of:
            errors.append("规则集在检索截止时间尚未生效")
        if any(item.metadata.effective_at > receipt.as_of for item in ruleset.required):
            errors.append("回执包含检索截止时间后生效的必需规则")
        for item in receipt.conditional_documents:
            rule = ruleset.documents.get(item.document_id)
            if rule and rule.metadata.effective_at > receipt.as_of:
                errors.append(f"回执包含检索截止时间后生效的条件规则：{item.document_id}")
        if datetime.fromisoformat(receipt.trusted_instruction.effective_at) > receipt.as_of:
            errors.append("可信分析指令在检索截止时间尚未生效")
        if receipt.filters.get("as_of") != receipt.as_of.isoformat():
            errors.append("回执过滤条件中的 as_of 不一致")
        if receipt.filters.get("ruleset") != f"{receipt.ruleset_id}@{receipt.ruleset_version}":
            errors.append("回执过滤条件中的规则集不一致")
        errors.extend(_verify_receipt_documents(root, ruleset, receipt))
        if require_current:
            active = active_ruleset(root)
            if (receipt.ruleset_id, receipt.ruleset_version) != (
                active.ruleset_id,
                active.ruleset_version,
            ):
                errors.append("规则回执不是当前活动规则集")
        if lock_at:
            if receipt.as_of > lock_at:
                errors.append("规则检索截止时间晚于锁定截止时间")
            if lock_at > document.metadata.kickoff_at:
                errors.append("锁定截止时间不得晚于开赛时间")
        market_value = market.value if isinstance(market, PrimaryMarket) else market
        if market_value and market_value != "pass" and market_value not in receipt.markets:
            errors.append(f"规则回执未覆盖主市场：{market_value}")
    except Exception as exc:
        errors.append(str(exc))
    return errors
