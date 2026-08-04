from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .aliases import AliasStore
from .cases import latest_cases
from .journal import (
    CaptureMode,
    FixtureCandidate,
    JournalIngestRequestV1,
    JournalOperation,
    JournalOperationResultV1,
    JournalSegmentV1,
    SegmentType,
    UserIntent,
    journal_status,
    ingest_journal,
    operate_journal,
)
from .markdown import MatchDocument
from .models import MarketSnapshot, MarketType, OddsFormat, SnapshotPhase
from .paths import match_files
from .observations import (
    FixtureBundleV1,
    MacauTimelineInputV1,
    MarketDataInputV1,
    MatchDataBundleV1,
    QuoteValuesV1,
    SourceKind,
    SummaryRowInputV1,
    ingest_bundle,
)
from .market_monitoring import (
    BaselineSource,
    ComparisonStatus,
    MarketArchiveComparisonV1,
    active_watchlist,
    archived_baseline,
    compare_snapshots,
    draft_sha256,
    evaluate_watchlist,
    render_comparison_sections,
)


class MarketArchiveError(ValueError):
    pass


class MarketArchiveRowV1(BaseModel):
    """One visually verified row from a screenshot; never an OCR inference."""

    model_config = ConfigDict(extra="forbid")

    market: MarketType
    provider_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    provider_name: str = Field(min_length=1)
    phase: SnapshotPhase
    raw_values: dict[str, str] = Field(min_length=1)
    source_screenshot: str = Field(min_length=1)
    row_ordinal: int = Field(ge=1)
    observed_at: datetime | None = None
    status: str | None = None
    visually_verified: bool = True

    @field_validator("observed_at")
    @classmethod
    def observed_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("observed_at 必须包含时区")
        return value


class MacauTimelineNodeV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    displayed_at: str = Field(min_length=1)
    status: str = "即"
    home_water: str
    line: str
    away_water: str
    source_screenshot: str = Field(min_length=1)
    row_ordinal: int = Field(ge=1)


class MarketArchiveDraftV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    fixture: FixtureCandidate
    captured_at: datetime
    actor: str = "lcz"
    market_scope: Literal["full_time"] = "full_time"
    screenshots: list[str] = Field(default_factory=list)
    rows: list[MarketArchiveRowV1] = Field(default_factory=list)
    macau_timeline: list[MacauTimelineNodeV1] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)

    @field_validator("captured_at")
    @classmethod
    def captured_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def unique_source_names(self) -> "MarketArchiveDraftV1":
        if len(self.screenshots) != len(set(self.screenshots)):
            raise ValueError("screenshots 不得重复")
        names = set(self.screenshots)
        references = [item.source_screenshot for item in self.rows]
        references.extend(item.source_screenshot for item in self.macau_timeline)
        unknown = sorted(set(references) - names)
        if unknown:
            raise ValueError("行情行引用了未声明截图：" + ", ".join(unknown))
        return self


class CompetitionResolutionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["explicit", "inferred", "unresolved"]
    competition_code: str | None = None
    competition: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class MarketArchivePreviewV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rendered_markdown: str
    fixture: FixtureCandidate
    competition_resolution: CompetitionResolutionV1
    snapshots: list[MarketSnapshot] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)


class AttachmentMappingV1(BaseModel):
    source_ref: str
    original_filename: str
    stored_filename: str
    sha256: str


class MarketArchiveResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journal: JournalOperationResultV1 | None = None
    entry_id: str
    target_type: Literal["match", "legacy_case", "inbox"]
    target_id: str | None = None
    attachment_mappings: list[AttachmentMappingV1] = Field(default_factory=list)
    snapshot_count: int = 0
    missing_items: list[str] = Field(default_factory=list)
    normalization: dict | None = None
    generated_prediction: Literal[False] = False


_EXPECTED_KEYS = {
    MarketType.ASIAN_HANDICAP: ("home_water", "line", "away_water"),
    MarketType.EUROPEAN_ODDS: ("home_win", "draw", "away_win"),
    MarketType.TOTAL_GOALS: ("over_water", "line", "under_water"),
    MarketType.KELLY_INDEX: ("home_win", "draw", "away_win"),
}
_ODDS_FORMAT = {
    MarketType.ASIAN_HANDICAP: OddsFormat.HONG_KONG,
    MarketType.EUROPEAN_ODDS: OddsFormat.DECIMAL,
    MarketType.TOTAL_GOALS: OddsFormat.HONG_KONG,
    MarketType.KELLY_INDEX: OddsFormat.KELLY,
}


