"""Knowledge Engine 观测适配器。

接入现有 observations 和 market_monitoring 模块。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..ports.observations import ObservationReaderPort


class CurrentObservationReader:
    """当前观测读取适配器。

    通过现有 observations 模块读取合格观测。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def read_observations(
        self,
        match_id: str,
        market: str,
        cutoff: datetime,
    ) -> list[dict[str, Any]]:
        from ...observations import prediction_eligible_market_observations

        ledger_map = {
            "one_x_two": "european_odds",
            "asian_handicap": "asian_handicap",
            "total_goals": "total_goals",
            "fixed_handicap_1x2": "fixed_handicap_1x2",
        }
        ledger_market = ledger_map.get(market, market)
        return prediction_eligible_market_observations(
            self._root,
            match_id=match_id,
            market=ledger_market,
            cutoff=cutoff,
        )

    def observation_conflicts(
        self,
        match_id: str,
        market: str,
        cutoff: datetime,
    ) -> list[str]:
        from ...observations import observation_conflict_ids

        ledger_map = {
            "one_x_two": "european_odds",
            "asian_handicap": "asian_handicap",
            "total_goals": "total_goals",
            "fixed_handicap_1x2": "fixed_handicap_1x2",
        }
        ledger_market = ledger_map.get(market, market)
        return sorted(
            observation_conflict_ids(
                self._root,
                match_id=match_id,
                market=ledger_market,
                cutoff=cutoff,
                prediction_eligible_only=True,
            )
        )