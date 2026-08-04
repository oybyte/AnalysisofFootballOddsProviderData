from __future__ import annotations

from ..calibration import CalibrationConfig


def require_contract4(config: CalibrationConfig) -> CalibrationConfig:
    if config.schema_version != 4:
        raise ValueError("rule_engine 仅接受 calibration contract 4 配置")
    return config