def _numeric(value: str) -> float | None:
    try:
        return float(value.strip())
    except ValueError:
        return None


def _line(value: str) -> float | None:
    value = value.strip().replace(" ", "")
    if value.startswith("-"):
        parsed = _line(value[1:])
        return -parsed if parsed is not None else None
    parts = value.split("/")
    if len(parts) > 2 or not parts:
        return None
    numbers = [_numeric(item) for item in parts]
    return sum(numbers) / len(numbers) if all(item is not None for item in numbers) else None


def _normalized_values(row: MarketArchiveRowV1) -> dict[str, float] | None:
    expected = _EXPECTED_KEYS.get(MarketType(row.market))
    if expected is None or not row.visually_verified or set(row.raw_values) != set(expected):
        return None
    normalized: dict[str, float] = {}
    for key, raw in row.raw_values.items():
        value = _line(raw) if key == "line" else _numeric(raw)
        if value is None:
            return None
        normalized[key] = value
    return normalized


def _stable_snapshot_id(fixture: FixtureCandidate, row: MarketArchiveRowV1, captured_at: datetime) -> str:
    identity = {
        "competition": fixture.competition_code or fixture.competition or "unknown",
        "home": fixture.home_team_id or fixture.home_team or "unknown",
        "away": fixture.away_team_id or fixture.away_team or "unknown",
        "kickoff": fixture.kickoff_at.isoformat() if fixture.kickoff_at else "unknown",
        "market": MarketType(row.market).value,
        "provider": row.provider_id,
        "phase": SnapshotPhase(row.phase).value,
        "observed": (row.observed_at or captured_at).isoformat(),
        "ordinal": row.row_ordinal,
        "raw": row.raw_values,
    }
    digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
    return f"market-{digest}"


def _source_ref(row: MarketArchiveRowV1) -> str:
    return f"user-screenshot:{row.source_screenshot}#{MarketType(row.market).value}/{row.provider_id}/{SnapshotPhase(row.phase).value}"


