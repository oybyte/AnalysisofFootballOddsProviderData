from __future__ import annotations

from ..calibration import CalibrationConfig


def resolve_profile(config: CalibrationConfig, competition_code: str) -> tuple[str, list[str], list[str]]:
    profile = config.profile_for(competition_code)
    return profile, config.profile_chain_for(competition_code), config.applicable_rule_ids(competition_code)
