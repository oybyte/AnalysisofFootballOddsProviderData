from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
import yaml

from .aliases import AliasError, AliasStore
from .cases import (
    CASE_SECTIONS,
    CaseMaterialStage,
    append_case_stage,
    append_case_material,
    archive_user_kickoff_evidence,
    apply_user_result_evidence,
    case_id_for_fixture,
    case_from_payload,
    expand_case_text,
    migrate_cases_to_v2,
    migrate_cases_to_v3,
    import_legacy_case,
    rebuild_cases,
    rename_case_paths,
    update_case_kickoff,
    validate_cases,
    write_case_directory,
)
from .case_retrieval import retrieve_cases
from .analysis_context import parse_receipt, prepare_analysis_context
from .analysis_workflow import restart_analysis
from .exporting import export_matches
from .evidence import EvidencePayload, append_evidence, build_evidence_report
from .evidence_registry import (
    EvidenceRecord,
    change_binding_status,
    migrate_evidence_manifests,
    register_evidence,
    validate_evidence_registry,
)
from .extraction import (
    accept_review_batch,
    amend_preamble_review_batch,
    build_source_inventory,
    draft_review_batches,
    make_review_batches,
    write_coverage_reports,
)
from .history_migration import (
    HISTORY_SOURCE_FAMILY,
    build_history_inventory,
    history_status,
    make_history_batches,
)
from .indexing import build_index, search_index, search_results_json
from .models import AnalysisOutlook, EvaluationValue, HandicapResult, MarketSnapshot, PrimaryMarket, Result1X2, Selection
from .paths import find_project_root
from .reporting import build_match_index, build_statistics
from .services import (
    ServiceError,
    create_match,
    finish_historical_match,
    finish_match,
    lock_match,
    parse_datetime,
    review_match,
    set_market_snapshots,
    void_match,
)
from .validation import validate_all, validate_document
from .markdown import MatchDocument
from .rules import load_ruleset, validate_rules
from .proposals import scaffold_ruleset_proposal
from .rules_release import release_ruleset, validate_ruleset_proposal
from .review_context import prepare_review_context
from .scenarios import (
    ScenarioObservation,
    ScenarioResolution,
    add_live_scenario,
    add_resolution,
    add_scenario,
    revise_scenario,
    set_no_scenario,
    validate_scenario_workflow,
)
from .schemas import build_schemas
from .transaction import recover_pending_transactions
from .validation_studies import (
    ValidationCasePayload,
    ValidationStudy,
    append_validation_case,
    build_validation_report,
    register_study,
)
from .historical_certification import certify_historical_cases, load_certification_manifest
from .agent_workflow import (
    doctor as agent_doctor_service,
    json_text as agent_json_text,
    render_analysis_report,
    start_agent,
    validate_analysis_draft,
    workflow_status,
)
from .desktop_agents import (
    certification_status,
    changes as agent_changes_service,
    configure_product,
    record_certification,
    sync_agents,
)
from .journal import (
    JournalAlignmentV1,
    JournalIngestRequestV1,
    JournalOperation,
    apply_journal,
    ingest_journal,
    journal_json,
    journal_status,
    operate_journal,
    resolve_journal,
    validate_journal,
)
from .market_archive import (
    MarketArchiveDraftV1,
    archive_market_draft,
    prepare_market_archive,
)
from .lock_lifecycle import (
    load_lock_candidate,
    lock_from_candidate,
    prepare_lock_candidate,
)
from .ledger import atomic_write_text
from .rule_engine.evaluation import (
    AnalysisDraftInput,
    ReasoningDisposition,
    build_outlook as build_contract4_outlook,
    evaluate_draft as evaluate_contract4_draft,
)
from .analytics import analytics_status, build_analytics, export_dataset, rule_report, validate_analytics


app = typer.Typer(help="足球盘口学习与比赛分析日志")
aliases_app = typer.Typer(help="维护球队和联赛标准别名")
source_app = typer.Typer(help="建立和审核不可变历史资料库存")
case_app = typer.Typer(help="重建和校验历史案例投影")
evidence_app = typer.Typer(help="维护追加式规则证据")
scenario_app = typer.Typer(help="登记和解析赛前、临场场景")
rules_app = typer.Typer(help="校验提案并发布不可变规则集")
analysis_app = typer.Typer(help="管理赛前分析草稿")
validation_app = typer.Typer(help="冻结外部验证队列并登记逐场证据")
market_app = typer.Typer(help="维护 Match V2 结构化盘口快照")
schemas_app = typer.Typer(help="生成并校验 JSON Schema")
analytics_app = typer.Typer(help="构建可重建的离线分析数据库")
agent_app = typer.Typer(help="供桌面 AI 智能体使用的统一门禁")
agent_certify_app = typer.Typer(help="记录和检查四端人工认证")
journal_app = typer.Typer(help="归档、绑定并结构化保存比赛长文")
market_archive_app = typer.Typer(help="从已核对的截图赔率草稿生成预览或归档")
app.add_typer(aliases_app, name="aliases")
app.add_typer(source_app, name="source")
app.add_typer(case_app, name="case")
app.add_typer(evidence_app, name="evidence")
app.add_typer(scenario_app, name="scenario")
app.add_typer(rules_app, name="rules")
app.add_typer(analysis_app, name="analysis")
app.add_typer(validation_app, name="validation-study")
app.add_typer(market_app, name="market-snapshots")
app.add_typer(schemas_app, name="schemas")
app.add_typer(analytics_app, name="analytics")
app.add_typer(agent_app, name="agent")
app.add_typer(journal_app, name="journal")
journal_app.add_typer(market_archive_app, name="market-archive")
agent_app.add_typer(agent_certify_app, name="certify")


@journal_app.command("ingest")
def journal_ingest(
    source_file: Annotated[Path, typer.Option("--source-file")],
    request_file: Annotated[Path, typer.Option("--request-file")],
    attachment: Annotated[list[Path] | None, typer.Option("--attachment")] = None,
    auto_apply: Annotated[bool, typer.Option("--auto-apply")] = False,
    allow_create_match: Annotated[bool, typer.Option("--allow-create-match")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        raw = yaml.safe_load(request_file.read_text(encoding="utf-8")) or {}
        request = JournalIngestRequestV1.model_validate(raw)
        record = ingest_journal(
            find_project_root(),
            source_file=source_file,
            request=request,
            attachments=attachment or [],
            auto_apply=auto_apply,
            allow_create_match=allow_create_match,
        )
        if json_output:
            typer.echo(journal_json(record))
        else:
            typer.echo(f"原文已归档：{record.source_path}")
            typer.echo(f"应用状态：{record.application_status}")
            typer.echo("未生成用户未要求的预测。")
            for action in record.next_actions:
                typer.echo(f"下一步：{action}")
    except Exception as exc:
        _fail(exc)


def _journal_operation_command(
    operation: JournalOperation,
    source_file: Path,
    request_file: Path,
    attachment: list[Path] | None,
    json_output: bool,
) -> None:
    raw = yaml.safe_load(request_file.read_text(encoding="utf-8")) or {}
    request = JournalIngestRequestV1.model_validate(raw)
    result = operate_journal(
        find_project_root(), operation=operation, source_file=source_file,
        request=request, attachments=attachment or [],
    )
    if json_output:
        typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2))
        return
    if result.deprecation_notice:
        typer.echo(result.deprecation_notice)
    entry = result.entry
    typer.echo(f"归档操作：{result.requested_operation.value} -> {result.effective_operation.value}")
    typer.echo(f"原文：{entry.source_path}")
    typer.echo(f"目标：{entry.target_type}/{entry.target_id or '-'}")
    typer.echo(f"应用状态：{entry.application_status}")
    for lifecycle in result.lifecycle_actions:
        suffix = f"：{lifecycle.reason}" if lifecycle.reason else ""
        typer.echo(f"生命周期：{lifecycle.action}={lifecycle.status.value}{suffix}")
    typer.echo("未生成用户未要求的预测。")
    for action in entry.next_actions:
        typer.echo(f"下一步：{action}")


