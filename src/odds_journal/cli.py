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
from .paths import find_project_root, match_files
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
from .rule_intakes import atomize_intake, ingest_intake, intake_status, scaffold_intake_rules, set_rule_disposition
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
    prematch_readiness,
    prematch_readiness_scan,
    render_analysis_report,
    start_agent,
    validate_analysis_draft,
    workflow_status,
)
from .desktop_agents import (
    auto_certify_codex_desktop,
    certification_status,
    changes as agent_changes_service,
    configure_product,
    record_certification,
    record_trae_cn_load_validation,
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
    prepare_market_comparison,
)
from .market_monitoring import PrematchRiskWatchlistDraftV1, prepare_watchlist
from .observations import (
    MatchDataBundleV1,
    backfill_legacy_snapshots,
    conflict_report as market_conflict_report,
    finish_bundle as finish_match_data_bundle,
    ingest_bundle as ingest_match_data_bundle,
    market_feature_snapshot,
    observation_inventory,
    observation_status,
    prepare_bundle as prepare_match_data_bundle,
    resolve_market_conflict,
    resolve_result_conflict,
    validate_observations,
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
from .rule_engine.evaluation_v5 import (
    AnalysisDraftInputV2,
    build_outlook_v5,
    evaluate_draft_v2,
)
from .analytics import analytics_status, build_analytics, export_dataset, rule_report, validate_analytics
from .ai_governance import activate_config, active_config, deactivate_config, sandbox_run, validate_config
from .backtest import build_inventory, build_labels, evaluate as evaluate_backtest, replay as replay_backtest
from .experiments import (
    ExperimentAdvisoryDisposition,
    ExperimentDisposition,
    LiveExperimentInput,
    activate_experiment,
    deactivate_experiment,
    evaluate_experiment,
    evaluate_experiment_advisories,
    evaluate_live_experiment,
    experiment_report,
    experiment_status,
    freeze_experiment_prediction,
    freeze_experiment_advisories,
    record_experiment_failure,
)


app = typer.Typer(help="足球盘口学习与比赛分析日志")
aliases_app = typer.Typer(help="维护球队和联赛标准别名")
source_app = typer.Typer(help="建立和审核不可变历史资料库存")
case_app = typer.Typer(help="重建和校验历史案例投影")
evidence_app = typer.Typer(help="维护追加式规则证据")
scenario_app = typer.Typer(help="登记和解析赛前、临场场景")
rules_app = typer.Typer(help="校验提案并发布不可变规则集")
rules_experiment_app = typer.Typer(help="管理未发布规则的双轨实验快照")
rules_intake_app = typer.Typer(help="将文本规则规范化为可审计实验候选")
analysis_app = typer.Typer(help="管理赛前分析草稿")
validation_app = typer.Typer(help="冻结外部验证队列并登记逐场证据")
market_app = typer.Typer(help="维护 Match V2 结构化盘口快照")
market_data_app = typer.Typer(help="维护追加式全量盘口观测")
market_observations_app = typer.Typer(help="规范化、去重并查询盘口时间序列")
schemas_app = typer.Typer(help="生成并校验 JSON Schema")
analytics_app = typer.Typer(help="构建可重建的离线分析数据库")
agent_app = typer.Typer(help="供桌面 AI 智能体使用的统一门禁")
agent_certify_app = typer.Typer(help="记录和检查四端人工认证")
ai_app = typer.Typer(help="管理隔离的 AI 研究轨")
ai_sandbox_app = typer.Typer(help="运行离线合成 AI sandbox")
ai_experiment_app = typer.Typer(help="管理 AI 研究实验")
ai_config_app = typer.Typer(help="管理内容寻址 AI 配置")
backtest_app = typer.Typer(help="管理确定性离线回放")
journal_app = typer.Typer(help="归档、绑定并结构化保存比赛长文")
market_archive_app = typer.Typer(help="从已核对的截图赔率草稿生成预览或归档")
app.add_typer(aliases_app, name="aliases")
app.add_typer(source_app, name="source")
app.add_typer(case_app, name="case")
app.add_typer(evidence_app, name="evidence")
app.add_typer(scenario_app, name="scenario")
app.add_typer(rules_app, name="rules")
rules_app.add_typer(rules_experiment_app, name="experiment")
rules_app.add_typer(rules_intake_app, name="intake")
app.add_typer(analysis_app, name="analysis")
app.add_typer(validation_app, name="validation-study")
app.add_typer(market_app, name="market-snapshots")
app.add_typer(market_data_app, name="market")
market_data_app.add_typer(market_observations_app, name="observations")
app.add_typer(schemas_app, name="schemas")
app.add_typer(analytics_app, name="analytics")
app.add_typer(agent_app, name="agent")
app.add_typer(ai_app, name="ai")
app.add_typer(backtest_app, name="backtest")
ai_app.add_typer(ai_sandbox_app, name="sandbox")
ai_app.add_typer(ai_experiment_app, name="experiment")
ai_experiment_app.add_typer(ai_config_app, name="config")
app.add_typer(journal_app, name="journal")
journal_app.add_typer(market_archive_app, name="market-archive")
agent_app.add_typer(agent_certify_app, name="certify")


@ai_sandbox_app.command("validate")
def ai_sandbox_validate(
    config: Annotated[Path, typer.Option("--config")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        item = validate_config(find_project_root(), config)
        payload = {"schema_version": 1, "valid": True, "config_id": item.config_id, "snapshot_sha256": item.snapshot_sha256}
        typer.echo(agent_json_text(payload) if json_output else f"[通过] sandbox 配置有效：{item.config_id}")
    except Exception as exc:
        _fail(exc)


@ai_sandbox_app.command("run")
def ai_sandbox_run(
    config: Annotated[Path, typer.Option("--config")],
    fixture: Annotated[Path, typer.Option("--fixture")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = sandbox_run(find_project_root(), config, fixture)
        typer.echo(agent_json_text(payload) if json_output else "[通过] 合成 AI sandbox 已完成")
    except Exception as exc:
        _fail(exc)


@ai_config_app.command("validate")
def ai_config_validate(
    config: Annotated[Path, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        item = validate_config(find_project_root(), config)
        payload = {"schema_version": 1, "valid": True, "config_id": item.config_id, "snapshot_sha256": item.snapshot_sha256}
        typer.echo(agent_json_text(payload) if json_output else f"[通过] AI 配置有效：{item.config_id}")
    except Exception as exc:
        _fail(exc)


@ai_config_app.command("activate")
def ai_config_activate(
    config: Annotated[Path, typer.Argument()],
    approved_by: Annotated[str, typer.Option("--approved-by")] = "",
    confirm_ai_experiment: Annotated[bool, typer.Option("--confirm-ai-experiment")] = False,
) -> None:
    try:
        if not confirm_ai_experiment:
            raise ValueError("激活 AI 配置需要 --confirm-ai-experiment")
        item = activate_config(find_project_root(), config, approved_by=approved_by)
        typer.echo(f"AI 配置已激活：{item.snapshot_sha256}")
    except Exception as exc:
        _fail(exc)


@ai_config_app.command("deactivate")
def ai_config_deactivate(
    approved_by: Annotated[str, typer.Option("--approved-by")] = "",
    reason: Annotated[str, typer.Option("--reason")] = "",
    confirm_ai_experiment: Annotated[bool, typer.Option("--confirm-ai-experiment")] = False,
) -> None:
    try:
        if not confirm_ai_experiment:
            raise ValueError("停用 AI 配置需要 --confirm-ai-experiment")
        item = deactivate_config(find_project_root(), approved_by=approved_by, reason=reason)
        typer.echo(f"AI 配置已停用：{item.snapshot_sha256}")
    except Exception as exc:
        _fail(exc)


@ai_config_app.command("status")
def ai_config_status(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        item = active_config(find_project_root())
        payload = {"schema_version": 1, "active": item.model_dump(mode="json") if item else None}
        typer.echo(agent_json_text(payload) if json_output else (f"活动 AI 配置：{item.snapshot_sha256}" if item else "没有活动 AI 配置"))
    except Exception as exc:
        _fail(exc)


@backtest_app.command("inventory")
def backtest_inventory(
    mode: Annotated[str, typer.Option("--mode")],
    ruleset: Annotated[str, typer.Option("--ruleset")],
    backtest_id: Annotated[str | None, typer.Option("--backtest-id")] = None,
) -> None:
    try:
        if mode not in {"historical_reproduction", "counterfactual_current_rules"}:
            raise ValueError("mode 必须为 historical_reproduction 或 counterfactual_current_rules")
        path, manifest = build_inventory(find_project_root(), mode=mode, ruleset_name=ruleset, backtest_id=backtest_id)
        typer.echo(f"回测资格清单已生成：{path} / {manifest.manifest_sha256}")
    except Exception as exc:
        _fail(exc)


@backtest_app.command("replay")
def backtest_replay(manifest: Annotated[Path, typer.Option("--manifest")]) -> None:
    try:
        path, item = replay_backtest(find_project_root(), manifest)
        typer.echo(f"回放预测已封存：{path} / {item.prediction_manifest_sha256}")
    except Exception as exc:
        _fail(exc)


@backtest_app.command("labels")
def backtest_labels(predictions: Annotated[Path, typer.Option("--predictions")]) -> None:
    try:
        path, item = build_labels(find_project_root(), predictions)
        typer.echo(f"回放标签已生成：{path} / {item.label_manifest_sha256}")
    except Exception as exc:
        _fail(exc)


@backtest_app.command("evaluate")
def backtest_evaluate(predictions: Annotated[Path, typer.Option("--predictions")], labels: Annotated[Path, typer.Option("--labels")]) -> None:
    try:
        path, item = evaluate_backtest(predictions, labels)
        typer.echo(f"回放结果已生成：{path} / {item.outcome_manifest_sha256}")
    except Exception as exc:
        _fail(exc)


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
    root = find_project_root()
    raw = yaml.safe_load(request_file.read_text(encoding="utf-8")) or {}
    request = JournalIngestRequestV1.model_validate(raw)
    result = operate_journal(
        root, operation=operation, source_file=source_file,
        request=request, attachments=attachment or [],
    )
    readiness = _archived_prematch_readiness(root, result.entry.target_type, result.entry.target_id)
    if json_output:
        payload = result.model_dump(mode="json")
        if readiness is not None:
            payload["prematch_readiness"] = readiness
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
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
    _render_archived_prematch_readiness(readiness)
    for action in entry.next_actions:
        typer.echo(f"下一步：{action}")


def _match_path_for_id(root: Path, match_id: str | None) -> Path | None:
    if match_id is None:
        return None
    for path in match_files(root):
        if MatchDocument.load(path).metadata.match_id == match_id:
            return path
    return None


def _archived_prematch_readiness(
    root: Path,
    target_type: str,
    target_id: str | None,
) -> dict | None:
    if target_type != "match":
        return None
    path = _match_path_for_id(root, target_id)
    if path is None:
        return None
    document = MatchDocument.load(path)
    if str(document.metadata.status) not in {"draft", "tracking"}:
        return None
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if now >= document.metadata.kickoff_at:
        return None
    return prematch_readiness(root, path, checked_at=now).model_dump(mode="json")


def _render_archived_prematch_readiness(readiness: dict | None) -> None:
    if readiness is None:
        return
    typer.echo(f"赛前锁定就绪：{readiness['summary']}")
    for blocker in readiness["blockers"]:
        typer.echo(f"待办：{blocker}")
    if readiness["next_command"]:
        typer.echo(f"下一步：{readiness['next_command']}")


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
    source_file: Annotated[Path | None, typer.Option("--source-file")] = None,
    request_file: Annotated[Path | None, typer.Option("--request-file")] = None,
    attachment: Annotated[list[Path] | None, typer.Option("--attachment")] = None,
    bundle: Annotated[Path | None, typer.Option("--bundle")] = None,
    match: Annotated[Path | None, typer.Option("--match")] = None,
    actor: Annotated[str, typer.Option("--actor")] = "lcz",
    received_at: Annotated[str | None, typer.Option("--received-at")] = None,
    confirm_historical: Annotated[bool, typer.Option("--confirm-historical")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        if bundle is not None:
            if source_file is not None or request_file is not None or attachment:
                raise ValueError("--bundle 不得与 journal 原文参数混用")
            bundle_value = _match_data_bundle(bundle)
            payload = finish_match_data_bundle(
                find_project_root(),
                bundle,
                bundle_value,
                match_path=match,
                actor=actor,
                received_at=parse_datetime(received_at) if received_at else None,
                confirm_historical=confirm_historical,
            )
            readiness = None
            if bundle_value.result is None:
                readiness = _archived_prematch_readiness(
                    find_project_root(), "match", payload.get("match_id")
                )
                if readiness is not None:
                    payload["prematch_readiness"] = readiness
            if json_output:
                typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
            else:
                typer.echo(f"bundle 已归档：{payload['archive_path']}")
                typer.echo(f"新增观测：{payload['normalization']['observations_added']}")
                typer.echo(f"赛果生命周期：{payload['result_lifecycle']['status']}")
                if payload["result_lifecycle"].get("reason"):
                    typer.echo(f"原因：{payload['result_lifecycle']['reason']}")
                    if payload["result_lifecycle"]["reason"] == "missing_valid_prematch_lock":
                        typer.echo("说明：该比赛赛前未完成正式锁定；系统不会根据赛果补建候选。")
                _render_archived_prematch_readiness(readiness)
            return
        if source_file is None or request_file is None:
            raise ValueError("必须提供 --bundle，或同时提供 --source-file 与 --request-file")
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
        readiness = _archived_prematch_readiness(
            find_project_root(), result.target_type, result.target_id
        )
        if json_output:
            payload = result.model_dump(mode="json")
            if readiness is not None:
                payload["prematch_readiness"] = readiness
            typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        else:
            typer.echo(f"已归档：{result.entry_id} -> {result.target_type}/{result.target_id or '-'}")
            typer.echo(f"结构化快照：{result.snapshot_count} 条")
            typer.echo("未生成用户未要求的预测。")
            _render_archived_prematch_readiness(readiness)
            for item in result.missing_items:
                typer.echo(f"未归档字段：{item}")
    except Exception as exc:
        _fail(exc)


@market_archive_app.command("compare")
def market_archive_compare(
    file: Annotated[Path, typer.Option("--file")],
    baseline_file: Annotated[Path | None, typer.Option("--baseline-file")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Compare a visual transcription with a session draft or the latest archived batch."""
    try:
        baseline = _market_archive_draft(baseline_file) if baseline_file else None
        result = prepare_market_comparison(
            find_project_root(), _market_archive_draft(file), baseline_draft=baseline,
        )
        if json_output:
            typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2))
        else:
            typer.echo(result.rendered_markdown, nl=False)
    except Exception as exc:
        _fail(exc)


@agent_app.command("prepare-watchlist")
def agent_prepare_watchlist(
    path: Annotated[Path, typer.Argument()],
    file: Annotated[Path, typer.Option("--file")],
    created_at: Annotated[str, typer.Option("--created-at")] = "now",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Freeze machine-readable checks sourced from existing prematch risk text."""
    try:
        document = MatchDocument.load(path)
        now = (
            datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
            if created_at == "now" else parse_datetime(created_at, document.metadata.timezone)
        )
        draft = PrematchRiskWatchlistDraftV1.model_validate(
            yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        )
        target, watchlist = prepare_watchlist(find_project_root(path), path, draft, created_at=now)
        if json_output:
            typer.echo(json.dumps({
                "path": target.relative_to(find_project_root(path)).as_posix(),
                "watchlist": watchlist.model_dump(mode="json"),
            }, ensure_ascii=False, sort_keys=True, indent=2))
        else:
            typer.echo(f"赛前风险监测清单已冻结：{target}")
            typer.echo(f"清单哈希：{watchlist.watchlist_sha256}")
            typer.echo("该清单只用于机械监测，不改变正式预测。")
    except Exception as exc:
        _fail(exc)


def _match_data_bundle(file: Path) -> MatchDataBundleV1:
    return MatchDataBundleV1.model_validate(yaml.safe_load(file.read_text(encoding="utf-8")) or {})


@market_observations_app.command("preview")
def market_observations_preview(
    file: Annotated[Path, typer.Option("--file")],
    match: Annotated[Path | None, typer.Option("--match")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate and normalize a bundle without writing repository data."""
    try:
        prepared = prepare_match_data_bundle(find_project_root(), _match_data_bundle(file), match_path=match)
        payload = {
            "schema_version": 1,
            "match_id": prepared["document"].metadata.match_id,
            "source_ref": prepared["source_ref"],
            "source_sha256": prepared["source_sha256"],
            "fixture_fact": prepared["fact"],
            "market_observations": prepared["observations"],
            "availability": prepared["availability"],
            "results": prepared["results"],
        }
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        else:
            typer.echo(f"比赛：{payload['match_id']}")
            typer.echo(f"盘口观测：{len(payload['market_observations'])} 条")
            typer.echo(f"未显示端点：{len(payload['availability'])} 条")
            typer.echo(f"赛果观测：{len(payload['results'])} 条")
            typer.echo("预览未写入仓库。")
    except Exception as exc:
        _fail(exc)


@market_observations_app.command("ingest")
def market_observations_ingest(
    file: Annotated[Path, typer.Option("--file")],
    match: Annotated[Path | None, typer.Option("--match")] = None,
    actor: Annotated[str, typer.Option("--actor")] = "lcz",
    received_at: Annotated[str | None, typer.Option("--received-at")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Append normalized observations; repeated bundle imports are idempotent."""
    try:
        received = parse_datetime(received_at) if received_at else None
        result = ingest_match_data_bundle(
            find_project_root(), _match_data_bundle(file), match_path=match,
            actor=actor, received_at=received,
        )
        if json_output:
            typer.echo(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2))
        else:
            typer.echo(f"比赛：{result.match_id}")
            typer.echo(f"新增观测：{result.observations_added}/{result.observations_seen}")
            typer.echo(f"新增来源：{result.source_links_added}")
            typer.echo(f"新增冲突：{result.conflicts_added}")
            typer.echo(f"兼容快照：+{result.compatibility_snapshots_added}")
            typer.echo("未生成预测、锁定或结算。")
    except Exception as exc:
        _fail(exc)


def _match_identity(match: Path | None) -> str | None:
    return MatchDocument.load(match).metadata.match_id if match else None


@market_observations_app.command("status")
@market_observations_app.command("coverage")
def market_observations_status(
    match: Annotated[Path | None, typer.Option("--match")] = None,
    all_matches: Annotated[bool, typer.Option("--all")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        if not match and not all_matches:
            raise ValueError("必须提供 --match 或 --all")
        payload = observation_status(find_project_root(), match_id=_match_identity(match))
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) if json_output else yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), nl=False)
    except Exception as exc:
        _fail(exc)


@market_observations_app.command("conflicts")
def market_observations_conflicts(
    match: Annotated[Path | None, typer.Option("--match")] = None,
    all_matches: Annotated[bool, typer.Option("--all")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        if not match and not all_matches:
            raise ValueError("必须提供 --match 或 --all")
        payload = market_conflict_report(find_project_root(), match_id=_match_identity(match))
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) if json_output else yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), nl=False)
    except Exception as exc:
        _fail(exc)


@market_observations_app.command("resolve-conflict")
def market_observations_resolve_conflict(
    conflict_group_id: Annotated[str, typer.Option("--conflict-group-id")],
    status: Annotated[str, typer.Option("--status")],
    reason: Annotated[str, typer.Option("--reason")],
    actor: Annotated[str, typer.Option("--actor")] = "lcz",
    observation_id: Annotated[str | None, typer.Option("--observation-id")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        if status not in {"confirmed_source", "both_valid", "superseded"}:
            raise ValueError("--status 必须为 confirmed_source、both_valid 或 superseded")
        payload = resolve_market_conflict(
            find_project_root(),
            conflict_group_id=conflict_group_id,
            status=status,  # type: ignore[arg-type]
            selected_observation_id=observation_id,
            reason=reason,
            actor=actor,
        )
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) if json_output else yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), nl=False)
    except Exception as exc:
        _fail(exc)


@market_observations_app.command("resolve-result-conflict")
def market_observations_resolve_result_conflict(
    conflict_group_id: Annotated[str, typer.Option("--conflict-group-id")],
    result_id: Annotated[str, typer.Option("--result-id")],
    reason: Annotated[str, typer.Option("--reason")],
    actor: Annotated[str, typer.Option("--actor")] = "lcz",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = resolve_result_conflict(
            find_project_root(), conflict_group_id=conflict_group_id,
            selected_result_id=result_id, reason=reason, actor=actor,
        )
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) if json_output else yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), nl=False)
    except Exception as exc:
        _fail(exc)


@market_observations_app.command("show-series")
def market_observations_show_series(
    match: Annotated[Path, typer.Option("--match")],
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        document = MatchDocument.load(match)
        cutoff = parse_datetime(as_of, document.metadata.timezone) if as_of else document.metadata.kickoff_at
        payload = market_feature_snapshot(find_project_root(), document.metadata.match_id, cutoff)
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) if json_output else yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), nl=False)
    except Exception as exc:
        _fail(exc)


@market_observations_app.command("backfill")
def market_observations_backfill(
    actor: Annotated[str, typer.Option("--actor")] = "migration",
    match: Annotated[Path | None, typer.Option("--match")] = None,
    max_matches: Annotated[int, typer.Option("--max-matches")] = 5,
    max_observations: Annotated[int, typer.Option("--max-observations")] = 5000,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = backfill_legacy_snapshots(
            find_project_root(), actor=actor, match_id=_match_identity(match),
            max_matches=max_matches, max_observations=max_observations,
        )
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) if json_output else yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), nl=False)
    except Exception as exc:
        _fail(exc)


@market_observations_app.command("inventory")
def market_observations_inventory(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = observation_inventory(find_project_root())
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) if json_output else yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), nl=False)
    except Exception as exc:
        _fail(exc)


@market_observations_app.command("validate")
def market_observations_validate() -> None:
    try:
        errors = validate_observations(find_project_root())
        if errors:
            for error in errors:
                typer.echo(f"[失败] {error}")
            raise typer.Exit(1)
        typer.echo("[通过] 全量盘口观测")
    except typer.Exit:
        raise
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
    installation_path: Annotated[Path | None, typer.Option("--installation-path")] = None,
    instruction_target: Annotated[Path | None, typer.Option("--instruction-target")] = None,
    confirm_import: Annotated[bool, typer.Option("--confirm-import")] = False,
    imported_version: Annotated[str | None, typer.Option("--imported-version")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = configure_product(
            find_project_root(),
            product,
            skill_root,
            installation_path=installation_path,
            instruction_target=instruction_target,
            confirm_import=confirm_import,
            imported_version=imported_version,
        )
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"已保存本机适配配置：{product}")
            if payload.get("installed_skill_path"):
                typer.echo(f"Skill 目标：{payload['installed_skill_path']}")
            if payload.get("installation_path"):
                typer.echo(f"安装路径：{payload['installation_path']}")
            if payload.get("instruction_target"):
                typer.echo(f"指令目标：{payload['instruction_target']}")
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
    approved_by: Annotated[str | None, typer.Option("--approved-by")] = None,
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
            typer.echo("Codex Desktop 已自动认证并提交同步产物；telosWork 包已生成，仍需在产品中人工导入并完成认证。")
            for product, state in payload.get("adapter_states", {}).items():
                suffix = f"（{state['reason']}）" if state.get("reason") else ""
                typer.echo(f"{product}: {state['status']}{suffix}")
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


@agent_certify_app.command("record-load-validation")
def agent_certify_record_load_validation(
    result_file: Annotated[Path, typer.Option("--file")],
) -> None:
    try:
        target = record_trae_cn_load_validation(find_project_root(), result_file)
        typer.echo(f"Trae CN 载入验证已记录：{target}")
    except Exception as exc:
        _fail(exc)


@agent_certify_app.command("auto")
def agent_certify_auto(
    product: Annotated[str, typer.Option("--product")] = "codex-desktop",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        if product != "codex-desktop":
            raise ValueError("自动认证当前仅支持 codex-desktop")
        payload = auto_certify_codex_desktop(find_project_root())
        typer.echo(agent_json_text(payload) if json_output else f"Codex Desktop 自动认证完成：{payload['certification_result']}")
    except Exception as exc:
        _fail(exc)


@agent_certify_app.command("status")
def agent_certify_status(
    product: Annotated[str | None, typer.Option("--product")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = certification_status(find_project_root(), product_id=product)
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            for item in payload["products"]:
                suffix = f" ({item['certification_method']})" if item.get("certification_method") else ""
                typer.echo(f"{item['product_id']} {item['current_version']}: {item['status']}{suffix}")
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
            readiness = payload["prematch_readiness"]
            typer.echo(f"赛前锁定就绪：{readiness['summary']}")
            for blocker in readiness["blockers"]:
                typer.echo(f"阻断：{blocker}")
            if readiness["next_command"]:
                typer.echo(f"推荐命令：{readiness['next_command']}")
            for action in payload["next_actions"]:
                typer.echo(f"下一步：{action}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("readiness")
def agent_readiness(
    path: Annotated[Path | None, typer.Argument()] = None,
    before: Annotated[str | None, typer.Option("--before")] = None,
    strict: Annotated[bool, typer.Option("--strict")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Read the prematch lock checklist without creating analysis or a lock candidate."""
    try:
        root = find_project_root(path) if path else find_project_root()
        if (path is None) == (before is None):
            raise ValueError("必须且只能提供 MATCH_PATH 或 --before")
        if path is not None:
            readiness = prematch_readiness(root, path)
            payload = readiness.model_dump(mode="json")
            failed = readiness.candidate_status != "valid" and readiness.match_status in {"draft", "tracking"}
            if json_output:
                typer.echo(agent_json_text(payload))
            else:
                typer.echo(f"比赛：{readiness.match_id}")
                typer.echo(f"赛前锁定就绪：{readiness.summary}")
                for name, completed in readiness.completed_stages.items():
                    typer.echo(f"阶段：{name}={'已完成' if completed else '待完成'}")
                for blocker in readiness.blockers:
                    typer.echo(f"阻断：{blocker}")
                if readiness.next_command:
                    typer.echo(f"下一步：{readiness.next_command}")
        else:
            cutoff = parse_datetime(before or "")
            items = prematch_readiness_scan(root, before=cutoff)
            failed = any(item.candidate_status != "valid" for item in items)
            payload = {
                "schema_version": 1,
                "checked_at": datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0).isoformat(),
                "before": cutoff.isoformat(),
                "matches": [item.model_dump(mode="json") for item in items],
                "strict_failed": strict and failed,
                "generated_prediction": False,
            }
            if json_output:
                typer.echo(agent_json_text(payload))
            else:
                if not items:
                    typer.echo("指定时间前没有 draft/tracking 比赛。")
                for item in items:
                    typer.echo(f"{item.kickoff_at.isoformat()} {item.match_id}: {item.summary}")
                    if item.next_command:
                        typer.echo(f"  下一步：{item.next_command}")
        if strict and failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
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
    """Evaluate a Contract 4 or Contract 7 Draft Input and build its Outlook."""
    try:
        root = find_project_root(path)
        document = MatchDocument.load(path)
        receipt = parse_receipt(document.sections["prematch-reasoning"])
        if receipt is None or receipt.schema_version not in {6, 7} or receipt.calibration_contract_version not in {4, 7}:
            raise ServiceError("agent evaluate-draft 仅适用于 Contract 4 V6 或 Contract 7 V7 回执")
        is_proposal = receipt.ruleset_origin == "proposal"
        if is_proposal and not proposal:
            raise ServiceError("提案规则评估必须显式使用 --proposal")
        if not is_proposal and proposal:
            raise ServiceError("已发布规则回执不得使用 --proposal")
        ruleset = load_ruleset(
            root,
            f"{receipt.ruleset_id}@{receipt.ruleset_version}",
            allow_proposal=is_proposal,
        )
        from .calibration import CalibrationConfig

        config = CalibrationConfig.model_validate(ruleset.calibration_config or {})
        base = root / "raw" / "matches" / document.metadata.match_id
        selected_draft = draft_file or base / "analysis-draft-input.yml"
        if not selected_draft.is_file():
            raise ServiceError(f"缺少 Draft Input：{selected_draft}")
        raw_draft = yaml.safe_load(selected_draft.read_text(encoding="utf-8")) or {}
        if receipt.calibration_contract_version == 7:
            draft = AnalysisDraftInputV2.model_validate(raw_draft)
            bundle = evaluate_draft_v2(
                root=root, match_id=document.metadata.match_id, metadata=document.metadata,
                cutoff=receipt.as_of, config=config,
                calibration_config_sha256=receipt.calibration_config_sha256 or "",
                market_snapshot_sha256=receipt.market_snapshots_sha256 or "", draft=draft,
                ruleset_version=receipt.ruleset_version,
            )
        else:
            draft = AnalysisDraftInput.model_validate(raw_draft)
            bundle = evaluate_contract4_draft(
                match_id=document.metadata.match_id, metadata=document.metadata,
                cutoff=receipt.as_of, config=config,
                calibration_config_sha256=receipt.calibration_config_sha256 or "",
                market_snapshot_sha256=receipt.market_snapshots_sha256 or "", draft=draft,
                ruleset_version=receipt.ruleset_version,
            )
        bundle_path = base / f"rule-evaluation-{bundle.bundle_sha256}.yml"
        atomic_write_text(bundle_path, yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        outlook_path: Path | None = None
        if dispositions_file is not None:
            raw = yaml.safe_load(dispositions_file.read_text(encoding="utf-8")) or []
            records = raw.get("dispositions", []) if isinstance(raw, dict) else raw
            dispositions = [ReasoningDisposition.model_validate(item) for item in records]
            outlook = build_outlook_v5(draft, bundle, dispositions) if receipt.calibration_contract_version == 7 else build_contract4_outlook(draft, bundle, dispositions)
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
                typer.echo(f"AnalysisOutlook V{outlook.schema_version} 已生成：{outlook_path}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("evaluate-experiment")
def agent_evaluate_experiment(
    path: Annotated[Path, typer.Argument()],
    dispositions_file: Annotated[Path | None, typer.Option("--dispositions-file")] = None,
    advisories_file: Annotated[Path | None, typer.Option("--advisories-file")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Evaluate the experiment snapshot pinned by agent start."""
    try:
        root = find_project_root(path)
        dispositions = None
        if dispositions_file is not None:
            raw = yaml.safe_load(dispositions_file.read_text(encoding="utf-8")) or []
            records = raw.get("dispositions", []) if isinstance(raw, dict) else raw
            dispositions = [ExperimentDisposition.model_validate(item) for item in records]
        advisory_dispositions = None
        if advisories_file is not None:
            raw = yaml.safe_load(advisories_file.read_text(encoding="utf-8")) or []
            records = raw.get("dispositions", []) if isinstance(raw, dict) else raw
            advisory_dispositions = [ExperimentAdvisoryDisposition.model_validate(item) for item in records]
        bundle_path, bundle, outlook_path, outlook = evaluate_experiment(
            root,
            path,
            dispositions=dispositions,
        )
        advisory_path = None
        advisory_bundle = None
        try:
            advisory_path, advisory_bundle, _ = evaluate_experiment_advisories(
                root, path, dispositions=advisory_dispositions,
            )
        except ValueError as exc:
            if "没有适用的提示规则" not in str(exc):
                raise
        payload = {
            "schema_version": 1,
            "match_id": bundle.match_id,
            "evaluation_bundle": bundle_path.relative_to(root).as_posix(),
            "evaluation_bundle_sha256": bundle.bundle_sha256,
            "triggered_rule_ids": [item.rule_id for item in bundle.events if item.status == "triggered"],
            "suppressed_rule_ids": [item.rule_id for item in bundle.events if item.status == "suppressed"],
            "outlook_file": outlook_path.relative_to(root).as_posix() if outlook_path else None,
            "experiment_status": outlook.experiment_status if outlook else "awaiting_dispositions",
            "generated_prediction": outlook is not None,
            "advisory_bundle": advisory_path.relative_to(root).as_posix() if advisory_path else None,
            "triggered_advisory_ids": [item.advisory_id for item in advisory_bundle.events if item.status == "triggered"] if advisory_bundle else [],
        }
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"实验规则评估 bundle 已生成：{bundle_path}")
            if outlook_path:
                typer.echo(f"实验 Outlook 已生成：{outlook_path}")
            else:
                typer.echo("请处置全部触发实验规则后再次传入 --dispositions-file。")
            if advisory_path:
                typer.echo(f"实验提示 Bundle 已生成：{advisory_path}")
    except Exception as exc:
        _fail(exc)


@agent_app.command("evaluate-live")
def agent_evaluate_live(
    path: Annotated[Path, typer.Argument()],
    event_file: Annotated[Path, typer.Option("--event-file")],
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        root = find_project_root(path)
        raw = yaml.safe_load(event_file.read_text(encoding="utf-8")) or {}
        if as_of:
            raw["observed_at"] = parse_datetime(as_of)
        event = LiveExperimentInput.model_validate(raw)
        target, receipt = evaluate_live_experiment(root, path, event)
        payload = {
            "schema_version": 1,
            "match_id": receipt.match_id,
            "receipt": target.relative_to(root).as_posix(),
            "triggered_rule": receipt.triggered_rule,
            "candidate_primary_range": list(receipt.candidate_primary_range),
        }
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"赛中实验回执已生成：{target}")
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
        experiment_prediction = None
        experiment_advisory = None
        try:
            frozen = freeze_experiment_prediction(root, path, receipt)
            experiment_prediction = frozen[0].relative_to(root).as_posix() if frozen else None
            frozen_advisory = freeze_experiment_advisories(root, path, receipt)
            experiment_advisory = frozen_advisory[0].relative_to(root).as_posix() if frozen_advisory else None
        except Exception as exc:
            now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
            record_experiment_failure(
                root,
                match_id=document.metadata.match_id,
                stage="prepare_lock",
                reason=str(exc),
                recorded_at=now,
            )
        payload = {
            "schema_version": 1,
            "match_id": receipt.match_id,
            "candidate_file": target.relative_to(root).as_posix(),
            "receipt_id": receipt.receipt_id,
            "data_cutoff_at": receipt.data_cutoff_at.isoformat(),
            "generated_prediction": False,
            "experiment_prediction_receipt": experiment_prediction,
            "experiment_advisory_receipt": experiment_advisory,
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


@rules_experiment_app.command("activate")
def rules_experiment_activate(
    version: Annotated[str, typer.Argument()],
    approved_by: Annotated[str, typer.Option("--approved-by")],
    confirm_experiment: Annotated[bool, typer.Option("--confirm-experiment")] = False,
    at: Annotated[str, typer.Option("--at")] = "now",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        if not confirm_experiment:
            raise ServiceError("激活未发布规则实验必须显式使用 --confirm-experiment")
        now = datetime.now().astimezone().replace(microsecond=0) if at == "now" else parse_datetime(at)
        active = activate_experiment(find_project_root(), version, approved_by=approved_by, activated_at=now)
        payload = active.model_dump(mode="json")
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(f"实验规则已激活：football-analysis@{version} revision {active.experiment_revision}")
            typer.echo(f"快照：{active.snapshot_path}")
    except Exception as exc:
        _fail(exc)


@rules_experiment_app.command("status")
def rules_experiment_status_command(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = experiment_status(find_project_root())
        if json_output:
            typer.echo(agent_json_text(payload))
        elif payload.get("active"):
            typer.echo(f"活动实验：football-analysis@{payload['ruleset_version']} revision {payload['experiment_revision']}")
            typer.echo(f"快照：{payload['snapshot_path']}")
        else:
            typer.echo("当前没有活动实验规则集")
    except Exception as exc:
        _fail(exc)


@rules_experiment_app.command("deactivate")
def rules_experiment_deactivate(
    approved_by: Annotated[str, typer.Option("--approved-by")],
    reason: Annotated[str, typer.Option("--reason")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        inactive = deactivate_experiment(
            find_project_root(),
            approved_by=approved_by,
            reason=reason,
            deactivated_at=datetime.now().astimezone().replace(microsecond=0),
        )
        if json_output:
            typer.echo(agent_json_text(inactive.model_dump(mode="json")))
        else:
            typer.echo(f"实验规则已停用：football-analysis@{inactive.ruleset_version}")
    except Exception as exc:
        _fail(exc)


@rules_experiment_app.command("report")
def rules_experiment_report(
    version: Annotated[str, typer.Argument()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        payload = experiment_report(find_project_root(), version)
        if json_output:
            typer.echo(agent_json_text(payload))
        else:
            typer.echo(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    except Exception as exc:
        _fail(exc)


@rules_intake_app.command("ingest")
def rules_intake_ingest(
    source_file: Annotated[Path, typer.Option("--file")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        result = ingest_intake(find_project_root(), source_file)
        payload = result.model_dump(mode="json")
        typer.echo(agent_json_text(payload) if json_output else f"规则 intake 已归档：{result.intake_id} / {result.import_status}")
    except Exception as exc:
        _fail(exc)


@rules_intake_app.command("inspect")
def rules_intake_inspect(
    intake_id: Annotated[str, typer.Option("--intake")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        atoms = atomize_intake(find_project_root(), intake_id)
        payload = {"schema_version": 1, "intake_id": intake_id, "atoms": [item.model_dump(mode="json") for item in atoms]}
        typer.echo(agent_json_text(payload) if json_output else f"规则原子已生成：{len(atoms)} 条")
    except Exception as exc:
        _fail(exc)


@rules_intake_app.command("scaffold")
def rules_intake_scaffold(
    intake_id: Annotated[str, typer.Option("--intake")],
    proposal: Annotated[str, typer.Option("--proposal")] = "1.7.0",
) -> None:
    try:
        target = scaffold_intake_rules(find_project_root(), intake_id, proposal)
        typer.echo(f"提示实验候选已生成：{target}")
    except Exception as exc:
        _fail(exc)


@rules_intake_app.command("status")
def rules_intake_status(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    try:
        payload = intake_status(find_project_root())
        typer.echo(agent_json_text(payload) if json_output else yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
    except Exception as exc:
        _fail(exc)


@rules_intake_app.command("promote")
def rules_intake_promote(
    rule_id: Annotated[str, typer.Option("--rule")],
    target: Annotated[str, typer.Option("--to")],
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    try:
        if target != "prediction_experiment":
            raise ValueError("promote 当前只支持 --to prediction_experiment")
        set_rule_disposition(find_project_root(), rule_id, "promoted_to_prediction", reason=reason)
    except Exception as exc:
        _fail(exc)


@rules_intake_app.command("defer")
def rules_intake_defer(rule_id: Annotated[str, typer.Option("--rule")], reason: Annotated[str, typer.Option("--reason")]) -> None:
    try:
        set_rule_disposition(find_project_root(), rule_id, "deferred", reason=reason)
        typer.echo(f"规则已延后：{rule_id}")
    except Exception as exc:
        _fail(exc)


@rules_intake_app.command("retire")
def rules_intake_retire(rule_id: Annotated[str, typer.Option("--rule")], reason: Annotated[str, typer.Option("--reason")]) -> None:
    try:
        set_rule_disposition(find_project_root(), rule_id, "retired", reason=reason)
        typer.echo(f"规则已退役：{rule_id}")
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
