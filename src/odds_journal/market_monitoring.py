from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .analysis_context import parse_receipt
from .ledger import sha256_json
from .markdown import MatchDocument
from .models import MarketSnapshot, MarketType, SnapshotPhase
from .observations import latest_capture_batch_snapshots
from .rules import sha256_text
from .services import ServiceError


WATCHLIST_ROOT = Path("data/risk-watchlists")


class ComparisonStatus(StrEnum):
    COMPARED = "compared"
    FIRST_CAPTURE = "first_capture"


class BaselineSource(StrEnum):
    SESSION_DRAFT = "session_draft"
    ARCHIVED_BATCH = "archived_batch"
    NONE = "none"


class ChangeType(StrEnum):
    NEW = "新增"
    UNCHANGED = "无变化"
    VALUE_CHANGED = "数值变化"
    LINE_CHANGED = "盘口升降"
    CONFLICT = "来源冲突"
    NOT_DISPLAYED = "本次未显示"
    INCOMPARABLE = "不可比较"


class RiskStatus(StrEnum):
    TRIGGERED = "已触发"
    NEAR = "接近触发"
    NOT_TRIGGERED = "未触发"
    UNKNOWN = "当前无法判断"


class EvaluatorType(StrEnum):
    MARKET_THRESHOLD = "market_threshold"
    MARKET_AND_TREND = "market_and_trend"
    STRUCTURED_FACT = "structured_fact"
    MANUAL_ONLY = "manual_only"


class RiskConditionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    original_risk_text: str = Field(min_length=1)
    trigger_text: str = Field(min_length=1)
    consequence_text: str = Field(min_length=1)
    evaluator_type: EvaluatorType
    market: MarketType | None = None
    provider_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]+$")
    phase: SnapshotPhase = SnapshotPhase.LATE
    field: Literal[
        "home_water", "away_water", "line", "home_win", "draw", "away_win",
        "over_water", "under_water",
    ] | None = None
    operator: Literal[">", ">=", "<", "<=", "=="] | None = None
    threshold: float | None = None
    line_constraint: float | None = None
    required_trend: Literal["rising", "falling"] | None = None
    near_tolerance: float | None = Field(default=None, gt=0)
    required_data_types: list[str] = Field(default_factory=list)
    source_location: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evaluator(self) -> "RiskConditionV1":
        numeric = self.evaluator_type in {
            EvaluatorType.MARKET_THRESHOLD,
            EvaluatorType.MARKET_AND_TREND,
        }
        fields = (self.market, self.provider_id, self.field, self.operator, self.threshold)
        if numeric and any(value is None for value in fields):
            raise ValueError("数值型风险条件必须绑定市场、机构、字段、比较符和阈值")
        if not numeric and any(value is not None for value in fields):
            raise ValueError("定性风险条件不得填写盘口阈值字段")
        if self.evaluator_type == EvaluatorType.MARKET_AND_TREND and self.required_trend is None:
            raise ValueError("market_and_trend 必须填写 required_trend")
        if self.evaluator_type != EvaluatorType.MARKET_AND_TREND and self.required_trend is not None:
            raise ValueError("只有 market_and_trend 可以填写 required_trend")
        tolerance = 0.25 if self.field == "line" else 0.05
        if numeric and self.near_tolerance is None:
            self.near_tolerance = tolerance
        if self.field == "line" and self.near_tolerance != 0.25:
            raise ValueError("盘口字段的接近触发容差必须为 0.25")
        if numeric and self.field != "line" and self.near_tolerance != 0.05:
            raise ValueError("欧赔、水位和凯利的接近触发容差必须为 0.05")
        return self


