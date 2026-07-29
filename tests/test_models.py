from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from odds_journal.models import MatchMetadata


def base_metadata() -> dict:
    return {
        "match_id": "20260730-kor-k1-fc-seoul-ulsan-hd",
        "kickoff_at": "2026-07-30T18:30:00+08:00",
        "competition_code": "KOR-K1",
        "competition": "韩K联",
        "home_team_id": "fc-seoul",
        "home_team": "FC首尔",
        "away_team_id": "ulsan-hd",
        "away_team": "蔚山HD",
        "analysis_started_at": "2026-07-30T10:00:00+08:00",
    }


def test_market_and_selection_must_match() -> None:
    values = base_metadata() | {
        "primary_market": "handicap",
        "primary_selection": "home",
    }
    with pytest.raises(ValidationError, match="不适用于"):
        MatchMetadata.model_validate(values)


def test_times_must_include_timezone() -> None:
    values = base_metadata() | {"kickoff_at": datetime(2026, 7, 30, 18, 30)}
    with pytest.raises(ValidationError, match="时区"):
        MatchMetadata.model_validate(values)


def test_score_and_total_goals_must_agree() -> None:
    values = base_metadata() | {"score": "2-1", "total_goals": 2}
    with pytest.raises(ValidationError, match="不一致"):
        MatchMetadata.model_validate(values)

