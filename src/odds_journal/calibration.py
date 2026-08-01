from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import (
    AnalysisDimension,
    AnalysisOutlook,
    CALIBRATION_RULE_IDS,
    CalibrationEvent,
    CalibrationMarketSummary,
    CalibrationSummary,
    FixedHandicapResult,
    MarketSnapshot,
    MatchMetadata,
    Selection,
)
from .rules import sha256_file


class CompetitionProfileConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competition_codes: list[str] = Field(min_length=1)


class CalibrationRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    reliability: Literal["experimental"] = "experimental"
    thresholds: dict[str, float] = Field(default_factory=dict)
    allowed_values: dict[str, list[float]] = Field(default_factory=dict)


class ComparisonPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_phases: list[Literal["opening", "mid", "late"]]
    late_window_minutes: int = Field(gt=0)
    asian_water_odds_format: Literal["hong_kong"]
    european_odds_format: Literal["decimal"]
    kelly_odds_format: Literal["kelly"]

    @model_validator(mode="after")
    def validate_phases(self) -> "ComparisonPolicyConfig":
        if self.required_phases != ["opening", "mid", "late"]:
            raise ValueError("校准比较阶段必须固定为 opening/mid/late")
        return self


class CalibrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    profile_id: Literal["low-stability-v1"]
    comparison_policy: ComparisonPolicyConfig
    competition_profiles: dict[str, CompetitionProfileConfig]
    recognized_providers: list[str]
    rules: list[CalibrationRuleConfig]

    @model_validator(mode="after")
    def validate_contract(self) -> "CalibrationConfig":
        ids = [item.rule_id for item in self.rules]
        if len(ids) != len(set(ids)) or set(ids) != set(CALIBRATION_RULE_IDS):
            raise ValueError("校准配置必须且只能定义八条低稳定性规则")
        codes = [
            code
            for profile in self.competition_profiles.values()
            for code in profile.competition_codes
        ]
        if len(codes) != len(set(codes)):
            raise ValueError("赛事代码不得同时属于多个校准 profile")
        if len(self.recognized_providers) != len(set(self.recognized_providers)):
            raise ValueError("认可机构列表不得重复")
        return self

    def profile_for(self, competition_code: str) -> str:
        for profile, config in self.competition_profiles.items():
            if competition_code in config.competition_codes:
                return profile
        return "not_applicable"

    def threshold(self, rule_id: str, name: str) -> float:
        rule = next(item for item in self.rules if item.rule_id == rule_id)
        try:
            return rule.thresholds[name]
        except KeyError as exc:
            raise ValueError(f"校准配置缺少阈值：{rule_id}.{name}") from exc

    def allowed(self, rule_id: str, name: str) -> list[float]:
        rule = next(item for item in self.rules if item.rule_id == rule_id)
        try:
            return rule.allowed_values[name]
        except KeyError as exc:
            raise ValueError(f"校准配置缺少允许值：{rule_id}.{name}") from exc


def load_calibration_config(path: Path, *, expected_sha256: str | None = None) -> CalibrationConfig:
    if expected_sha256 and sha256_file(path) != expected_sha256:
        raise ValueError("校准配置哈希不一致")
    return CalibrationConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def _market(snapshot: MarketSnapshot) -> str:
    return str(snapshot.market)


def _phase(snapshot: MarketSnapshot) -> str:
    return str(snapshot.phase)


def _format(snapshot: MarketSnapshot) -> str:
    return str(snapshot.odds_format)


def _snapshots(
    metadata: MatchMetadata,
    market: str,
    provider: str,
    cutoff: datetime,
) -> list[MarketSnapshot]:
    return sorted(
        (
            item
            for item in metadata.market_snapshots
            if _market(item) == market
            and item.provider_id == provider
            and item.captured_at <= cutoff
            and item.captured_at <= metadata.kickoff_at
            and _phase(item) != "live"
        ),
        key=lambda item: (item.captured_at, item.snapshot_id),
    )


