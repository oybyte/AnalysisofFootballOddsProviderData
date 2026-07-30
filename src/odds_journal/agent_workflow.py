from __future__ import annotations

from datetime import datetime
from importlib import metadata as importlib_metadata
import json
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
from .indexing import INDEX_SCHEMA_VERSION, current_source_fingerprint, index_metadata
from .markdown import MatchDocument, has_substantive_content
from .models import AnalysisOutlook, MatchStatus, PrimaryMarket
from .rules import active_ruleset, load_ruleset, sha256_file, validate_rules
from .scenarios import parse_scenarios, validate_scenario_workflow


TRACE_START = "<!-- analysis-trace:start -->"
TRACE_END = "<!-- analysis-trace:end -->"
TRACE_RE = re.compile(
    rf"{re.escape(TRACE_START)}\s*### 分析追踪\s*```yaml\s*(.*?)\s*```\s*{re.escape(TRACE_END)}",
    re.DOTALL,
)
CERTAINTY_TERMS = ("必中", "必胜", "稳胆", "百分百", "100%", "绝对命中")


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
        "reviewed": status == MatchStatus.REVIEWED,
    }
    next_actions: list[str] = []
    if status == MatchStatus.VOID:
        next_actions.append("比赛已作废，不继续分析")
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
        "missing_data": missing_data,
        "status": workflow_status(root, path),
        "prohibited_actions": [
            "不得在场景和案例回执前写入实质分析",
            "不得把检索案例视为语义等价或预测",
            "不得绕过 validate-draft 锁定 Match V2",
        ],
    }


def validate_analysis_draft(
    root: Path,
    document: MatchDocument,
    *,
    outlook: AnalysisOutlook | None = None,
) -> list[str]:
    errors: list[str] = []
    reasoning = document.sections["prematch-reasoning"]
    receipt = parse_receipt(reasoning)
    if receipt is None:
        return ["缺少规则检索回执"]
    errors.extend(validate_analysis_receipt(root, document, require_current=True))
    scenarios = parse_scenarios(reasoning)
    case_receipt = parse_case_receipt(reasoning)
    if receipt.schema_version >= 2:
        errors.extend(validate_scenario_workflow(document, require_v2=True))
        errors.extend(validate_case_receipt(root, document, require_current=True))
    analysis = parse_analysis_content(reasoning)
    if analysis_is_placeholder(reasoning):
        errors.append("分析正文仍是模板或缺少实质内容")
    if any(term in analysis for term in CERTAINTY_TERMS):
        errors.append("分析正文包含确定性承诺用语")
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
    return list(dict.fromkeys(errors))


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(r"\d+", value)[:4])


def _windows_products() -> dict[str, dict[str, Any]]:
    products = {
        "teloswork": {"display_name": "telosWork", "minimum_version": "3.7.8", "tested_version": "3.7.8"},
        "workbuddy": {"display_name": "WorkBuddy", "minimum_version": "5.3.5", "tested_version": "5.3.5"},
        "trae-work": {"display_name": "TRAE Work", "minimum_version": "3.3.80", "tested_version": "3.3.80"},
    }
    if platform.system() != "Windows":
        return products
    try:
        import winreg

        roots = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, key_path in roots:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        with winreg.OpenKey(key, winreg.EnumKey(key, index)) as child:
                            try:
                                name = str(winreg.QueryValueEx(child, "DisplayName")[0])
                            except OSError:
                                continue
                            target = None
                            lowered = name.lower()
                            if "teloswork" in lowered:
                                target = "teloswork"
                            elif "workbuddy" in lowered:
                                target = "workbuddy"
                            elif "trae" in lowered:
                                target = "trae-work"
                            if target:
                                try:
                                    version = str(winreg.QueryValueEx(child, "DisplayVersion")[0])
                                except OSError:
                                    version = "unknown"
                                try:
                                    icon = str(winreg.QueryValueEx(child, "DisplayIcon")[0]).split(",", 1)[0]
                                except OSError:
                                    icon = ""
                                products[target].update(
                                    installed=True,
                                    version=version,
                                    executable=icon,
                                )
            except OSError:
                continue
    except ImportError:
        pass
    return products