def _resolve_node_time(node: MacauTimelineNodeV1, draft: MarketArchiveDraftV1) -> datetime | None:
    try:
        value = datetime.fromisoformat(node.displayed_at)
        if value.tzinfo is not None and value.utcoffset() is not None:
            return value
    except ValueError:
        pass
    match = re.fullmatch(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", node.displayed_at.strip())
    if not match or draft.fixture.kickoff_at is None:
        return None
    month, day, hour, minute = map(int, match.groups())
    kickoff = draft.fixture.kickoff_at.astimezone(ZoneInfo(draft.fixture.timezone))
    candidates = []
    for year in (kickoff.year - 1, kickoff.year, kickoff.year + 1):
        try:
            candidate = datetime(year, month, day, hour, minute, tzinfo=kickoff.tzinfo)
        except ValueError:
            continue
        if candidate <= draft.captured_at.astimezone(kickoff.tzinfo):
            candidates.append(candidate)
    if not candidates:
        return None
    closest = min(candidates, key=lambda item: abs((kickoff - item).total_seconds()))
    # A candidate more than 370 days from kickoff is a date ambiguity, not evidence.
    return closest if abs((kickoff - closest).days) <= 370 else None


def _alias_id(aliases: AliasStore, name: str | None, kind: str) -> str | None:
    if not name:
        return None
    found = aliases.find_team_id(name) if kind == "team" else aliases.find_competition_code(name)
    return found or AliasStore.provisional_id(kind, name)


def _competition_name(aliases: AliasStore, code: str, fallback: str | None = None) -> str | None:
    records = aliases._load(aliases.competition_path, "competitions")["competitions"]
    return str(records[code]["canonical_name"]) if code in records else fallback


def resolve_fixture(root: Path, fixture: FixtureCandidate) -> tuple[FixtureCandidate, CompetitionResolutionV1]:
    """Resolve local identities; only infer a league from both teams' historical records."""
    aliases = AliasStore(root)
    values = fixture.model_dump(mode="python")
    values["home_team_id"] = values.get("home_team_id") or _alias_id(aliases, fixture.home_team, "team")
    values["away_team_id"] = values.get("away_team_id") or _alias_id(aliases, fixture.away_team, "team")
    if fixture.competition:
        values["competition_code"] = values.get("competition_code") or _alias_id(aliases, fixture.competition, "competition")
        return FixtureCandidate.model_validate(values), CompetitionResolutionV1(
            status="explicit", competition_code=values["competition_code"], competition=fixture.competition
        )
    if fixture.competition_code:
        return FixtureCandidate.model_validate(values), CompetitionResolutionV1(
            status="explicit", competition_code=fixture.competition_code,
            competition=_competition_name(aliases, fixture.competition_code),
        )
    home_id, away_id = values.get("home_team_id"), values.get("away_team_id")
    if not home_id or not away_id:
        return FixtureCandidate.model_validate(values), CompetitionResolutionV1(status="unresolved", reason="主队或客队无法对应本地标准身份")
    home: dict[str, list[str]] = defaultdict(list)
    away: dict[str, list[str]] = defaultdict(list)
    names: dict[str, str] = {}
    for path in match_files(root):
        metadata = MatchDocument.load(path).metadata
        if not metadata.competition_code:
            continue
        names.setdefault(metadata.competition_code, metadata.competition)
        if metadata.home_team_id == home_id or metadata.away_team_id == home_id:
            home[metadata.competition_code].append(metadata.match_id)
        if metadata.home_team_id == away_id or metadata.away_team_id == away_id:
            away[metadata.competition_code].append(metadata.match_id)
    for case in latest_cases(root).values():
        if not case.competition_code:
            continue
        if case.home_team_id == home_id or case.away_team_id == home_id:
            home[case.competition_code].append(case.case_id)
        if case.home_team_id == away_id or case.away_team_id == away_id:
            away[case.competition_code].append(case.case_id)
    candidates = sorted(set(home) & set(away))
    if len(candidates) != 1:
        reason = "两队本地联赛交集为空" if not candidates else "两队本地联赛交集不唯一"
        return FixtureCandidate.model_validate(values), CompetitionResolutionV1(status="unresolved", reason=reason)
    code = candidates[0]
    values["competition_code"] = code
    values["competition"] = names.get(code) or _competition_name(aliases, code)
    if not values["competition"]:
        return FixtureCandidate.model_validate(values), CompetitionResolutionV1(status="unresolved", reason="唯一联赛缺少可展示名称")
    return FixtureCandidate.model_validate(values), CompetitionResolutionV1(
        status="inferred", competition_code=code, competition=values["competition"], source_ids=sorted(set(home[code] + away[code]))
    )


def _timeline_rows(draft: MarketArchiveDraftV1) -> tuple[list[MarketArchiveRowV1], list[str]]:
    if not draft.macau_timeline:
        return [], []
    parsed = [(node, _resolve_node_time(node, draft)) for node in draft.macau_timeline]
    missing = [f"澳门走势时间无法确认：{node.displayed_at}" for node, value in parsed if value is None]
    valid = sorted(((node, value) for node, value in parsed if value is not None), key=lambda item: item[1])
    if not valid:
        return [], missing
    result = []
    for index, (node, observed_at) in enumerate(valid):
        phase = SnapshotPhase.OPENING if index == 0 else SnapshotPhase.LATE if index == len(valid) - 1 else SnapshotPhase.MID
        result.append(MarketArchiveRowV1(
            market=MarketType.ASIAN_HANDICAP, provider_id="macau", provider_name="澳*",
            phase=phase, raw_values={"home_water": node.home_water, "line": node.line, "away_water": node.away_water},
            source_screenshot=node.source_screenshot, row_ordinal=node.row_ordinal, observed_at=observed_at, status=node.status,
        ))
    return result, missing


def _snapshots(draft: MarketArchiveDraftV1, fixture: FixtureCandidate) -> tuple[list[MarketSnapshot], list[str], list[MarketArchiveRowV1]]:
    timeline, missing = _timeline_rows(draft)
    rows = list(draft.rows)
    if timeline:
        rows = [row for row in rows if not (row.market == MarketType.ASIAN_HANDICAP and row.provider_id == "macau")] + timeline
    snapshots: list[MarketSnapshot] = []
    for row in rows:
        normalized = _normalized_values(row)
        if normalized is None:
            missing.append(f"未归档快照：{row.provider_name}/{MarketType(row.market).value}/{SnapshotPhase(row.phase).value}（字段不完整、不可读或未视觉确认）")
            continue
        snapshots.append(MarketSnapshot(
            snapshot_id=_stable_snapshot_id(fixture, row, draft.captured_at), market=row.market, phase=row.phase,
            captured_at=row.observed_at or draft.captured_at, provider_id=row.provider_id, source_ref=_source_ref(row),
            odds_format=_ODDS_FORMAT[MarketType(row.market)], raw_values=row.raw_values, normalized_values=normalized,
        ))
    return snapshots, missing, rows


def _value(row: MarketArchiveRowV1 | None) -> str:
    if row is None:
        return "-"
    order = _EXPECTED_KEYS.get(MarketType(row.market), ())
    return " / ".join(row.raw_values.get(key, "-") for key in order)


def render_preview(draft: MarketArchiveDraftV1, fixture: FixtureCandidate, resolution: CompetitionResolutionV1, rows: list[MarketArchiveRowV1], missing: list[str]) -> str:
    kickoff = fixture.kickoff_at.isoformat(sep=" ") if fixture.kickoff_at else "未确认"
    lines = [
        f"联赛：{fixture.competition or '未确认'}",
        f"比赛：{fixture.home_team or '未确认'} vs {fixture.away_team or '未确认'}",
        f"开赛时间：{kickoff}",
        "市场范围：全场",
        f"采集时间：{draft.captured_at.isoformat(sep=' ')}",
        "数据来源：用户提供截图",
        "",
        "## 澳门让球走势",
    ]
    macau = [row for row in rows if row.market == MarketType.ASIAN_HANDICAP and row.provider_id == "macau" and row.observed_at]
    if macau:
        lines += ["| 时间 | 状态 | 主水 | 盘口 | 客水 |", "|---|---|---:|---:|---:|"]
        for row in sorted(macau, key=lambda item: item.observed_at or draft.captured_at):
            lines.append(f"| {(row.observed_at or draft.captured_at).isoformat(sep=' ', timespec='minutes')} | {row.status or '-'} | {row.raw_values['home_water']} | {row.raw_values['line']} | {row.raw_values['away_water']} |")
    else:
        lines.append("未提供澳门详细走势。")
    labels = {
        MarketType.ASIAN_HANDICAP: ("## 其他机构让球盘", "主水 / 主让盘口 / 客水"),
        MarketType.EUROPEAN_ODDS: ("## 胜平负欧赔", "主胜 / 平局 / 客胜"),
        MarketType.TOTAL_GOALS: ("## 总进球", "大球水 / 盘口 / 小球水"),
        MarketType.KELLY_INDEX: ("## 凯利指数", "主胜 / 平局 / 客胜"),
    }
    for market, (title, shape) in labels.items():
        lines += ["", title, f"（{shape}）", "| 机构 | 初盘 | 即盘 |", "|---|---|---|"]
        grouped: dict[str, dict[SnapshotPhase, MarketArchiveRowV1]] = defaultdict(dict)
        names: dict[str, str] = {}
        for row in rows:
            if row.market == market and not (market == MarketType.ASIAN_HANDICAP and row.provider_id == "macau" and macau):
                grouped[row.provider_id][row.phase] = row
                names[row.provider_id] = row.provider_name
        if grouped:
            for provider_id in sorted(grouped):
                current = grouped[provider_id]
                lines.append(f"| {names[provider_id]} | {_value(current.get(SnapshotPhase.OPENING))} | {_value(current.get(SnapshotPhase.LATE))} |")
        else:
            lines.append("| 未提供 | - | - |")
    lines += ["", "## 数据完整性", *(f"- {item}" for item in sorted(set(missing or draft.missing_items)))]
    if not (missing or draft.missing_items):
        lines.append("- 已归档的行均已视觉确认；未提供的市场已在对应表格中标注。")
    if resolution.status == "unresolved":
        lines.append(f"- 身份待处理：{resolution.reason}")
    return "\n".join(lines).rstrip() + "\n"


def prepare_market_archive(root: Path, draft: MarketArchiveDraftV1) -> MarketArchivePreviewV1:
    fixture, resolution = resolve_fixture(root, draft.fixture)
    snapshots, extraction_missing, rows = _snapshots(draft, fixture)
    missing = [*draft.missing_items, *extraction_missing]
    return MarketArchivePreviewV1(
        rendered_markdown=render_preview(draft, fixture, resolution, rows, missing), fixture=fixture,
        competition_resolution=resolution, snapshots=snapshots, missing_items=missing,
    )


def prepare_market_comparison(
    root: Path,
    draft: MarketArchiveDraftV1,
    *,
    baseline_draft: MarketArchiveDraftV1 | None = None,
) -> MarketArchiveComparisonV1:
    """Render a read-only current preview plus a prior-batch comparison and watch checks."""
    current = prepare_market_archive(root, draft)
    baseline_snapshots: list[MarketSnapshot] = []
    baseline_source = BaselineSource.NONE
    baseline_captured_at = None
    baseline_sha256 = None
    if baseline_draft is not None:
        baseline = prepare_market_archive(root, baseline_draft)
        current_identity = (
            current.fixture.home_team_id, current.fixture.away_team_id, current.fixture.kickoff_at,
        )
        baseline_identity = (
            baseline.fixture.home_team_id, baseline.fixture.away_team_id, baseline.fixture.kickoff_at,
        )
        if current_identity != baseline_identity:
            raise MarketArchiveError("基线草稿与当前草稿不是同一场比赛")
        if baseline_draft.captured_at >= draft.captured_at:
            raise MarketArchiveError("基线采集时间必须早于当前采集时间")
        baseline_snapshots = baseline.snapshots
        baseline_source = BaselineSource.SESSION_DRAFT
        baseline_captured_at = baseline_draft.captured_at
        baseline_sha256 = draft_sha256(baseline_draft)
    else:
        match_path = _exact_match_path(root, current.fixture)
        if match_path is not None:
            match_id = MatchDocument.load(match_path).metadata.match_id
            archived = archived_baseline(root, match_id, draft.captured_at)
            if archived is not None:
                _, baseline_captured_at, baseline_sha256, baseline_snapshots = archived
                baseline_source = BaselineSource.ARCHIVED_BATCH
    status = ComparisonStatus.COMPARED if baseline_snapshots else ComparisonStatus.FIRST_CAPTURE
    changes = compare_snapshots(current.snapshots, baseline_snapshots) if baseline_snapshots else []
    watchlist = None
    match_path = _exact_match_path(root, current.fixture)
    if match_path is not None:
        match_id = MatchDocument.load(match_path).metadata.match_id
        loaded = active_watchlist(root, match_id)
        watchlist = loaded[1] if loaded else None
    risks = evaluate_watchlist(
        watchlist,
        current.snapshots,
        baseline_snapshots,
        captured_at=draft.captured_at,
        kickoff_at=current.fixture.kickoff_at,
    ) if current.fixture.kickoff_at else []
    rendered = current.rendered_markdown.rstrip() + "\n" + render_comparison_sections(changes, risks, status)
    return MarketArchiveComparisonV1(
        rendered_markdown=rendered,
        comparison_status=status,
        baseline_source=baseline_source,
        baseline_captured_at=baseline_captured_at,
        baseline_sha256=baseline_sha256,
        current_sha256=draft_sha256(draft),
        change_events=changes,
        risk_watch_evaluations=risks,
    )


def _exact_target_exists(root: Path, fixture: FixtureCandidate) -> bool:
    return _exact_match_path(root, fixture) is not None or any(
        case.home_team_id == fixture.home_team_id and case.away_team_id == fixture.away_team_id and case.kickoff_at == fixture.kickoff_at
        for case in latest_cases(root).values()
    )


def _exact_match_path(root: Path, fixture: FixtureCandidate) -> Path | None:
    if not (fixture.home_team_id and fixture.away_team_id and fixture.kickoff_at):
        return None
    for path in match_files(root):
        metadata = MatchDocument.load(path).metadata
        if metadata.home_team_id == fixture.home_team_id and metadata.away_team_id == fixture.away_team_id and metadata.kickoff_at == fixture.kickoff_at:
            return path
    return None


def _attachment_mappings(root: Path, entry, snapshots: list[MarketSnapshot]) -> list[AttachmentMappingV1]:
    attachment_manifest = yaml.safe_load((root / entry.attachments_path).read_text(encoding="utf-8")) or {}
    files = {item["original_filename"]: item for item in attachment_manifest.get("attachments", [])}
    mappings = []
    for snapshot in snapshots:
        filename = snapshot.source_ref.split(":", 1)[1].split("#", 1)[0]
        if filename in files:
            record = files[filename]
            mappings.append(AttachmentMappingV1(source_ref=snapshot.source_ref, original_filename=filename, stored_filename=record["stored_filename"], sha256=record["sha256"]))
    return mappings


def _same_attachments(root: Path, entry, attachments: list[Path]) -> bool:
    manifest = yaml.safe_load((root / entry.attachments_path).read_text(encoding="utf-8")) or {}
    existing = {item["original_filename"]: item["sha256"] for item in manifest.get("attachments", [])}
    supplied = {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in attachments}
    return existing == supplied


def _bundle_quote(row: MarketArchiveRowV1) -> QuoteValuesV1:
    raw = row.raw_values
    market = MarketType(row.market)
    if market == MarketType.ASIAN_HANDICAP:
        return QuoteValuesV1(home=raw["home_water"], line=raw["line"], away=raw["away_water"])
    if market == MarketType.TOTAL_GOALS:
        return QuoteValuesV1(over=raw["over_water"], line=raw["line"], under=raw["under_water"])
    return QuoteValuesV1(home=raw["home_win"], draw=raw["draw"], away=raw["away_win"])


def _normalization_bundle(
    draft: MarketArchiveDraftV1,
    preview: MarketArchivePreviewV1,
    *,
    entry_id: str,
    source_ref: str,
    source_sha256: str,
) -> MatchDataBundleV1:
    fixture = preview.fixture
    if not all((fixture.competition_code, fixture.competition, fixture.home_team, fixture.away_team, fixture.kickoff_at)):
        raise MarketArchiveError("规范化盘口要求比赛身份已唯一确认")
    timeline = [
        MacauTimelineInputV1(
            displayed_at=item.displayed_at,
            status=item.status,
            home_water=item.home_water,
            line=item.line,
            away_water=item.away_water,
            sequence_no=index,
        )
        for index, item in enumerate(draft.macau_timeline, start=1)
    ]
    rows = [
        item for item in draft.rows
        if item.visually_verified
        and not (
            timeline and item.market == MarketType.ASIAN_HANDICAP and item.provider_id == "macau"
        )
    ]
    grouped: dict[tuple[MarketType, str, str], dict[SnapshotPhase, MarketArchiveRowV1]] = defaultdict(dict)
    for row in rows:
        grouped[(MarketType(row.market), row.provider_id, row.provider_name)][SnapshotPhase(row.phase)] = row
    summaries: dict[MarketType, list[SummaryRowInputV1]] = defaultdict(list)
    for (market, provider_id, provider_name), endpoints in grouped.items():
        opening = endpoints.get(SnapshotPhase.OPENING)
        current = endpoints.get(SnapshotPhase.LATE)
        summaries[market].append(SummaryRowInputV1(
            provider_id=provider_id,
            provider_name=provider_name,
            opening=_bundle_quote(opening) if opening else None,
            current=_bundle_quote(current) if current else None,
            opening_status="available" if opening else "not_provided",
            current_status="available" if current else "not_provided",
            opening_observed_at=opening.observed_at if opening else None,
            current_observed_at=current.observed_at if current else None,
        ))
    return MatchDataBundleV1(
        bundle_id=f"market-archive-{entry_id}",
        fixture=FixtureBundleV1(
            competition_code=fixture.competition_code,
            competition=str(fixture.competition),
            home_team=str(fixture.home_team),
            away_team=str(fixture.away_team),
            kickoff_at=fixture.kickoff_at,
            timezone=fixture.timezone,
        ),
        market_data=MarketDataInputV1(
            source_kind=SourceKind.SCREENSHOT_VERIFIED,
            source_captured_at=draft.captured_at,
            source_ref=source_ref,
            source_sha256=source_sha256,
            capture_batch_id=entry_id,
            macau_handicap_timeline=timeline,
            handicap_summary=summaries[MarketType.ASIAN_HANDICAP],
            european_odds_summary=summaries[MarketType.EUROPEAN_ODDS],
            total_goals_summary=summaries[MarketType.TOTAL_GOALS],
            kelly_summary=summaries[MarketType.KELLY_INDEX],
        ),
    )


def archive_market_draft(root: Path, draft: MarketArchiveDraftV1, attachments: list[Path]) -> MarketArchiveResultV1:
    supplied = [item.name for item in attachments]
    if len(supplied) != len(set(supplied)):
        raise MarketArchiveError("附件原始文件名不得重复")
    missing_attachments = sorted(set(draft.screenshots) - set(supplied))
    if missing_attachments:
        raise MarketArchiveError("归档必须提供所有声明的原始截图：" + ", ".join(missing_attachments))
    preview = prepare_market_archive(root, draft)
    fixture = preview.fixture
    ambiguity = []
    if preview.competition_resolution.status == "unresolved":
        ambiguity.append("fixture_identity_unresolved")
    source = preview.rendered_markdown
    existing_path = _exact_match_path(root, fixture)
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if existing_path is not None:
        for existing in journal_status(root, match_path=existing_path):
            if existing.source_sha256 == source_sha256 and _same_attachments(root, existing, attachments):
                return MarketArchiveResultV1(
                    entry_id=existing.entry_id, target_type=existing.target_type, target_id=existing.target_id,
                    attachment_mappings=_attachment_mappings(root, existing, preview.snapshots),
                    snapshot_count=len(preview.snapshots), missing_items=preview.missing_items,
                )
    request = JournalIngestRequestV1(
        capture_mode=CaptureMode.CANONICAL_CHAT_TEXT, received_at=draft.captured_at, actor=draft.actor,
        user_intent=UserIntent.STORE_ONLY, fixture_candidate=fixture, classification_confidence=0.96 if not ambiguity else 0.50,
        ambiguity_flags=ambiguity,
        segments=[JournalSegmentV1(
            segment_id="market-archive", segment_type=SegmentType.MARKET_DATA, source_line_start=1,
            source_line_end=max(1, len(source.splitlines())), observed_at=draft.captured_at,
            classification_confidence=0.96 if not ambiguity else 0.50, ambiguity_flags=ambiguity,
            normalized_markdown=source, payload={"market_snapshots": [item.model_dump(mode="json") for item in preview.snapshots]},
        )],
    )
    with tempfile.TemporaryDirectory(prefix="odds-market-archive-") as temporary:
        source_file = Path(temporary) / "market-archive.md"
        source_file.write_text(source, encoding="utf-8", newline="\n")
        if ambiguity:
            entry = ingest_journal(root, source_file=source_file, request=request, attachments=attachments, auto_apply=False)
            operation_result = None
        else:
            operation = JournalOperation.APPEND if _exact_target_exists(root, fixture) else JournalOperation.NEW
            operation_result = operate_journal(root, operation=operation, source_file=source_file, request=request, attachments=attachments)
            entry = operation_result.entry
    normalization = None
    if entry.target_type == "match" and entry.target_id:
        target_path = next(
            path for path in match_files(root)
            if MatchDocument.load(path).metadata.match_id == entry.target_id
        )
        bundle = _normalization_bundle(
            draft,
            preview,
            entry_id=entry.entry_id,
            source_ref=entry.source_path,
            source_sha256=entry.source_sha256,
        )
        normalization = ingest_bundle(
            root,
            bundle,
            match_path=target_path,
            actor=draft.actor,
            received_at=draft.captured_at,
            project_compatibility=False,
        ).model_dump(mode="json")
    return MarketArchiveResultV1(
        journal=operation_result, entry_id=entry.entry_id, target_type=entry.target_type, target_id=entry.target_id,
        attachment_mappings=_attachment_mappings(root, entry, preview.snapshots), snapshot_count=len(preview.snapshots), missing_items=preview.missing_items,
        normalization=normalization,
    )
