from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .ai_governance import active_config
from .ai_research import _primary_claims, read_studies
from .ledger import atomic_write_text


def _real_provider_available(root: Path, config) -> tuple[bool, str]:
    """检查真实 LLM provider 是否可用。"""
    if config is None:
        return False, "没有活动 AI 配置"
    # 从配置快照中读取 provider_id
    try:
        import yaml
        snapshot_config = root / config.snapshot_path / "config.yml"
        if not snapshot_config.is_file():
            return False, "配置快照文件不存在"
        snapshot = yaml.safe_load(snapshot_config.read_text(encoding="utf-8")) or {}
        provider_id = snapshot.get("provider_id", "")
    except Exception:
        return False, "无法读取配置快照"
    if provider_id == "fake-offline":
        return False, "活动配置使用 fake-offline provider"
    api_key = os.environ.get("ODDS_JOURNAL_LLM_API_KEY")
    if not api_key:
        return False, "未设置 ODDS_JOURNAL_LLM_API_KEY 环境变量"
    # 检查出站策略是否允许网络访问
    policy_path = root / "ai/ai-experiment-policies/openai-gpt4o-mini.yml"
    if policy_path.is_file():
        import yaml as _yaml
        policy = _yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
        if policy.get("network_access") != "allow":
            return False, "出站策略未允许网络访问"
        if policy.get("approved_at") is None:
            return False, "出站策略尚未审批"
    return True, "真实 LLM provider 可用"


class AICapabilityStatusV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    capability: Literal[
        "governance", "formal_draft_compiler", "structured_prematch_facts",
        "backtest", "backtest_dataset", "shadow_research", "real_provider",
        "case_rerank", "formal_isolation",
    ]
    status: Literal["ready", "controlled_disabled", "missing", "blocked"]
    reason: str


def status(root: Path) -> dict[str, Any]:
    config = active_config(root)
    manifests = sorted((root / "raw/backtests").glob("*/dataset-manifest.yml")) if (root / "raw/backtests").exists() else []
    active_path = root / "knowledge/rulesets/football-analysis/active.yml"
    active_text = active_path.read_text(encoding="utf-8") if active_path.is_file() else ""
    compiler_active = "ruleset_version: 1.9.0" in active_text
    compiler_implemented = (root / "knowledge/rule-proposals/football-analysis/1.9.0/manifest.yml").is_file()
    checks = [
        AICapabilityStatusV1(capability="governance", status="ready", reason="受信资产、默认拒绝出站与内容寻址配置已实现"),
        AICapabilityStatusV1(
            capability="formal_draft_compiler",
            status="ready" if compiler_active else "controlled_disabled" if compiler_implemented else "missing",
            reason="正式 1.9.0 已激活，可生成确定性草稿候选" if compiler_active else "1.9.0 编译器提案已实现但尚未发布" if compiler_implemented else "尚未实现正式草稿编译器",
        ),
        AICapabilityStatusV1(capability="structured_prematch_facts", status="ready", reason="内容寻址 FactBundle 与赛前截止门禁已实现"),
        AICapabilityStatusV1(capability="backtest", status="ready" if manifests else "controlled_disabled", reason="存在资格清单" if manifests else "尚未创建回测资格清单"),
        AICapabilityStatusV1(capability="backtest_dataset", status="ready" if manifests else "controlled_disabled", reason="存在可回放资格清单" if manifests else "尚未创建确定性回测 Dataset Manifest"),
        AICapabilityStatusV1(capability="shadow_research", status="ready" if config else "controlled_disabled", reason="活动 AI 配置可用于 FakeProvider 研究" if config else "没有活动 AI 配置，研究运行保持关闭"),
        AICapabilityStatusV1(capability="real_provider", status="ready" if _real_provider_available(root, config)[0] else "controlled_disabled", reason=_real_provider_available(root, config)[1]),
        AICapabilityStatusV1(capability="case_rerank", status="controlled_disabled", reason="默认 BM25；只有 lcz 明确批准的研究配置可调用候选封闭重排"),
        AICapabilityStatusV1(capability="formal_isolation", status="ready", reason="AI 台账、Outlook、Outcome 与正式 Match/锁定/结算目录和统计独立"),
    ]
    payload = {"schema_version": 1, "checks": [item.model_dump(mode="json") for item in checks], "study_count": len(read_studies(root)), "primary_claim_count": len(_primary_claims(root))}
    target = root / "reports" / "ai-experiments" / "capability-status.json"
    atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def validate(root: Path) -> list[str]:
    payload = status(root)
    return [item["capability"] + ": " + item["reason"] for item in payload["checks"] if item["status"] == "blocked"]
