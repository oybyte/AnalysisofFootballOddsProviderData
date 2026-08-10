from __future__ import annotations

from typing import Iterable

from .conflicts import independent_supports


def move_up_once(ranking: list[str], selection: str) -> list[str]:
    result = list(ranking)
    if selection in result and result.index(selection) > 0:
        index = result.index(selection)
        result[index - 1], result[index] = result[index], result[index - 1]
    return result


def apply_rankings(baseline: dict[str, list[str]], events: Iterable[dict], *, adopted_only: bool) -> dict[str, list[str]]:
    result = {market: list(ranking) for market, ranking in baseline.items()}
    for event in sorted(events, key=lambda item: item["rule_id"]):
        if not event["triggered"] or event["effect"] != "ranking":
            continue
        if adopted_only and event.get("disposition") != "adopted":
            continue
        market = event.get("target_market")
        if market in result:
            result[market] = move_up_once(result[market], event["target_selection"])
    return result


def apply_governed_rankings(
    baseline: dict[str, list[str]], events: Iterable[dict], *, adopted_only: bool
) -> dict[str, list[str]]:
    """Apply one-place adjustments without allowing a single rule to replace the anchor."""
    frozen_events = list(events)
    result = {market: list(ranking) for market, ranking in baseline.items()}
    for event in sorted(frozen_events, key=lambda item: item["rule_id"]):
        if not event["triggered"] or event["effect"] != "ranking":
            continue
        if adopted_only and event.get("disposition") != "adopted":
            continue
        market = event.get("target_market")
        if market not in result:
            continue
        ranking = result[market]
        target = event["target_selection"]
        if target in ranking and ranking.index(target) > 1:
            result[market] = move_up_once(ranking, target)

    for market, ranking in result.items():
        baseline_ranking = baseline[market]
        eligible = [
            selection
            for selection in baseline_ranking[1:]
            if independent_supports(frozen_events, market, selection)
        ]
        if len(eligible) != 1:
            continue
        target = eligible[0]
        target_index = ranking.index(target)
        ranking[0], ranking[target_index] = ranking[target_index], ranking[0]
    return result
