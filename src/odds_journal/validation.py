from __future__ import annotations

from pathlib import Path

from .aliases import AliasStore
from .cases import validate_cases
from .evidence import validate_evidence
from .evidence_registry import EVIDENCE_LEDGER, validate_evidence_registry
from .extraction import (
    EXTRACTION_RELATIVE,
    load_media_inventory,
    load_text_inventory,
    validate_extraction_state,
    verify_source_hashes,
)
from .ledger import read_ledger
from .markdown import MatchDocument, has_substantive_content
from .models import MatchStatus
from .paths import match_files
from .rules import validate_rules
from .validation_studies import validate_validation_studies


def validate_v2_reasoning_order(reasoning: str, *, require_complete: bool = False) -> list[str]:
    from .analysis_context import ANALYSIS_START, RECEIPT_START
    from .case_retrieval import CASE_RECEIPT_START
    from .scenarios import SCENARIOS_START

    markers = [RECEIPT_START, SCENARIOS_START, CASE_RECEIPT_START, ANALYSIS_START]
    present = [(reasoning.find(marker), marker) for marker in markers if marker in reasoning]
    errors: list[str] = []
    if require_complete and len(present) != len(markers):
        missing = [marker for marker in markers if marker not in reasoning]
        errors.append("v2 赛前推演缺少固定区块：" + ", ".join(missing))
    if [position for position, _ in present] != sorted(position for position, _ in present):
        errors.append("v2 赛前推演区块顺序必须为规则、场景、案例、分析正文")
    return errors


def validate_document(document: MatchDocument, aliases: AliasStore) -> list[str]:
    errors: list[str] = []
    receipt_checked = False
    metadata = document.metadata
    status = MatchStatus(metadata.status)

    if not aliases.has_team(metadata.home_team_id):
        errors.append(f"未知主队 ID：{metadata.home_team_id}")
    if not aliases.has_team(metadata.away_team_id):
        errors.append(f"未知客队 ID：{metadata.away_team_id}")
    if not aliases.has_competition(metadata.competition_code):
        errors.append(f"未知联赛代码：{metadata.competition_code}")

    errors.extend(f"图片不存在：{target}" for target in document.broken_images())

    try:
        from .analysis_context import parse_analysis_content, parse_receipt, validate_analysis_receipt

        parse_analysis_content(document.sections["prematch-reasoning"])
        receipt = parse_receipt(document.sections["prematch-reasoning"])
        if receipt is not None:
            receipt_checked = True
            errors.extend(validate_analysis_receipt(aliases.root, document))
            if receipt.schema_version >= 2:
                from .case_retrieval import parse_case_receipt, validate_case_receipt
                from .scenarios import parse_scenarios, validate_scenario_workflow

                require_complete = status in {
                    MatchStatus.LOCKED,
                    MatchStatus.FINISHED,
                    MatchStatus.REVIEWED,
                }
                errors.extend(
                    validate_v2_reasoning_order(
                        document.sections["prematch-reasoning"], require_complete=require_complete
                    )
                )
                scenarios = parse_scenarios(document.sections["prematch-reasoning"])
                case_receipt = parse_case_receipt(document.sections["prematch-reasoning"])
                if scenarios is not None or require_complete:
                    errors.extend(
                        validate_scenario_workflow(document, require_v2=require_complete)
                    )
                if case_receipt is not None or require_complete:
                    errors.extend(
                        validate_case_receipt(
                            aliases.root,
                            document,
                            require_current=status in {MatchStatus.DRAFT, MatchStatus.TRACKING},
                        )
                    )
    except Exception as exc:
        errors.append(str(exc))

    lock_exists = bool(metadata.prematch_lock_sha256)
    if status in {MatchStatus.LOCKED, MatchStatus.FINISHED, MatchStatus.REVIEWED} or lock_exists:
        try:
            from .analysis_context import validate_analysis_receipt

            if not receipt_checked:
                receipt_errors = validate_analysis_receipt(aliases.root, document)
                for error in receipt_errors:
                    if error not in errors:
                        errors.append(error)
        except Exception as exc:
            if str(exc) not in errors:
                errors.append(str(exc))
        for name in ("prematch-facts", "prematch-reasoning", "prematch-locked"):
            if "TODO:replace-before-lock" in document.sections[name]:
                errors.append(f"锁定章节仍包含待填写标记：{name}")
            if not has_substantive_content(document.sections[name]):
                errors.append(f"锁定章节缺少有效内容：{name}")
        current_hash = document.prematch_hash()
        if metadata.prematch_lock_sha256 != current_hash:
            errors.append("赛前锁定内容已变化，哈希校验失败")

    if status == MatchStatus.FINISHED and not has_substantive_content(document.sections["result"]):
        errors.append("finished 比赛缺少赛果正文")
    if status == MatchStatus.REVIEWED:
        if not has_substantive_content(document.sections["result"]):
            errors.append("reviewed 比赛缺少赛果正文")
        if "TODO:replace-before-review" in document.sections["postmatch-review"]:
            errors.append("复盘章节仍包含待填写标记")
        if not has_substantive_content(document.sections["postmatch-review"], minimum=20):
            errors.append("reviewed 比赛缺少有效复盘正文")
        try:
            from .analysis_context import parse_receipt

            receipt = parse_receipt(document.sections["prematch-reasoning"])
            if receipt and receipt.schema_version >= 2:
                from .review_context import parse_review_content, validate_review_receipt

                errors.extend(validate_review_receipt(aliases.root, document))
                if "TODO:replace-before-review" in parse_review_content(
                    document.sections["postmatch-review"]
                ):
                    errors.append("复盘正文仍包含待填写标记")
        except Exception as exc:
            errors.append(str(exc))
    return errors