def doctor(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    python_ok = sys.version_info[:2] == (3, 11)
    checks["python"] = {"version": platform.python_version(), "ok": python_ok}
    if not python_ok:
        errors.append("必须使用 Python 3.11")
    venv_python = root / ".venv" / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    checks["venv"] = {"path": venv_python.as_posix(), "ok": venv_python.exists()}
    if not venv_python.exists():
        errors.append("项目虚拟环境不存在")
    try:
        package_version = importlib_metadata.version("odds-journal")
    except importlib_metadata.PackageNotFoundError:
        package_version = "not-installed"
        errors.append("odds-journal 未安装到当前解释器")
    checks["cli"] = {"version": package_version, "ok": package_version == "0.1.0"}
    active_spec = None
    try:
        active = active_ruleset(root)
        active_spec = f"{active.ruleset_id}@{active.ruleset_version}"
        ruleset = load_ruleset(root, f"{active.ruleset_id}@{active.ruleset_version}")
        rule_errors = [error for values in validate_rules(root).values() for error in values]
        checks["ruleset"] = {
            "id": active.ruleset_id,
            "version": active.ruleset_version,
            "sha256": ruleset.content_sha256,
            "ok": not rule_errors,
        }
        errors.extend(rule_errors)
    except Exception as exc:
        checks["ruleset"] = {"ok": False, "error": str(exc)}
        errors.append(str(exc))
    manifest_path = root / "ai" / "desktop-agent-manifest.yml"
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if manifest.get("cli_version") != package_version:
            errors.append("桌面智能体 manifest 的 CLI 版本与当前包不一致")
        if active_spec and manifest.get("active_ruleset") != active_spec:
            errors.append("桌面智能体 manifest 的活动规则集与 active.yml 不一致")
        instruction_checks = []
        for item in manifest.get("trusted_instructions", []):
            path = root / item["path"]
            raw = path.read_text(encoding="utf-8")
            front = yaml.safe_load(raw.split("---", 2)[1]) or {}
            digest = sha256_file(path)
            ok = (
                front.get("document_id") == item.get("document_id")
                and front.get("document_type") == "instruction"
                and front.get("trusted_instruction") is True
                and digest == item.get("content_sha256")
            )
            instruction_checks.append({"path": item["path"], "sha256": digest, "ok": ok})
            if not ok:
                errors.append(f"可信指令清单或哈希不匹配：{item['path']}")
        checks["trusted_instructions"] = instruction_checks
    except Exception as exc:
        checks["trusted_instructions"] = {"ok": False, "error": str(exc)}
        errors.append(str(exc))
    metadata = index_metadata(root)
    expected_fingerprint = current_source_fingerprint(root)
    index_ok = (
        metadata.get("schema_version") == str(INDEX_SCHEMA_VERSION)
        and metadata.get("source_fingerprint") == expected_fingerprint
    )
    checks["index"] = {
        "metadata": metadata,
        "expected_source_fingerprint": expected_fingerprint,
        "ok": index_ok,
    }
    if not index_ok:
        warnings.append("检索索引缺失或版本过期，请运行 build-index")
    products = _windows_products()
    for product_id, item in products.items():
        installed = bool(item.get("installed"))
        version = str(item.get("version", "0"))
        item["ok"] = installed and _version_tuple(version) >= _version_tuple(item["minimum_version"])
        if platform.system() == "Windows" and not item["ok"]:
            warnings.append(f"{item['display_name']} 未安装或低于认证版本")
        elif installed and version != item["tested_version"]:
            warnings.append(
                f"{item['display_name']} 当前版本 {version} 尚未完成认证（已认证 {item['tested_version']}）"
            )
    checks["products"] = products
    skill_source = root / "integrations" / "skills" / "football-odds-journal" / "SKILL.md"
    source_hash = sha256_file(skill_source) if skill_source.exists() else None
    home = Path.home()
    workbuddy_base = (
        home / ".workbuddy" / "skills"
        if (home / ".workbuddy" / "skills").exists()
        else home / ".codebuddy" / "skills"
    )
    adapter_paths = {
        "codex-desktop": home / ".codex" / "skills" / "football-odds-journal" / "SKILL.md",
        "workbuddy": workbuddy_base / "football-odds-journal" / "SKILL.md",
    }
    adapter_checks: dict[str, Any] = {}
    for product_id, path in adapter_paths.items():
        installed_hash = sha256_file(path) if path.exists() else None
        adapter_checks[product_id] = {
            "path": path.as_posix(),
            "installed": path.exists(),
            "matches_repository": bool(source_hash and installed_hash == source_hash),
        }
    adapter_checks["trae-work"] = {
        "path": (root / "AGENTS.md").as_posix(),
        "installed": (root / "AGENTS.md").exists(),
        "matches_repository": True,
    }
    telos_package = root / "dist" / "football-odds-journal.skill"
    adapter_checks["teloswork"] = {
        "package_path": telos_package.as_posix(),
        "package_ready": telos_package.exists(),
        "manual_import_required": True,
    }
    checks["adapters"] = adapter_checks
    for product_id in ("codex-desktop", "workbuddy"):
        if not adapter_checks[product_id]["matches_repository"]:
            warnings.append(f"{product_id} Skill 未安装或与仓库版本不一致")
    if not adapter_checks["teloswork"]["package_ready"]:
        warnings.append("telosWork Skill 安装包尚未生成")
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        checks["git"] = {"available": True, "dirty": bool(result.stdout.strip())}
    else:
        checks["git"] = {"available": False, "dirty": None}
        warnings.append("未找到 Git")
    return {
        "schema_version": 1,
        "ok": not errors,
        "platform": platform.system().lower(),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
