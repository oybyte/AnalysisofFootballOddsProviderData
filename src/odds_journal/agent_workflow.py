from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
import yaml

from .analysis_context import (
    analysis_is_placeholder,
    parse_analysis_content,
    parse_receipt,
    prepare_analysis_context,
    validate_analysis_receipt,
)
from .case_retrieval import parse_case_receipt, validate_case_receipt
from .markdown import MatchDocument, has_substantive_content
from .models import AnalysisOutlook, MatchStatus, PrimaryMarket
from .ledger import atomic_write_text
from .paths import match_files
from .scenarios import parse_scenarios, validate_scenario_workflow


TRACE_START = "<!-- analysis-trace:start -->"
TRACE_END = "<!-- analysis-trace:end -->"
TRACE_RE = re.compile(
    rf"{re.escape(TRACE_START)}\s*### 分析追踪\s*```yaml\s*(.*?)\s*```\s*{re.escape(TRACE_END)}",
    re.DOTALL,
)
CERTAINTY_TERMS = ("必中", "必胜", "稳胆", "百分百", "100%", "绝对命中")
ANALYSIS_HEADINGS = [
    "### 一、澳盘时序梳理与盘路定性",
    "### 二、胜平负欧赔走势",
    "### 三、凯利指数交叉验证",
    "### 四、大小球辅助参考",
    "### 五、综合权重推演",
    "### 六、后市观测清单",
]
CHAPTER_FIVE_ITEMS = (
    "胜平负优先级",
    "亚洲让球优先级",
    "固定让球胜平负优先级",
    "总进球",
    "比分权重",
    "校准规则处置",
)
CHAPTER_SIX_ITEMS = ("正向强化信号", "风险预警信号")


