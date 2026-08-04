from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .analysis_context import analysis_is_placeholder, parse_receipt
from .ledger import append_payloads, read_ledger, sha256_json
from .markdown import MatchDocument
from .models import MarketSnapshot, MatchStatus
from .paths import match_files
from .transaction import RepositoryTransaction


MARKET_OBSERVATION_LEDGER = Path("knowledge/market-observations/events.jsonl")
MARKET_SOURCE_LEDGER = Path("knowledge/market-observations/source-links.jsonl")
FIXTURE_FACT_LEDGER = Path("knowledge/match-facts/events.jsonl")
MATCH_RESULT_LEDGER = Path("knowledge/match-results/events.jsonl")

PROVIDER_ALIASES = {
    "澳*": "macau",
    "澳门": "macau",
    "macau": "macau",
    "36*": "bet365",
    "365": "bet365",
    "bet365": "bet365",
    "威*": "william-hill",
    "威廉希尔": "william-hill",
    "william-hill": "william-hill",
    "立*": "ladbrokes",
    "立博": "ladbrokes",
    "ladbrokes": "ladbrokes",
    "interwet*": "interwetten",
    "interwetten": "interwetten",
    "betfair*": "betfair",
    "betfair": "betfair",
    "最大值": "kelly-aggregate-max",
    "最小值": "kelly-aggregate-min",
    "6家平均": "kelly-aggregate-6avg",
}


class ObservationError(ValueError):
    pass


class SourceKind(StrEnum):
    USER_CONFIRMED_TEXT = "user_confirmed_text"
    SCREENSHOT_VERIFIED = "screenshot_verified"
    LEGACY_SNAPSHOT = "legacy_snapshot"


class TimePrecision(StrEnum):
    EXACT = "exact"
    PHASE_ONLY = "phase_only"
    UNKNOWN = "unknown"


class ObservationPhase(StrEnum):
    OPENING = "opening"
    MID = "mid"
    LATE = "late"
    CURRENT = "current"


class QuoteRole(StrEnum):
    MAIN_LINE = "main_line"
    ALTERNATE_LINE = "alternate_line"
    PROVIDER = "provider"
    AGGREGATE = "aggregate"


class ResultStatus(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"


class FixtureBundleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    competition_code: str | None = None
    competition: str = Field(min_length=1)
    home_team: str = Field(min_length=1)
    away_team: str = Field(min_length=1)
    kickoff_at: datetime
    timezone: str = "Asia/Shanghai"
    venue: str | None = None
    weather: str | None = None

    @field_validator("kickoff_at")
    @classmethod
    def kickoff_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("kickoff_at 必须包含时区")
        return value


class QuoteValuesV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home: str | None = None
    draw: str | None = None
    away: str | None = None
    over: str | None = None
    under: str | None = None
    line: str | None = None

    @model_validator(mode="after")
    def non_empty(self) -> "QuoteValuesV1":
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("盘口值不能为空")
        return self


class MacauTimelineInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayed_at: str = Field(min_length=1)
    status: str = "即"
    home_water: str
    line: str
    away_water: str
    source_line_start: int | None = Field(default=None, ge=1)
    source_line_end: int | None = Field(default=None, ge=1)
    sequence_no: int | None = Field(default=None, ge=1)


class SummaryRowInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str | None = None
    provider_name: str = Field(min_length=1)
    opening: QuoteValuesV1 | None = None
    current: QuoteValuesV1 | None = None
    opening_status: Literal["available", "not_displayed", "not_provided"] = "available"
    current_status: Literal["available", "not_displayed", "not_provided"] = "available"
    opening_observed_at: datetime | None = None
    current_observed_at: datetime | None = None
    quote_role: QuoteRole = QuoteRole.PROVIDER
    source_line_start: int | None = Field(default=None, ge=1)
    source_line_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def phase_values(self) -> "SummaryRowInputV1":
        if self.opening_status == "available" and self.opening is None:
            raise ValueError(f"{self.provider_name} 初盘标记 available 但缺少数值")
        if self.current_status == "available" and self.current is None:
            raise ValueError(f"{self.provider_name} 即盘标记 available 但缺少数值")
        return self

    @field_validator("opening_observed_at", "current_observed_at")
    @classmethod
    def endpoint_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("端点 observed_at 必须包含时区")
        return value


class MarketDataInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: SourceKind
    source_captured_at: datetime | None = None
    source_ref: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    capture_batch_id: str | None = None
    macau_handicap_timeline: list[MacauTimelineInputV1] = Field(default_factory=list)
    handicap_summary: list[SummaryRowInputV1] = Field(default_factory=list)
    european_odds_summary: list[SummaryRowInputV1] = Field(default_factory=list)
    total_goals_summary: list[SummaryRowInputV1] = Field(default_factory=list)
    kelly_summary: list[SummaryRowInputV1] = Field(default_factory=list)

    @field_validator("source_captured_at")
    @classmethod
    def capture_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("source_captured_at 必须包含时区")
        return value


class MatchResultInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ResultStatus = ResultStatus.CONFIRMED
    halftime_score: str | None = None
    final_score: str | None = None
    observed_at: datetime | None = None
    source_ref: str | None = None

    @field_validator("halftime_score", "final_score")
    @classmethod
    def score_shape(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"\d+-\d+", value):
            raise ValueError("比分必须使用 H-A 格式")
        return value

    @field_validator("observed_at")
    @classmethod
    def result_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("赛果 observed_at 必须包含时区")
        return value


class MatchDataBundleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    bundle_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    fixture: FixtureBundleV1
    market_data: MarketDataInputV1 | None = None
    result: MatchResultInputV1 | None = None


class MarketObservationEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    observation_id: str
    match_id: str
    source_kind: SourceKind
    source_ref: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_line_start: int | None = None
    source_line_end: int | None = None
    received_at: datetime
    source_captured_at: datetime | None = None
    time_precision: TimePrecision
    observed_at: datetime | None = None
    phase_hint: ObservationPhase | None = None
    display_status: str | None = None
    capture_batch_id: str
    sequence_no: int | None = None
    provider_id: str
    provider_name_raw: str
    market: Literal["asian_handicap", "european_odds", "total_goals", "kelly_index"]
    market_scope: Literal["full_time"] = "full_time"
    quote_role: QuoteRole
    odds_format: Literal["hong_kong", "decimal", "kelly"]
    raw_values: dict[str, str]
    normalized_line: float | None = None
    normalized_prices: dict[str, float]
    availability_status: Literal["available", "not_displayed"] = "available"
    normalization_eligible: bool = True
    prediction_eligible: bool
    retrospective_validation_eligible: Literal["eligible", "pending_certification", "ineligible"]
    ineligibility_reasons: list[str] = Field(default_factory=list)
    possible_duplicate_of: str | None = None

    @model_validator(mode="after")
    def time_contract(self) -> "MarketObservationEventV1":
        if self.time_precision == TimePrecision.EXACT and self.observed_at is None:
            raise ValueError("exact 观测必须包含 observed_at")
        if self.time_precision != TimePrecision.EXACT and self.observed_at is not None:
            raise ValueError("非 exact 观测不得伪造 observed_at")
        if self.availability_status == "not_displayed":
            if self.normalization_eligible or self.prediction_eligible or self.normalized_prices:
                raise ValueError("未显示端点只能作为不可用覆盖记录保存")
        elif not self.normalized_prices:
            raise ValueError("可用观测必须包含规范化价格")
        return self


class FixtureFactObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fact_id: str
    match_id: str
    competition_code: str
    competition_raw: str
    home_team_id: str
    home_team_raw: str
    away_team_id: str
    away_team_raw: str
    kickoff_at: datetime
    timezone: str
    venue: str | None = None
    weather_raw: str | None = None
    weather_type: str | None = None
    temperature_min: float | None = None
    temperature_max: float | None = None
    source_ref: str
    source_sha256: str
    received_at: datetime


class MatchResultObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    result_id: str
    match_id: str
    period: Literal["half_time", "full_time"]
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    score: str
    result_status: ResultStatus
    observed_at: datetime | None = None
    received_at: datetime
    source_ref: str
    source_sha256: str
    result_1x2: Literal["home", "draw", "away"] | None = None
    total_goals: int | None = None


class ResultSourceLinkV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    result_source_link_id: str
    result_id: str
    match_id: str
    source_ref: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class IngestSummaryV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    bundle_id: str
    match_id: str
    observations_seen: int
    observations_added: int
    source_links_added: int
    conflicts_added: int
    facts_added: int
    results_added: int
    compatibility_snapshots_added: int
    dispositions: dict[str, int]


def _numeric(value: str) -> float:
    try:
        return float(value.strip())
    except ValueError as exc:
        raise ObservationError(f"无法规范化数值：{value}") from exc


def normalize_line(value: str) -> float:
    text = value.strip().replace(" ", "")
    sign = -1.0 if text.startswith("-") else 1.0
    text = text[1:] if text.startswith("-") else text
    parts = text.split("/")
    if not parts or len(parts) > 2:
        raise ObservationError(f"无法规范化盘口：{value}")
    return round(sign * sum(_numeric(part) for part in parts) / len(parts), 6)


def canonical_provider(provider_name: str, provider_id: str | None = None) -> str:
    if provider_id:
        value = provider_id.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]+", value):
            raise ObservationError(f"provider_id 无效：{provider_id}")
        return value
    key = provider_name.strip().lower()
    if key not in PROVIDER_ALIASES:
        raise ObservationError(f"未知机构，必须显式提供 provider_id：{provider_name}")
    return PROVIDER_ALIASES[key]


