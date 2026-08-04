from __future__ import annotations

from typing import Iterable


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
