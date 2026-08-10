from __future__ import annotations

from .models import AsianSettlement, FixedHandicapResult, Selection


def _quarter_legs(line: float) -> tuple[float, float]:
    quarter = round(line * 4)
    if abs(line * 4 - quarter) > 1e-8:
        raise ValueError("亚洲让球必须按 0.25 档位记录")
    if abs(quarter) % 2 == 0:
        return line, line
    lower = quarter // 2 / 2
    upper = lower + 0.5
    return lower, upper


def settle_asian_handicap(
    home_goals: int,
    away_goals: int,
    home_line: float,
    selection: Selection | str,
) -> AsianSettlement:
    selected = Selection(selection)
    if selected not in {Selection.HOME_HANDICAP, Selection.AWAY_HANDICAP}:
        raise ValueError("亚洲让球结算方向必须是 home_handicap 或 away_handicap")

    outcomes: list[int] = []
    for leg in _quarter_legs(home_line):
        adjusted = home_goals + leg - away_goals
        home_outcome = 1 if adjusted > 0 else -1 if adjusted < 0 else 0
        outcomes.append(home_outcome if selected == Selection.HOME_HANDICAP else -home_outcome)
    total = sum(outcomes)
    return {
        2: AsianSettlement.FULL_WIN,
        1: AsianSettlement.HALF_WIN,
        0: AsianSettlement.PUSH,
        -1: AsianSettlement.HALF_LOSS,
        -2: AsianSettlement.FULL_LOSS,
    }[total]


def settle_fixed_handicap_1x2(
    home_goals: int, away_goals: int, home_line: int
) -> FixedHandicapResult:
    adjusted = home_goals + home_line - away_goals
    if adjusted > 0:
        return FixedHandicapResult.HANDICAP_HOME
    if adjusted < 0:
        return FixedHandicapResult.HANDICAP_AWAY
    return FixedHandicapResult.HANDICAP_DRAW


def total_goals_range_hit(home_goals: int, away_goals: int, minimum: int, maximum: int) -> bool:
    return minimum <= home_goals + away_goals <= maximum


def settle_total_goals(
    home_goals: int, away_goals: int, line: float, selection: str
) -> AsianSettlement:
    if selection not in {"over", "under"}:
        raise ValueError("总进球结算方向必须是 over 或 under")
    total = home_goals + away_goals
    outcomes: list[int] = []
    for leg in _quarter_legs(line):
        over_outcome = 1 if total > leg else -1 if total < leg else 0
        outcomes.append(over_outcome if selection == "over" else -over_outcome)
    return {
        2: AsianSettlement.FULL_WIN,
        1: AsianSettlement.HALF_WIN,
        0: AsianSettlement.PUSH,
        -1: AsianSettlement.HALF_LOSS,
        -2: AsianSettlement.FULL_LOSS,
    }[sum(outcomes)]


def score_candidate_hit(home_goals: int, away_goals: int, candidates: list[str]) -> bool:
    return f"{home_goals}-{away_goals}" in candidates