class PrematchRiskWatchlistDraftV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    watchlist_id: str = Field(pattern=r"^watchlist-[a-z0-9-]+$")
    match_id: str
    source_text: str = Field(min_length=1)
    conditions: list[RiskConditionV1] = Field(min_length=1)
    supersedes_watchlist_id: str | None = None

    @model_validator(mode="after")
    def unique_conditions(self) -> "PrematchRiskWatchlistDraftV1":
        ids = [item.condition_id for item in self.conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("condition_id 不得重复")
        return self


class PrematchRiskWatchlistV1(PrematchRiskWatchlistDraftV1):
    created_at: datetime
    data_cutoff_at: datetime
    source_analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_section_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    watchlist_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at", "data_cutoff_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Watchlist 时间必须包含时区")
        return value


class MarketChangeEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    market: MarketType
    provider_id: str
    phase: SnapshotPhase
    field: str
    previous_value: str | None = None
    current_value: str | None = None
    numeric_delta: float | None = None
    previous_line: str | None = None
    current_line: str | None = None
    comparable: bool
    change_type: ChangeType
    baseline_snapshot_id: str | None = None
    current_snapshot_id: str | None = None
    note: str | None = None


class RiskWatchEvaluationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    condition_id: str
    risk_text: str
    previous_value: str | None = None
    current_value: str | None = None
    threshold: str | None = None
    status: RiskStatus
    evidence: str
    source_snapshot_ids: list[str] = Field(default_factory=list)


class MarketArchiveComparisonV1(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    schema_version: Literal[1] = 1
    rendered_markdown: str
    comparison_status: ComparisonStatus
    baseline_source: BaselineSource
    baseline_captured_at: datetime | None = None
    baseline_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    current_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    change_events: list[MarketChangeEventV1] = Field(default_factory=list)
    risk_watch_evaluations: list[RiskWatchEvaluationV1] = Field(default_factory=list)


def _watchlist_hash(payload: dict) -> str:
    clean = dict(payload)
    clean.pop("watchlist_sha256", None)
    return sha256_json(clean)


def load_watchlist(path: Path) -> PrematchRiskWatchlistV1:
    value = PrematchRiskWatchlistV1.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    if value.watchlist_sha256 != _watchlist_hash(value.model_dump(mode="json")):
        raise ServiceError("Watchlist 哈希无效")
    return value


def watchlist_files(root: Path, match_id: str) -> list[Path]:
    directory = root / WATCHLIST_ROOT / match_id
    return sorted(directory.glob("watchlist-*.yml")) if directory.exists() else []


def active_watchlist(root: Path, match_id: str) -> tuple[Path, PrematchRiskWatchlistV1] | None:
    loaded = [(path, load_watchlist(path)) for path in watchlist_files(root, match_id)]
    if not loaded:
        return None
    superseded = {item.supersedes_watchlist_id for _, item in loaded if item.supersedes_watchlist_id}
    active = [(path, item) for path, item in loaded if item.watchlist_id not in superseded]
    if len(active) != 1:
        raise ServiceError("该比赛存在多个未被替代的 Watchlist")
    return active[0]


def prepare_watchlist(
    root: Path,
    match_path: Path,
    draft: PrematchRiskWatchlistDraftV1,
    *,
    created_at: datetime,
) -> tuple[Path, PrematchRiskWatchlistV1]:
    document = MatchDocument.load(match_path)
    if draft.match_id != document.metadata.match_id:
        raise ServiceError("Watchlist match_id 与比赛不一致")
    reasoning = document.sections["prematch-reasoning"]
    if draft.source_text.strip() not in reasoning:
        raise ServiceError("Watchlist 原文不存在于当前赛前推演")
    for condition in draft.conditions:
        if condition.original_risk_text.strip() not in draft.source_text:
            raise ServiceError(f"风险条件不在 source_text 中：{condition.condition_id}")
    receipt = parse_receipt(reasoning)
    if receipt is None:
        raise ServiceError("赛前推演缺少分析回执")
    if created_at >= document.metadata.kickoff_at:
        from .lock_lifecycle import latest_lock_candidate

        candidate = latest_lock_candidate(root, document.metadata.match_id)
        if candidate is None or candidate[1].prematch_reasoning_sha256 != sha256_text(reasoning):
            raise ServiceError("开赛后仅能从已冻结且哈希未变化的赛前原文补建 Watchlist")
    previous = active_watchlist(root, draft.match_id)
    if draft.supersedes_watchlist_id:
        if previous is None or previous[1].watchlist_id != draft.supersedes_watchlist_id:
            raise ServiceError("supersedes_watchlist_id 不是当前有效 Watchlist")
    elif previous is not None and previous[1].watchlist_id != draft.watchlist_id:
        raise ServiceError("已有有效 Watchlist；修订必须填写 supersedes_watchlist_id")
    raw = draft.model_dump(mode="json") | {
        "created_at": created_at,
        "data_cutoff_at": receipt.as_of,
        "source_analysis_receipt_sha256": sha256_json(receipt.model_dump(mode="json")),
        "source_section_sha256": sha256_text(reasoning),
        "watchlist_sha256": "0" * 64,
    }
    provisional = PrematchRiskWatchlistV1.model_validate(raw)
    raw = provisional.model_dump(mode="json")
    raw["watchlist_sha256"] = _watchlist_hash(raw)
    watchlist = PrematchRiskWatchlistV1.model_validate(raw)
    target = root / WATCHLIST_ROOT / draft.match_id / f"{draft.watchlist_id}-{watchlist.watchlist_sha256[:12]}.yml"
    if target.exists():
        existing = load_watchlist(target)
        if existing.watchlist_sha256 == watchlist.watchlist_sha256:
            return target, existing
        raise ServiceError("Watchlist 目标文件已存在且内容不同")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(watchlist.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return target, watchlist


def _raw_field(snapshot: MarketSnapshot, field: str) -> str | None:
    aliases = {"home_win": "home", "away_win": "away"}
    value = snapshot.raw_values.get(field)
    if value is None:
        value = snapshot.raw_values.get(aliases.get(field, ""))
    return str(value) if value is not None else None


def _number_field(snapshot: MarketSnapshot, field: str) -> float | None:
    aliases = {"home_win": "home", "away_win": "away"}
    value = snapshot.normalized_values.get(field)
    if value is None:
        value = snapshot.normalized_values.get(aliases.get(field, ""))
    return float(value) if value is not None else None


def _snapshot_map(snapshots: list[MarketSnapshot]) -> tuple[dict[tuple[str, str, str], MarketSnapshot], set[tuple[str, str, str]]]:
    grouped: dict[tuple[str, str, str], list[MarketSnapshot]] = {}
    for item in snapshots:
        key = (str(item.market), item.provider_id, str(item.phase))
        grouped.setdefault(key, []).append(item)
    conflicts = {
        key for key, values in grouped.items()
        if len({sha256_json(item.raw_values) for item in values}) > 1
    }
    return {key: max(values, key=lambda item: (item.captured_at, item.snapshot_id)) for key, values in grouped.items()}, conflicts


def _market_fields(market: str) -> tuple[str, ...]:
    return {
        MarketType.ASIAN_HANDICAP.value: ("home_water", "line", "away_water"),
        MarketType.EUROPEAN_ODDS.value: ("home_win", "draw", "away_win"),
        MarketType.TOTAL_GOALS.value: ("over_water", "line", "under_water"),
        MarketType.KELLY_INDEX.value: ("home_win", "draw", "away_win"),
    }[market]


def _is_macau_timeline(current: list[MarketSnapshot], baseline: list[MarketSnapshot]) -> bool:
    def distinct_times(values: list[MarketSnapshot]) -> set[datetime]:
        return {
            item.captured_at for item in values
            if item.provider_id == "macau" and item.market == MarketType.ASIAN_HANDICAP.value
        }

    return len(distinct_times(current)) > 1 or len(distinct_times(baseline)) > 1


def _macau_timeline_changes(
    current: list[MarketSnapshot], baseline: list[MarketSnapshot]
) -> list[MarketChangeEventV1]:
    def by_time(values: list[MarketSnapshot]) -> dict[datetime, list[MarketSnapshot]]:
        grouped: dict[datetime, list[MarketSnapshot]] = {}
        for item in values:
            if item.provider_id == "macau" and item.market == MarketType.ASIAN_HANDICAP.value:
                grouped.setdefault(item.captured_at, []).append(item)
        return grouped

    current_by_time = by_time(current)
    baseline_by_time = by_time(baseline)
    events: list[MarketChangeEventV1] = []
    for observed_at in sorted(current_by_time):
        current_values = current_by_time[observed_at]
        baseline_values = baseline_by_time.get(observed_at, [])
        current_hashes = {sha256_json(item.raw_values) for item in current_values}
        baseline_hashes = {sha256_json(item.raw_values) for item in baseline_values}
        if baseline_values and len(current_hashes) == 1 and current_hashes == baseline_hashes:
            continue

        current_item = max(current_values, key=lambda item: item.snapshot_id)
        baseline_item = max(baseline_values, key=lambda item: item.snapshot_id) if baseline_values else None
        conflict = len(current_hashes) > 1 or len(baseline_hashes) > 1 or bool(baseline_values)
        for field in _market_fields(MarketType.ASIAN_HANDICAP.value):
            events.append(MarketChangeEventV1(
                market=MarketType.ASIAN_HANDICAP,
                provider_id="macau",
                phase=SnapshotPhase(current_item.phase),
                field=field,
                previous_value=_raw_field(baseline_item, field) if baseline_item else None,
                current_value=_raw_field(current_item, field),
                previous_line=_raw_field(baseline_item, "line") if baseline_item else None,
                current_line=_raw_field(current_item, "line"),
                comparable=False,
                change_type=ChangeType.CONFLICT if conflict else ChangeType.NEW,
                baseline_snapshot_id=baseline_item.snapshot_id if baseline_item else None,
                current_snapshot_id=current_item.snapshot_id,
                note=(
                    f"澳门详细时序在 {observed_at.isoformat()} 出现不同数值"
                    if conflict else f"澳门详细时序新增节点 {observed_at.isoformat()}"
                ),
            ))
    return events


def compare_snapshots(current: list[MarketSnapshot], baseline: list[MarketSnapshot]) -> list[MarketChangeEventV1]:
    timeline_mode = _is_macau_timeline(current, baseline)
    events = _macau_timeline_changes(current, baseline) if timeline_mode else []
    if timeline_mode:
        current = [
            item for item in current
            if not (item.provider_id == "macau" and item.market == MarketType.ASIAN_HANDICAP.value)
        ]
        baseline = [
            item for item in baseline
            if not (item.provider_id == "macau" and item.market == MarketType.ASIAN_HANDICAP.value)
        ]
    current_map, current_conflicts = _snapshot_map(current)
    baseline_map, baseline_conflicts = _snapshot_map(baseline)
    market_order = {
        MarketType.ASIAN_HANDICAP.value: 0,
        MarketType.EUROPEAN_ODDS.value: 1,
        MarketType.TOTAL_GOALS.value: 2,
        MarketType.KELLY_INDEX.value: 3,
    }
    keys = set(current_map) | set(baseline_map)
    for key in sorted(keys, key=lambda item: (market_order[item[0]], item[1], item[2])):
        current_item, baseline_item = current_map.get(key), baseline_map.get(key)
        market, provider, phase = key
        for field in _market_fields(market):
            old = _raw_field(baseline_item, field) if baseline_item else None
            new = _raw_field(current_item, field) if current_item else None
            old_line = _raw_field(baseline_item, "line") if baseline_item else None
            new_line = _raw_field(current_item, "line") if current_item else None
            conflict = key in current_conflicts or key in baseline_conflicts
            comparable = bool(current_item and baseline_item and not conflict)
            note = None
            if conflict:
                kind, comparable, note = ChangeType.CONFLICT, False, "同一批次存在不同数值"
            elif current_item is None:
                kind, comparable = ChangeType.NOT_DISPLAYED, False
            elif baseline_item is None:
                kind, comparable = ChangeType.NEW, False
            elif phase == SnapshotPhase.OPENING.value and old != new:
                kind, comparable, note = ChangeType.CONFLICT, False, "初盘变化仅视为来源修订或冲突"
            elif field != "line" and market in {MarketType.ASIAN_HANDICAP.value, MarketType.TOTAL_GOALS.value} and old_line != new_line:
                kind, comparable, note = ChangeType.INCOMPARABLE, False, "盘口档位不同，水位不直接相减"
            elif old == new:
                kind = ChangeType.UNCHANGED
            elif field == "line":
                kind = ChangeType.LINE_CHANGED
            else:
                kind = ChangeType.VALUE_CHANGED
            delta = None
            if comparable and old != new:
                old_number, new_number = _number_field(baseline_item, field), _number_field(current_item, field)
                if old_number is not None and new_number is not None:
                    delta = round(new_number - old_number, 6)
            events.append(MarketChangeEventV1(
                market=MarketType(market), provider_id=provider, phase=SnapshotPhase(phase), field=field,
                previous_value=old, current_value=new, numeric_delta=delta,
                previous_line=old_line, current_line=new_line, comparable=comparable,
                change_type=kind, baseline_snapshot_id=baseline_item.snapshot_id if baseline_item else None,
                current_snapshot_id=current_item.snapshot_id if current_item else None, note=note,
            ))
    return events


def _passes(value: float, operator: str, threshold: float) -> bool:
    return {
        ">": value > threshold, ">=": value >= threshold, "<": value < threshold,
        "<=": value <= threshold, "==": value == threshold,
    }[operator]


def _toward(value: float, previous: float, operator: str) -> bool:
    return value > previous if operator in {">", ">="} else value < previous if operator in {"<", "<="} else False


def evaluate_watchlist(
    watchlist: PrematchRiskWatchlistV1 | None,
    current: list[MarketSnapshot],
    baseline: list[MarketSnapshot],
    *,
    captured_at: datetime,
    kickoff_at: datetime,
) -> list[RiskWatchEvaluationV1]:
    if watchlist is None:
        return []
    current_map, current_conflicts = _snapshot_map(current)
    baseline_map, baseline_conflicts = _snapshot_map(baseline)
    results = []
    for condition in watchlist.conditions:
        threshold_text = None if condition.threshold is None else f"{condition.operator} {condition.threshold:g}"
        if captured_at >= kickoff_at:
            results.append(RiskWatchEvaluationV1(
                condition_id=condition.condition_id, risk_text=condition.original_risk_text,
                threshold=threshold_text, status=RiskStatus.UNKNOWN, evidence="赛前监测窗口已结束",
            ))
            continue
        if condition.evaluator_type in {EvaluatorType.STRUCTURED_FACT, EvaluatorType.MANUAL_ONLY}:
            results.append(RiskWatchEvaluationV1(
                condition_id=condition.condition_id, risk_text=condition.original_risk_text,
                status=RiskStatus.UNKNOWN, evidence="当前赔率截图不能证明该定性条件",
            ))
            continue
        key = (str(condition.market), str(condition.provider_id), str(condition.phase))
        current_item, baseline_item = current_map.get(key), baseline_map.get(key)
        if current_item is None or key in current_conflicts:
            results.append(RiskWatchEvaluationV1(
                condition_id=condition.condition_id, risk_text=condition.original_risk_text,
                threshold=threshold_text, status=RiskStatus.UNKNOWN, evidence="当前机构字段缺失或存在来源冲突",
            ))
            continue
        baseline_invalid = baseline_item is None or key in baseline_conflicts
        if condition.evaluator_type == EvaluatorType.MARKET_AND_TREND and baseline_invalid:
            results.append(RiskWatchEvaluationV1(
                condition_id=condition.condition_id, risk_text=condition.original_risk_text,
                current_value=_raw_field(current_item, str(condition.field)), threshold=threshold_text,
                status=RiskStatus.UNKNOWN, evidence="缺少可比基线或基线存在来源冲突",
                source_snapshot_ids=[current_item.snapshot_id],
            ))
            continue
        current_value = _number_field(current_item, str(condition.field))
        previous_value = (
            _number_field(baseline_item, str(condition.field)) if not baseline_invalid else None
        )
        current_raw = _raw_field(current_item, str(condition.field))
        previous_raw = _raw_field(baseline_item, str(condition.field)) if not baseline_invalid else None
        if condition.line_constraint is not None and _number_field(current_item, "line") != condition.line_constraint:
            results.append(RiskWatchEvaluationV1(
                condition_id=condition.condition_id, risk_text=condition.original_risk_text,
                previous_value=previous_raw, current_value=current_raw, threshold=threshold_text,
                status=RiskStatus.UNKNOWN, evidence="当前盘口档位不满足条件约束",
                source_snapshot_ids=[current_item.snapshot_id],
            ))
            continue
        if current_value is None:
            status, evidence = RiskStatus.UNKNOWN, "当前字段无法规范化"
        else:
            threshold = float(condition.threshold)
            threshold_pass = _passes(current_value, str(condition.operator), threshold)
            trend_ok = True
            if condition.evaluator_type == EvaluatorType.MARKET_AND_TREND:
                trend_ok = previous_value is not None and (
                    current_value > previous_value if condition.required_trend == "rising" else current_value < previous_value
                )
            if threshold_pass and trend_ok:
                status, evidence = RiskStatus.TRIGGERED, "当前值满足阈值和所需趋势"
            elif threshold_pass and not trend_ok:
                status, evidence = RiskStatus.NOT_TRIGGERED, "已到阈值，但未满足继续同向变化"
            elif previous_value is not None and _toward(current_value, previous_value, str(condition.operator)) and abs(current_value - threshold) <= float(condition.near_tolerance):
                status, evidence = RiskStatus.NEAR, "当前值朝阈值移动且进入固定容差"
            elif previous_value is None and abs(current_value - threshold) <= float(condition.near_tolerance):
                status, evidence = RiskStatus.UNKNOWN, "当前值接近阈值，但缺少可比基线判断变化方向"
            else:
                status, evidence = RiskStatus.NOT_TRIGGERED, "当前值未满足阈值"
        ids = [current_item.snapshot_id]
        if not baseline_invalid:
            ids.insert(0, baseline_item.snapshot_id)
        results.append(RiskWatchEvaluationV1(
            condition_id=condition.condition_id, risk_text=condition.original_risk_text,
            previous_value=previous_raw, current_value=current_raw, threshold=threshold_text,
            status=status, evidence=evidence, source_snapshot_ids=ids,
        ))
    return results


def archived_baseline(root: Path, match_id: str, before: datetime) -> tuple[str, datetime, str, list[MarketSnapshot]] | None:
    value = latest_capture_batch_snapshots(root, match_id=match_id, before=before)
    if value is None:
        return None
    batch_id, captured_at, snapshots = value
    return batch_id, captured_at, sha256_json([item.model_dump(mode="json") for item in snapshots]), snapshots


def render_comparison_sections(events: list[MarketChangeEventV1], risks: list[RiskWatchEvaluationV1], status: ComparisonStatus) -> str:
    lines = ["", "## 相较上次数据变化", ""]
    if status == ComparisonStatus.FIRST_CAPTURE:
        lines.append("首次采集，无历史基线。")
    else:
        lines += ["| 市场 | 机构 | 阶段 | 字段 | 上次 | 本次 | 差值 | 类型 |", "|---|---|---|---|---:|---:|---:|---|"]
        for item in events:
            delta = "-" if item.numeric_delta is None else f"{item.numeric_delta:+g}"
            lines.append(
                f"| {item.market} | {item.provider_id} | {item.phase} | {item.field} | "
                f"{item.previous_value or '-'} | {item.current_value or '-'} | {delta} | {item.change_type} |"
            )
            if item.note:
                lines.append(f"<!-- comparison-note:{item.provider_id}:{item.field} {item.note} -->")
    lines += ["", "## 赛前风险提示监测", ""]
    if not risks:
        lines.append("未找到该场已固化的赛前风险监测清单。")
    else:
        lines += ["| 风险条件 | 上次值 | 当前值 | 阈值 | 状态 | 数据依据 |", "|---|---:|---:|---:|---|---|"]
        for item in risks:
            lines.append(
                f"| {item.risk_text.replace('|', '｜')} | {item.previous_value or '-'} | "
                f"{item.current_value or '-'} | {item.threshold or '-'} | {item.status} | {item.evidence} |"
            )
    return "\n".join(lines) + "\n"


def draft_sha256(value: BaseModel) -> str:
    return hashlib.sha256(json.dumps(value.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