def _hash(value: Any) -> str:
    return sha256_json(value)


def _source_sha(root: Path, source_ref: str | None, explicit: str | None, bundle: MatchDataBundleV1) -> str:
    if source_ref:
        candidate = (root / source_ref).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            candidate = Path()
        if candidate.is_file():
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if explicit and explicit != actual:
                raise ObservationError("source_sha256 与 source_ref 文件内容不一致")
            return actual
    if explicit:
        return explicit
    return _hash(bundle.model_dump(mode="json"))


def _resolve_match(root: Path, bundle: MatchDataBundleV1, match_path: Path | None = None) -> tuple[Path, MatchDocument]:
    if match_path is not None:
        document = MatchDocument.load(match_path)
        fixture = bundle.fixture
        if document.metadata.home_team != fixture.home_team or document.metadata.away_team != fixture.away_team:
            raise ObservationError("bundle 主客队与指定 Match 不一致")
        if document.metadata.kickoff_at != fixture.kickoff_at:
            raise ObservationError("bundle 开赛时间与指定 Match 不一致")
        if fixture.competition_code and document.metadata.competition_code != fixture.competition_code:
            raise ObservationError("bundle 联赛代码与指定 Match 不一致")
        return match_path, document
    candidates: list[tuple[Path, MatchDocument]] = []
    for path in match_files(root):
        document = MatchDocument.load(path)
        if (
            document.metadata.home_team == bundle.fixture.home_team
            and document.metadata.away_team == bundle.fixture.away_team
            and document.metadata.kickoff_at == bundle.fixture.kickoff_at
        ):
            candidates.append((path, document))
    if len(candidates) != 1:
        raise ObservationError("比赛身份无法唯一绑定，请显式提供 --match")
    return candidates[0]


def _parse_displayed_at(text: str, kickoff: datetime, timezone: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", text.strip())
    if not match:
        raise ObservationError(f"详细时序时间无法确认：{text}")
    month, day, hour, minute = map(int, match.groups())
    zone = ZoneInfo(timezone)
    local_kickoff = kickoff.astimezone(zone)
    candidates = []
    for year in (local_kickoff.year - 1, local_kickoff.year, local_kickoff.year + 1):
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=zone)
        except ValueError:
            continue
        if candidate < local_kickoff:
            candidates.append(candidate)
    if not candidates:
        raise ObservationError(f"详细时序时间不早于开赛：{text}")
    return min(candidates, key=lambda item: abs((local_kickoff - item).total_seconds()))


def _weather(value: str | None) -> tuple[str | None, float | None, float | None]:
    if not value:
        return None, None, None
    temperatures = [float(item) for item in re.findall(r"(-?\d+(?:\.\d+)?)\s*℃", value)]
    weather_type = re.split(r"-?\d", value, maxsplit=1)[0].strip() or None
    return weather_type, min(temperatures) if temperatures else None, max(temperatures) if temperatures else None


def _price_payload(market: str, values: QuoteValuesV1) -> tuple[dict[str, str], float | None, dict[str, float], str]:
    raw = {key: value for key, value in values.model_dump().items() if value is not None}
    if market == "asian_handicap":
        required = {"home", "line", "away"}
        odds_format = "hong_kong"
        prices = {"home": _numeric(raw["home"]), "away": _numeric(raw["away"])} if required <= set(raw) else {}
    elif market == "total_goals":
        required = {"over", "line", "under"}
        odds_format = "hong_kong"
        prices = {"over": _numeric(raw["over"]), "under": _numeric(raw["under"])} if required <= set(raw) else {}
    else:
        required = {"home", "draw", "away"}
        odds_format = "kelly" if market == "kelly_index" else "decimal"
        prices = {key: _numeric(raw[key]) for key in ("home", "draw", "away")} if required <= set(raw) else {}
    if not prices:
        raise ObservationError(f"{market} 字段不完整：需要 {', '.join(sorted(required))}")
    line = normalize_line(raw["line"]) if "line" in raw else None
    return raw, line, prices, odds_format


def _eligibility(received_at: datetime, observed_at: datetime | None, kickoff: datetime, source_kind: SourceKind) -> tuple[bool, str, list[str]]:
    reasons = []
    prediction = received_at < kickoff and (observed_at is None or observed_at < kickoff)
    if received_at >= kickoff:
        reasons.append("source_received_after_kickoff")
    if observed_at is not None and observed_at >= kickoff:
        reasons.append("observation_not_prematch")
    retrospective = "eligible" if prediction else "pending_certification" if source_kind in {SourceKind.SCREENSHOT_VERIFIED, SourceKind.USER_CONFIRMED_TEXT} else "ineligible"
    return prediction, retrospective, reasons


def _observation_identity(payload: dict[str, Any]) -> str:
    identity = {
        "match_id": payload["match_id"], "provider_id": payload["provider_id"],
        "market": payload["market"], "market_scope": payload["market_scope"],
        "quote_role": payload["quote_role"], "time_precision": payload["time_precision"],
        "observed_at": payload.get("observed_at"), "phase_hint": payload.get("phase_hint"),
        "capture_batch_id": payload["capture_batch_id"], "normalized_line": payload.get("normalized_line"),
        "normalized_prices": payload["normalized_prices"],
    }
    return "observation-" + _hash(identity)[:24]


def _natural_key(payload: dict[str, Any]) -> str:
    time_key = payload.get("observed_at") if payload["time_precision"] == "exact" else f"{payload.get('phase_hint')}|{payload['capture_batch_id']}"
    return "|".join(str(payload.get(key)) for key in ("match_id", "provider_id", "market", "market_scope", "quote_role")) + "|" + str(time_key)


def _value_hash(payload: dict[str, Any]) -> str:
    return _hash({
        "odds_format": payload["odds_format"],
        "line": payload.get("normalized_line"),
        "prices": payload["normalized_prices"],
        "availability_status": payload.get("availability_status", "available"),
    })


def _source_link_id(observation_id: str, source_sha256: str, start: int | None, end: int | None) -> str:
    return "source-link-" + _hash([observation_id, source_sha256, start, end])[:24]


def _result_source_link_id(result_id: str, source_sha256: str, source_ref: str) -> str:
    return "result-source-link-" + _hash([result_id, source_sha256, source_ref])[:24]


def _fixture_value_hash(payload: dict[str, Any]) -> str:
    ignored = {"fact_id", "source_ref", "source_sha256", "received_at"}
    return _hash({key: value for key, value in payload.items() if key not in ignored})


def _event_payloads(path: Path) -> list[dict[str, Any]]:
    return [event.payload for event in read_ledger(path)] if path.exists() else []