def _three_nodes(
    metadata: MatchMetadata,
    market: str,
    provider: str,
    odds_format: str,
    cutoff: datetime,
    late_window_minutes: int,
) -> tuple[list[MarketSnapshot] | None, str | None]:
    values = [
        item
        for item in _snapshots(metadata, market, provider, cutoff)
        if _format(item) == odds_format
    ]
    groups = {phase: [item for item in values if _phase(item) == phase] for phase in ("opening", "mid", "late")}
    if any(not groups[phase] for phase in groups):
        return None, "insufficient_data"
    selected = [groups["opening"][0], groups["mid"][-1], groups["late"][-1]]
    if selected[-1].captured_at < metadata.kickoff_at - timedelta(minutes=late_window_minutes):
        return None, "insufficient_data"
    if not (selected[0].captured_at < selected[1].captured_at < selected[2].captured_at):
        return None, "insufficient_data"
    return selected, None


def _number(snapshot: MarketSnapshot, key: str) -> float | None:
    value = snapshot.normalized_values.get(key)
    return float(value) if value is not None else None


def _delta(left: float, right: float) -> float:
    return round(left - right, 6)


def _identity(nodes: list[MarketSnapshot]) -> tuple[str | None, str | None]:
    opening = [_number(nodes[0], key) for key in ("home", "draw", "away")]
    late = [_number(nodes[-1], key) for key in ("home", "draw", "away")]
    if any(value is None for value in [*opening, *late]):
        return None, None
    labels = ("home", "draw", "away")
    opening_min = [index for index, value in enumerate(opening) if value == min(opening)]
    late_min = [index for index, value in enumerate(late) if value == min(late)]
    opening_max = [index for index, value in enumerate(opening) if value == max(opening)]
    late_max = [index for index, value in enumerate(late) if value == max(late)]
    favorite = labels[opening_min[0]] if len(opening_min) == len(late_min) == 1 and opening_min == late_min else None
    underdog = labels[opening_max[0]] if len(opening_max) == len(late_max) == 1 and opening_max == late_max else None
    return favorite, underdog


def _full_ranking(values: list[str], allowed: tuple[str, ...]) -> list[str]:
    return [*values, *(item for item in allowed if item not in values)]


def _promote_once(ranking: list[str], target: str) -> list[str]:
    result = list(ranking)
    index = result.index(target)
    if index > 1:
        result[index - 1], result[index] = result[index], result[index - 1]
    return result


def _same_line_run(
    snapshots: list[MarketSnapshot], depths: list[float], start: int
) -> list[MarketSnapshot]:
    target = depths[start]
    output: list[MarketSnapshot] = []
    for snapshot, depth in zip(snapshots[start:], depths[start:]):
        if depth != target:
            break
        output.append(snapshot)
    return output


def _base_event(
    rule_id: str,
    market: str,
    target: str,
    ranking: list[str],
    dimensions: list[str],
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "reliability": "experimental",
        "triggered": False,
        "not_triggered_reason": "threshold_not_met",
        "target_market": market,
        "target_selection": target,
        "source_dimensions": dimensions,
        "source_provider_ids": [],
        "source_snapshot_ids": [],
        "correlation_keys": [],
        "threshold_observations": {},
        "before_ranking": ranking,
        "proposed_ranking": ranking,
        "final_ranking": ranking,
        "adjustment_level": 0,
        "primary_changed": False,
        "supporting_evidence": [],
        "counter_evidence": [],
    }


def _trigger(
    raw: dict[str, Any],
    *,
    providers: list[str],
    snapshots: list[MarketSnapshot],
    observations: dict[str, Any],
    correlation_keys: list[str] | None = None,
) -> CalibrationEvent:
    observations = {
        **observations,
        "snapshots": [
            {
                "snapshot_id": item.snapshot_id,
                "raw_values": item.raw_values,
                "normalized_values": item.normalized_values,
            }
            for item in snapshots
        ],
    }
    raw.update(
        {
            "triggered": True,
            "not_triggered_reason": None,
            "source_provider_ids": list(dict.fromkeys(providers)),
            "source_snapshot_ids": list(dict.fromkeys(item.snapshot_id for item in snapshots)),
            "correlation_keys": correlation_keys or [],
            "threshold_observations": observations,
            "proposed_ranking": _promote_once(raw["before_ranking"], raw["target_selection"]),
            "final_ranking": raw["before_ranking"],
            "adjustment_level": 1,
            "supporting_evidence": [f"{raw['rule_id']} 刚性阈值已满足"],
            "counter_evidence": ["实验规则只校准权重，不单独构成第一顺位换位依据"],
        }
    )
    return CalibrationEvent.model_validate(raw)