def validate_all(root: Path) -> dict[Path, list[str]]:
    aliases = AliasStore(root)
    results: dict[Path, list[str]] = {}
    seen_ids: dict[str, Path] = {}
    for path in match_files(root):
        try:
            document = MatchDocument.load(path)
            errors = validate_document(document, aliases)
            previous = seen_ids.get(document.metadata.match_id)
            if previous:
                errors.append(f"match_id 与 {previous} 重复")
            else:
                seen_ids[document.metadata.match_id] = path
        except Exception as exc:
            errors = [str(exc)]
        results[path] = errors

    all_ids = set(seen_ids)
    for path in match_files(root):
        try:
            document = MatchDocument.load(path)
        except Exception:
            continue
        previous_id = document.metadata.supersedes_match_id
        if previous_id and previous_id not in all_ids:
            results[path].append(f"supersedes_match_id 不存在：{previous_id}")

    alias_errors = aliases.validate_uniqueness()
    if alias_errors:
        results[root / "data"] = alias_errors
    results.update(validate_rules(root))
    results.update(validate_validation_studies(root))
    from .journal import validate_journal
    from .lock_lifecycle import validate_lifecycle

    results.update(validate_journal(root))
    results.update(validate_lifecycle(root))
    extraction = root / EXTRACTION_RELATIVE
    if extraction.exists():
        source_errors: list[str] = []
        try:
            verify_source_hashes(root / "knowledge/sources/doubao-2026-07-28")
            load_text_inventory(root)
            load_media_inventory(root)
            for name in (
                "claim-events.jsonl",
                "disposition-events.jsonl",
                "conflict-events.jsonl",
                "case-events.jsonl",
            ):
                read_ledger(extraction / name)
            source_errors.extend(validate_extraction_state(root))
        except Exception as exc:
            source_errors.append(str(exc))
        results[extraction / "source.yml"] = source_errors
        results.update(validate_cases(root))
        results.update(validate_evidence(root))
        evidence_ledger = root / EVIDENCE_LEDGER
        if evidence_ledger.exists():
            results[evidence_ledger] = validate_evidence_registry(root)
    return results