def _active_observations(root: Path) -> list[dict[str, Any]]:
    events = _event_payloads(root / MARKET_OBSERVATION_LEDGER)
    superseded = {item.get("supersedes_observation_id") for item in events if item.get("supersedes_observation_id")}
    return [item for item in events if item.get("event_type") == "recorded" and item.get("observation_id") not in superseded]


def _active_results(root: Path) -> list[dict[str, Any]]:
    events = _event_payloads(root / MATCH_RESULT_LEDGER)
    superseded = {
        item.get("supersedes_result_id")
        for item in events
        if item.get("event_type") == "superseded" and item.get("supersedes_result_id")
    }
    return [
        item for item in events
        if item.get("event_type", "recorded") == "recorded"
        and item.get("result_id") not in superseded
    ]


def _result_resolutions(root: Path) -> dict[str, dict[str, Any]]:
    resolutions = {}
    for item in _event_payloads(root / MATCH_RESULT_LEDGER):
        if item.get("event_type") == "conflict_resolution":
            resolutions[str(item["conflict_group_id"])] = item
    return resolutions


def result_conflict_report(root: Path, *, match_id: str | None = None) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in _active_results(root):
        if match_id and item["match_id"] != match_id:
            continue
        grouped[(item["match_id"], item["period"])].append(item)
    output = []
    resolutions = _result_resolutions(root)
    for (current_match_id, period), values in sorted(grouped.items()):
        if len({item["score"] for item in values}) <= 1:
            continue
        group_id = "result-conflict-" + _hash([current_match_id, period])[:20]
        output.append({
            "conflict_group_id": group_id,
            "match_id": current_match_id,
            "period": period,
            "status": resolutions.get(group_id, {}).get("status", "unresolved"),
            "selected_result_id": resolutions.get(group_id, {}).get("selected_result_id"),
            "reason": resolutions.get(group_id, {}).get("reason"),
            "observations": values,
        })
    return output


def resolve_result_conflict(
    root: Path,
    *,
    conflict_group_id: str,
    selected_result_id: str,
    reason: str,
    actor: str,
) -> dict[str, Any]:
    groups = {item["conflict_group_id"]: item for item in result_conflict_report(root)}
    group = groups.get(conflict_group_id)
    if group is None:
        raise ObservationError(f"赛果冲突不存在：{conflict_group_id}")
    if selected_result_id not in {item["result_id"] for item in group["observations"]}:
        raise ObservationError("selected_result_id 不属于该赛果冲突")
    if not reason.strip():
        raise ObservationError("赛果冲突处置必须提供理由")
    previous = _result_resolutions(root).get(conflict_group_id)
    payload = {
        "event_type": "conflict_resolution",
        "conflict_group_id": conflict_group_id,
        "match_id": group["match_id"],
        "period": group["period"],
        "status": "superseded",
        "selected_result_id": selected_result_id,
        "reason": reason.strip(),
    }
    if previous:
        payload["_supersedes_event_id"] = (
            f"match-result-conflict-resolution:{conflict_group_id}:{_hash(previous)[:16]}"
        )
    event_hash = _hash({key: value for key, value in payload.items() if key != "_supersedes_event_id"})[:16]
    ledger = root / MATCH_RESULT_LEDGER
    recorded_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    with RepositoryTransaction(root, files=[ledger], directories=[], operation="result-conflict-resolution") as transaction:
        append_payloads(
            ledger, [payload], recorded_at=recorded_at, actor=actor,
            event_id_factory=lambda _item, _index: f"match-result-conflict-resolution:{conflict_group_id}:{event_hash}",
        )
        transaction.commit()
    return next(item for item in result_conflict_report(root) if item["conflict_group_id"] == conflict_group_id)


def _conflict_resolutions(root: Path) -> dict[str, dict[str, Any]]:
    resolutions: dict[str, dict[str, Any]] = {}
    for item in _event_payloads(root / MARKET_OBSERVATION_LEDGER):
        if item.get("event_type") == "conflict_resolution":
            resolutions[str(item["conflict_group_id"])] = item
    return resolutions