def _not_triggered(raw: dict[str, Any], reason: str, **observations: Any) -> CalibrationEvent:
    raw["not_triggered_reason"] = reason
    raw["threshold_observations"] = observations
    return CalibrationEvent.model_validate(raw)


def evaluate_calibration(
    metadata: MatchMetadata,
    outlook: AnalysisOutlook,
    config: CalibrationConfig,
    *,
    cutoff: datetime,
) -> tuple[str, list[CalibrationEvent], CalibrationSummary]:
    profile = config.profile_for(metadata.competition_code)
    if outlook.schema_version == 2 and outlook.calibration_summary is not None:
        one_baseline = list(outlook.calibration_summary.one_x_two.baseline_ranking)
        fixed_baseline = list(outlook.calibration_summary.fixed_handicap_1x2.baseline_ranking)
    else:
        one_baseline = _full_ranking(
            outlook.one_x_two.choices if outlook.one_x_two else [Selection.HOME.value, Selection.DRAW.value],
            (Selection.HOME.value, Selection.DRAW.value, Selection.AWAY.value),
        )
        fixed_baseline = _full_ranking(
            outlook.fixed_handicap_1x2.ranking.choices if outlook.fixed_handicap_1x2 else [FixedHandicapResult.HANDICAP_HOME.value, FixedHandicapResult.HANDICAP_DRAW.value],
            tuple(item.value for item in FixedHandicapResult),
        )
    summary = CalibrationSummary(
        one_x_two=CalibrationMarketSummary(baseline_ranking=one_baseline, final_ranking=one_baseline),
        fixed_handicap_1x2=CalibrationMarketSummary(baseline_ranking=fixed_baseline, final_ranking=fixed_baseline),
        asian_handicap={"cover_signal": "neutral", "cover_signal_rule_ids": []},
    )
    if profile == "not_applicable":
        return profile, [], summary

    policy = config.comparison_policy
    euro, euro_error = _three_nodes(
        metadata,
        "european_odds",
        "macau",
        policy.european_odds_format,
        cutoff,
        policy.late_window_minutes,
    )
    favorite, underdog = _identity(euro) if euro else (None, None)
    fixed_favorite = (
        FixedHandicapResult.HANDICAP_HOME.value
        if favorite == Selection.HOME.value
        else FixedHandicapResult.HANDICAP_AWAY.value
    )
    events: list[CalibrationEvent] = []
    asian, asian_error = _three_nodes(
        metadata,
        "asian_handicap",
        "macau",
        policy.asian_water_odds_format,
        cutoff,
        policy.late_window_minutes,
    )

    # Rules 1-3: Macau Asian market, with all water comparisons constrained to one line.
    for rule_id, target in (
        ("lsl-asian-rise-water-rise", FixedHandicapResult.HANDICAP_DRAW.value),
        ("lsl-deep-line-falling-water", fixed_favorite),
        ("lsl-deep-line-drop-risk", FixedHandicapResult.HANDICAP_DRAW.value),
    ):
        raw = _base_event(rule_id, "fixed_handicap_1x2", target, fixed_baseline, [AnalysisDimension.ASIAN_HANDICAP_MARKET.value])
        if asian_error or euro_error or favorite not in {"home", "away"}:
            events.append(_not_triggered(raw, "insufficient_data"))
            continue
        all_asian = [
            item
            for item in _snapshots(metadata, "asian_handicap", "macau", cutoff)
            if _format(item) == "hong_kong"
        ]
        line_key = "home_line"
        water_key = f"{favorite}_water"
        if any(_number(item, line_key) is None or _number(item, water_key) is None for item in all_asian):
            events.append(_not_triggered(raw, "insufficient_data"))
            continue
        sign = -1.0 if favorite == "home" else 1.0
        depths = [sign * float(_number(item, line_key)) for item in all_asian]
        if rule_id == "lsl-asian-rise-water-rise":
            allowed_steps = set(config.allowed(rule_id, "line_rise_steps"))
            rises = [index for index in range(1, len(depths)) if round(depths[index] - depths[index - 1], 2) in allowed_steps]
            if not rises:
                events.append(_not_triggered(raw, "threshold_not_met", line_rise=0))
                continue
            index = rises[-1]
            new_depth = depths[index]
            same_line = _same_line_run(all_asian, depths, index)
            threshold = config.threshold(rule_id, "water_rise_min")
            delta = _delta(float(_number(same_line[-1], water_key)), float(_number(same_line[0], water_key))) if len(same_line) >= 2 else None
            if len(same_line) < 2 or same_line[-1].snapshot_id != all_asian[-1].snapshot_id:
                events.append(_not_triggered(raw, "insufficient_data", same_line_nodes=len(same_line)))
            elif delta is not None and delta >= threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=same_line, observations={"line_depth": new_depth, "water_delta": delta, "operator": ">=", "threshold": threshold}))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", water_delta=delta, threshold=threshold))
        elif rule_id == "lsl-deep-line-falling-water":
            minimum = config.threshold(rule_id, "minimum_line_depth")
            threshold = config.threshold(rule_id, "water_fall_min")
            same_line = [item for item, depth in zip(all_asian, depths) if depth == depths[-1]]
            delta = _delta(float(_number(same_line[0], water_key)), float(_number(same_line[-1], water_key))) if len(same_line) >= 2 else None
            no_drop = all(right >= left for left, right in zip(depths, depths[1:]))
            if depths[0] >= minimum and no_drop and delta is not None and delta >= threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=same_line, observations={"minimum_depth": min(depths), "water_fall": delta, "operator": ">=", "threshold": threshold}))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", minimum_depth=min(depths), water_fall=delta, no_drop=no_drop))
        else:
            minimum = config.threshold(rule_id, "minimum_line_depth")
            threshold = config.threshold(rule_id, "post_drop_water_rise_strict")
            drops = [index for index in range(1, len(depths)) if depths[index - 1] >= minimum and depths[index] < depths[index - 1] and all_asian[index].captured_at >= metadata.kickoff_at - timedelta(minutes=policy.late_window_minutes)]
            if not drops:
                events.append(_not_triggered(raw, "threshold_not_met", late_drop=False))
                continue
            index = drops[-1]
            new_depth = depths[index]
            same_line = _same_line_run(all_asian, depths, index)
            delta = _delta(float(_number(same_line[-1], water_key)), float(_number(same_line[0], water_key))) if len(same_line) >= 2 else None
            if len(same_line) < 2:
                events.append(_not_triggered(raw, "insufficient_data", same_line_nodes=len(same_line)))
            elif delta is not None and delta > threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=same_line, observations={"line_depth": new_depth, "water_delta": delta, "operator": ">", "threshold": threshold}))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", water_delta=delta, threshold=threshold))

    # Rule 4.
    raw = _base_event("lsl-favorite-kelly-draw-resonance", "one_x_two", Selection.DRAW.value, one_baseline, [AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.KELLY_INDEX.value])
    kelly, kelly_error = _three_nodes(
        metadata,
        "kelly_index",
        "macau",
        policy.kelly_odds_format,
        cutoff,
        policy.late_window_minutes,
    )
    if euro_error or kelly_error or favorite not in {"home", "away"}:
        events.append(_not_triggered(raw, "insufficient_data"))
    else:
        required_values = (
            _number(euro[0], favorite),
            _number(euro[-1], favorite),
            _number(kelly[0], favorite),
            _number(kelly[-1], favorite),
            _number(kelly[-1], "draw"),
        )
        if any(value is None for value in required_values):
            events.append(_not_triggered(raw, "insufficient_data"))
            odds_fall = kelly_fall = late_favorite = late_draw = None
        else:
            odds_fall = _delta(required_values[0], required_values[1])
            kelly_fall = _delta(required_values[2], required_values[3])
            late_favorite = required_values[3]
            late_draw = required_values[4]
            threshold = config.threshold(raw["rule_id"], "minimum_fall")
            if late_favorite >= late_draw and odds_fall >= threshold and kelly_fall >= threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=[*euro, *kelly], observations={"odds_fall": odds_fall, "kelly_fall": kelly_fall, "late_favorite_kelly": late_favorite, "late_draw_kelly": late_draw}, correlation_keys=["macau:odds-kelly"]))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", odds_fall=odds_fall, kelly_fall=kelly_fall, late_favorite_kelly=late_favorite, late_draw_kelly=late_draw))

    # Rule 5.
    raw = _base_event("lsl-single-side-draw-protection", "one_x_two", Selection.DRAW.value, one_baseline, [AnalysisDimension.EUROPEAN_ODDS.value])
    qualifying: dict[tuple[str, int], list[tuple[str, list[MarketSnapshot]]]] = {}
    for provider in ("macau", "william-hill", "ladbrokes"):
        nodes, error = _three_nodes(
            metadata,
            "european_odds",
            provider,
            policy.european_odds_format,
            cutoff,
            policy.late_window_minutes,
        )
        if error or nodes is None:
            continue
        draw_values = [_number(item, "draw") for item in nodes]
        if any(value is None for value in draw_values):
            continue
        for endpoint in ("home", "away"):
            values = [_number(item, endpoint) for item in nodes]
            if any(value is None for value in values):
                continue
            direction = 1 if values[-1] > values[0] else -1
            monotonic = all((right - left) * direction >= 0 for left, right in zip(values, values[1:]))
            net = round(abs(values[-1] - values[0]), 6)
            draw_range = round(max(draw_values) - min(draw_values), 6)
            if monotonic and net >= config.threshold(raw["rule_id"], "endpoint_net_change_min") and draw_range <= config.threshold(raw["rule_id"], "draw_range_max") and draw_values[-1] <= draw_values[0]:
                qualifying.setdefault((endpoint, direction), []).append((provider, nodes))
    provider_count = int(config.threshold(raw["rule_id"], "provider_count_min"))
    group = next((values for values in qualifying.values() if len(values) >= provider_count), None)
    if group:
        selected = group[:provider_count]
        events.append(_trigger(raw, providers=[item[0] for item in selected], snapshots=[snap for _, nodes in selected for snap in nodes], observations={"qualifying_providers": [item[0] for item in selected], "provider_count": len(selected)}))
    else:
        reason = "insufficient_data" if not qualifying else "threshold_not_met"
        events.append(_not_triggered(raw, reason, qualifying_provider_count=max((len(item) for item in qualifying.values()), default=0)))

    # Rule 6.
    target = underdog if underdog in {"home", "away"} else Selection.AWAY.value
    raw = _base_event("lsl-underdog-kelly-defense", "one_x_two", target, one_baseline, [AnalysisDimension.EUROPEAN_ODDS.value, AnalysisDimension.KELLY_INDEX.value])
    if euro_error or kelly_error or underdog not in {"home", "away"}:
        events.append(_not_triggered(raw, "insufficient_data"))
    else:
        odds_values = [_number(item, underdog) for item in euro]
        kelly_values = [_number(item, underdog) for item in kelly]
        if any(value is None for value in [*odds_values, *kelly_values]):
            events.append(_not_triggered(raw, "insufficient_data"))
        else:
            threshold = config.threshold(raw["rule_id"], "minimum_fall")
            monotonic = all(right <= left for values in (odds_values, kelly_values) for left, right in zip(values, values[1:]))
            falls = (_delta(odds_values[0], odds_values[-1]), _delta(kelly_values[0], kelly_values[-1]))
            if monotonic and min(falls) >= threshold:
                events.append(_trigger(raw, providers=["macau"], snapshots=[*euro, *kelly], observations={"odds_fall": falls[0], "kelly_fall": falls[1]}, correlation_keys=["macau:odds-kelly"]))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", monotonic=monotonic, odds_fall=falls[0], kelly_fall=falls[1]))

    # Rule 7.
    raw = _base_event("lsl-kelly-narrow-range", "one_x_two", Selection.DRAW.value, one_baseline, [AnalysisDimension.KELLY_INDEX.value, AnalysisDimension.ASIAN_HANDICAP_MARKET.value])
    if kelly_error or asian_error or favorite not in {"home", "away"}:
        events.append(_not_triggered(raw, "insufficient_data"))
    else:
        late_values = [_number(kelly[-1], key) for key in ("home", "draw", "away")]
        line_values = [_number(item, "home_line") for item in asian]
        water_values = [_number(item, f"{favorite}_water") for item in asian]
        if any(value is None for value in [*late_values, *line_values, *water_values]):
            events.append(_not_triggered(raw, "insufficient_data"))
        else:
            spread = round(max(late_values) - min(late_values), 6)
            sign = -1 if favorite == "home" else 1
            depths = [sign * value for value in line_values]
            water_rise = _delta(water_values[-1], water_values[0])
            same_line_rise = depths[0] == depths[-1] and water_rise > config.threshold(raw["rule_id"], "favorite_water_rise_strict")
            line_drop = depths[-1] < max(depths[:-1])
            if spread <= config.threshold(raw["rule_id"], "kelly_spread_max") and (same_line_rise or line_drop):
                events.append(_trigger(raw, providers=["macau"], snapshots=[*kelly, *asian], observations={"kelly_spread": spread, "same_line_water_rise": same_line_rise, "late_line_drop": line_drop}, correlation_keys=["macau:kelly-asian"]))
            else:
                events.append(_not_triggered(raw, "threshold_not_met", kelly_spread=spread, same_line_water_rise=same_line_rise, late_line_drop=line_drop))

    # Rule 8.
    raw = _base_event("lsl-extreme-over-calibration", "fixed_handicap_1x2", fixed_favorite, fixed_baseline, [AnalysisDimension.TOTAL_GOALS_MARKET.value])
    qualifying_total: tuple[str, list[MarketSnapshot]] | None = None
    exact_line = config.threshold(raw["rule_id"], "exact_total_line")
    for provider in config.recognized_providers:
        nodes, error = _three_nodes(
            metadata,
            "total_goals",
            provider,
            policy.asian_water_odds_format,
            cutoff,
            policy.late_window_minutes,
        )
        if error or nodes is None:
            continue
        line = _number(nodes[-1], "line")
        over = _number(nodes[-1], "over_water")
        if line == exact_line and over is not None and over <= config.threshold(raw["rule_id"], "over_water_max"):
            qualifying_total = (provider, nodes)
            break
    if qualifying_total:
        provider, nodes = qualifying_total
        events.append(_trigger(raw, providers=[provider], snapshots=nodes, observations={"late_line": exact_line, "late_over_water": _number(nodes[-1], "over_water"), "operator": "<=", "threshold": config.threshold(raw["rule_id"], "over_water_max")}))
    else:
        events.append(_not_triggered(raw, "insufficient_data", exact_line=exact_line))

    cover_ids = [item.rule_id for item in events if item.triggered and item.rule_id in {"lsl-asian-rise-water-rise", "lsl-deep-line-drop-risk", "lsl-deep-line-falling-water"}]
    if "lsl-deep-line-falling-water" in cover_ids and not set(cover_ids) & {"lsl-asian-rise-water-rise", "lsl-deep-line-drop-risk"}:
        summary.asian_handicap.cover_signal = "support"
    elif set(cover_ids) & {"lsl-asian-rise-water-rise", "lsl-deep-line-drop-risk"}:
        summary.asian_handicap.cover_signal = "risk"
    summary.asian_handicap.cover_signal_rule_ids = cover_ids
    return profile, events, summary
