from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator
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


class ExcludedRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    reason: str = Field(min_length=2)


class AnalysisTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    ruleset_id: str
    ruleset_version: str
    data_cutoff_at: datetime
    applied_rule_ids: list[str] = Field(min_length=1)
    excluded_rules: list[ExcludedRule] = Field(default_factory=list)
    source_refs: list[str] = Field(min_length=1)
    scenario_instance_ids: list[str] = Field(default_factory=list)
    case_ids: list[str] = Field(default_factory=list)

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


def workflow_status(root: Path, path: Path) -> dict[str, Any]:
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
        if receipt.schema_version == 4:
            next_actions.append("运行 agent validate-draft、agent render-draft 和 agent prepare-lock")
        else:
            next_actions.append("运行 agent validate-draft，通过后执行 lock")
    elif status == MatchStatus.LOCKED:
        next_actions.append("等待赛果；临场信息仅追加到 live-update")
    elif status == MatchStatus.FINISHED:
        next_actions.append("运行 prepare-review 并解析全部场景")
    return {
        "schema_version": 1,
        "match_id": document.metadata.match_id,
        "match_path": path.resolve().as_posix(),
        "match_status": status.value,
        "stages": stages,
        "next_actions": next_actions,
    }


def start_agent(
    root: Path,
    path: Path,
    *,
    as_of: datetime | None = None,
    markets: list[PrimaryMarket] | None = None,
) -> dict[str, Any]:
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
    return {
        "schema_version": 1,
        "task": "prepare_analysis_only",
        "generated_prediction": False,
        "context_path": context_path.relative_to(root).as_posix(),
        "ruleset": f"{receipt.ruleset_id}@{receipt.ruleset_version}",
        "data_cutoff_at": receipt.as_of.isoformat(),
        "trusted_instruction": payload["trusted_instruction"],
        "required_rules": payload["required_rules"],
        "conditional_rules": payload["conditional_rules"],
        "competition_profile": receipt.competition_profile,
        "calibration_contract_version": receipt.calibration_contract_version,
        "calibration_config_sha256": receipt.calibration_config_sha256,
        "applicable_calibration_rule_ids": receipt.applicable_calibration_rule_ids,
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
    if outlook.schema_version != 2:
        return ["校准契约要求 AnalysisOutlook V2"]
    if outlook.competition_profile != receipt.competition_profile:
        errors.append("AnalysisOutlook competition_profile 与分析回执不一致")
    if outlook.calibration_contract_version != receipt.calibration_contract_version:
        errors.append("AnalysisOutlook 校准契约版本与分析回执不一致")
    if str(outlook.data_mode) == "pass":
        return errors
    ruleset = load_ruleset(root, f"{receipt.ruleset_id}@{receipt.ruleset_version}")
    config = CalibrationConfig.model_validate(ruleset.calibration_config or {})
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
    if outlook.calibration_summary:
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
) -> list[str]:
    errors: list[str] = []
    reasoning = document.sections["prematch-reasoning"]
    receipt = parse_receipt(reasoning)
    if receipt is None:
        return ["缺少规则检索回执"]
    errors.extend(validate_analysis_receipt(root, document, require_current=require_current))
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
    if receipt.schema_version == 4:
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
            if receipt.schema_version == 4:
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
) -> Path:
    document = MatchDocument.load(path)
    errors = validate_analysis_draft(root, document, outlook=outlook)
    if errors:
        raise ValueError("；".join(errors))
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    assert receipt is not None
    report = analysis_report_text(document, receipt)
    target = root / "raw" / "matches" / document.metadata.match_id / "analysis-report.md"
    atomic_write_text(target, report)
    return target


def analysis_report_text(document: MatchDocument, receipt: Any) -> str:
    analysis = parse_analysis_content(document.sections["prematch-reasoning"])
    cutoff = receipt.as_of.strftime("%Y-%m-%d %H:%M")
    kickoff = document.metadata.kickoff_at.strftime("%Y-%m-%d %H:%M")
    return (
        f"# {document.metadata.home_team} VS {document.metadata.away_team} 盘面完整推演（数据截止：{cutoff}）\n\n"
        f"比赛时间：{kickoff}\n\n"
        "场地：未记录\n\n"
        f"比赛类型：{document.metadata.competition}\n\n"
        f"{analysis.strip()}\n"
    )



def doctor(root: Path) -> dict[str, Any]:
    from .desktop_agents import doctor as desktop_doctor

    return desktop_doctor(root)


def json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
