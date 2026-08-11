"""Knowledge Engine 特征模型。

FeatureSnapshotV2 冻结比赛特征，包含观测、事实、案例、时序和盘口属性。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FeatureSnapshotV2(BaseModel):
    """冻结的比赛特征快照 V2。

    从 Contract 8 可复用特征提取，增加盘深、流动性、数据质量等维度。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2] = 2
    match_id: str = Field(min_length=1)
    as_of: datetime
    kickoff_at: datetime
    compiler_version: str = Field(min_length=1)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 观测/事实/案例引用
    observation_ids: tuple[str, ...] = Field(default_factory=tuple)
    fact_ids: tuple[str, ...] = Field(default_factory=tuple)
    case_ids: tuple[str, ...] = Field(default_factory=tuple)
    observation_collection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_collection_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    case_collection_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    # 时序数据（按 provider/market/line/odds_format 维度）
    time_series: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # 节点精度
    node_phases: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    node_precision: dict[str, Literal["opening", "mid", "late"]] = Field(default_factory=dict)

    # 净变化
    net_changes: dict[str, float] = Field(default_factory=dict)

    # 趋势纯度
    trend_purities: dict[str, float] = Field(default_factory=dict)

    # 冲突
    conflicts: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    # 比赛类型
    match_type: Literal["league", "cup", "friendly"] | None = None

    # 盘深
    handicap_depth: float | None = Field(default=None)
    handicap_depth_category: Literal["shallow", "medium", "deep", "extreme"] | None = None

    # 流动性
    liquidity_score: float | None = Field(default=None, ge=0, le=1)

    # 数据质量
    data_quality: Literal["complete", "degraded", "insufficient"] = "complete"
    missing_markets: tuple[str, ...] = Field(default_factory=tuple)
    missing_providers: tuple[str, ...] = Field(default_factory=tuple)

    # 单位与舍入
    odds_unit: Literal["decimal", "hong_kong"] = "decimal"
    line_precision: int = Field(default=2, ge=0, le=4)

    # Null 语义
    null_semantics: dict[str, Literal["not_observed", "suppressed", "error"]] = Field(
        default_factory=dict
    )

    # 特征哈希
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of", "kickoff_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("特征时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_time_boundary(self) -> "FeatureSnapshotV2":
        if self.as_of >= self.kickoff_at:
            raise ValueError("as_of 必须在 kickoff_at 之前")
        return self


class PolicyKernelBaselineV1(BaseModel):
    """强制 Policy Kernel 基线。

    由代码和 Decision Contract 强制执行，不参与 BM25 检索。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    as_of: datetime

    # 时间边界
    cutoff_valid: bool = True
    post_kickoff_leak: bool = False

    # 来源认证
    all_sources_authenticated: bool = True
    unauthenticated_sources: tuple[str, ...] = Field(default_factory=tuple)

    # 冲突门禁
    has_unresolved_conflicts: bool = False
    conflict_ids: tuple[str, ...] = Field(default_factory=tuple)

    # 同机构/同市场/同盘口/同赔率格式限制
    homogeneous_provider_valid: bool = True
    homogeneous_market_valid: bool = True
    homogeneous_line_valid: bool = True
    homogeneous_odds_format_valid: bool = True

    # 市场隔离
    cross_market_isolation: bool = True

    # pass 不可重新打开
    baseline_pass: bool = False
    pass_markets: tuple[str, ...] = Field(default_factory=tuple)

    # advisory 零正式效果
    advisory_only: bool = False

    # research_only 赛前不适用
    research_prematch_blocked: bool = True

    # 独立证据要求
    independent_evidence_total_goals: bool = False
    independent_evidence_score: bool = False
    independent_evidence_fixed_handicap: bool = False

    policy_kernel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        return value