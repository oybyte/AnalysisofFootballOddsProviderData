from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner
import yaml

from odds_journal.agent_workflow import _validate_fixed_analysis_structure, workflow_status
from odds_journal.analysis_context import set_analysis_content
from odds_journal.cli import app
from odds_journal.markdown import MatchDocument

from .test_analysis_context import factual_match


def test_schema_four_analysis_uses_fixed_six_sections() -> None:
    valid = """
### 一、澳盘时序梳理与盘路定性
内容
### 二、胜平负欧赔走势
内容
### 三、凯利指数交叉验证
内容
### 四、大小球辅助参考
内容
### 五、综合权重推演
胜平负优先级
亚洲让球优先级
固定让球胜平负优先级
总进球
比分权重
校准规则处置
### 六、后市观测清单
正向强化信号
风险预警信号
"""
    assert _validate_fixed_analysis_structure(valid) == []
    broken = valid.replace("### 四、大小球辅助参考", "### 四、进球参考")
    assert any("缺少固定章节" in item for item in _validate_fixed_analysis_structure(broken))


def test_agent_start_prepares_context_without_prediction(project_root: Path, monkeypatch) -> None:
    path = factual_match(project_root)
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(
        app,
        [
            "agent",
            "start",
            str(path),
            "--market",
            "handicap",
            "--as-of",
            "2026-07-30T17:30:00+08:00",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["generated_prediction"] is False
    assert payload["task"] == "prepare_analysis_only"
    assert payload["analysis_receipt_schema_version"] == 1
    assert payload["analysis_outlook_schema_version"] is None
    assert payload["status"]["stages"]["rules_prepared"] is True
    assert "primary_selection" not in result.output


def test_agent_status_reports_next_gate(project_root: Path) -> None:
    path = factual_match(project_root)
    payload = workflow_status(project_root, path)
    assert payload["stages"]["facts_ready"] is True
    assert payload["next_actions"] == ["运行 agent start 准备规则上下文"]


def test_validate_draft_rejects_certainty_language(project_root: Path, monkeypatch) -> None:
    path = factual_match(project_root)
    monkeypatch.chdir(project_root)
    prepared = CliRunner().invoke(
        app,
        [
            "agent",
            "start",
            str(path),
            "--as-of",
            "2026-07-30T17:30:00+08:00",
        ],
    )
    assert prepared.exit_code == 0, prepared.output
    document = MatchDocument.load(path)
    document.replace_section(
        "prematch-reasoning",
        set_analysis_content(document.sections["prematch-reasoning"], "该方向百分百命中。"),
    )
    document.save()
    result = CliRunner().invoke(app, ["agent", "validate-draft", str(path), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert any("确定性承诺" in item for item in payload["errors"])


def test_all_product_adapters_point_to_canonical_entry() -> None:
    root = Path(__file__).resolve().parents[1]
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    skill = (
        root / "integrations/skills/football-odds-journal/SKILL.md"
    ).read_text(encoding="utf-8")
    trae = (root / "integrations/trae/PROJECT_INSTRUCTIONS.md").read_text(encoding="utf-8")
    for content in (agents, skill, trae):
        assert "AI_START_HERE.md" in content
    assert "prepare-analysis" not in skill
    assert "盘口" not in skill
    suite = yaml.safe_load(
        (root / "integrations/certification/scenarios.yml").read_text(encoding="utf-8")
    )
    assert {item["scenario_id"] for item in suite["scenarios"]} == {
        "extraction-only",
        "governed-analysis",
        "degraded-or-pass",
        "failed-gate",
            "postmatch-review",
            "long-text-storage",
            "historical-result-completion",
            "low-stability-calibration",
            "normalized-market-bundle",
        }