def _conflict_index(
    observations: list[dict[str, Any]],
    resolutions: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, str], dict[str, list[dict[str, Any]]]]:
    by_natural: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        by_natural[_natural_key(item)].append(item)
    by_observation: dict[str, str] = {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for natural, values in by_natural.items():
        if len({_value_hash(item) for item in values}) <= 1:
            continue
        group_id = "market-conflict-" + _hash(natural)[:20]
        groups[group_id] = values
        resolution = (resolutions or {}).get(group_id)
        selected = resolution.get("selected_observation_id") if resolution else None
        for item in values:
            if resolution and resolution.get("status") in {"confirmed_source", "superseded"} and item["observation_id"] == selected:
                continue
            by_observation[item["observation_id"]] = group_id
    return by_observation, groups


def _make_market_observation(
    *, match_id: str, source: MarketDataInputV1, source_ref: str, source_sha256: str,
    received_at: datetime, kickoff: datetime, provider_id: str, provider_name: str,
    market: str, role: QuoteRole, values: QuoteValuesV1, time_precision: TimePrecision,
    phase: ObservationPhase | None, observed_at: datetime | None, sequence_no: int | None,
    display_status: str | None, source_line_start: int | None, source_line_end: int | None,
) -> dict[str, Any]:
    raw, line, prices, odds_format = _price_payload(market, values)
    prediction, retrospective, reasons = _eligibility(received_at, observed_at, kickoff, source.source_kind)
    capture_batch_id = source.capture_batch_id or "capture-" + _hash([source_sha256, source.source_captured_at.isoformat() if source.source_captured_at else None])[:16]
    payload = MarketObservationEventV1(
        observation_id="observation-placeholder", match_id=match_id, source_kind=source.source_kind,
        source_ref=source_ref, source_sha256=source_sha256, source_line_start=source_line_start,
        source_line_end=source_line_end, received_at=received_at, source_captured_at=source.source_captured_at,
        time_precision=time_precision, observed_at=observed_at, phase_hint=phase, display_status=display_status,
        capture_batch_id=capture_batch_id, sequence_no=sequence_no, provider_id=provider_id,
        provider_name_raw=provider_name, market=market, quote_role=role, odds_format=odds_format,
        raw_values=raw, normalized_line=line, normalized_prices=prices,
        prediction_eligible=prediction, retrospective_validation_eligible=retrospective,
        ineligibility_reasons=reasons,
    ).model_dump(mode="json")
    payload["observation_id"] = _observation_identity(payload)
    return payload


def _make_availability_observation(
    *, match_id: str, source: MarketDataInputV1, source_ref: str,
    source_sha256: str, received_at: datetime, provider_id: str,
    provider_name: str, market: str, role: QuoteRole,
    phase: ObservationPhase, source_line_start: int | None,
    source_line_end: int | None,
) -> dict[str, Any]:
    capture_batch_id = source.capture_batch_id or "capture-" + _hash([
        source_sha256,
        source.source_captured_at.isoformat() if source.source_captured_at else None,
    ])[:16]
    odds_format = "kelly" if market == "kelly_index" else "decimal" if market == "european_odds" else "hong_kong"
    payload = MarketObservationEventV1(
        observation_id="observation-placeholder",
        match_id=match_id,
        source_kind=source.source_kind,
        source_ref=source_ref,
        source_sha256=source_sha256,
        source_line_start=source_line_start,
        source_line_end=source_line_end,
        received_at=received_at,
        source_captured_at=source.source_captured_at,
        time_precision=TimePrecision.PHASE_ONLY,
        phase_hint=phase,
        capture_batch_id=capture_batch_id,
        provider_id=provider_id,
        provider_name_raw=provider_name,
        market=market,
        quote_role=role,
        odds_format=odds_format,
        raw_values={},
        normalized_prices={},
        availability_status="not_displayed",
        normalization_eligible=False,
        prediction_eligible=False,
        retrospective_validation_eligible="ineligible",
        ineligibility_reasons=["quote_not_displayed"],
    ).model_dump(mode="json")
    payload["observation_id"] = _observation_identity(payload)
    return payload


def prepare_bundle(root: Path, bundle: MatchDataBundleV1, *, match_path: Path | None = None, received_at: datetime | None = None) -> dict[str, Any]:
    path, document = _resolve_match(root, bundle, match_path)
    received = received_at or datetime.now(ZoneInfo(bundle.fixture.timezone)).replace(microsecond=0)
    source = bundle.market_data
    source_ref = source.source_ref if source and source.source_ref else f"bundle:{bundle.bundle_id}"
    source_sha = _source_sha(root, source_ref if source else None, source.source_sha256 if source else None, bundle)
    observations: list[dict[str, Any]] = []
    availability: list[dict[str, Any]] = []
    if source:
        for index, node in enumerate(source.macau_handicap_timeline, start=1):
            observed = _parse_displayed_at(node.displayed_at, bundle.fixture.kickoff_at, bundle.fixture.timezone)
            observations.append(_make_market_observation(
                match_id=document.metadata.match_id, source=source, source_ref=source_ref,
                source_sha256=source_sha, received_at=received, kickoff=bundle.fixture.kickoff_at,
                provider_id="macau", provider_name="澳*", market="asian_handicap",
                role=QuoteRole.MAIN_LINE,
                values=QuoteValuesV1(home=node.home_water, line=node.line, away=node.away_water),
                time_precision=TimePrecision.EXACT, phase=None, observed_at=observed,
                sequence_no=node.sequence_no or index, display_status=node.status,
                source_line_start=node.source_line_start, source_line_end=node.source_line_end,
            ))
        summaries = (
            ("asian_handicap", source.handicap_summary),
            ("european_odds", source.european_odds_summary),
            ("total_goals", source.total_goals_summary),
            ("kelly_index", source.kelly_summary),
        )
        for market, rows in summaries:
            for row in rows:
                provider = canonical_provider(row.provider_name, row.provider_id)
                role = QuoteRole.AGGREGATE if provider.startswith("kelly-aggregate-") else (QuoteRole.MAIN_LINE if market in {"asian_handicap", "total_goals"} else QuoteRole.PROVIDER)
                for phase_name, values, status in (
                    (ObservationPhase.OPENING, row.opening, row.opening_status),
                    (ObservationPhase.LATE, row.current, row.current_status),
                ):
                    if status == "not_provided":
                        continue
                    if status == "not_displayed":
                        availability.append({"match_id": document.metadata.match_id, "provider_id": provider, "market": market, "phase_hint": phase_name.value, "availability_status": "not_displayed", "capture_batch_id": source.capture_batch_id or bundle.bundle_id})
                        observations.append(_make_availability_observation(
                            match_id=document.metadata.match_id,
                            source=source,
                            source_ref=source_ref,
                            source_sha256=source_sha,
                            received_at=received,
                            provider_id=provider,
                            provider_name=row.provider_name,
                            market=market,
                            role=role,
                            phase=phase_name,
                            source_line_start=row.source_line_start,
                            source_line_end=row.source_line_end,
                        ))
                        continue
                    assert values is not None
                    endpoint_time = row.opening_observed_at if phase_name == ObservationPhase.OPENING else row.current_observed_at
                    if endpoint_time is None and phase_name == ObservationPhase.LATE:
                        endpoint_time = source.source_captured_at
                    observations.append(_make_market_observation(
                        match_id=document.metadata.match_id, source=source, source_ref=source_ref,
                        source_sha256=source_sha, received_at=received, kickoff=bundle.fixture.kickoff_at,
                        provider_id=provider, provider_name=row.provider_name, market=market, role=role,
                        values=values, time_precision=TimePrecision.EXACT if endpoint_time is not None else TimePrecision.PHASE_ONLY,
                        phase=phase_name, observed_at=endpoint_time,
                        sequence_no=None, display_status=None, source_line_start=row.source_line_start,
                        source_line_end=row.source_line_end,
                    ))
    weather_type, temperature_min, temperature_max = _weather(bundle.fixture.weather)
    fact_raw = {
        "match_id": document.metadata.match_id, "competition_code": document.metadata.competition_code,
        "competition_raw": bundle.fixture.competition, "home_team_id": document.metadata.home_team_id,
        "home_team_raw": bundle.fixture.home_team, "away_team_id": document.metadata.away_team_id,
        "away_team_raw": bundle.fixture.away_team, "kickoff_at": bundle.fixture.kickoff_at,
        "timezone": bundle.fixture.timezone, "venue": bundle.fixture.venue,
        "weather_raw": bundle.fixture.weather, "weather_type": weather_type,
        "temperature_min": temperature_min, "temperature_max": temperature_max,
        "source_ref": source_ref, "source_sha256": source_sha, "received_at": received,
    }
    fact_raw["fact_id"] = "fixture-fact-" + _hash({key: str(value) for key, value in fact_raw.items() if key not in {"received_at", "source_ref"}})[:24]
    fact = FixtureFactObservationV1.model_validate(fact_raw).model_dump(mode="json")
    results: list[dict[str, Any]] = []
    if bundle.result:
        if bundle.result.observed_at and bundle.result.observed_at < bundle.fixture.kickoff_at:
            raise ObservationError("赛果 observed_at 不得早于开赛时间")
        result_ref = bundle.result.source_ref or source_ref
        for period, score in (("half_time", bundle.result.halftime_score), ("full_time", bundle.result.final_score)):
            if score is None:
                continue
            home, away = map(int, score.split("-"))
            result_raw = {
                "match_id": document.metadata.match_id, "period": period, "home_score": home,
                "away_score": away, "score": score, "result_status": bundle.result.status,
                "observed_at": bundle.result.observed_at, "received_at": received,
                "source_ref": result_ref, "source_sha256": source_sha,
                "result_1x2": ("home" if home > away else "away" if home < away else "draw") if period == "full_time" else None,
                "total_goals": home + away if period == "full_time" else None,
            }
            result_raw["result_id"] = "match-result-" + _hash({
                "match_id": document.metadata.match_id,
                "period": period,
                "score": score,
                "result_status": str(bundle.result.status),
            })[:24]
            results.append(MatchResultObservationV1.model_validate(result_raw).model_dump(mode="json"))
    return {"match_path": path, "document": document, "source_ref": source_ref, "source_sha256": source_sha, "received_at": received, "fact": fact, "observations": observations, "availability": availability, "results": results}


def _compatibility_snapshot(payload: dict[str, Any], phase: str) -> MarketSnapshot:
    market = payload["market"]
    prices = payload["normalized_prices"]
    raw = payload["raw_values"]
    if market == "asian_handicap":
        normalized = {"home_line": payload["normalized_line"], "line": payload["normalized_line"], "home_water": prices["home"], "away_water": prices["away"]}
        raw_values = {"home_line": raw["line"], "line": raw["line"], "home_water": raw["home"], "away_water": raw["away"]}
    elif market == "total_goals":
        normalized = {"line": payload["normalized_line"], "over_water": prices["over"], "under_water": prices["under"]}
        raw_values = {"line": raw["line"], "over_water": raw["over"], "under_water": raw["under"]}
    else:
        normalized = {"home": prices["home"], "draw": prices["draw"], "away": prices["away"], "home_win": prices["home"], "away_win": prices["away"]}
        raw_values = {"home": raw["home"], "draw": raw["draw"], "away": raw["away"], "home_win": raw["home"], "away_win": raw["away"]}
    return MarketSnapshot(
        snapshot_id="market-obs-" + payload["observation_id"].split("-")[-1], market=market,
        phase=phase, captured_at=datetime.fromisoformat(payload["observed_at"]), provider_id=payload["provider_id"],
        source_ref=f"market-observation:{payload['observation_id']}", odds_format=payload["odds_format"],
        raw_values=raw_values, normalized_values=normalized,
    )


def _project_compatibility(path: Path, document: MatchDocument, active: list[dict[str, Any]], conflicted_ids: set[str]) -> int:
    if document.metadata.schema_version != 2 or MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        return 0
    if parse_receipt(document.sections["prematch-reasoning"]) or not analysis_is_placeholder(document.sections["prematch-reasoning"]):
        return 0
    by_series: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in active:
        if item["match_id"] != document.metadata.match_id or item["observation_id"] in conflicted_ids:
            continue
        if not item["prediction_eligible"] or item["time_precision"] != "exact":
            continue
        by_series[(item["provider_id"], item["market"])].append(item)
    generated: list[MarketSnapshot] = []
    for values in by_series.values():
        ordered = sorted(values, key=lambda item: (item["observed_at"], item["observation_id"]))
        for index, item in enumerate(ordered):
            phase = "opening" if index == 0 else "late" if index == len(ordered) - 1 else "mid"
            generated.append(_compatibility_snapshot(item, phase))
    existing = {item.snapshot_id: item for item in document.metadata.market_snapshots if not item.snapshot_id.startswith("market-obs-")}
    existing.update({item.snapshot_id: item for item in generated})
    before = len(document.metadata.market_snapshots)
    document.metadata.market_snapshots = list(existing.values())
    document.save()
    return max(0, len(document.metadata.market_snapshots) - before)


def ingest_bundle(
    root: Path,
    bundle: MatchDataBundleV1,
    *,
    match_path: Path | None = None,
    actor: str = "lcz",
    received_at: datetime | None = None,
    project_compatibility: bool = True,
) -> IngestSummaryV1:
    prepared = prepare_bundle(root, bundle, match_path=match_path, received_at=received_at)
    path: Path = prepared["match_path"]
    document: MatchDocument = prepared["document"]
    observation_path = root / MARKET_OBSERVATION_LEDGER
    source_path = root / MARKET_SOURCE_LEDGER
    fact_path = root / FIXTURE_FACT_LEDGER
    result_path = root / MATCH_RESULT_LEDGER
    existing_observations = _active_observations(root)
    by_id = {item["observation_id"]: item for item in existing_observations}
    by_natural: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in existing_observations:
        by_natural[_natural_key(item)].append(item)
    observation_payloads: list[dict[str, Any]] = []
    source_payloads: list[dict[str, Any]] = []
    conflicts = 0
    dispositions: dict[str, int] = defaultdict(int)
    conflict_ids: set[str] = set()
    for item in prepared["observations"]:
        natural = _natural_key(item)
        exact = by_id.get(item["observation_id"])
        if exact:
            dispositions["duplicate"] += 1
            target_id = exact["observation_id"]
        else:
            candidates = by_natural.get(natural, [])
            differing = [candidate for candidate in candidates if _value_hash(candidate) != _value_hash(item)]
            if differing:
                group = "market-conflict-" + _hash(natural)[:20]
                item["conflict_group_id"] = group
                item["conflict_status"] = "unresolved"
                for candidate in differing:
                    conflict_ids.add(candidate["observation_id"])
                conflict_ids.add(item["observation_id"])
                conflicts += 1
                dispositions["conflicted"] += 1
                item["event_type"] = "recorded"
                observation_payloads.append(item)
                by_id[item["observation_id"]] = item
                by_natural[natural].append(item)
                target_id = item["observation_id"]
            elif candidates:
                dispositions["source_linked"] += 1
                target_id = candidates[0]["observation_id"]
            else:
                item["conflict_group_id"] = None
                item["conflict_status"] = None
                dispositions["normalized"] += 1
                item["event_type"] = "recorded"
                observation_payloads.append(item)
                by_id[item["observation_id"]] = item
                by_natural[natural].append(item)
                target_id = item["observation_id"]
        link_id = _source_link_id(target_id, item["source_sha256"], item.get("source_line_start"), item.get("source_line_end"))
        source_payloads.append({
            "source_link_id": link_id, "observation_id": target_id, "match_id": item["match_id"],
            "source_ref": item["source_ref"], "source_sha256": item["source_sha256"],
            "source_line_start": item.get("source_line_start"), "source_line_end": item.get("source_line_end"),
        })
    existing_facts = [
        item for item in _event_payloads(fact_path)
        if item.get("match_id") == document.metadata.match_id
    ]
    fact_payloads: list[dict[str, Any]] = []
    same_fact = next(
        (item for item in existing_facts if _fixture_value_hash(item) == _fixture_value_hash(prepared["fact"])),
        None,
    )
    if same_fact is None:
        fact_payloads = [prepared["fact"]]
        if existing_facts:
            fact_payloads[0]["_supersedes_event_id"] = f"fixture-fact:{existing_facts[-1]['fact_id']}"

    existing_results = {item["result_id"]: item for item in _active_results(root)}
    result_payloads: list[dict[str, Any]] = []
    result_source_payloads: list[dict[str, Any]] = []
    for item in prepared["results"]:
        if item["result_id"] not in existing_results:
            result_payloads.append({"event_type": "recorded", **item})
        else:
            dispositions["result_duplicate"] += 1
        link = ResultSourceLinkV1(
            result_source_link_id=_result_source_link_id(
                item["result_id"], item["source_sha256"], item["source_ref"]
            ),
            result_id=item["result_id"],
            match_id=item["match_id"],
            source_ref=item["source_ref"],
            source_sha256=item["source_sha256"],
        ).model_dump(mode="json")
        result_source_payloads.append({"event_type": "source_link", **link})
    recorded_at = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    ledgers = [observation_path, source_path, fact_path, result_path]
    with RepositoryTransaction(root, files=[*ledgers, path], directories=[], operation="market-observation-ingest") as transaction:
        created_observations = append_payloads(observation_path, observation_payloads, recorded_at=recorded_at, actor=actor, event_id_factory=lambda item, _: f"market-observation:{item['observation_id']}")
        created_sources = append_payloads(source_path, source_payloads, recorded_at=recorded_at, actor=actor, event_id_factory=lambda item, _: f"market-source:{item['source_link_id']}")
        created_facts = append_payloads(fact_path, fact_payloads, recorded_at=recorded_at, actor=actor, event_id_factory=lambda item, _: f"fixture-fact:{item['fact_id']}")
        created_results = append_payloads(
            result_path,
            result_payloads,
            recorded_at=recorded_at,
            actor=actor,
            event_id_factory=lambda item, _: f"match-result:{item['result_id']}",
        )
        append_payloads(
            result_path,
            result_source_payloads,
            recorded_at=recorded_at,
            actor=actor,
            event_id_factory=lambda item, _: f"match-result-source:{item['result_source_link_id']}",
        )
        active = _active_observations(root)
        derived_conflicts, _ = _conflict_index(active, _conflict_resolutions(root))
        conflict_ids.update(derived_conflicts)
        compatibility_added = (
            _project_compatibility(path, MatchDocument.load(path), active, conflict_ids)
            if project_compatibility else 0
        )
        transaction.commit()
    return IngestSummaryV1(
        bundle_id=bundle.bundle_id, match_id=document.metadata.match_id,
        observations_seen=len(prepared["observations"]), observations_added=len(created_observations),
        source_links_added=len(created_sources), conflicts_added=conflicts,
        facts_added=len(created_facts), results_added=len(created_results),
        compatibility_snapshots_added=compatibility_added, dispositions=dict(dispositions),
    )


def finish_bundle(
    root: Path,
    bundle_file: Path,
    bundle: MatchDataBundleV1,
    *,
    match_path: Path | None = None,
    actor: str = "lcz",
    received_at: datetime | None = None,
    confirm_historical: bool = False,
) -> dict[str, Any]:
    """Archive, normalize, then independently apply the existing result lifecycle."""
    path, document = _resolve_match(root, bundle, match_path)
    source_bytes = bundle_file.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    archive = (
        root / "raw" / "matches" / document.metadata.match_id / "match-data-bundles"
        / f"{bundle.bundle_id}-{source_sha[:12]}.yml"
    )
    if archive.exists() and archive.read_bytes() != source_bytes:
        raise ObservationError(f"bundle 归档路径已存在且内容不同：{archive}")
    if not archive.exists():
        with RepositoryTransaction(
            root,
            files=[archive],
            directories=[],
            operation="match-data-bundle-archive",
        ) as transaction:
            archive.parent.mkdir(parents=True, exist_ok=True)
            temporary = archive.with_suffix(archive.suffix + ".tmp")
            temporary.write_bytes(source_bytes)
            temporary.replace(archive)
            transaction.commit()

    source_ref = archive.relative_to(root).as_posix()
    market_data = bundle.market_data or MarketDataInputV1(
        source_kind=SourceKind.USER_CONFIRMED_TEXT
    )
    market_data = market_data.model_copy(update={
        "source_ref": market_data.source_ref or source_ref,
        "source_sha256": market_data.source_sha256 or source_sha,
    })
    result = bundle.result
    if result is not None and not result.source_ref:
        result = result.model_copy(update={"source_ref": source_ref})
    archived_bundle = bundle.model_copy(update={
        "market_data": market_data,
        "result": result,
    })
    normalized = ingest_bundle(
        root,
        archived_bundle,
        match_path=path,
        actor=actor,
        received_at=received_at,
    )

    lifecycle = {"status": "not_requested", "reason": None}
    if result is not None and result.final_score:
        conflicts = [
            item for item in result_conflict_report(root, match_id=document.metadata.match_id)
            if item["period"] == "full_time" and item["status"] == "unresolved"
        ]
        current = MatchDocument.load(path)
        current_status = MatchStatus(current.metadata.status)
        if conflicts:
            lifecycle = {"status": "blocked", "reason": "full_time_result_conflicted"}
        elif current_status in {MatchStatus.FINISHED, MatchStatus.REVIEWED, MatchStatus.HISTORICAL_FINISHED}:
            lifecycle = {
                "status": "already_finished" if current.metadata.score == result.final_score else "blocked",
                "reason": None if current.metadata.score == result.final_score else "stored_result_differs_from_bundle",
            }
        else:
            lifecycle_at = result.observed_at or received_at or datetime.now(
                ZoneInfo(document.metadata.timezone)
            ).replace(microsecond=0)
            if current_status == MatchStatus.LOCKED:
                from .services import finish_match

                finish_match(
                    path,
                    score=result.final_score,
                    result_1x2=None,
                    handicap_result=None,
                    recorded_at=lifecycle_at,
                    key_events=None,
                    result_source=source_ref,
                )
                lifecycle = {"status": "finished", "reason": None}
            elif current_status in {MatchStatus.DRAFT, MatchStatus.TRACKING} and confirm_historical:
                if actor.strip() != "lcz":
                    raise ObservationError("历史完结必须由 lcz 明确确认")
                from .services import finish_historical_match

                finish_historical_match(
                    path,
                    score=result.final_score,
                    recorded_at=lifecycle_at,
                    key_events=None,
                    result_source=source_ref,
                )
                lifecycle = {"status": "historical_finished", "reason": None}
            else:
                lifecycle = {
                    "status": "archived_only",
                    "reason": "missing_valid_prematch_lock",
                }
    return {
        "schema_version": 1,
        "bundle_id": bundle.bundle_id,
        "match_id": document.metadata.match_id,
        "archive_path": source_ref,
        "source_sha256": source_sha,
        "normalization": normalized.model_dump(mode="json"),
        "result_lifecycle": lifecycle,
    }


def market_feature_snapshot(root: Path, match_id: str, cutoff: datetime) -> dict[str, Any]:
    active = [item for item in _active_observations(root) if item["match_id"] == match_id]
    resolutions = _conflict_resolutions(root)
    conflict_index, conflict_groups = _conflict_index(active, resolutions)
    normalized_exact = [
        item for item in active
        if item["time_precision"] == "exact"
        and item.get("observed_at")
        and datetime.fromisoformat(item["observed_at"]) <= cutoff
        and item.get("normalization_eligible") is True
        and item.get("availability_status", "available") == "available"
        and item["observation_id"] not in conflict_index
    ]
    prediction_eligible = [item for item in normalized_exact if item.get("prediction_eligible") is True]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in normalized_exact:
        key = "|".join((item["provider_id"], item["market"], item["market_scope"], item["quote_role"]))
        groups[key].append(item)
    series = []
    for key, values in sorted(groups.items()):
        ordered = sorted(values, key=lambda item: (item["observed_at"], item["observation_id"]))
        line_path = [item.get("normalized_line") for item in ordered if item.get("normalized_line") is not None]
        price_keys = sorted({name for item in ordered for name in item["normalized_prices"]})
        same_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in ordered:
            same_line[str(item.get("normalized_line"))].append(item)
        line_series = []
        for line, nodes in sorted(same_line.items()):
            prices: dict[str, list[float]] = {name: [float(node["normalized_prices"][name]) for node in nodes if name in node["normalized_prices"]] for name in price_keys}
            changes = {name: round(items[-1] - items[0], 6) if len(items) >= 2 else None for name, items in prices.items()}
            reversals = {}
            purity = {}
            max_drawdown = {}
            for name, items in prices.items():
                deltas = [right - left for left, right in zip(items, items[1:])]
                nonzero = [delta for delta in deltas if delta]
                reversals[name] = sum(1 for left, right in zip(nonzero, nonzero[1:]) if left * right < 0)
                direction = 1 if sum(nonzero) >= 0 else -1
                purity[name] = round(sum(1 for delta in nonzero if delta * direction > 0) / len(nonzero), 6) if nonzero else 1.0
                peak = items[0] if items else 0.0
                drawdown = 0.0
                for value in items:
                    peak = max(peak, value)
                    drawdown = max(drawdown, peak - value)
                max_drawdown[name] = round(drawdown, 6)
            line_series.append({"line": None if line == "None" else float(line), "observation_ids": [node["observation_id"] for node in nodes], "prices": prices, "changes": changes, "reversals": reversals, "trend_purity": purity, "max_drawdown": max_drawdown})
        line_steps = [round(right - left, 6) for left, right in zip(line_path, line_path[1:])]
        series.append({
            "series_key": key, "provider_id": ordered[0]["provider_id"], "market": ordered[0]["market"],
            "quote_role": ordered[0]["quote_role"], "observation_ids": [item["observation_id"] for item in ordered],
            "observed_at": [item["observed_at"] for item in ordered], "line_path": line_path,
            "line_steps": line_steps, "line_rises": sum(step > 0 for step in line_steps),
            "line_drops": sum(step < 0 for step in line_steps), "same_line_series": line_series,
            "stable_throughout": bool(len(ordered) >= 2 and all(not step for step in line_steps) and all(all(change == 0 for change in row["changes"].values() if change is not None) for row in line_series)),
        })
    phase_only = [item for item in active if item["time_precision"] == "phase_only"]
    phase_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in phase_only:
        if item.get("availability_status", "available") != "available":
            continue
        key = "|".join((
            item["provider_id"], item["market"], item["market_scope"],
            item["quote_role"], item["capture_batch_id"],
        ))
        phase_groups[key].append(item)
    endpoint_series = []
    phase_order = {"opening": 0, "mid": 1, "current": 2, "late": 3}
    for key, values in sorted(phase_groups.items()):
        ordered = sorted(values, key=lambda item: (
            phase_order.get(str(item.get("phase_hint")), 9), item["observation_id"]
        ))
        first, last = ordered[0], ordered[-1]
        same_line = first.get("normalized_line") == last.get("normalized_line")
        line_change = (
            round(float(last["normalized_line"]) - float(first["normalized_line"]), 6)
            if first.get("normalized_line") is not None and last.get("normalized_line") is not None
            else None
        )
        endpoint_series.append({
            "series_key": key,
            "provider_id": first["provider_id"],
            "market": first["market"],
            "quote_role": first["quote_role"],
            "observation_ids": [item["observation_id"] for item in ordered],
            "phases": [item.get("phase_hint") for item in ordered],
            "line_endpoints": [first.get("normalized_line"), last.get("normalized_line")],
            "line_change": line_change,
            "price_changes": {
                name: (
                    round(float(last["normalized_prices"][name]) - float(first["normalized_prices"][name]), 6)
                    if name in first["normalized_prices"] and name in last["normalized_prices"] and same_line
                    else None
                )
                for name in sorted(set(first["normalized_prices"]) | set(last["normalized_prices"]))
            },
            "normalized_price_endpoints": [
                first["normalized_prices"], last["normalized_prices"]
            ],
            "endpoint_change": line_change,
            "endpoint_values_equal": _value_hash(first) == _value_hash(last),
            "intermediate_path_status": "unknown",
            "stable_throughout": "unverified",
        })
    direction_matrix = []
    for item in [*series, *endpoint_series]:
        line_steps = item.get("line_steps") or ([] if item.get("line_change") is None else [item["line_change"]])
        price_changes = item.get("price_changes") or {}
        if not price_changes and item.get("same_line_series"):
            last_line = item["same_line_series"][-1]
            price_changes = last_line.get("changes", {})
        line_delta = sum(line_steps) if line_steps else 0.0
        if item["market"] == "total_goals":
            price_delta = price_changes.get("over")
            direction = "over" if line_delta > 0 or (line_delta == 0 and price_delta is not None and price_delta < 0) else "under" if line_delta < 0 or (line_delta == 0 and price_delta is not None and price_delta > 0) else "neutral"
        elif item["market"] == "asian_handicap":
            price_delta = price_changes.get("home")
            direction = "home" if line_delta > 0 or (line_delta == 0 and price_delta is not None and price_delta < 0) else "away" if line_delta < 0 or (line_delta == 0 and price_delta is not None and price_delta > 0) else "neutral"
        else:
            direction = "neutral"
        direction_matrix.append({
            "provider_id": item["provider_id"], "market": item["market"],
            "series_key": item["series_key"], "direction": direction,
            "head_provider": item["provider_id"] in {"william-hill", "ladbrokes"},
        })
    late_start = cutoff - timedelta(minutes=60)
    late_observation_ids = sorted(
        item["observation_id"] for item in normalized_exact
        if datetime.fromisoformat(item["observed_at"]) >= late_start
    )
    excluded = []
    for item in active:
        reasons = []
        if item["observation_id"] in conflict_index:
            reasons.append("unresolved_conflict")
        if item.get("availability_status") == "not_displayed":
            reasons.append("not_displayed")
        if item.get("time_precision") != "exact":
            reasons.append("time_not_exact")
        if not item.get("prediction_eligible"):
            reasons.extend(item.get("ineligibility_reasons") or ["prediction_ineligible"])
        if reasons:
            excluded.append({"observation_id": item["observation_id"], "reasons": sorted(set(reasons))})
    payload = {
        "schema_version": 2, "match_id": match_id, "cutoff": cutoff.isoformat(),
        "observation_ids": sorted(item["observation_id"] for item in normalized_exact),
        "prediction_eligible_observation_ids": sorted(item["observation_id"] for item in prediction_eligible),
        "observation_set_sha256": _hash(sorted(item["observation_id"] for item in normalized_exact)),
        "series": series, "phase_only_series": endpoint_series,
        "phase_only_observation_ids": sorted(item["observation_id"] for item in phase_only),
        "late_60m_observation_ids": late_observation_ids,
        "provider_direction_matrix": direction_matrix,
        "time_precision_counts": {
            precision: sum(item["time_precision"] == precision for item in active)
            for precision in ("exact", "phase_only", "unknown")
        },
        "excluded_observations": excluded,
        "conflicts": [
            {"conflict_group_id": group_id, "status": resolutions.get(group_id, {}).get("status", "unresolved")}
            for group_id in sorted(conflict_groups)
        ],
        "data_status": "conflicted" if any(
            resolutions.get(group_id, {}).get("status", "unresolved") in {"unresolved", "both_valid"}
            for group_id in conflict_groups
        ) else "complete" if normalized_exact else "insufficient_data",
        "prediction_data_status": "complete" if prediction_eligible else "insufficient_data",
        "fund_flow_status": "unknown", "causal_attribution": "unverified",
    }
    payload["feature_snapshot_sha256"] = _hash(payload)
    return payload


def effective_market_snapshots(root: Path, match_id: str, cutoff: datetime) -> list[MarketSnapshot]:
    active = [item for item in _active_observations(root) if item["match_id"] == match_id]
    conflict_index, _ = _conflict_index(active, _conflict_resolutions(root))
    eligible = [
        item for item in active
        if item["time_precision"] == "exact"
        and item.get("prediction_eligible") is True
        and item.get("observed_at")
        and datetime.fromisoformat(item["observed_at"]) <= cutoff
        and item["observation_id"] not in conflict_index
    ]
    groups: dict[tuple[str, str, float | None], list[dict[str, Any]]] = defaultdict(list)
    for item in eligible:
        groups[(item["provider_id"], item["market"], item.get("normalized_line"))].append(item)
    snapshots: list[MarketSnapshot] = []
    for values in groups.values():
        ordered = sorted(values, key=lambda item: (item["observed_at"], item["observation_id"]))
        for index, item in enumerate(ordered):
            phase = "opening" if index == 0 else "late" if index == len(ordered) - 1 else "mid"
            snapshots.append(_compatibility_snapshot(item, phase))
    return sorted(snapshots, key=lambda item: (item.captured_at, item.snapshot_id))


def observation_status(root: Path, *, match_id: str | None = None) -> dict[str, Any]:
    active = _active_observations(root)
    if match_id:
        active = [item for item in active if item["match_id"] == match_id]
    conflict_index, _ = _conflict_index(active, _conflict_resolutions(root))
    dispositions = defaultdict(int)
    for item in active:
        dispositions["conflicted" if item["observation_id"] in conflict_index else "normalized"] += 1
        dispositions[item["time_precision"]] += 1
        dispositions["prediction_eligible" if item["prediction_eligible"] else "prediction_ineligible"] += 1
    return {"match_id": match_id, "observations": len(active), "dispositions": dict(sorted(dispositions.items()))}


def conflict_report(root: Path, *, match_id: str | None = None) -> list[dict[str, Any]]:
    active = _active_observations(root)
    if match_id:
        active = [item for item in active if item["match_id"] == match_id]
    resolutions = _conflict_resolutions(root)
    _, groups = _conflict_index(active, resolutions)
    return [{
        "conflict_group_id": key,
        "match_id": values[0]["match_id"],
        "status": resolutions.get(key, {}).get("status", "unresolved"),
        "selected_observation_id": resolutions.get(key, {}).get("selected_observation_id"),
        "reason": resolutions.get(key, {}).get("reason"),
        "observations": values,
    } for key, values in sorted(groups.items())]


def resolve_market_conflict(
    root: Path,
    *,
    conflict_group_id: str,
    status: Literal["confirmed_source", "both_valid", "superseded"],
    selected_observation_id: str | None,
    reason: str,
    actor: str,
) -> dict[str, Any]:
    groups = {item["conflict_group_id"]: item for item in conflict_report(root)}
    group = groups.get(conflict_group_id)
    if group is None:
        raise ObservationError(f"盘口冲突不存在：{conflict_group_id}")
    ids = {item["observation_id"] for item in group["observations"]}
    if status in {"confirmed_source", "superseded"}:
        if selected_observation_id not in ids:
            raise ObservationError("确认来源或替代处置必须选择冲突组内 observation_id")
    elif selected_observation_id is not None:
        raise ObservationError("both_valid 不接受单一 selected_observation_id")
    if not reason.strip():
        raise ObservationError("冲突处置必须提供理由")
    recorded_at = datetime.now(ZoneInfo("Asia/Shanghai")).replace(microsecond=0)
    previous = _conflict_resolutions(root).get(conflict_group_id)
    payload = {
        "event_type": "conflict_resolution",
        "conflict_group_id": conflict_group_id,
        "match_id": group["match_id"],
        "status": status,
        "selected_observation_id": selected_observation_id,
        "reason": reason.strip(),
    }
    if previous:
        previous_hash = _hash(previous)[:16]
        payload["_supersedes_event_id"] = f"market-conflict-resolution:{conflict_group_id}:{previous_hash}"
    event_hash = _hash({key: value for key, value in payload.items() if key != "_supersedes_event_id"})[:16]
    path = root / MARKET_OBSERVATION_LEDGER
    with RepositoryTransaction(root, files=[path], directories=[], operation="market-conflict-resolution") as transaction:
        append_payloads(
            path,
            [payload],
            recorded_at=recorded_at,
            actor=actor,
            event_id_factory=lambda _item, _index: f"market-conflict-resolution:{conflict_group_id}:{event_hash}",
        )
        transaction.commit()
    return next(item for item in conflict_report(root) if item["conflict_group_id"] == conflict_group_id)


def validate_observations(root: Path) -> list[str]:
    errors: list[str] = []
    for relative, model, key in (
        (MARKET_OBSERVATION_LEDGER, MarketObservationEventV1, "observation_id"),
        (FIXTURE_FACT_LEDGER, FixtureFactObservationV1, "fact_id"),
    ):
        try:
            payloads = _event_payloads(root / relative)
            for item in payloads:
                if relative == MARKET_OBSERVATION_LEDGER and item.get("event_type") == "conflict_resolution":
                    continue
                candidate = dict(item)
                candidate.pop("event_type", None)
                candidate.pop("conflict_group_id", None)
                candidate.pop("conflict_status", None)
                candidate.pop("supersedes_observation_id", None)
                model.model_validate(candidate)
                if not item.get(key):
                    errors.append(f"{relative} 缺少 {key}")
        except Exception as exc:
            errors.append(f"{relative}：{exc}")
    try:
        _event_payloads(root / MARKET_SOURCE_LEDGER)
    except Exception as exc:
        errors.append(f"{MARKET_SOURCE_LEDGER}：{exc}")
    try:
        for item in _event_payloads(root / MATCH_RESULT_LEDGER):
            candidate = dict(item)
            event_type = candidate.pop("event_type", "recorded")
            if event_type == "recorded":
                MatchResultObservationV1.model_validate(candidate)
            elif event_type == "source_link":
                ResultSourceLinkV1.model_validate(candidate)
            elif event_type == "conflict_resolution":
                if not all(candidate.get(key) for key in ("conflict_group_id", "match_id", "period", "selected_result_id", "reason")):
                    errors.append(f"{MATCH_RESULT_LEDGER} 赛果冲突处置字段不完整")
            elif event_type != "superseded":
                errors.append(f"{MATCH_RESULT_LEDGER} 未知 event_type：{event_type}")
        for conflict in result_conflict_report(root):
            if not conflict["observations"]:
                errors.append(f"{MATCH_RESULT_LEDGER} 空赛果冲突：{conflict['conflict_group_id']}")
    except Exception as exc:
        errors.append(f"{MATCH_RESULT_LEDGER}：{exc}")
    return errors


def observation_inventory(root: Path) -> dict[str, Any]:
    active = _active_observations(root)
    by_match = Counter(item["match_id"] for item in active)
    candidates = []
    for path in match_files(root):
        document = MatchDocument.load(path)
        legacy = [
            item for item in document.metadata.market_snapshots
            if not item.snapshot_id.startswith("market-obs-")
        ]
        candidates.append({
            "match_id": document.metadata.match_id,
            "match_path": path.relative_to(root).as_posix(),
            "legacy_snapshots": len(legacy),
            "normalized_observations": by_match.get(document.metadata.match_id, 0),
        })
    return {
        "schema_version": 1,
        "matches": len(candidates),
        "legacy_snapshots": sum(item["legacy_snapshots"] for item in candidates),
        "normalized_observations": len(active),
        "items": candidates,
    }


def backfill_legacy_snapshots(
    root: Path,
    *,
    actor: str = "migration",
    match_id: str | None = None,
    max_matches: int = 5,
    max_observations: int = 5000,
) -> dict[str, int]:
    if max_matches < 1 or max_matches > 5:
        raise ObservationError("历史回填每批最多 5 场")
    if max_observations < 1 or max_observations > 5000:
        raise ObservationError("历史回填每批最多 5,000 条观测")
    totals = {"matches": 0, "snapshots": 0, "added": 0}
    for path in match_files(root):
        document = MatchDocument.load(path)
        if match_id and document.metadata.match_id != match_id:
            continue
        if totals["matches"] >= max_matches:
            break
        if not document.metadata.market_snapshots:
            continue
        observations = []
        for index, snapshot in enumerate(document.metadata.market_snapshots, start=1):
            raw = snapshot.raw_values
            normalized = snapshot.normalized_values
            market = str(snapshot.market)
            if market == "asian_handicap":
                line = normalized.get("home_line", normalized.get("line"))
                prices = {"home": normalized.get("home_water"), "away": normalized.get("away_water")}
            elif market == "total_goals":
                line = normalized.get("line")
                prices = {"over": normalized.get("over_water"), "under": normalized.get("under_water")}
            else:
                line = None
                prices = {"home": normalized.get("home", normalized.get("home_win")), "draw": normalized.get("draw"), "away": normalized.get("away", normalized.get("away_win"))}
            if any(value is None for value in prices.values()):
                continue
            source_sha = _hash([snapshot.source_ref, snapshot.snapshot_id])
            prediction, retrospective, reasons = _eligibility(snapshot.captured_at, snapshot.captured_at, document.metadata.kickoff_at, SourceKind.LEGACY_SNAPSHOT)
            payload = MarketObservationEventV1(
                observation_id="observation-placeholder", match_id=document.metadata.match_id,
                source_kind=SourceKind.LEGACY_SNAPSHOT, source_ref=snapshot.source_ref,
                source_sha256=source_sha, received_at=snapshot.captured_at, source_captured_at=snapshot.captured_at,
                time_precision=TimePrecision.EXACT, observed_at=snapshot.captured_at,
                phase_hint=ObservationPhase(str(snapshot.phase)) if str(snapshot.phase) in {"opening", "mid", "late"} else None,
                capture_batch_id=f"legacy-{document.metadata.match_id}", sequence_no=index,
                provider_id=snapshot.provider_id, provider_name_raw=snapshot.provider_id, market=market,
                quote_role=QuoteRole.AGGREGATE if snapshot.provider_id.startswith("kelly-aggregate-") else QuoteRole.MAIN_LINE if market in {"asian_handicap", "total_goals"} else QuoteRole.PROVIDER,
                odds_format=str(snapshot.odds_format), raw_values={key: str(value) for key, value in raw.items()},
                normalized_line=float(line) if line is not None else None,
                normalized_prices={key: float(value) for key, value in prices.items()},
                prediction_eligible=prediction, retrospective_validation_eligible=retrospective,
                ineligibility_reasons=reasons,
            ).model_dump(mode="json")
            payload["observation_id"] = _observation_identity(payload)
            observations.append(payload)
        if not observations:
            continue
        if totals["snapshots"] + len(observations) > max_observations:
            break
        # Use the same append semantics without rebuilding the input rows.
        observation_path = root / MARKET_OBSERVATION_LEDGER
        source_path = root / MARKET_SOURCE_LEDGER
        recorded_at = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
        existing = _active_observations(root)
        by_id = {item["observation_id"]: item for item in existing}
        by_natural: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in existing:
            by_natural[_natural_key(item)].append(item)
        observation_payloads = []
        source_payloads = []
        for item in observations:
            target_id = item["observation_id"]
            if target_id not in by_id:
                same_value = next(
                    (candidate for candidate in by_natural.get(_natural_key(item), []) if _value_hash(candidate) == _value_hash(item)),
                    None,
                )
                if same_value:
                    target_id = same_value["observation_id"]
                else:
                    payload = {**item, "event_type": "recorded", "conflict_group_id": None, "conflict_status": None}
                    observation_payloads.append(payload)
                    by_id[item["observation_id"]] = item
                    by_natural[_natural_key(item)].append(item)
            source_payloads.append({
                "source_link_id": _source_link_id(target_id, item["source_sha256"], None, None),
                "observation_id": target_id, "match_id": item["match_id"],
                "source_ref": item["source_ref"], "source_sha256": item["source_sha256"],
                "source_line_start": None, "source_line_end": None,
            })
        with RepositoryTransaction(root, files=[observation_path, source_path], directories=[], operation="market-observation-backfill") as transaction:
            created = append_payloads(observation_path, observation_payloads, recorded_at=recorded_at, actor=actor, event_id_factory=lambda item, _: f"market-observation:{item['observation_id']}")
            append_payloads(source_path, source_payloads, recorded_at=recorded_at, actor=actor, event_id_factory=lambda item, _: f"market-source:{item['source_link_id']}")
            transaction.commit()
        totals["matches"] += 1
        totals["snapshots"] += len(observations)
        totals["added"] += len(created)
    return totals
