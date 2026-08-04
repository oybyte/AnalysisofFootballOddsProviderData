from __future__ import annotations

from datetime import datetime
from typing import Any

from ..models import MatchMetadata, MarketSnapshot


def _number(snapshot: MarketSnapshot, key: str) -> float | None:
    value = snapshot.normalized_values.get(key)
    return float(value) if value is not None else None


def market_nodes(metadata: MatchMetadata, market: str, cutoff: datetime, provider: str = "macau") -> list[MarketSnapshot]:
    return sorted(
        [
            item for item in metadata.market_snapshots
            if str(item.market) == market
            and item.provider_id == provider
            and item.captured_at <= cutoff
            and item.captured_at < metadata.kickoff_at
            and str(item.phase) in {"opening", "mid", "late"}
        ],
        key=lambda item: (item.captured_at, item.snapshot_id),
    )


def three_comparable(nodes: list[MarketSnapshot], line_key: str | None = None) -> tuple[bool, str]:
    phases = {str(item.phase) for item in nodes}
    if not {"opening", "mid", "late"}.issubset(phases):
        return False, "missing_three_phases"
    if len(nodes) < 3:
        return False, "insufficient_nodes"
    if line_key and any(_number(item, line_key) is None for item in nodes):
        return False, "missing_line"
    return True, "complete"


def same_line_three_nodes(nodes: list[MarketSnapshot], line_key: str) -> tuple[bool, str]:
    comparable, reason = three_comparable(nodes, line_key)
    if not comparable:
        return False, reason
    lines = {_number(item, line_key) for item in nodes}
    if len(lines) != 1:
        return False, "cross_line_nodes"
    return True, "complete"


def non_increasing(nodes: list[MarketSnapshot], key: str) -> bool | None:
    values = [_number(item, key) for item in nodes]
    if len(values) < 2 or any(value is None for value in values):
        return None
    return all(float(right) <= float(left) for left, right in zip(values, values[1:]))


def relative_change(nodes: list[MarketSnapshot], key: str) -> float | None:
    values = [_number(item, key) for item in nodes]
    if len(values) < 2 or any(value is None for value in values) or float(values[0]) == 0:
        return None
    return round((float(values[-1]) - float(values[0])) / float(values[0]), 6)


def net_change(nodes: list[MarketSnapshot], key: str) -> float | None:
    values = [_number(item, key) for item in nodes]
    if len(values) < 2 or any(value is None for value in values):
        return None
    return round(float(values[-1]) - float(values[0]), 6)


def trend_purity(nodes: list[MarketSnapshot], key: str) -> float | None:
    values = [_number(item, key) for item in nodes]
    if len(values) < 2 or any(value is None for value in values):
        return None
    deltas = [float(right) - float(left) for left, right in zip(values, values[1:])]
    nonzero = [value for value in deltas if value]
    if not nonzero:
        return 1.0
    direction = 1 if sum(nonzero) >= 0 else -1
    return round(sum(1 for value in nonzero if value * direction > 0) / len(nonzero), 6)


def feature_snapshot(metadata: MatchMetadata, cutoff: datetime) -> dict[str, Any]:
    asian = market_nodes(metadata, "asian_handicap", cutoff)
    euro = market_nodes(metadata, "european_odds", cutoff)
    total = market_nodes(metadata, "total_goals", cutoff)
    kelly = market_nodes(metadata, "kelly_index", cutoff)
    providers = sorted({item.provider_id for item in metadata.market_snapshots if item.captured_at <= cutoff})
    late_asian = asian[-1] if asian else None
    late_euro = euro[-1] if euro else None
    late_kelly = kelly[-1] if kelly else None
    asian_same_line, asian_line_reason = same_line_three_nodes(asian, "home_line")
    total_same_line, total_line_reason = same_line_three_nodes(total, "line")
    late_favorite_odds = None
    if late_euro:
        home_odds = _number(late_euro, "home")
        away_odds = _number(late_euro, "away")
        if home_odds is not None and away_odds is not None:
            late_favorite_odds = min(home_odds, away_odds)
    late_kelly_values = [
        _number(late_kelly, key) if late_kelly else None
        for key in ("home", "draw", "away")
    ]
    late_kelly_spread = None
    if all(value is not None for value in late_kelly_values):
        late_kelly_spread = round(max(late_kelly_values) - min(late_kelly_values), 6)
    return {
        "asian_nodes": [item.snapshot_id for item in asian],
        "euro_nodes": [item.snapshot_id for item in euro],
        "total_nodes": [item.snapshot_id for item in total],
        "kelly_nodes": [item.snapshot_id for item in kelly],
        "providers": providers,
        "asian_three_nodes": three_comparable(asian, "home_line")[0],
        "total_three_nodes": three_comparable(total, "line")[0],
        "euro_three_nodes": three_comparable(euro)[0],
        "kelly_three_nodes": three_comparable(kelly)[0],
        "asian_same_line_three_nodes": asian_same_line,
        "asian_same_line_reason": asian_line_reason,
        "total_same_line_three_nodes": total_same_line,
        "total_same_line_reason": total_line_reason,
        "asian_home_water_non_increasing": non_increasing(asian, "home_water"),
        "asian_home_water_change": net_change(asian, "home_water"),
        "total_over_water_change": net_change(total, "over_water"),
        "away_odds_change": net_change(euro, "away"),
        "away_odds_relative_change": relative_change(euro, "away"),
        "home_odds_change": net_change(euro, "home"),
        "draw_odds_change": net_change(euro, "draw"),
        "draw_odds_relative_change": relative_change(euro, "draw"),
        "home_kelly_change": net_change(kelly, "home"),
        "draw_kelly_change": net_change(kelly, "draw"),
        "home_water_purity": trend_purity(asian, "home_water"),
        "over_water_purity": trend_purity(total, "over_water"),
        "late_home_line": _number(late_asian, "home_line") if late_asian else None,
        "late_home_water": _number(late_asian, "home_water") if late_asian else None,
        "late_total_line": _number(total[-1], "line") if total else None,
        "late_over_water": _number(total[-1], "over_water") if total else None,
        "late_home_odds": _number(late_euro, "home") if late_euro else None,
        "late_favorite_odds": late_favorite_odds,
        "late_home_kelly": _number(late_kelly, "home") if late_kelly else None,
        "late_away_kelly": _number(late_kelly, "away") if late_kelly else None,
        "late_draw_kelly": _number(late_kelly, "draw") if late_kelly else None,
        "late_kelly_spread": late_kelly_spread,
    }
