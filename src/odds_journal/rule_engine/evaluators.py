from __future__ import annotations

from typing import Any


def evaluate(rule_id: str, features: dict[str, Any], thresholds: dict[str, float]) -> tuple[bool, str, dict[str, Any]]:
    """Evaluate an explicitly configured Contract 4 rule without inferring selections."""
    def required(*names: str) -> bool:
        return all(features.get(name) is not None for name in names)

    if rule_id == "trend-purity-v1":
        value = max(features.get("home_water_purity") or 0.0, features.get("over_water_purity") or 0.0)
        threshold = thresholds["minimum_purity"]
        return value >= threshold, "threshold_not_met", {"purity": value, "threshold": threshold, "operator": ">="}
    if rule_id == "provider-consensus-divergence-v1":
        value = len(features["providers"])
        threshold = thresholds["provider_count_min"]
        return value >= threshold, "threshold_not_met", {"provider_count": value, "threshold": threshold, "operator": ">="}
    if rule_id == "cross-dimension-netting-v1":
        available = sum(bool(features.get(name)) for name in ("asian_three_nodes", "euro_three_nodes", "kelly_three_nodes", "total_three_nodes"))
        return available >= 2, "insufficient_data", {"independent_dimensions": available, "threshold": 2, "operator": ">="}
    if rule_id == "late-market-anomaly-v1":
        if not required("late_home_water"):
            return False, "insufficient_data", {}
        threshold = thresholds["high_water_min"]
        return features["late_home_water"] >= threshold, "threshold_not_met", {"late_home_water": features["late_home_water"], "threshold": threshold, "operator": ">="}
    if rule_id == "single-kelly-value-guard-v1":
        if not required("late_away_kelly"):
            return False, "insufficient_data", {}
        threshold = thresholds["single_value_max"]
        return features["late_away_kelly"] <= threshold, "threshold_not_met", {"kelly": features["late_away_kelly"], "threshold": threshold, "operator": "<="}
    if rule_id == "total-goals-cross-market-v1":
        if not required("total_over_water_change", "late_over_water", "late_total_line", "late_home_line", "late_favorite_odds"):
            return False, "insufficient_data", {}
        fall = -features["total_over_water_change"]
        threshold = thresholds["over_water_fall_min"]
        depth = abs(features["late_home_line"])
        favorite = features["late_favorite_odds"]
        passed = (
            features.get("total_same_line_three_nodes")
            and features.get("asian_three_nodes")
            and features.get("euro_three_nodes")
            and fall >= threshold
            and features["late_over_water"] <= thresholds["over_water_max"]
            and features["late_total_line"] <= thresholds["total_line_max"]
            and depth >= thresholds["deep_line_min"]
            and favorite <= thresholds["deep_favorite_odds_max"]
            and not (depth <= thresholds["shallow_line_max"] and favorite >= thresholds["shallow_favorite_odds_min"])
        )
        return passed, "threshold_not_met", {"over_water_fall": fall, "threshold": threshold, "late_over_water": features["late_over_water"], "operator": ">="}
    if rule_id == "korea-goal-drop-v1":
        if not required("total_over_water_change") or not features.get("total_same_line_three_nodes"):
            return False, "insufficient_data", {}
        fall = -features["total_over_water_change"]
        threshold = thresholds["over_water_fall_min"]
        return fall >= threshold, "threshold_not_met", {"over_water_fall": fall, "threshold": threshold, "operator": ">="}
    if rule_id == "score-baseline-v1":
        if not required("late_home_odds", "late_home_line", "late_favorite_odds"):
            return False, "insufficient_data", {}
        low_home = features["late_home_odds"] <= thresholds["home_odds_max"]
        shallow_low_favorite = (
            abs(features["late_home_line"]) <= thresholds["shallow_line_max"]
            and features["late_favorite_odds"] < thresholds["shallow_favorite_odds_max"]
        )
        return low_home or shallow_low_favorite, "threshold_not_met", {"home_odds": features["late_home_odds"], "shallow_low_favorite": shallow_low_favorite}
    if rule_id == "hidden-draw-away-cut-v1":
        if not required("away_odds_relative_change", "late_away_kelly", "draw_odds_relative_change", "draw_kelly_change"):
            return False, "insufficient_data", {}
        if not features.get("euro_three_nodes") or not features.get("kelly_three_nodes"):
            return False, "insufficient_data", {}
        away_fall = -features["away_odds_relative_change"]
        passed = (
            away_fall >= thresholds["away_odds_fall_min"]
            and thresholds["kelly_min"] <= features["late_away_kelly"] <= thresholds["kelly_max"]
            and abs(features["draw_odds_relative_change"]) <= thresholds["draw_range_max"]
            and abs(features["draw_kelly_change"]) <= thresholds["draw_kelly_range_max"]
        )
        return passed, "threshold_not_met", {"away_odds_fall": away_fall, "away_kelly": features["late_away_kelly"]}
    if rule_id == "korea-deep-line-loss-tolerance-v1":
        if not required("late_home_line", "late_home_water", "home_odds_change", "home_kelly_change"):
            return False, "insufficient_data", {}
        reverse = thresholds["reverse_delta_min"]
        passed = (
            abs(features["late_home_line"]) >= thresholds["minimum_line_depth"]
            and features["late_home_water"] >= thresholds["high_water_min"]
            and features.get("asian_three_nodes")
            and features.get("euro_three_nodes")
            and features.get("kelly_three_nodes")
            and features["home_odds_change"] <= -reverse
            and features["home_kelly_change"] >= reverse
        )
        return passed, "threshold_not_met", {"line_depth": abs(features["late_home_line"]), "late_water": features["late_home_water"]}
    if rule_id == "deep-line-stable-cover-v1":
        if not required("late_home_line", "late_home_water") or not features.get("asian_same_line_three_nodes"):
            return False, "insufficient_data", {}
        depth = abs(features["late_home_line"])
        if depth >= thresholds["minimum_line_depth"]:
            passed = thresholds["deep_water_min"] <= features["late_home_water"] <= thresholds["deep_water_max"]
        else:
            passed = (
                depth == thresholds.get("half_one_line", 0.75)
                and features["late_home_water"] <= thresholds["half_line_water_max"]
                and features.get("asian_home_water_non_increasing") is True
            )
        return passed, "threshold_not_met", {"line_depth": depth, "late_water": features["late_home_water"]}
    if rule_id == "quarter-low-water-inducement-v1":
        if not required("late_home_line", "late_home_water", "asian_home_water_change", "home_odds_change", "late_kelly_spread"):
            return False, "insufficient_data", {}
        passed = (
            features.get("asian_same_line_three_nodes")
            and features.get("euro_three_nodes")
            and features.get("kelly_three_nodes")
            and abs(features["late_home_line"]) in thresholds.get("line_depths", [0.25, 0.5])
            and features["late_home_water"] <= thresholds["half_line_water_max"]
            and features["asian_home_water_change"] < 0
            and features.get("asian_home_water_non_increasing") is True
            and features["home_odds_change"] > 0
            and features["late_kelly_spread"] <= thresholds["kelly_spread_max"]
        )
        return passed, "threshold_not_met", {"line_depth": abs(features["late_home_line"]), "late_water": features["late_home_water"]}
    if rule_id == "draw-kelly-parity-v1":
        if not required("late_draw_kelly", "late_away_kelly"):
            return False, "insufficient_data", {}
        spread = abs(features["late_draw_kelly"] - features["late_away_kelly"])
        return spread <= thresholds["kelly_spread_parity"], "threshold_not_met", {"kelly_spread": spread, "threshold": thresholds["kelly_spread_parity"], "operator": "<="}
    # Legacy low-stability rules remain isolated in Contract 4 until their inputs are fully normalized.
    return False, "insufficient_data", {"reason": "evaluator_requires_dedicated_feature"}