class PrematchReadinessV1(BaseModel):
    """Read-only explanation of what remains before a normal prematch lock."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    kickoff_at: datetime
    checked_at: datetime
    match_status: str
    kickoff_passed: bool
    ruleset_origin: Literal["published", "proposal"] | None = None
    completed_stages: dict[str, bool]
    candidate_status: Literal["missing", "invalid", "stale", "valid", "locked"]
    blockers: list[str] = Field(default_factory=list)
    next_command: str | None = None
    can_prepare_lock: bool = False
    can_lock: bool = False
    summary: str
    generated_prediction: Literal[False] = False

    @field_validator("kickoff_at", "checked_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("赛前就绪检查时间必须包含时区")
        return value


class ExcludedRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    reason: str = Field(min_length=2)


class AnalysisTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2] = 1
    ruleset_id: str
    ruleset_version: str
    data_cutoff_at: datetime
    applied_rule_ids: list[str] = Field(min_length=1)
    excluded_rules: list[ExcludedRule] = Field(default_factory=list)
    source_refs: list[str] = Field(min_length=1)
    scenario_instance_ids: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)
    ruleset_origin: Literal["published", "proposal"] | None = None
    deterministic_rule_ids: list[str] = Field(default_factory=list)
    disposition_rule_ids: list[str] = Field(default_factory=list)
    control_rule_ids: list[str] = Field(default_factory=list)
    profile_chain: list[str] = Field(default_factory=list)
    evaluation_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("data_cutoff_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("analysis_trace.data_cutoff_at 必须包含时区")
        return value

    @field_validator("applied_rule_ids", "source_refs", "scenario_instance_ids", "case_ids")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("analysis_trace 列表不得重复")
        return value

    @field_validator("deterministic_rule_ids", "disposition_rule_ids", "control_rule_ids", "profile_chain")
    @classmethod
    def unique_contract4_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("AnalysisTrace V2 列表不得重复")
        return value

    @model_validator(mode="after")
    def validate_v2(self) -> "AnalysisTrace":
        if self.schema_version == 2:
            if self.ruleset_origin is None or not self.deterministic_rule_ids or not self.profile_chain or not self.evaluation_bundle_sha256:
                raise ValueError("AnalysisTrace V2 必须绑定规则来源、机器规则、profile 链和评估 bundle")
        return self


def parse_analysis_trace(reasoning: str, *, required: bool = False) -> AnalysisTrace | None:
    analysis = parse_analysis_content(reasoning)
    starts = analysis.count(TRACE_START)
    ends = analysis.count(TRACE_END)
    if starts == 0 and ends == 0:
        if required:
            raise ValueError("分析正文缺少 analysis-trace 区块")
        return None
    if starts != 1 or ends != 1:
        raise ValueError("analysis-trace 标记必须各出现一次")
    match = TRACE_RE.search(analysis)
    if not match:
        raise ValueError("analysis-trace 格式无效")
    return AnalysisTrace.model_validate(yaml.safe_load(match.group(1)) or {})


def render_analysis_trace(trace: AnalysisTrace) -> str:
    body = yaml.safe_dump(trace.model_dump(mode="json"), allow_unicode=True, sort_keys=False).rstrip()
    return f"{TRACE_START}\n### 分析追踪\n\n```yaml\n{body}\n```\n{TRACE_END}"


def _match_command(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _load_outlook(root: Path, document: MatchDocument) -> tuple[AnalysisOutlook | None, list[str]]:
    path = root / "raw" / "matches" / document.metadata.match_id / "analysis-outlook.yml"
    if not path.is_file():
        return None, ["缺少 AnalysisOutlook；请先完成评估和草稿校验"]
    try:
        return AnalysisOutlook.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {}), []
    except Exception as exc:
        return None, [f"AnalysisOutlook 无效：{exc}"]


def prematch_readiness(
    root: Path,
    path: Path,
    *,
    checked_at: datetime | None = None,
) -> PrematchReadinessV1:
    """Inspect, but never create or alter, the formal prematch lock chain."""

    document = MatchDocument.load(path)
    metadata = document.metadata
    status = MatchStatus(metadata.status)
    now = checked_at or datetime.now(ZoneInfo(metadata.timezone)).replace(microsecond=0)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("checked_at 必须包含时区")
    now = now.astimezone(ZoneInfo(metadata.timezone))
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    scenarios = parse_scenarios(document.sections["prematch-reasoning"])
    case_receipt = parse_case_receipt(document.sections["prematch-reasoning"])
    analysis_complete = not analysis_is_placeholder(document.sections["prematch-reasoning"])
    facts_ready = has_substantive_content(document.sections["prematch-facts"])
    outlook, outlook_errors = _load_outlook(root, document)
    command_path = _match_command(root, path)
    report_path = root / "raw" / "matches" / metadata.match_id / "analysis-report.md"
    report_required = receipt is not None and receipt.schema_version in {4, 6, 7}
    report_ready = receipt is not None and (
        not report_required
        or (report_path.is_file() and report_path.read_text(encoding="utf-8") == analysis_report_text(document, receipt, outlook=outlook))
    )
    draft_errors: list[str] = []
    if receipt is not None and analysis_complete and outlook is not None:
        try:
            draft_errors = validate_analysis_draft(
                root,
                document,
                outlook=outlook,
                allow_proposal=receipt.ruleset_origin == "proposal",
            )
        except Exception as exc:
            draft_errors = [str(exc)]
    draft_valid = receipt is not None and analysis_complete and outlook is not None and not draft_errors
    completed_stages = {
        "facts_archived": facts_ready,
        "rules_prepared": receipt is not None,
        "scenarios_recorded": scenarios is not None,
        "cases_retrieved": case_receipt is not None,
        "analysis_completed": analysis_complete,
        "draft_validated": draft_valid,
        "report_rendered": report_ready,
    }

    candidate_status: Literal["missing", "invalid", "stale", "valid", "locked"] = "missing"
    candidate_errors: list[str] = []
    if status in {MatchStatus.LOCKED, MatchStatus.FINISHED, MatchStatus.REVIEWED}:
        candidate_status = "locked"
    elif status != MatchStatus.HISTORICAL_FINISHED:
        # lock_lifecycle imports this module, so this must remain a local import.
        from .lock_lifecycle import latest_lock_candidate, validate_lock_candidate

        try:
            candidate = latest_lock_candidate(root, metadata.match_id)
        except Exception as exc:
            candidate = None
            candidate_status = "invalid"
            candidate_errors.append(f"锁定候选回执无法读取：{exc}")
        if candidate is not None:
            _, candidate_receipt = candidate
            try:
                validate_lock_candidate(root, path, candidate_receipt, require_current=True)
            except Exception as exc:
                candidate_errors = [str(exc)]
                candidate_status = "stale"
            else:
                candidate_status = "valid"

    kickoff_passed = now >= metadata.kickoff_at
    blockers: list[str] = []
    next_command: str | None = None
    proposal = receipt is not None and receipt.ruleset_origin == "proposal"
    if status == MatchStatus.HISTORICAL_FINISHED:
        blockers.append("历史赛果已归档；赛前未锁定，禁止补建候选、锁定或结算")
    elif status in {MatchStatus.FINISHED, MatchStatus.REVIEWED}:
        blockers.append("比赛已完成正式生命周期，不再执行赛前锁定")
    elif status == MatchStatus.LOCKED:
        blockers.append("比赛已锁定；临场材料只能追加到 live-update")
    elif kickoff_passed and candidate_status in {"missing", "invalid", "stale"}:
        blockers.append("比赛已开赛且无有效赛前候选，禁止补建 LockCandidateReceipt")
    elif proposal:
        blockers.append("当前规则回执来自 proposal，仅可离线实验，不可生成候选或锁定")
    elif candidate_status == "invalid":
        blockers.extend(candidate_errors)
        blockers.append("锁定候选回执无效，必须在开赛前重新生成")
        next_command = (
            f"odds-journal agent prepare-lock {command_path} "
            "--market MARKET --selection SELECTION --confidence VALUE"
        )
    elif candidate_status == "stale":
        blockers.extend(candidate_errors)
        blockers.append("锁定候选与当前赛前内容不一致，必须重新校验、渲染并冻结")
        next_command = f"odds-journal agent validate-draft {command_path}"
    elif not facts_ready:
        blockers.append("缺少可核验赛前事实")
        next_command = "补充赛前事实和可核验来源"
    elif receipt is None:
        blockers.append("尚未准备分析规则上下文")
        next_command = f"odds-journal agent start {command_path}"
    elif receipt.schema_version >= 2 and scenarios is None:
        blockers.append("尚未登记赛前场景或 no-scenario")
        next_command = f"odds-journal scenario no-scenario {command_path} --reason REASON"
    elif receipt.schema_version >= 2 and case_receipt is None:
        blockers.append("尚未检索可比较案例")
        next_command = f"odds-journal retrieve-cases {command_path}"
    elif not analysis_complete:
        blockers.append("尚未完成赛前分析正文和 analysis-trace")
        next_command = "填写赛前分析正文及 analysis-trace"
    elif receipt.schema_version in {6, 7} and outlook is None:
        blockers.extend(outlook_errors)
        blockers.append(f"Contract {receipt.calibration_contract_version} 尚未形成 AnalysisOutlook")
        next_command = (
            f"odds-journal agent evaluate-draft {command_path} "
            "--draft-file DRAFT.yml --dispositions-file DISPOSITIONS.yml"
        )
    elif not draft_valid:
        blockers.extend(draft_errors or outlook_errors)
        blockers.append("分析草稿尚未通过锁定前校验")
        next_command = f"odds-journal agent validate-draft {command_path}"
    elif not report_ready:
        blockers.append("规范分析报告缺失或已过期")
        next_command = f"odds-journal agent render-draft {command_path}"
    elif candidate_status == "missing":
        blockers.append("缺少开赛前 LockCandidateReceiptV1/V2")
        next_command = (
            f"odds-journal agent prepare-lock {command_path} "
            "--market MARKET --selection SELECTION --confidence VALUE"
        )
    elif candidate_status == "valid" and not kickoff_passed:
        next_command = f"odds-journal lock {command_path} --candidate-file CANDIDATE.yml"
    elif candidate_status == "valid":
        blockers.append("比赛已开赛；有效候选只能由完赛审计链按既有规则处理，不能再普通锁定")

    can_prepare_lock = (
        status in {MatchStatus.DRAFT, MatchStatus.TRACKING}
        and not kickoff_passed
        and not proposal
        and draft_valid
        and report_ready
        and candidate_status in {"missing", "invalid", "stale"}
    )
    can_lock = candidate_status == "valid" and not kickoff_passed and status in {MatchStatus.DRAFT, MatchStatus.TRACKING}
    if status == MatchStatus.HISTORICAL_FINISHED:
        summary = "历史赛果已归档，赛前未锁定，禁止补建"
    elif candidate_status == "locked":
        summary = "已锁定"
    elif candidate_status == "valid" and can_lock:
        summary = "候选有效，待在开赛前完成锁定"
    elif kickoff_passed and candidate_status in {"missing", "invalid", "stale"}:
        summary = "赛前数据已归档，但候选回执缺失或无效且比赛已开赛，禁止补建"
    elif candidate_status == "stale":
        summary = "候选已过期，必须重新校验并冻结"
    elif candidate_status == "invalid":
        summary = "候选回执无效，必须在开赛前重新生成"
    else:
        summary = "未生成锁定候选，尚未完成正式赛前锁定"
    return PrematchReadinessV1(
        match_id=metadata.match_id,
        kickoff_at=metadata.kickoff_at,
        checked_at=now,
        match_status=status.value,
        kickoff_passed=kickoff_passed,
        ruleset_origin=(receipt.ruleset_origin if receipt else None),
        completed_stages=completed_stages,
        candidate_status=candidate_status,
        blockers=list(dict.fromkeys(blockers)),
        next_command=next_command,
        can_prepare_lock=can_prepare_lock,
        can_lock=can_lock,
        summary=summary,
    )


def prematch_readiness_scan(root: Path, *, before: datetime, checked_at: datetime | None = None) -> list[PrematchReadinessV1]:
    if before.tzinfo is None or before.utcoffset() is None:
        raise ValueError("before 必须包含时区")
    results = []
    for path in match_files(root):
        document = MatchDocument.load(path)
        if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
            continue
        if document.metadata.kickoff_at <= before:
            results.append(prematch_readiness(root, path, checked_at=checked_at))
    return sorted(results, key=lambda item: (item.kickoff_at, item.match_id))


def workflow_status(
    root: Path,
    path: Path,
    *,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    document = MatchDocument.load(path)
    reasoning = document.sections["prematch-reasoning"]
    receipt = parse_receipt(reasoning)
    scenarios = parse_scenarios(reasoning)
    case_receipt = parse_case_receipt(reasoning)
    analysis_complete = not analysis_is_placeholder(reasoning)
    facts_ready = has_substantive_content(document.sections["prematch-facts"])
    status = MatchStatus(document.metadata.status)
    stages = {
        "facts_ready": facts_ready,
        "rules_prepared": receipt is not None,
        "scenarios_recorded": scenarios is not None,
        "cases_retrieved": case_receipt is not None,
        "analysis_completed": analysis_complete,
        "locked": status in {MatchStatus.LOCKED, MatchStatus.FINISHED, MatchStatus.REVIEWED},
        "finished": status in {MatchStatus.FINISHED, MatchStatus.REVIEWED},
        "historical_finished": status == MatchStatus.HISTORICAL_FINISHED,
        "reviewed": status == MatchStatus.REVIEWED,
    }
    next_actions: list[str] = []
    if status == MatchStatus.VOID:
        next_actions.append("比赛已作废，不继续分析")
    elif status == MatchStatus.HISTORICAL_FINISHED:
        next_actions.append("历史赛果已归档；赛前未锁定，禁止预测结算和正式复盘")
    elif not facts_ready:
        next_actions.append("补充赛前事实和可核验来源")
    elif receipt is None:
        next_actions.append("运行 agent start 准备规则上下文")
    elif receipt.schema_version >= 2 and scenarios is None:
        next_actions.append("运行 scenario add 或 scenario no-scenario")
    elif receipt.schema_version >= 2 and case_receipt is None:
        next_actions.append("运行 retrieve-cases")
    elif not analysis_complete:
        next_actions.append("阅读规则和案例后填写分析正文及 analysis-trace")
    elif status in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        if receipt.schema_version in {5, 6, 7, 8} and receipt.ruleset_origin == "proposal":
            if receipt.schema_version == 8:
                next_actions.append("运行 agent build-draft、由 lcz 执行 agent accept-draft，再离线 evaluate/validate/render；提案不得锁定")
            else:
                next_actions.append("运行 agent validate-draft --proposal 和 agent render-draft --proposal；提案不得锁定")
        elif receipt.schema_version == 6:
            next_actions.append(
                "运行 agent evaluate-draft、agent validate-draft、agent render-draft 和 agent prepare-lock"
            )
        elif receipt.schema_version == 4:
            next_actions.append("运行 agent validate-draft、agent render-draft 和 agent prepare-lock")
        else:
            next_actions.append("运行 agent validate-draft，通过后执行 lock")
    elif status == MatchStatus.LOCKED:
        next_actions.append("等待赛果；临场信息仅追加到 live-update")
    elif status == MatchStatus.FINISHED:
        next_actions.append("运行 prepare-review 并解析全部场景")
    readiness = prematch_readiness(root, path, checked_at=checked_at)
    if status in {MatchStatus.DRAFT, MatchStatus.TRACKING} and readiness.kickoff_passed:
        if readiness.candidate_status in {"missing", "invalid", "stale"}:
            next_actions = ["比赛已开赛且无有效赛前候选，禁止补建 LockCandidateReceipt"]
        elif readiness.candidate_status == "valid":
            next_actions = ["比赛已开赛；有效候选只能由完赛审计链按既有规则处理"]
    return {
        "schema_version": 1,
        "match_id": document.metadata.match_id,
        "match_path": path.resolve().as_posix(),
        "match_status": status.value,
        "stages": stages,
        "next_actions": next_actions,
        "prematch_readiness": readiness.model_dump(mode="json"),
    }


def start_agent(
    root: Path,
    path: Path,
    *,
    as_of: datetime | None = None,
    markets: list[PrimaryMarket] | None = None,
    ruleset_spec: str | None = None,
    proposal: bool = False,
) -> dict[str, Any]:
    if proposal and not ruleset_spec:
        raise ValueError("--proposal 必须与明确的 --ruleset 一起使用")
    document = MatchDocument.load(path)
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if as_of is None:
        if now > document.metadata.kickoff_at:
            raise ValueError("当前时间已晚于开赛时间，必须显式提供历史 --as-of")
        as_of = now
    context_path, payload, receipt = prepare_analysis_context(
        root,
        path,
        prepared_at=now,
        as_of=as_of,
        markets=markets,
        ruleset_spec=ruleset_spec,
        proposal=proposal,
    )
    refreshed = MatchDocument.load(path)
    snapshots = refreshed.metadata.market_snapshots
    macau_phases = sorted(
        {
            str(item.phase)
            for item in snapshots
            if item.provider_id == "macau" and str(item.market) == "asian_handicap"
        }
    )
    missing_data: list[str] = []
    if refreshed.metadata.schema_version == 2:
        if not macau_phases:
            missing_data.append("缺少澳门亚盘")
        if not {"opening", "mid", "late"}.issubset(set(macau_phases)):
            missing_data.append("缺少初盘/中盘/临盘三个澳门可比节点")
    experiment_payload: dict[str, Any] | None = None
    if not proposal and receipt.ruleset_origin != "proposal":
        try:
            from .experiments import prepare_experiment_context

            prepared = prepare_experiment_context(root, path, receipt)
            if prepared is not None:
                experiment_path, experiment_receipt = prepared
                experiment_payload = {
                    "active": True,
                    "ruleset": f"football-analysis@{experiment_receipt.experiment_ruleset_version}",
                    "experiment_revision": experiment_receipt.experiment_revision,
                    "proposal_sha256": experiment_receipt.proposal_sha256,
                    "receipt_path": experiment_path.relative_to(root).as_posix(),
                    "receipt_sha256": experiment_receipt.receipt_sha256,
                    "profile_chain": experiment_receipt.profile_chain,
                    "applicable_rule_ids": experiment_receipt.applicable_rule_ids,
                }
        except Exception as exc:
            from .experiments import record_experiment_failure

            record_experiment_failure(
                root,
                match_id=refreshed.metadata.match_id,
                stage="agent_start",
                reason=str(exc),
                recorded_at=now,
            )
            experiment_payload = {"active": False, "status": "failed", "reason": str(exc)}

    # Knowledge Engine V2 状态（旁路阶段，只读）
    knowledge_engine_payload: dict[str, Any] = {"active": False, "status": "not_available"}
    try:
        from .knowledge_engine.adapters.draft_workflow_registry import DraftWorkflowRegistry

        registry = DraftWorkflowRegistry(root)
        ke_status = registry.agent_start_status()
        knowledge_engine_payload = {
            "active": True,
            "status": "shadow_ready" if ke_status["index"]["ready"] else "index_not_ready",
            "contracts": ke_status["contracts"],
            "snapshot": ke_status["snapshot"],
            "index": ke_status["index"],
            "ai": ke_status["ai"],
            "studies": ke_status["studies"],
        }
    except Exception:
        pass

    return {
        "schema_version": 1,
        "task": "prepare_analysis_only",
        "generated_prediction": False,
        "context_path": context_path.relative_to(root).as_posix(),
        "ruleset": f"{receipt.ruleset_id}@{receipt.ruleset_version}",
        "analysis_receipt_schema_version": receipt.schema_version,
        "analysis_outlook_schema_version": 6 if receipt.schema_version == 8 else 5 if receipt.schema_version == 7 else 4 if receipt.schema_version == 6 else 3 if receipt.schema_version == 5 else 2 if receipt.schema_version == 4 else 1 if receipt.schema_version == 3 else None,
        "data_cutoff_at": receipt.as_of.isoformat(),
        "trusted_instruction": payload["trusted_instruction"],
        "required_rules": payload["required_rules"],
        "conditional_rules": payload["conditional_rules"],
        "competition_profile": receipt.competition_profile,
        "calibration_contract_version": receipt.calibration_contract_version,
        "calibration_config_sha256": receipt.calibration_config_sha256,
        "applicable_calibration_rule_ids": receipt.applicable_calibration_rule_ids,
        "ruleset_origin": receipt.ruleset_origin or "published",
        "experiment": experiment_payload or {"active": False, "status": "not_configured"},
        "knowledge_engine": knowledge_engine_payload,
        "missing_data": missing_data,
        "status": workflow_status(root, path),
        "prohibited_actions": [
            "不得在场景和案例回执前写入实质分析",
            "不得把检索案例视为语义等价或预测",
            "不得绕过 validate-draft 锁定 Match V2",
        ],
    }


def _validate_fixed_analysis_structure(analysis: str) -> list[str]:
    errors: list[str] = []
    positions = [analysis.find(item) for item in ANALYSIS_HEADINGS]
    if any(position < 0 for position in positions):
        missing = [item for item, position in zip(ANALYSIS_HEADINGS, positions) if position < 0]
        errors.append("分析正文缺少固定章节：" + "、".join(missing))
        return errors
    if positions != sorted(positions):
        errors.append("分析正文六个固定章节顺序错误")
        return errors
    if any(analysis.count(item) != 1 for item in ANALYSIS_HEADINGS):
        errors.append("分析正文固定章节必须各出现一次")
    chapter_five = analysis[positions[4] : positions[5]]
    missing_five = [item for item in CHAPTER_FIVE_ITEMS if item not in chapter_five]
    if missing_five:
        errors.append("综合权重推演缺少：" + "、".join(missing_five))
    chapter_six = analysis[positions[5] :]
    missing_six = [item for item in CHAPTER_SIX_ITEMS if item not in chapter_six]
    if missing_six:
        errors.append("后市观测清单缺少：" + "、".join(missing_six))
    return errors


def _validate_calibration_outlook(
    root: Path,
    document: MatchDocument,
    receipt: Any,
    outlook: AnalysisOutlook,
) -> list[str]:
    from .calibration import CalibrationConfig, evaluate_calibration
    from .rules import load_ruleset

    errors: list[str] = []
    expected_outlook = 6 if receipt.schema_version == 8 else 5 if receipt.schema_version == 7 else 4 if receipt.schema_version == 6 else 3 if receipt.schema_version == 5 else 2
    if outlook.schema_version != expected_outlook:
        return [f"校准契约要求 AnalysisOutlook V{expected_outlook}"]
    if outlook.competition_profile != receipt.competition_profile:
        errors.append("AnalysisOutlook competition_profile 与分析回执不一致")
    if outlook.calibration_contract_version != receipt.calibration_contract_version:
        errors.append("AnalysisOutlook 校准契约版本与分析回执不一致")
    ruleset = load_ruleset(
        root,
        f"{receipt.ruleset_id}@{receipt.ruleset_version}",
        allow_proposal=receipt.schema_version in {5, 6, 7, 8} and receipt.ruleset_origin == "proposal",
    )
    config = CalibrationConfig.model_validate(ruleset.calibration_config or {})
    if receipt.calibration_contract_version == 8:
        from .formal_draft import validate_outlook_bundle_v3

        errors.extend(validate_outlook_bundle_v3(root, document.path, receipt, config, outlook))
        return errors
    if str(outlook.data_mode) == "pass":
        return errors
    if receipt.calibration_contract_version == 4:
        from .rule_engine.evaluation import validate_outlook_bundle

        errors.extend(validate_outlook_bundle(
            root=root,
            metadata=document.metadata,
            receipt=receipt,
            config=config,
            outlook=outlook,
        ))
        return errors
    if receipt.calibration_contract_version == 7:
        from .rule_engine.evaluation_v5 import validate_outlook_bundle_v2

        errors.extend(validate_outlook_bundle_v2(
            root=root, metadata=document.metadata, receipt=receipt, config=config, outlook=outlook,
        ))
        return errors
    profile, expected_events, expected_summary = evaluate_calibration(
        document.metadata,
        outlook,
        config,
        cutoff=receipt.as_of,
    )
    if profile != receipt.competition_profile:
        errors.append("机器校准 profile 与分析回执不一致")
    actual_by_id = {item.rule_id: item for item in outlook.calibration_events}
    for expected in expected_events:
        actual = actual_by_id.get(expected.rule_id)
        if actual is None:
            errors.append(f"缺少校准规则处置：{expected.rule_id}")
            continue
        fields = (
            "triggered",
            "not_triggered_reason",
            "applicability",
            "effect",
            "target_market",
            "target_selection",
            "source_dimensions",
            "source_provider_ids",
            "source_snapshot_ids",
            "correlation_keys",
            "threshold_observations",
            "before_ranking",
            "proposed_ranking",
            "adjustment_level",
        )
        mismatches = [field for field in fields if getattr(actual, field) != getattr(expected, field)]
        if mismatches:
            errors.append(f"{expected.rule_id} 与确定性触发结果不一致：{', '.join(mismatches)}")
    if receipt.schema_version == 5:
        snapshots = {item.snapshot_id: item for item in document.metadata.market_snapshots}
        assert outlook.score_matrix is not None
        for row in outlook.score_matrix.rows:
            for snapshot_id in row.source_snapshot_ids:
                snapshot = snapshots.get(snapshot_id)
                if snapshot is None:
                    errors.append(f"评分矩阵引用不存在快照：{snapshot_id}")
                elif snapshot.provider_id not in row.source_provider_ids:
                    errors.append(f"评分矩阵 provider 与快照不一致：{snapshot_id}")
                elif row.evidence_ids and snapshot.evidence_id not in row.evidence_ids:
                    errors.append(f"评分矩阵 evidence_id 与快照不一致：{snapshot_id}")
        triggered = {item.rule_id: item for item in outlook.calibration_events if item.triggered}
        for rule_id, item in triggered.items():
            if item.effect == "total_goals_pool" and not any(candidate.rule_id == rule_id for candidate in outlook.total_goals_candidate_pool):
                errors.append(f"{rule_id} 触发后缺少总进球候选")
            if item.effect == "score_pool" and not any(candidate.rule_id == rule_id for candidate in outlook.score_candidate_pool):
                errors.append(f"{rule_id} 触发后缺少比分候选")
            if item.effect == "outcome_risk_pool" and not any(candidate.rule_id == rule_id for candidate in outlook.outcome_risk_pool):
                errors.append(f"{rule_id} 触发后缺少结果风险候选")
    elif outlook.calibration_summary:
        if outlook.calibration_summary.one_x_two.baseline_ranking != expected_summary.one_x_two.baseline_ranking:
            errors.append("胜平负校准基础排序与分析输出不一致")
        if outlook.calibration_summary.fixed_handicap_1x2.baseline_ranking != expected_summary.fixed_handicap_1x2.baseline_ranking:
            errors.append("固定让球校准基础排序与分析输出不一致")
        if outlook.calibration_summary.asian_handicap != expected_summary.asian_handicap:
            errors.append("亚洲盘 cover_signal 与触发规则不一致")
    return errors


def validate_analysis_draft(
    root: Path,
    document: MatchDocument,
    *,
    outlook: AnalysisOutlook | None = None,
    require_current: bool = True,
    allow_proposal: bool = False,
) -> list[str]:
    errors: list[str] = []
    reasoning = document.sections["prematch-reasoning"]
    receipt = parse_receipt(reasoning)
    if receipt is None:
        return ["缺少规则检索回执"]
    errors.extend(validate_analysis_receipt(root, document, require_current=require_current, allow_proposal=allow_proposal))
    scenarios = parse_scenarios(reasoning)
    case_receipt = parse_case_receipt(reasoning)
    if receipt.schema_version >= 2:
        errors.extend(validate_scenario_workflow(document, require_v2=True))
        errors.extend(validate_case_receipt(root, document, require_current=require_current))
    analysis = parse_analysis_content(reasoning)
    if analysis_is_placeholder(reasoning):
        errors.append("分析正文仍是模板或缺少实质内容")
    if any(term in analysis for term in CERTAINTY_TERMS):
        errors.append("分析正文包含确定性承诺用语")
    if receipt.schema_version >= 4:
        errors.extend(_validate_fixed_analysis_structure(analysis))
    try:
        trace = parse_analysis_trace(reasoning, required=receipt.schema_version >= 3)
        if trace:
            if (trace.ruleset_id, trace.ruleset_version) != (
                receipt.ruleset_id,
                receipt.ruleset_version,
            ):
                errors.append("analysis-trace 规则集与检索回执不一致")
            if trace.data_cutoff_at != receipt.as_of:
                errors.append("analysis-trace 数据截止时间与检索回执不一致")
            if receipt.schema_version in {6, 7, 8}:
                if trace.schema_version != 2:
                    errors.append("Contract 4/7/8 必须使用 AnalysisTrace V2")
                if trace.ruleset_origin != receipt.ruleset_origin:
                    errors.append("AnalysisTrace V2 规则来源与回执不一致")
                if trace.profile_chain != receipt.competition_profiles:
                    errors.append("AnalysisTrace V2 profile 链与回执不一致")
                if outlook and trace.evaluation_bundle_sha256 != outlook.evaluation_bundle_sha256:
                    errors.append("AnalysisTrace V2 未绑定 Outlook 的评估 bundle")
            loaded_ids = {
                item.document_id
                for item in [*receipt.required_documents, *receipt.conditional_documents]
            }
            applied = set(trace.applied_rule_ids)
            excluded = {item.rule_id for item in trace.excluded_rules}
            if applied & excluded:
                errors.append("同一规则不能同时采用和排除")
            if applied | excluded != loaded_ids:
                errors.append("analysis-trace 必须逐项处置全部已加载规则")
            scenario_ids = (
                {item.scenario_instance_id for item in scenarios.instances} if scenarios else set()
            )
            if set(trace.scenario_instance_ids) != scenario_ids:
                errors.append("analysis-trace 场景 ID 与场景区块不一致")
            case_ids = {item.case_id for item in case_receipt.selected_cases} if case_receipt else set()
            if set(trace.case_ids) != case_ids:
                errors.append("analysis-trace 案例 ID 与案例回执不一致")
    except Exception as exc:
        errors.append(str(exc))
    if document.metadata.schema_version == 2:
        if outlook is None:
            errors.append("Match V2 必须提供 analysis_outlook")
        else:
            try:
                values = document.metadata.model_dump(mode="json")
                values["analysis_outlook"] = outlook.model_dump(mode="json")
                document.metadata.__class__.model_validate(values)
            except Exception as exc:
                errors.append(str(exc))
            if receipt.schema_version >= 4:
                try:
                    errors.extend(_validate_calibration_outlook(root, document, receipt, outlook))
                except Exception as exc:
                    errors.append(str(exc))
    return list(dict.fromkeys(errors))


def render_analysis_report(
    root: Path,
    path: Path,
    *,
    outlook: AnalysisOutlook,
    allow_proposal: bool = False,
) -> Path:
    document = MatchDocument.load(path)
    errors = validate_analysis_draft(root, document, outlook=outlook, allow_proposal=allow_proposal)
    if errors:
        raise ValueError("；".join(errors))
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    assert receipt is not None
    report = analysis_report_text(document, receipt, outlook=outlook)
    target = root / "raw" / "matches" / document.metadata.match_id / "analysis-report.md"
    atomic_write_text(target, report)
    return target


def analysis_report_text(document: MatchDocument, receipt: Any, *, outlook: AnalysisOutlook | None = None) -> str:
    analysis = parse_analysis_content(document.sections["prematch-reasoning"])
    cutoff = receipt.as_of.strftime("%Y-%m-%d %H:%M")
    kickoff = document.metadata.kickoff_at.strftime("%Y-%m-%d %H:%M")
    market_notice = ""
    if outlook and outlook.schema_version in {5, 6}:
        passed = [
            f"{market}：{'；'.join(outlook.market_pass_reasons.get(market, []))}"
            for market, status in outlook.market_statuses.items() if status == "pass"
        ]
        degraded = [
            f"{market}：{'；'.join((outlook.market_assessments.get(market) or {}).get('degradation_reasons', []))}"
            for market, status in outlook.market_statuses.items() if status == "degraded"
        ]
        notices = []
        if degraded:
            notices.append("- 降级判断：" + "；".join(degraded))
        if passed:
            notices.append("- 无判断：" + "；".join(passed))
        if notices:
            market_notice = "\n\n## 机器市场状态\n\n" + "\n".join(notices) + "\n"
    return (
        f"# {document.metadata.home_team} VS {document.metadata.away_team} 盘面完整推演（数据截止：{cutoff}）\n\n"
        f"比赛时间：{kickoff}\n\n"
        "场地：未记录\n\n"
        f"比赛类型：{document.metadata.competition}\n\n"
        f"{analysis.strip()}\n{market_notice}"
    )



def doctor(root: Path) -> dict[str, Any]:
    from .desktop_agents import doctor as desktop_doctor

    return desktop_doctor(root)


def json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
