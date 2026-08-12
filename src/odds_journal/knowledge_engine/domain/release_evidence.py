"""Knowledge Engine 发布证据模型。

KnowledgeReleaseEvidenceV1 内容寻址存放于
knowledge/rule-proposals/football-analysis/2.0.0/evidence/
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MarketEnablement(StrEnum):
    """市场启用状态。"""

    ENABLED = "enabled"
    BASELINE_ONLY = "baseline_only"
    DISABLED = "disabled"


class KnowledgeReleaseEvidenceV1(BaseModel):
    """知识发布证据 V1。

    内容寻址存放于 knowledge/rule-proposals/football-analysis/2.0.0/evidence/。
    未达标市场自动维持 baseline_only 或 disabled，不得自动升级为 enabled。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    evidence_id: str = Field(min_length=1)

    # 提案绑定
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 快照与索引
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    logical_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # Study 绑定
    study_ids: tuple[str, ...] = Field(default_factory=tuple)
    primary_run_ids: tuple[str, ...] = Field(default_factory=tuple)
    valid_outcome_ids: tuple[str, ...] = Field(default_factory=tuple)

    # 报告与审计
    study_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manual_audit_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    experiment_disposition_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    # 市场启用矩阵
    market_enablement: dict[str, str] = Field(default_factory=dict)

    # 门禁结果
    gate_results: dict[str, dict[str, Any]] = Field(default_factory=dict)

    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_market_matrix(self) -> "KnowledgeReleaseEvidenceV1":
        """验证市场矩阵固定约束。"""
        # fixed_handicap_1x2 永远 disabled
        if self.market_enablement.get("fixed_handicap_1x2") != "disabled":
            raise ValueError("fixed_handicap_1x2 必须为 disabled")
        # score 永远 disabled
        if self.market_enablement.get("score") != "disabled":
            raise ValueError("score 必须为 disabled")
        # 其他市场只能是 enabled/baseline_only/disabled
        for market, state in self.market_enablement.items():
            if state not in ("enabled", "baseline_only", "disabled"):
                raise ValueError(f"市场 {market} 状态无效：{state}")
        return self


# 发布预检门禁阈值
RELEASE_GATE_THRESHOLDS = {
    "min_prospective_outcomes": 60,
    "min_enabled_market_samples": 20,
    "max_1x2_brier_increment": 0.02,
    "max_1x2_log_loss_increment": 0.05,
    "max_top1_accuracy_drop_pp": 5,
    "max_utility_drop": 0.05,
    "min_applicability_samples": 100,
    "min_applicability_accuracy": 0.95,
}


class ReleasePreflightResult(BaseModel):
    """发布预检结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    proposal: str
    passed: bool
    gate_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    market_enablement: dict[str, str] = Field(default_factory=dict)
    failure_reasons: tuple[str, ...] = Field(default_factory=tuple)
    preflight_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
