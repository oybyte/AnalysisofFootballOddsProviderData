"""Contract 9 正式契约模型。

新增并注册：
- AnalysisDraftInputV4
- EvaluationBundleV4
- AnalysisOutlookV7
- DraftBuildReceiptV2

V7 市场语义：
- status: assessed | degraded | pass（保留现有正式市场状态）
- knowledge_mode: enabled | baseline_only | pass（独立知识状态）
- knowledge_change: none | reorder | confidence_cap | suppress
- baseline_ranking / knowledge_ranking / final_ranking
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── V4 Draft Input ────────────────────────────────────────


class AnalysisDraftInputV4(BaseModel):
    """Contract 9 分析草稿输入 V4。

    必须冻结全部输入哈希：
    Draft Build Receipt / OfficialBaselineSnapshot / FeatureSnapshot /
    PolicyKernelBaseline / KnowledgeSnapshot / KnowledgeIndexManifest /
    KnowledgeRetrievalReceipt / KnowledgeEvaluationBundle /
    KnowledgeDraftCandidate / market enablement matrix
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[4] = 4
    match_id: str = Field(min_length=1)
    as_of: datetime
    compiler_version: str = Field(min_length=1)

    # 正式基线绑定
    analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    official_baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 知识引擎输入
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 市场启用矩阵
    market_enablement: dict[str, str] = Field(default_factory=dict)

    # 校准
    calibration_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    draft_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_market_matrix(self) -> "AnalysisDraftInputV4":
        if self.market_enablement.get("fixed_handicap_1x2") != "disabled":
            raise ValueError("fixed_handicap_1x2 必须为 disabled")
        if self.market_enablement.get("score") != "disabled":
            raise ValueError("score 必须为 disabled")
        return self


# ── V4 Evaluation Bundle ──────────────────────────────────


class EvaluationBundleV4(BaseModel):
    """Contract 9 评估包 V4。

    由可追溯草稿输入生成，包含 V7 市场语义。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[4] = 4
    match_id: str = Field(min_length=1)
    as_of: datetime

    # 输入绑定
    draft_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # V7 市场评估
    market_assessments: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # 置信度
    confidence: float | None = Field(default=None, ge=0, le=1)
    degraded: bool = False
    degraded_reasons: tuple[str, ...] = Field(default_factory=tuple)

    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_market_semantics(self) -> "EvaluationBundleV4":
        """验证 V7 市场语义固定行为。"""
        for market, assessment in self.market_assessments.items():
            status = assessment.get("status")
            knowledge_mode = assessment.get("knowledge_mode")

            # knowledge_mode: pass 必须对应 status: pass
            if knowledge_mode == "pass" and status != "pass":
                raise ValueError(f"{market} knowledge_mode=pass 必须对应 status=pass")

            # pass 市场不得有候选
            if status == "pass" and assessment.get("ranking"):
                raise ValueError(f"{market} pass 市场不得有候选")

            # 首选变化固定 degraded
            knowledge_change = assessment.get("knowledge_change")
            if knowledge_change == "reorder":
                if not assessment.get("degraded"):
                    raise ValueError(f"{market} 首选变化必须 degraded")
                confidence = assessment.get("confidence")
                if confidence is not None and confidence > 0.69:
                    raise ValueError(f"{market} 首选变化置信度不得超过 0.69")
        return self


# ── V7 Analysis Outlook ───────────────────────────────────


class AnalysisOutlookV7(BaseModel):
    """Contract 9 AnalysisOutlook V7。

    保留现有正式市场状态 status，新增独立知识状态。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[7] = 7
    match_id: str = Field(min_length=1)
    as_of: datetime
    kickoff_at: datetime

    # 正式产物绑定
    analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 5 市场声明 assessed/pass 状态
    market_status: dict[str, str] = Field(default_factory=dict)

    # V7 知识市场语义
    market_knowledge: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # 候选
    candidates: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # 置信度
    confidence: float | None = Field(default=None, ge=0, le=1)
    degraded: bool = False

    outlook_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of", "kickoff_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_v7_semantics(self) -> "AnalysisOutlookV7":
        """验证 V7 市场语义固定行为。"""
        # 5 市场必须声明状态
        required_markets = {"one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score"}
        declared = set(self.market_status.keys())
        if not required_markets.issubset(declared):
            missing = required_markets - declared
            raise ValueError(f"缺少市场状态声明：{missing}")

        for market, status in self.market_status.items():
            if status not in ("assessed", "degraded", "pass"):
                raise ValueError(f"{market} status 无效：{status}")

            # pass 市场不得有候选
            if status == "pass" and market in self.candidates:
                raise ValueError(f"{market} pass 市场不得有候选")

            # 知识语义
            knowledge = self.market_knowledge.get(market, {})
            knowledge_mode = knowledge.get("knowledge_mode")
            if knowledge_mode == "pass" and status != "pass":
                raise ValueError(f"{market} knowledge_mode=pass 必须对应 status=pass")

            # baseline pass 永远不能被知识重开
            if status == "pass" and knowledge_mode and knowledge_mode != "pass":
                raise ValueError(f"{market} baseline pass 不能被知识重开")

            # 首选变化固定 degraded
            knowledge_change = knowledge.get("knowledge_change")
            if knowledge_change == "reorder":
                if status != "degraded":
                    raise ValueError(f"{market} 首选变化必须 degraded")
                confidence = knowledge.get("confidence")
                if confidence is not None and confidence > 0.69:
                    raise ValueError(f"{market} 首选变化置信度不得超过 0.69")

        # score 候选必须恰好两个（仅当 score 市场被评估时）
        if self.market_status.get("score") in ("assessed", "degraded"):
            score_candidates = self.candidates.get("score", {}).get("candidates", [])
            if len(score_candidates) != 2:
                raise ValueError("score 市场被评估时候选必须恰好两个")

        return self


# ── V2 Draft Build Receipt ────────────────────────────────


class DraftBuildReceiptV2(BaseModel):
    """Contract 9 草稿构建回执 V2。

    accept-draft 必须由 lcz 确认 candidate hash，输入变化即拒绝接受。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[2] = 2
    match_id: str = Field(min_length=1)
    built_at: datetime
    as_of: datetime

    # 规则集
    ruleset_id: str = Field(min_length=1)
    ruleset_version: str = Field(min_length=1)
    ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 知识引擎绑定
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    index_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 候选
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    # 市场矩阵
    market_enablement: dict[str, str] = Field(default_factory=dict)

    compiler_version: str = "knowledge-engine-v1"
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("built_at", "as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_market_matrix(self) -> "DraftBuildReceiptV2":
        if self.market_enablement.get("fixed_handicap_1x2") != "disabled":
            raise ValueError("fixed_handicap_1x2 必须为 disabled")
        if self.market_enablement.get("score") != "disabled":
            raise ValueError("score 必须为 disabled")
        return self