@journal_app.command("new")
def journal_new(
    source_file: Annotated[Path, typer.Option("--source-file")],
    request_file: Annotated[Path, typer.Option("--request-file")],
    attachment: Annotated[list[Path] | None, typer.Option("--attachment")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        _journal_operation_command(JournalOperation.NEW, source_file, request_file, attachment, json_output)
    except Exception as exc:
        _fail(exc)


@journal_app.command("append")
def journal_append(
    source_file: Annotated[Path, typer.Option("--source-file")],
    request_file: Annotated[Path, typer.Option("--request-file")],
    attachment: Annotated[list[Path] | None, typer.Option("--attachment")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        _journal_operation_command(JournalOperation.APPEND, source_file, request_file, attachment, json_output)
    except Exception as exc:
        _fail(exc)


@journal_app.command("review")
def journal_review(
    source_file: Annotated[Path, typer.Option("--source-file")],
    request_file: Annotated[Path, typer.Option("--request-file")],
    attachment: Annotated[list[Path] | None, typer.Option("--attachment")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        _journal_operation_command(JournalOperation.REVIEW, source_file, request_file, attachment, json_output)
    except Exception as exc:
        _fail(exc)


@journal_app.command("finish")
def journal_finish(
    source_file: Annotated[Path, typer.Option("--source-file")],
    request_file: Annotated[Path, typer.Option("--request-file")],
    attachment: Annotated[list[Path] | None, typer.Option("--attachment")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        _journal_operation_command(JournalOperation.FINISH, source_file, request_file, attachment, json_output)
    except Exception as exc:
        _fail(exc)


def _market_archive_draft(file: Path) -> MarketArchiveDraftV1:
    raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
    return MarketArchiveDraftV1.model_validate(raw)


@market_archive_app.command("preview")
def market_archive_preview(
    file: Annotated[Path, typer.Option("--file")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a visual transcription and render it without writing repository data."""
    try:
        preview = prepare_market_archive(find_project_root(), _market_archive_draft(file))
        if json_output:
            typer.echo(json.dumps(preview.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2))
        else:
            typer.echo(preview.rendered_markdown, nl=False)
    except Exception as exc:
        _fail(exc)


@market_archive_app.command("archive")
def market_archive_archive(
    file: Annotated[Path, typer.Option("--file")],
    attachment: Annotated[list[Path] | None, typer.Option("--attachment")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Archive a reviewed market draft. This command never generates analysis or predictions."""
    try:
        result = archive_market_draft(find_project_root(), _market_archive_draft(file), attachment or [])
        if json_output:
            typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2))
        else:
            typer.echo(f"已归档：{result.entry_id} -> {result.target_type}/{result.target_id or '-'}")
            typer.echo(f"结构化快照：{result.snapshot_count} 条")
            typer.echo("未生成用户未要求的预测。")
            for item in result.missing_items:
                typer.echo(f"未归档字段：{item}")
    except Exception as exc:
        _fail(exc)


@journal_app.command("status")
def journal_status_command(
    match: Annotated[Path | None, typer.Option("--match")] = None,
    entry_id: Annotated[str | None, typer.Option("--entry-id")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        records = journal_status(find_project_root(), entry_id=entry_id, match_path=match)
        if json_output:
            typer.echo(json.dumps([item.model_dump(mode="json") for item in records], ensure_ascii=False, sort_keys=True, indent=2))
        else:
            for item in records:
                typer.echo(f"{item.entry_id}: {item.application_status} -> {item.target_type}/{item.target_id or '-'}")
    except Exception as exc:
        _fail(exc)


@journal_app.command("resolve")
def journal_resolve(
    entry_id: Annotated[str, typer.Argument()],
    match: Annotated[Path, typer.Option("--match")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        record = resolve_journal(find_project_root(), entry_id, match)
        typer.echo(journal_json(record) if json_output else f"已绑定：{entry_id} -> {record.target_id}")
    except Exception as exc:
        _fail(exc)


@journal_app.command("apply")
def journal_apply(
    match_path: Annotated[Path, typer.Argument()],
    entry_id: Annotated[str, typer.Argument()],
    segment: Annotated[list[str] | None, typer.Option("--segment")] = None,
    alignment_file: Annotated[Path | None, typer.Option("--alignment-file")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        alignment = None
        if alignment_file:
            alignment = JournalAlignmentV1.model_validate(
                yaml.safe_load(alignment_file.read_text(encoding="utf-8")) or {}
            )
        record = apply_journal(
            find_project_root(), entry_id=entry_id, match_path=match_path,
            segment_ids=segment, alignment=alignment,
        )
        typer.echo(journal_json(record) if json_output else f"应用状态：{record.application_status}")
        if record.application_status == "blocked":
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@journal_app.command("validate")
def journal_validate_command(
    all_entries: Annotated[bool, typer.Option("--all")] = False,
) -> None:
    try:
        results = validate_journal(find_project_root())
        failed = False
        for path, errors in results.items():
            if errors:
                failed = True
                typer.echo(f"[失败] {path}")
                for error in errors:
                    typer.echo(f"  - {error}")
            else:
                typer.echo(f"[通过] {path}")
        if failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@agent_app.command("doctor")
def agent_doctor(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = agent_doctor_service(find_project_root())
    if json_output:
        typer.echo(agent_json_text(payload))
    else:
        typer.echo("[通过] 桌面智能体环境" if payload["ok"] else "[失败] 桌面智能体环境")
        for warning in payload["warnings"]:
            typer.echo(f"[警告] {warning}")
        for error in payload["errors"]:
            typer.echo(f"[错误] {error}")
    if not payload["ok"]:
        raise typer.Exit(1)


@agent_app.command("configure")
def agent_configure(
    product: Annotated[str, typer.Option("--product")],
    skill_root: Annotated[Path | None, typer.Option("--skill-root")] = None,
    confirm_import: Annotated[bool, typer.Option("--confirm-import")] = False,
    imported_version: Annotated[str | None, typer.Option("--imported-version")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = configure_product(
            find_project_root(),
            product,
            skill_root,
            confirm_import=confirm_import,
            imported_version=imported_version,
        )
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"已保存本机适配配置：{product}")
            if payload.get("installed_skill_path"):
                typer.echo(f"Skill 目标：{payload['installed_skill_path']}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("changes")
def agent_changes(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = agent_changes_service(find_project_root())
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"变更分类：{payload['classification']}")
            for item in payload["reasons"]:
                typer.echo(f"[{item['kind']}] {item['reason']}")
            for action in payload["required_actions"]:
                typer.echo(f"下一步：{action}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("sync")
def agent_sync(
    approved_by: Annotated[str, typer.Option("--approved-by")],
    confirm_sync: Annotated[bool, typer.Option("--confirm-sync")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = sync_agents(
            find_project_root(), approved_by=approved_by, confirm_sync=confirm_sync
        )
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"同步事务完成：{payload['transaction_id']}")
            typer.echo("telosWork 包已生成，仍需在产品中人工导入并完成认证。")
    except Exception as exc:
        _fail(exc)


@agent_certify_app.command("record")
def agent_certify_record(
    result_file: Annotated[Path, typer.Option("--file")],
) -> None:
    try:
        target = record_certification(find_project_root(), result_file)
        typer.echo(f"认证结果已记录：{target}")
    except Exception as exc:
        _fail(exc)


@agent_certify_app.command("status")
def agent_certify_status(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = certification_status(find_project_root())
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            for item in payload["products"]:
                typer.echo(f"{item['product_id']} {item['current_version']}: {item['status']}")
                for reason in item["reasons"]:
                    typer.echo(f"  - {reason}")
        if not payload["all_passed"]:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@agent_app.command("status")
def agent_status(
    path: Annotated[Path, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = workflow_status(find_project_root(), path)
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"比赛：{payload['match_id']}；状态：{payload['match_status']}")
            for action in payload["next_actions"]:
                typer.echo(f"下一步：{action}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("start")
def agent_start(
    path: Annotated[Path, typer.Argument()],
    market: Annotated[list[PrimaryMarket] | None, typer.Option("--market")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    ruleset: Annotated[str | None, typer.Option("--ruleset")] = None,
    proposal: Annotated[bool, typer.Option("--proposal")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = start_agent(
            find_project_root(),
            path,
            as_of=parse_datetime(as_of) if as_of else None,
            markets=market,
            ruleset_spec=ruleset,
            proposal=proposal,
        )
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"规则上下文已准备：{payload['ruleset']}")
            typer.echo(f"数据截止：{payload['data_cutoff_at']}")
            for item in payload["missing_data"]:
                typer.echo(f"[缺失] {item}")
            for action in payload["status"]["next_actions"]:
                typer.echo(f"下一步：{action}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("evaluate-draft")
def agent_evaluate_draft(
    path: Annotated[Path, typer.Argument()],
    draft_file: Annotated[Path | None, typer.Option("--draft-file")] = None,
    dispositions_file: Annotated[Path | None, typer.Option("--dispositions-file")] = None,
    proposal: Annotated[bool, typer.Option("--proposal")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Evaluate a Contract 4 Draft Input and optionally build an Outlook V4."""
    try:
        root = find_project_root(path)
        document = MatchDocument.load(path)
        receipt = parse_receipt(document.sections["analysis"])
        if receipt is None or receipt.schema_version != 6 or receipt.calibration_contract_version != 4:
            raise ServiceError("agent evaluate-draft 仅适用于 Contract 4 AnalysisReceipt V6")
        if receipt.ruleset_origin != "proposal" or not proposal:
            raise ServiceError("Contract 4 当前仅允许显式 --proposal 离线评估")
        ruleset = load_ruleset(root, f"{receipt.ruleset_id}@{receipt.ruleset_version}", allow_proposal=True)
        from .calibration import CalibrationConfig

        config = CalibrationConfig.model_validate(ruleset.calibration_config or {})
        base = root / "raw" / "matches" / document.metadata.match_id
        selected_draft = draft_file or base / "analysis-draft-input.yml"
        if not selected_draft.is_file():
            raise ServiceError(f"缺少 Contract 4 Draft Input：{selected_draft}")
        draft = AnalysisDraftInput.model_validate(yaml.safe_load(selected_draft.read_text(encoding="utf-8")) or {})
        bundle = evaluate_contract4_draft(
            match_id=document.metadata.match_id,
            metadata=document.metadata,
            cutoff=receipt.as_of,
            config=config,
            calibration_config_sha256=receipt.calibration_config_sha256 or "",
            market_snapshot_sha256=receipt.market_snapshots_sha256 or "",
            draft=draft,
        )
        bundle_path = base / f"rule-evaluation-{bundle.bundle_sha256}.yml"
        atomic_write_text(bundle_path, yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        outlook_path: Path | None = None
        if dispositions_file is not None:
            raw = yaml.safe_load(dispositions_file.read_text(encoding="utf-8")) or []
            records = raw.get("dispositions", []) if isinstance(raw, dict) else raw
            dispositions = [ReasoningDisposition.model_validate(item) for item in records]
            outlook = build_contract4_outlook(draft, bundle, dispositions)
            outlook_path = base / "analysis-outlook.yml"
            atomic_write_text(outlook_path, yaml.safe_dump(outlook.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        payload = {
            "schema_version": 1,
            "match_id": document.metadata.match_id,
            "evaluation_bundle": bundle_path.relative_to(root).as_posix(),
            "evaluation_bundle_sha256": bundle.bundle_sha256,
            "triggered_rule_ids": [item.rule_id for item in bundle.events if item.triggered],
            "outlook_file": outlook_path.relative_to(root).as_posix() if outlook_path else None,
            "generated_prediction": False,
        }
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"Contract 4 评估 bundle 已生成：{bundle_path}")
            if outlook_path is None:
                typer.echo("请为所有触发规则提供 dispositions 后再次运行 --dispositions-file。")
            else:
                typer.echo(f"AnalysisOutlook V4 已生成：{outlook_path}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("validate-draft")
def agent_validate_draft(
    path: Annotated[Path, typer.Argument()],
    outlook_file: Annotated[Path | None, typer.Option("--outlook-file")] = None,
    proposal: Annotated[bool, typer.Option("--proposal")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        document = MatchDocument.load(path)
        outlook = None
        selected = outlook_file
        if selected is None and document.metadata.schema_version == 2:
            candidate = (
                find_project_root()
                / "raw"
                / "matches"
                / document.metadata.match_id
                / "analysis-outlook.yml"
            )
            selected = candidate if candidate.exists() else None
        if selected is not None:
            outlook = AnalysisOutlook.model_validate(
                yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
            )
        errors = validate_analysis_draft(find_project_root(), document, outlook=outlook, allow_proposal=proposal)
        payload = {
            "schema_version": 1,
            "match_id": document.metadata.match_id,
            "valid": not errors,
            "errors": errors,
            "outlook_file": selected.as_posix() if selected else None,
        }
        if json_output:
            typer.echo(agent_json_text(payload))
        elif errors:
            for error in errors:
                typer.echo(f"[失败] {error}")
        else:
            typer.echo("[通过] 分析草稿满足锁定前门禁")
        if errors:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@agent_app.command("render-draft")
def agent_render_draft(
    path: Annotated[Path, typer.Argument()],
    outlook_file: Annotated[Path | None, typer.Option("--outlook-file")] = None,
    proposal: Annotated[bool, typer.Option("--proposal")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        root = find_project_root(path)
        document = MatchDocument.load(path)
        selected = outlook_file or (
            root / "raw" / "matches" / document.metadata.match_id / "analysis-outlook.yml"
        )
        outlook = AnalysisOutlook.model_validate(
            yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
        )
        target = render_analysis_report(root, path, outlook=outlook, allow_proposal=proposal)
        payload = {
            "schema_version": 1,
            "match_id": document.metadata.match_id,
            "analysis_report": target.relative_to(root).as_posix(),
            "analysis_report_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"规范分析报告已生成：{target}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("prepare-lock")
def agent_prepare_lock(
    path: Annotated[Path, typer.Argument()],
    market: Annotated[PrimaryMarket, typer.Option("--market")],
    selection: Annotated[Selection, typer.Option("--selection")],
    secondary: Annotated[Selection | None, typer.Option("--secondary")] = None,
    confidence: Annotated[float | None, typer.Option("--confidence")] = None,
    outlook_file: Annotated[Path | None, typer.Option("--outlook-file")] = None,
    actor: Annotated[str, typer.Option("--actor")] = "lcz",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        root = find_project_root(path)
        document = MatchDocument.load(path)
        selected = outlook_file or (
            root / "raw" / "matches" / document.metadata.match_id / "analysis-outlook.yml"
        )
        target, receipt = prepare_lock_candidate(
            root,
            path,
            market=market,
            selection=selection,
            secondary=secondary,
            confidence=confidence,
            outlook_path=selected,
            actor=actor,
        )
        payload = {
            "schema_version": 1,
            "match_id": receipt.match_id,
            "candidate_file": target.relative_to(root).as_posix(),
            "receipt_id": receipt.receipt_id,
            "data_cutoff_at": receipt.data_cutoff_at.isoformat(),
            "generated_prediction": False,
            "next_command": f"odds-journal lock {path} --candidate-file {target}",
        }
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"锁定候选回执已生成：{target}")
            typer.echo("请在开赛前使用 --candidate-file 完成普通锁定。")
    except Exception as exc:
        _fail(exc)


@market_app.command("set")
def market_snapshots_set(
    path: Annotated[Path, typer.Argument()],
    snapshots_file: Annotated[Path, typer.Option("--file")],
) -> None:
    try:
        raw = yaml.safe_load(snapshots_file.read_text(encoding="utf-8")) or []
        if not isinstance(raw, list):
            raise ValueError("盘口快照文件顶层必须是列表")
        snapshots = [MarketSnapshot.model_validate(item) for item in raw]
        set_market_snapshots(path, snapshots)
        typer.echo(f"结构化盘口快照已写入：{len(snapshots)} 条")
    except Exception as exc:
        _fail(exc)


@validation_app.command("register")
def validation_study_register(
    study_file: Annotated[Path, typer.Option("--study-file")],
) -> None:
    try:
        study = ValidationStudy.model_validate(
            yaml.safe_load(study_file.read_text(encoding="utf-8")) or {}
        )
        typer.echo(f"验证研究已冻结：{register_study(find_project_root(), study)}")
    except Exception as exc:
        _fail(exc)


@validation_app.command("add-case")
def validation_study_add_case(
    case_file: Annotated[Path, typer.Option("--case-file")],
    actor: Annotated[str, typer.Option("--actor")],
    at: Annotated[str, typer.Option("--at")] = "now",
) -> None:
    try:
        payload = ValidationCasePayload.model_validate(
            yaml.safe_load(case_file.read_text(encoding="utf-8")) or {}
        )
        append_validation_case(
            find_project_root(), payload, actor=actor, recorded_at=parse_datetime(at)
        )
        typer.echo(f"验证案例已追加：{payload.validation_case_id}")
    except Exception as exc:
        _fail(exc)


@validation_app.command("report")
def validation_study_report() -> None:
    try:
        path, payload = build_validation_report(find_project_root())
        typer.echo(f"验证研究报告：{path}；研究数：{len(payload['studies'])}")
    except Exception as exc:
        _fail(exc)


@app.callback()
def configure_console() -> None:
    """Use UTF-8 consistently on Windows, including redirected JSON output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")
    try:
        recovered = recover_pending_transactions(find_project_root())
        if recovered:
            typer.echo(f"已自动恢复中断事务：{', '.join(recovered)}", err=True)
    except Exception as exc:
        _fail(exc)


@schemas_app.command("build")
def schemas_build() -> None:
    try:
        changed = build_schemas(find_project_root())
        typer.echo(f"已生成 JSON Schema；更新 {len(changed)} 个文件。")
    except Exception as exc:
        _fail(exc)


@analytics_app.command("build")
def analytics_build(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        payload = build_analytics(find_project_root())
        if json_output:
            typer.echo(agent_json_text({**payload, "path": str(payload["path"])}))
        else:
            typer.echo(f"Analytics Database 已{'重建' if payload['rebuilt'] else '复用'}：{payload['path']}")
    except Exception as exc:
        _fail(exc)


@analytics_app.command("validate")
def analytics_validate(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        errors = validate_analytics(find_project_root())
        payload = {"schema_version": 1, "valid": not errors, "errors": errors}
        if json_output:
            typer.echo(agent_json_text(payload))
        elif errors:
            for error in errors:
                typer.echo(f"[失败] {error}")
        else:
            typer.echo("[通过] Analytics Database 完整且未过期")
        if errors:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@analytics_app.command("status")
def analytics_status_command(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        payload = analytics_status(find_project_root())
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    except Exception as exc:
        _fail(exc)


@analytics_app.command("rule-report")
def analytics_rule_report(
    rule_id: Annotated[str, typer.Option("--rule-id")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        rows = rule_report(find_project_root(), rule_id)
        if json_output:
            typer.echo(agent_json_text({"schema_version": 1, "rule_id": rule_id, "rows": rows}))
        else:
            typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
    except Exception as exc:
        _fail(exc)


@analytics_app.command("export-dataset")
def analytics_export_dataset(
    as_of: Annotated[str, typer.Option("--as-of")],
    output: Annotated[Path, typer.Option("--output")] = Path("ai/analytics/dataset.jsonl"),
) -> None:
    try:
        root = find_project_root()
        count = export_dataset(root, root / output, as_of=as_of)
        typer.echo(f"已导出 {count} 条无泄漏数据集记录：{root / output}")
    except Exception as exc:
        _fail(exc)


@schemas_app.command("check")
def schemas_check() -> None:
    try:
        build_schemas(find_project_root(), check=True)
        typer.echo("[通过] JSON Schema 与 Pydantic 模型一致")
    except Exception as exc:
        _fail(exc)


def _fail(exc: Exception) -> None:
    typer.echo(f"错误：{exc}", err=True)
    raise typer.Exit(1)


def _yaml_model(path: Path, model_type):
    import yaml

    return model_type.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


@scenario_app.command("add")
def scenario_add(
    path: Annotated[Path, typer.Argument()],
    payload: Annotated[Path, typer.Option("--file", help="ScenarioObservation YAML 文件")],
) -> None:
    try:
        observation = _yaml_model(payload, ScenarioObservation)
        add_scenario(path, observation)
        typer.echo(f"赛前场景已登记：{observation.scenario_instance_id}")
    except Exception as exc:
        _fail(exc)


@scenario_app.command("revise")
def scenario_revise(
    path: Annotated[Path, typer.Argument()],
    scenario_id: Annotated[str, typer.Argument()],
    payload: Annotated[Path, typer.Option("--file", help="修订后的 ScenarioObservation YAML")],
) -> None:
    try:
        observation = _yaml_model(payload, ScenarioObservation)
        revise_scenario(path, scenario_id, observation)
        typer.echo(f"赛前场景已修订：{scenario_id}")
    except Exception as exc:
        _fail(exc)


@scenario_app.command("no-scenario")
def scenario_no_scenario(
    path: Annotated[Path, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    try:
        set_no_scenario(path, reason)
        typer.echo("已记录未识别到可复用场景。")
    except Exception as exc:
        _fail(exc)


@scenario_app.command("add-live")
def scenario_add_live(
    path: Annotated[Path, typer.Argument()],
    payload: Annotated[Path, typer.Option("--file", help="ScenarioObservation YAML 文件")],
) -> None:
    try:
        observation = _yaml_model(payload, ScenarioObservation)
        add_live_scenario(path, observation)
        typer.echo(f"临场场景已追加：{observation.scenario_instance_id}")
    except Exception as exc:
        _fail(exc)


@scenario_app.command("resolve")
def scenario_resolve(
    path: Annotated[Path, typer.Argument()],
    payload: Annotated[Path, typer.Option("--file", help="ScenarioResolution YAML 文件")],
) -> None:
    try:
        resolution = _yaml_model(payload, ScenarioResolution)
        add_resolution(path, resolution)
        typer.echo(f"场景解析已追加：{resolution.scenario_instance_id}")
    except Exception as exc:
        _fail(exc)


@scenario_app.command("validate")
def scenario_validate(path: Annotated[Path, typer.Argument()]) -> None:
    try:
        document = MatchDocument.load(path)
        receipt = parse_receipt(document.sections["prematch-reasoning"])
        errors = validate_scenario_workflow(
            document, require_v2=bool(receipt and receipt.schema_version >= 2)
        )
        if errors:
            raise ValueError("；".join(errors))
        typer.echo("场景工作流校验通过。")
    except Exception as exc:
        _fail(exc)


@aliases_app.command("add-team")
def add_team(
    team_id: Annotated[str, typer.Option("--id")],
    name: Annotated[str, typer.Option("--name")],
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
) -> None:
    try:
        AliasStore(find_project_root()).add_team(team_id, name, alias or [])
        typer.echo(f"已新增球队：{team_id}")
    except (AliasError, RuntimeError) as exc:
        _fail(exc)


@aliases_app.command("add-competition")
def add_competition(
    code: Annotated[str, typer.Option("--code")],
    name: Annotated[str, typer.Option("--name")],
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
) -> None:
    try:
        AliasStore(find_project_root()).add_competition(code, name, alias or [])
        typer.echo(f"已新增联赛：{code}")
    except (AliasError, RuntimeError) as exc:
        _fail(exc)


@source_app.command("inventory")
def source_inventory(
    source_dir: Annotated[Path, typer.Argument()] = Path(
        "knowledge/sources/doubao-2026-07-28"
    ),
) -> None:
    try:
        root = find_project_root(source_dir)
        atoms, media = build_source_inventory(root, source_dir)
        typer.echo(f"文本原子库存已生成：{len(atoms)} 个原子")
        typer.echo(f"媒体库存已生成：{len(media)} 个文件")
    except Exception as exc:
        _fail(exc)


@source_app.command("migrate-history")
def source_migrate_history(
    source_file: Annotated[Path, typer.Argument()],
) -> None:
    """Archive and inventory the numbered historical Doubao conversation."""
    try:
        root = find_project_root(source_file)
        record = build_history_inventory(root, source_file)
        typer.echo(
            f"历史来源已归档：{record['source_family_id']}，"
            f"atoms={record['text_atom_count']}，unresolved={record['unresolved_unit_count']}"
        )
    except Exception as exc:
        _fail(exc)


@source_app.command("history-batches")
def source_history_batches(
    max_units: Annotated[int, typer.Option("--max-units", min=1, max=349)] = 20,
    max_chars: Annotated[int, typer.Option("--max-chars", min=1000)] = 50_000,
) -> None:
    try:
        paths = make_history_batches(find_project_root(), max_units=max_units, max_chars=max_chars)
        typer.echo(f"{HISTORY_SOURCE_FAMILY} 已生成 {len(paths)} 个批次。")
        for path in paths:
            typer.echo(str(path))
    except Exception as exc:
        _fail(exc)


@source_app.command("history-status")
def source_history_status() -> None:
    try:
        typer.echo(json.dumps(history_status(find_project_root()), ensure_ascii=False, indent=2))
    except Exception as exc:
        _fail(exc)


@source_app.command("status")
def source_status(
    source_family: Annotated[str, typer.Option("--source-family")] = HISTORY_SOURCE_FAMILY,
) -> None:
    try:
        if source_family == HISTORY_SOURCE_FAMILY:
            value = history_status(find_project_root())
        else:
            source = find_project_root() / "knowledge" / "extraction" / source_family / "source.yml"
            if not source.exists():
                raise ValueError(f"来源不存在：{source_family}")
            value = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        typer.echo(json.dumps(value, ensure_ascii=False, indent=2))
    except Exception as exc:
        _fail(exc)


@source_app.command("make-batches")
def source_make_batches(
    max_rounds: Annotated[int, typer.Option("--max-rounds", min=1, max=207)] = 20,
    max_chars: Annotated[int, typer.Option("--max-chars", min=1000)] = 50_000,
) -> None:
    try:
        paths = make_review_batches(
            find_project_root(), max_rounds=max_rounds, max_chars=max_chars
        )
        typer.echo(f"已生成 {len(paths)} 个审查批次。")
        for path in paths:
            typer.echo(str(path))
    except Exception as exc:
        _fail(exc)


@source_app.command("accept-batch")
def source_accept_batch(batch: Annotated[Path, typer.Argument()]) -> None:
    try:
        counts = accept_review_batch(find_project_root(batch), batch)
        typer.echo(
            "批次已写入追加式台账："
            + "，".join(f"{key}={value}" for key, value in counts.items())
        )
    except Exception as exc:
        _fail(exc)


@source_app.command("draft-batches")
def source_draft_batches(
    reviewed_by: Annotated[str, typer.Option("--reviewed-by")] = "codex",
    reviewed_at: Annotated[str, typer.Option("--reviewed-at")] = "now",
) -> None:
    try:
        paths = draft_review_batches(
            find_project_root(),
            reviewed_by=reviewed_by,
            reviewed_at=parse_datetime(reviewed_at),
        )
        typer.echo(f"已生成 {len(paths)} 个历史资料初审批次；未修改原始资料。")
    except Exception as exc:
        _fail(exc)


@source_app.command("amend-preamble")
def source_amend_preamble() -> None:
    try:
        path = amend_preamble_review_batch(find_project_root())
        typer.echo(f"前言原子已加入补充批次：{path}")
    except Exception as exc:
        _fail(exc)


@source_app.command("coverage")
def source_coverage_command(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        markdown_path, json_path, result = write_coverage_reports(find_project_root())
        if json_output:
            typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
            return
        typer.echo(f"覆盖报告：{markdown_path} / {json_path}")
        typer.echo(f"可审计覆盖完成：{'是' if result.auditable_complete else '否'}")
    except Exception as exc:
        _fail(exc)


@case_app.command("rebuild")
def case_rebuild() -> None:
    try:
        root = find_project_root()
        rename_case_paths(root)
        paths = rebuild_cases(root)
        typer.echo(f"已重建 {len(paths)} 个历史案例投影。")
    except Exception as exc:
        _fail(exc)


@case_app.command("migrate-v2")
def case_migrate_v2(
    recorded_at: Annotated[str, typer.Option("--recorded-at")] = "2026-07-29T21:00:00+08:00",
) -> None:
    """Freeze V1 case projections, append V2 revisions, and archive supplied result screenshots."""
    try:
        root = find_project_root()
        paths = migrate_cases_to_v2(root, recorded_at=parse_datetime(recorded_at))
        paths = apply_user_result_evidence(root, recorded_at=parse_datetime(recorded_at)) or paths
        paths = expand_case_text(root, recorded_at=parse_datetime(recorded_at)) or paths
        rename_case_paths(root)
        paths = rebuild_cases(root)
        directory = write_case_directory(root)
        typer.echo(f"已迁移 {len(paths)} 个历史案例到 V2；目录：{directory}")
    except Exception as exc:
        _fail(exc)


@case_app.command("validate")
def case_validate() -> None:
    try:
        results = validate_cases(find_project_root())
        failed = False
        for path, errors in results.items():
            if errors:
                failed = True
                typer.echo(f"[失败] {path}")
                for error in errors:
                    typer.echo(f"  - {error}")
            else:
                typer.echo(f"[通过] {path}")
        if failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@case_app.command("migrate-v3")
def case_migrate_v3(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    recorded_at: Annotated[str, typer.Option("--recorded-at")] = "now",
) -> None:
    """Upgrade current legacy cases without changing historical revisions."""
    try:
        result = migrate_cases_to_v3(
            find_project_root(), recorded_at=parse_datetime(recorded_at), dry_run=dry_run
        )
        prefix = "预检" if dry_run else "迁移完成"
        typer.echo(f"{prefix}：新增 {result['migrated']} 个 V3 revision；跳过 {result['skipped']} 个。")
    except Exception as exc:
        _fail(exc)


@case_app.command("certify-historical")
def case_certify_historical(
    manifest: Annotated[Path, typer.Option("--manifest")],
    actor: Annotated[str, typer.Option("--actor")],
    at: Annotated[str, typer.Option("--at")] = "now",
    strict: Annotated[bool, typer.Option("--strict")] = False,
) -> None:
    """Append auditable historical-case certifications without rewriting prior revisions."""
    try:
        if not strict:
            raise ValueError("历史案例认证必须显式提供 --strict")
        result = certify_historical_cases(
            find_project_root(),
            load_certification_manifest(manifest),
            actor=actor,
            recorded_at=parse_datetime(at),
        )
        typer.echo(
            f"历史案例认证完成：审查 {result['reviewed']}，认证通过 {result['certified']}，幂等跳过 {result['skipped']}。"
        )
    except Exception as exc:
        _fail(exc)


@case_app.command("append")
def case_append(
    section: Annotated[str, typer.Option("--section", help="要追加的案例章节")],
    text_file: Annotated[Path, typer.Option("--text-file", help="UTF-8 文本文件")],
    case_id: Annotated[str | None, typer.Option("--case-id")] = None,
    fixture_fingerprint: Annotated[str | None, typer.Option("--fixture-fingerprint")] = None,
    source_atom_id: Annotated[list[str] | None, typer.Option("--source-atom-id")] = None,
    media_id: Annotated[list[str] | None, typer.Option("--media-id")] = None,
    evidence_id: Annotated[list[str] | None, typer.Option("--evidence-id")] = None,
    recorded_at: Annotated[str, typer.Option("--recorded-at")] = "now",
) -> None:
    """Append new material to the existing canonical document for one fixture."""
    try:
        if (case_id is None) == (fixture_fingerprint is None):
            raise ValueError("必须且只能提供 --case-id 或 --fixture-fingerprint")
        if section not in CASE_SECTIONS:
            raise ValueError(f"--section 必须为以下之一：{', '.join(CASE_SECTIONS)}")
        if not text_file.is_file():
            raise ValueError(f"追加文本不存在：{text_file}")
        root = find_project_root()
        resolved_case_id = case_id or case_id_for_fixture(root, fixture_fingerprint or "")
        path = append_case_material(
            root,
            case_id=resolved_case_id,
            section=section,
            content=text_file.read_text(encoding="utf-8"),
            recorded_at=parse_datetime(recorded_at),
            source_atom_ids=source_atom_id,
            media_ids=media_id,
            evidence_ids=evidence_id,
        )
        if path is None:
            typer.echo("追加内容已存在；未创建新案例或新修订。")
            return
        typer.echo(f"材料已追加到既有案例：{path}")
        typer.echo("已生成新的审计修订；建议执行 git add/commit。")
    except Exception as exc:
        _fail(exc)


@case_app.command("import")
def case_import(
    case_file: Annotated[Path, typer.Option("--case-file")],
    actor: Annotated[str, typer.Option("--actor")] = "codex",
) -> None:
    try:
        case = case_from_payload(yaml.safe_load(case_file.read_text(encoding="utf-8")) or {})
        path = import_legacy_case(find_project_root(), case, actor=actor)
        typer.echo(f"历史案例已导入：{path}")
    except Exception as exc:
        _fail(exc)


@case_app.command("append-stage")
def case_append_stage(
    case_id: Annotated[str, typer.Option("--case-id")],
    stage_file: Annotated[Path, typer.Option("--stage-file")],
    actor: Annotated[str, typer.Option("--actor")] = "codex",
    at: Annotated[str, typer.Option("--at")] = "now",
) -> None:
    try:
        stage = CaseMaterialStage.model_validate(
            yaml.safe_load(stage_file.read_text(encoding="utf-8")) or {}
        )
        path = append_case_stage(
            find_project_root(),
            case_id=case_id,
            stage=stage,
            recorded_at=parse_datetime(at),
            actor=actor,
        )
        typer.echo(f"阶段材料已追加：{path}")
    except Exception as exc:
        _fail(exc)


@case_app.command("set-kickoff")
def case_set_kickoff(
    case_id: Annotated[str, typer.Option("--case-id")],
    kickoff: Annotated[str, typer.Option("--kickoff")],
    evidence_id: Annotated[list[str], typer.Option("--evidence-id")],
    correction_reason: Annotated[str | None, typer.Option("--correction-reason")] = None,
) -> None:
    """Confirm a legacy kickoff time and move its current document out of unknown/."""
    try:
        root = find_project_root()
        path = update_case_kickoff(
            root,
            case_id=case_id,
            kickoff_at=parse_datetime(kickoff),
            evidence_ids=evidence_id,
            recorded_at=datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0),
            correction_reason=correction_reason,
        )
        typer.echo(f"已确认开赛时间并更新案例路径：{path}")
    except Exception as exc:
        _fail(exc)


@evidence_app.command("link")
def evidence_link(
    rule_id: Annotated[str, typer.Option("--rule-id")],
    case_type: Annotated[str, typer.Option("--case-type")],
    case_id: Annotated[str, typer.Option("--case-id")],
    case_cluster_id: Annotated[str, typer.Option("--case-cluster-id")],
    market: Annotated[PrimaryMarket, typer.Option("--market")],
    relation: Annotated[str, typer.Option("--relation")],
    target_definition: Annotated[str, typer.Option("--target")],
    baseline_definition: Annotated[str, typer.Option("--baseline")],
    summary: Annotated[str, typer.Option("--summary")],
    reviewed_by: Annotated[str, typer.Option("--reviewed-by")],
    ruleset_version: Annotated[str | None, typer.Option("--ruleset-version")] = None,
    proposal_sha256: Annotated[str | None, typer.Option("--proposal-sha256")] = None,
    scenario_instance_id: Annotated[str | None, typer.Option("--scenario-instance-id")] = None,
    eligible: Annotated[bool, typer.Option("--eligible/--ineligible")] = False,
    ineligibility_reason: Annotated[list[str] | None, typer.Option("--ineligibility-reason")] = None,
    recorded_at: Annotated[str, typer.Option("--recorded-at")] = "now",
    evidence_id: Annotated[str | None, typer.Option("--evidence-id")] = None,
) -> None:
    try:
        root = find_project_root()
        rule_hash = None
        if ruleset_version:
            ruleset = load_ruleset(root, f"football-analysis@{ruleset_version}")
            if rule_id not in ruleset.documents:
                raise ValueError(f"规则不存在：{rule_id}")
            rule_hash = ruleset.documents[rule_id].content_sha256
        identity = evidence_id or (
            "ev-"
            + hashlib.sha256(
                f"{rule_id}|{case_type}|{case_id}|{scenario_instance_id}|{relation}".encode("utf-8")
            ).hexdigest()[:16]
        )
        payload = EvidencePayload(
            evidence_id=identity,
            rule_id=rule_id,
            observed_ruleset_version=ruleset_version,
            rule_content_sha256=rule_hash,
            proposal_sha256=proposal_sha256,
            case_type=case_type,
            case_id=case_id,
            case_cluster_id=case_cluster_id,
            scenario_instance_id=scenario_instance_id,
            market=market,
            target_definition=target_definition,
            baseline_definition=baseline_definition,
            relation=relation,
            eligibility="eligible" if eligible else "ineligible",
            ineligibility_reasons=ineligibility_reason or ([] if eligible else ["未声明合格原因"]),
            summary=summary,
            reviewed_by=reviewed_by,
        )
        append_evidence(
            root,
            payload,
            recorded_at=parse_datetime(recorded_at),
        )
        typer.echo(f"证据已追加：{identity}")
    except Exception as exc:
        _fail(exc)


@evidence_app.command("migrate-manifests")
def evidence_migrate_manifests(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Import legacy screenshot manifests into the append-only evidence registry."""
    try:
        result = migrate_evidence_manifests(find_project_root(), dry_run=dry_run)
        typer.echo(
            f"证据注册表{'预检' if dry_run else '迁移完成'}："
            f"{result['records']} 个文件，{result['bindings']} 个绑定，{result['corrections']} 个纠错。"
        )
    except Exception as exc:
        _fail(exc)


@evidence_app.command("validate")
def evidence_validate_registry() -> None:
    try:
        errors = validate_evidence_registry(find_project_root())
        if errors:
            for error in errors:
                typer.echo(f"[失败] {error}")
            raise typer.Exit(1)
        typer.echo("[通过] 用户证据注册表")
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@evidence_app.command("register")
def evidence_register(
    record_file: Annotated[Path, typer.Option("--record-file")],
    actor: Annotated[str, typer.Option("--actor")],
) -> None:
    try:
        record = EvidenceRecord.model_validate(
            yaml.safe_load(record_file.read_text(encoding="utf-8")) or {}
        )
        register_evidence(find_project_root(), record, actor=actor)
        typer.echo(f"证据已登记：{record.evidence_id}")
    except Exception as exc:
        _fail(exc)


@evidence_app.command("reject-binding")
def evidence_reject_binding(
    evidence_id: Annotated[str, typer.Argument()],
    binding_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason")],
    actor: Annotated[str, typer.Option("--actor")],
    replacement: Annotated[str | None, typer.Option("--replacement-binding-id")] = None,
) -> None:
    try:
        change_binding_status(
            find_project_root(), evidence_id=evidence_id, binding_id=binding_id,
            status="rejected", reason=reason, replacement_binding_id=replacement,
            recorded_at=datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0), actor=actor,
        )
        typer.echo(f"证据绑定已拒绝：{binding_id}")
    except Exception as exc:
        _fail(exc)


@evidence_app.command("supersede")
def evidence_supersede_binding(
    evidence_id: Annotated[str, typer.Argument()],
    binding_id: Annotated[str, typer.Argument()],
    replacement: Annotated[str, typer.Option("--replacement-binding-id")],
    reason: Annotated[str, typer.Option("--reason")],
    actor: Annotated[str, typer.Option("--actor")],
) -> None:
    try:
        change_binding_status(
            find_project_root(), evidence_id=evidence_id, binding_id=binding_id,
            status="superseded", reason=reason, replacement_binding_id=replacement,
            recorded_at=datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0), actor=actor,
        )
        typer.echo(f"证据绑定已替代：{binding_id}")
    except Exception as exc:
        _fail(exc)


@evidence_app.command("report")
def evidence_report() -> None:
    try:
        markdown_path, json_path, payload = build_evidence_report(find_project_root())
        typer.echo(f"规则证据报告：{markdown_path} / {json_path}")
        typer.echo(f"当前有效事件：{payload['active_events']}")
    except Exception as exc:
        _fail(exc)


@app.command("new")
def new_match(
    kickoff: Annotated[str, typer.Option("--kickoff")],
    competition_code: Annotated[str, typer.Option("--competition-code")],
    competition: Annotated[str, typer.Option("--competition")],
    home_id: Annotated[str, typer.Option("--home-id")],
    home: Annotated[str, typer.Option("--home")],
    away_id: Annotated[str, typer.Option("--away-id")],
    away: Annotated[str, typer.Option("--away")],
    timezone: Annotated[str, typer.Option("--timezone")] = "Asia/Shanghai",
    match_id: Annotated[str | None, typer.Option("--match-id")] = None,
    supersedes: Annotated[str | None, typer.Option("--supersedes")] = None,
) -> None:
    try:
        root = find_project_root()
        path = create_match(
            root,
            kickoff=parse_datetime(kickoff, timezone),
            timezone=timezone,
            competition_code=competition_code,
            competition=competition,
            home_team_id=home_id,
            home_team=home,
            away_team_id=away_id,
            away_team=away,
            match_id=match_id,
            supersedes_match_id=supersedes,
            schema_version=2,
        )
        typer.echo(f"已创建：{path}")
    except (ServiceError, RuntimeError) as exc:
        _fail(exc)


@app.command("validate")
def validate(
    path: Annotated[Path | None, typer.Argument()] = None,
    all_matches: Annotated[bool, typer.Option("--all")] = False,
    rules_only: Annotated[bool, typer.Option("--rules")] = False,
) -> None:
    try:
        root = find_project_root(path)
        if rules_only:
            results = validate_rules(root)
        elif all_matches or path is None:
            results = validate_all(root)
        else:
            document = MatchDocument.load(path)
            results = {path: validate_document(document, AliasStore(root))}
        failed = False
        for item, errors in results.items():
            if errors:
                failed = True
                typer.echo(f"[失败] {item}")
                for error in errors:
                    typer.echo(f"  - {error}")
            else:
                typer.echo(f"[通过] {item}")
        if failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@app.command("prepare-analysis")
def prepare_analysis(
    path: Annotated[Path, typer.Argument()],
    ruleset: Annotated[str | None, typer.Option("--ruleset")] = None,
    market: Annotated[list[PrimaryMarket] | None, typer.Option("--market")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    limit_rules: Annotated[int, typer.Option("--limit-rules", min=0, max=100)] = 20,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        root = find_project_root(path)
        document = MatchDocument.load(path)
        now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
        if as_of is None and now > document.metadata.kickoff_at:
            raise ServiceError("比赛已开赛；历史准备必须显式提供不晚于开赛时间的 --as-of")
        cutoff = parse_datetime(as_of, document.metadata.timezone) if as_of else now
        context_path, payload, receipt = prepare_analysis_context(
            root,
            path,
            prepared_at=now,
            as_of=cutoff,
            ruleset_spec=ruleset,
            markets=market,
            limit_rules=limit_rules,
        )
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        typer.echo(f"分析规则上下文已生成：{context_path}")
        typer.echo(
            f"规则集 {receipt.ruleset_id}@{receipt.ruleset_version}；"
            f"必需规则 {len(receipt.required_documents)}；"
            f"条件规则 {len(receipt.conditional_documents)}"
        )
        typer.echo("尚未生成比赛预测；请先阅读上下文，再填写赛前推演。")
    except Exception as exc:
        _fail(exc)


@app.command("lock")
def lock(
    path: Annotated[Path, typer.Argument()],
    market: Annotated[PrimaryMarket | None, typer.Option("--market")] = None,
    selection: Annotated[Selection | None, typer.Option("--selection")] = None,
    at: Annotated[str, typer.Option("--at")] = "now",
    secondary: Annotated[Selection | None, typer.Option("--secondary")] = None,
    confidence: Annotated[float | None, typer.Option("--confidence")] = None,
    outlook_file: Annotated[Path | None, typer.Option("--outlook-file")] = None,
    candidate_file: Annotated[Path | None, typer.Option("--candidate-file")] = None,
    actor: Annotated[str, typer.Option("--actor")] = "lcz",
) -> None:
    try:
        root = find_project_root(path)
        if candidate_file is not None:
            load_lock_candidate(candidate_file)
            lock_from_candidate(root, path, candidate_file, actor=actor)
            typer.echo("赛前内容已通过候选回执锁定。建议立即执行 git add/commit。")
            return
        if market is None or selection is None:
            raise ServiceError("未提供 --candidate-file 时必须填写 --market 和 --selection")
        document = MatchDocument.load(path)
        receipt = parse_receipt(document.sections["prematch-reasoning"])
        if receipt is not None and receipt.schema_version == 4:
            raise ServiceError("AnalysisReceipt V4 必须使用 agent prepare-lock 生成的候选回执锁定")
        outlook = None
        if outlook_file is not None:
            outlook = AnalysisOutlook.model_validate(
                yaml.safe_load(outlook_file.read_text(encoding="utf-8")) or {}
            )
        lock_match(
            path,
            at=parse_datetime(at, document.metadata.timezone),
            market=market,
            selection=selection,
            secondary=secondary,
            confidence=confidence,
            analysis_outlook=outlook,
        )
        typer.echo("赛前内容已锁定。建议立即执行 git add/commit。")
    except Exception as exc:
        _fail(exc)


@app.command("retrieve-cases")
def retrieve_cases_command(
    path: Annotated[Path, typer.Argument()],
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 10,
    prepared_at: Annotated[str, typer.Option("--prepared-at")] = "now",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        document = MatchDocument.load(path)
        context_path, payload, receipt = retrieve_cases(
            find_project_root(path),
            path,
            prepared_at=parse_datetime(prepared_at, document.metadata.timezone),
            limit=limit,
        )
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        typer.echo(f"历史案例上下文已生成：{context_path}")
        typer.echo(f"已选择 {len(receipt.selected_cases)} 个候选案例；尚未生成比赛方向。")
    except Exception as exc:
        _fail(exc)


@app.command("prepare-review")
def prepare_review(
    path: Annotated[Path, typer.Argument()],
    prepared_at: Annotated[str, typer.Option("--prepared-at")] = "now",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        document = MatchDocument.load(path)
        context_path, payload, receipt = prepare_review_context(
            find_project_root(path),
            path,
            prepared_at=parse_datetime(prepared_at, document.metadata.timezone),
        )
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        typer.echo(f"复盘上下文已生成：{context_path}")
        typer.echo(
            f"锁定规则集 {receipt.locked_ruleset.ruleset_version}；"
            f"当前规则集 {receipt.current_ruleset.ruleset_version} 仅供赛后参考。"
        )
    except Exception as exc:
        _fail(exc)


@analysis_app.command("restart")
def analysis_restart(
    path: Annotated[Path, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason")],
    at: Annotated[str, typer.Option("--at")] = "now",
) -> None:
    try:
        document = MatchDocument.load(path)
        archive = restart_analysis(
            path,
            reason=reason,
            restarted_at=parse_datetime(at, document.metadata.timezone),
        )
        typer.echo(f"旧分析草稿已归档：{archive}")
        typer.echo("规则、场景、案例和分析区已重置；请重新执行 prepare-analysis。")
    except Exception as exc:
        _fail(exc)


@rules_app.command("scaffold-proposal")
def rules_scaffold_proposal(
    version: Annotated[str, typer.Argument()] = "1.1.0",
    prepared_at: Annotated[str, typer.Option("--prepared-at")] = "now",
    base_version: Annotated[str | None, typer.Option("--base-version")] = None,
) -> None:
    try:
        path = scaffold_ruleset_proposal(
            find_project_root(),
            version,
            prepared_at=parse_datetime(prepared_at),
            base_version=base_version,
        )
        typer.echo(f"规则集提案已生成：{path}")
    except Exception as exc:
        _fail(exc)


@rules_app.command("proposal-validate")
def rules_proposal_validate(version: Annotated[str, typer.Argument()]) -> None:
    try:
        results = validate_ruleset_proposal(find_project_root(), version)
        failed = False
        for path, errors in results.items():
            if errors:
                failed = True
                typer.echo(f"[失败] {path}")
                for error in errors:
                    typer.echo(f"  - {error}")
            else:
                typer.echo(f"[通过] {path}")
        if failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@rules_app.command("release")
def rules_release(
    version: Annotated[str, typer.Argument()],
    approved_by: Annotated[str, typer.Option("--approved-by")],
    at: Annotated[str, typer.Option("--at")] = "now",
) -> None:
    try:
        path = release_ruleset(
            find_project_root(),
            version,
            approved_by=approved_by,
            effective_at=parse_datetime(at),
        )
        typer.echo(f"规则集已发布并激活：{path}")
    except Exception as exc:
        _fail(exc)


@app.command("finish")
def finish(
    path: Annotated[Path, typer.Argument()],
    score: Annotated[str, typer.Option("--score")],
    result_1x2: Annotated[Result1X2 | None, typer.Option("--result-1x2")] = None,
    handicap_result: Annotated[HandicapResult | None, typer.Option("--handicap-result")] = None,
    recorded_at: Annotated[str, typer.Option("--recorded-at")] = "now",
    key_events: Annotated[str | None, typer.Option("--key-events")] = None,
    source: Annotated[str | None, typer.Option("--source")] = None,
) -> None:
    try:
        document = MatchDocument.load(path)
        finish_match(
            path,
            score=score,
            result_1x2=result_1x2,
            handicap_result=handicap_result,
            recorded_at=parse_datetime(recorded_at, document.metadata.timezone),
            key_events=key_events,
            result_source=source,
        )
        typer.echo("赛果已记录。")
    except Exception as exc:
        _fail(exc)


@app.command("finish-historical")
def finish_historical(
    path: Annotated[Path, typer.Argument()],
    score: Annotated[str, typer.Option("--score")],
    source: Annotated[str, typer.Option("--source")],
    recorded_at: Annotated[str, typer.Option("--recorded-at")] = "now",
    key_events: Annotated[str | None, typer.Option("--key-events")] = None,
) -> None:
    """Record an evidenced result for an unlocked historical Match without creating a lock."""
    try:
        document = MatchDocument.load(path)
        finish_historical_match(
            path,
            score=score,
            recorded_at=parse_datetime(recorded_at, document.metadata.timezone),
            key_events=key_events,
            result_source=source,
        )
        typer.echo("历史赛果已记录。")
    except Exception as exc:
        _fail(exc)


@app.command("void")
def mark_void(
    path: Annotated[Path, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    try:
        void_match(path, reason=reason)
        typer.echo("比赛已标记为 void。")
    except Exception as exc:
        _fail(exc)


@app.command("review")
def review(
    path: Annotated[Path, typer.Argument()],
    primary: Annotated[EvaluationValue, typer.Option("--primary")],
    handicap: Annotated[EvaluationValue, typer.Option("--handicap")] = EvaluationValue.NOT_APPLICABLE,
    total_goals_range: Annotated[EvaluationValue, typer.Option("--total-goals-range")] = EvaluationValue.NOT_APPLICABLE,
    score_range: Annotated[EvaluationValue, typer.Option("--score-range")] = EvaluationValue.NOT_APPLICABLE,
    confidence_calibration: Annotated[EvaluationValue, typer.Option("--confidence-calibration")] = EvaluationValue.NOT_APPLICABLE,
    reviewed_at: Annotated[str, typer.Option("--reviewed-at")] = "now",
    changed_main: Annotated[bool | None, typer.Option("--changed-main/--unchanged-main")] = None,
) -> None:
    try:
        document = MatchDocument.load(path)
        review_match(
            path,
            reviewed_at=parse_datetime(reviewed_at, document.metadata.timezone),
            primary=primary,
            handicap=handicap,
            total_goals_range=total_goals_range,
            score_range=score_range,
            confidence_calibration=confidence_calibration,
            changed_main=changed_main,
        )
        typer.echo("复盘已完成。")
    except Exception as exc:
        _fail(exc)


@app.command("export")
def export_command(
    skip_invalid: Annotated[bool, typer.Option("--skip-invalid")] = False,
) -> None:
    try:
        count, diagnostics = export_matches(find_project_root(), skip_invalid=skip_invalid)
        typer.echo(f"已导出 {count} 场比赛。")
        for message in diagnostics:
            typer.echo(f"跳过：{message}")
    except Exception as exc:
        _fail(exc)


@app.command("build-index")
def build_index_command() -> None:
    try:
        path, count = build_index(find_project_root())
        typer.echo(f"索引已生成：{path}（{count} 个片段）")
    except Exception as exc:
        _fail(exc)


@app.command("search")
def search(
    query: Annotated[str, typer.Argument()],
    competition_code: Annotated[str | None, typer.Option("--competition-code")] = None,
    team_id: Annotated[str | None, typer.Option("--team-id")] = None,
    section_type: Annotated[str | None, typer.Option("--section-type")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    exclude_match_id: Annotated[str | None, typer.Option("--exclude-match-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        results = search_index(
            find_project_root(),
            query,
            competition_code=competition_code,
            team_id=team_id,
            section_type=section_type,
            as_of=parse_datetime(as_of) if as_of else None,
            exclude_match_id=exclude_match_id,
            limit=limit,
        )
        if json_output:
            typer.echo(search_results_json(results))
            return
        for result in results:
            typer.echo(
                f"[{result.section_type}] {result.source_path} "
                f"effective_at={result.effective_at or '-'} score={result.score:.3f}"
            )
            typer.echo(result.content[:300].replace("\n", " "))
            typer.echo("")
    except Exception as exc:
        _fail(exc)


@app.command("stats")
def stats() -> None:
    try:
        root = find_project_root()
        index_path = build_match_index(root)
        markdown_path, json_path, payload = build_statistics(root)
        typer.echo(f"比赛索引：{index_path}")
        typer.echo(f"统计报告：{markdown_path} / {json_path}")
        typer.echo(f"有效复盘比赛：{payload['reviewed_matches']}")
    except Exception as exc:
        _fail(exc)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
