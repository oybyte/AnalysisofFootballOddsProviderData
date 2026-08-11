"""Knowledge Engine 概率预测模型。

MarketProbabilityForecastV1 初版只用于胜平负。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MarketProbabilityForecastV1(BaseModel):
    """市场概率预测 V1。

    基线概率来自合格机构最新欧赔去返还率后的跨机构中位概率。
    初版只用于胜平负市场。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    as_of: datetime
    market: Literal["one_x_two"] = "one_x_two"

    # 来源机构
    provider_ids: tuple[str, ...] = Field(min_length=3)

    # 基线概率 (home, draw, away)
    baseline_probabilities: dict[str, float] = Field(min_length=3, max_length=3)

    # 是否生成了有效概率
    forecast_valid: bool = True
    forecast_invalid_reason: str | None = None

    forecast_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_probabilities(self) -> "MarketProbabilityForecastV1":
        if self.forecast_valid:
            keys = {"home", "draw", "away"}
            if set(self.baseline_probabilities) != keys:
                raise ValueError("胜平负概率必须包含 home/draw/away 三项")
            values = [self.baseline_probabilities[k] for k in ("home", "draw", "away")]
            if any(v < 0 or v > 1 for v in values):
                raise ValueError("概率必须在 [0, 1] 范围内")
            if abs(sum(values) - 1.0) > 1e-6:
                raise ValueError("三项概率总和必须为 1（误差 ≤ 1e-6）")
        else:
            if not self.forecast_invalid_reason:
                raise ValueError("无效预测必须记录原因")
        return self

    @property
    def ranking(self) -> list[str]:
        """按概率降序排列。"""
        return sorted(
            self.baseline_probabilities,
            key=lambda k: (-self.baseline_probabilities[k], k),
        )


class SettlementUtility(BaseModel):
    """结算效用值。"""

    model_config = ConfigDict(frozen=True)

    full_win: float = 1.00
    half_win: float = 0.75
    push: float = 0.50
    half_loss: float = 0.25
    full_loss: float = 0.00