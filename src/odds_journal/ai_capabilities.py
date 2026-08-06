from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .ai_governance import active_config
from .ai_research import _primary_claims, read_studies
from .ledger import atomic_write_text


class AICapabilityStatusV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    capability: Literal["governance", "backtest", "shadow_research", "case_rerank", "formal_isolation"]
    status: Literal["ready", "controlled_disabled", "missing", "blocked"]
    reason: str


def status(root: Path) -> dict[str, Any]:
    config = active_config(root)
    manifests = sorted((root / "raw/backtests").glob("*/dataset-manifest.yml")) if (root / "raw/backtests").exists() else []
    checks = [
        AICapabilityStatusV1(capability="governance", status="ready", reason="受信资产、默认拒绝出站与内容寻址配置已实现"),
        AICapabilityStatusV1(capability="backtest", status="ready" if manifests else "controlled_disabled", reason="存在资格清单" if manifests else "尚未创建回测资格清单"),
        AICapabilityStatusV1(capability="shadow_research", status="ready" if config else "controlled_disabled", reason="活动 AI 配置可用于 FakeProvider 研究" if config else "没有活动 AI 配置，研究运行保持关闭"),
        AICapabilityStatusV1(capability="case_rerank", status="controlled_disabled", reason="默认 BM25；只有 lcz 明确批准的研究配置可调用候选封闭重排"),
        AICapabilityStatusV1(capability="formal_isolation", status="ready", reason="AI 台账、Outlook、Outcome 与正式 Match/锁定/结算目录和统计独立"),
    ]
    payload = {"schema_version": 1, "checks": [item.model_dump(mode="json") for item in checks], "study_count": len(read_studies(root)), "primary_claim_count": len(_primary_claims(root))}
    target = root / "reports" / "ai-experiments" / "capability-status.json"
    atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return payload


def validate(root: Path) -> list[str]:
    payload = status(root)
    return [item["capability"] + ": " + item["reason"] for item in payload["checks"] if item["status"] in {"missing", "blocked"}]
