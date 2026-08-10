from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .analysis_context import AnalysisReceipt, parse_receipt, set_analysis_content
from .calibration import CalibrationConfig
from .ledger import append_payloads, atomic_write_text, read_ledger, sha256_json
from .markdown import MatchDocument
from .models import (
    AnalysisOutlook, CalibrationEvent, MatchStatus, RecordIntegrity,
)
from .observations import observation_conflict_ids, prediction_eligible_market_observations
from .rules import load_ruleset
from .rule_engine.audit import stable_sha256
from .rule_engine.candidates import apply_governed_rankings
from .rule_engine.evaluation import MachineRuleEvent, ReasoningDisposition, _source_ids
from .rule_engine.evaluators import evaluate
from .rule_engine.features import feature_snapshot
from .rule_engine.profiles import resolve_profile
from .transaction import RepositoryTransaction


MARKETS = ("one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score")
FACT_LEDGER = Path("knowledge/evidence/prematch-fact-events.jsonl")
COMPILER_VERSION = "formal-draft-v1"


class PrematchFactV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(min_length=1)
    fact_type: Literal[
        "team_strength_rating", "competition_tier", "venue_status",
        "squad_availability", "recent_form",
    ]
    subject: Literal["home", "away", "match"]
    value: dict[str, Any]
    source_ref: str = Field(min_length=1)
    observed_at: datetime
    received_at: datetime
    authentication_status: Literal["authenticated", "unverified"]

    @field_validator("observed_at", "received_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("赛前事实时间必须包含时区")
        return value


class PrematchFactBundleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    as_of: datetime
    facts: list[PrematchFactV1]
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("FactBundle as_of 必须包含时区")
        return value

    @model_validator(mode="after")
    def unique_facts(self) -> "PrematchFactBundleV1":
        ids = [item.fact_id for item in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("FactBundle fact_id 不得重复")
        return self


class FormalAnalysisGateV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_status: Literal["ready", "pass"]
    identity_status: Literal["valid", "conflicted"]
    cutoff_status: Literal["valid", "invalid"]
    reasons: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_gate(self) -> "FormalAnalysisGateV2":
        failed = self.identity_status == "conflicted" or self.cutoff_status == "invalid"
        if failed != (self.lifecycle_status == "pass"):
            raise ValueError("全局门禁状态与身份/截止时间状态不一致")
        if failed and not self.reasons:
            raise ValueError("全局 pass 必须记录原因")
        return self


class MarketAssessmentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Literal["one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score"]
    status: Literal["assessed", "degraded", "pass"]
    input_mode: Literal["market_only", "full_context"]
    ranking: list[str] = Field(default_factory=list)
    line: float | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    provider_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    pass_reasons: list[str] = Field(default_factory=list)
    degradation_reasons: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status(self) -> "MarketAssessmentV1":
        if len(self.ranking) != len(set(self.ranking)):
            raise ValueError("市场排序不得重复")
        if self.status == "pass":
            if self.ranking or not self.pass_reasons:
                raise ValueError("pass 市场不得保留排序且必须记录原因")
        elif not self.ranking or self.pass_reasons:
            raise ValueError("可评估市场必须保留排序且不得填写 pass_reasons")
        if self.status == "degraded" and not self.degradation_reasons:
            raise ValueError("degraded 市场必须记录降级原因")
        if self.status == "assessed" and self.degradation_reasons:
            raise ValueError("assessed 市场不得记录降级原因")
        return self


class DraftBuildReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    built_at: datetime
    as_of: datetime
    ruleset_id: str
    ruleset_version: str
    ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    calibration_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_observations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    compiler_version: Literal["formal-draft-v1"] = COMPILER_VERSION
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AnalysisDraftInputV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = 3
    match_id: str
    as_of: datetime
    analysis_input_mode: Literal["market_only", "full_context"]
    compiler_version: Literal["formal-draft-v1"] = COMPILER_VERSION
    calibration_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_observations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fact_bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    formal_gate: FormalAnalysisGateV2
    market_assessments: dict[str, MarketAssessmentV1]
    hypotheses: dict[str, dict[str, str]]
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def complete_markets(self) -> "AnalysisDraftInputV3":
        if set(self.market_assessments) != set(MARKETS):
            raise ValueError("Contract 8 草稿必须逐项覆盖五个市场")
        if set(self.hypotheses) != set(MARKETS):
            raise ValueError("Contract 8 草稿必须逐项冻结五个市场的双向假设")
        for market, item in self.market_assessments.items():
            if item.market != market:
                raise ValueError("市场评估键与 market 字段不一致")
            required = {"supporting_hypothesis", "counter_hypothesis", "invalidation_condition"}
            if set(self.hypotheses[market]) != required or any(not value for value in self.hypotheses[market].values()):
                raise ValueError(f"{market} 双向假设不完整")
        return self


class DraftAcceptanceReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_at: datetime
    approved_by: Literal["lcz"]
    draft_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationBundleV3(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3] = 3
    match_id: str
    cutoff_at: datetime
    ruleset_version: str
    calibration_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    draft_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_observations_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile_chain: list[str]
    competition_profile: str
    formal_gate: FormalAnalysisGateV2
    market_assessments: dict[str, MarketAssessmentV1]
    features: dict[str, Any]
    events: list[MachineRuleEvent]
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _hash_model(model: BaseModel, hash_field: str) -> str:
    raw = model.model_dump(mode="json")
    raw[hash_field] = "0" * 64
    return sha256_json(raw)


def _latest_by_provider(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in sorted(
        rows,
        key=lambda item: (datetime.fromisoformat(str(item["observed_at"])), item["observation_id"]),
    ):
        latest[row["provider_id"]] = row
    return [latest[key] for key in sorted(latest)]


def _probabilities(prices: dict[str, Any], keys: tuple[str, ...], odds_format: str) -> dict[str, float]:
    raw: dict[str, float] = {}
    for key in keys:
        price = float(prices[key])
        decimal = price + 1.0 if odds_format == "hong_kong" else price
        if decimal <= 1:
            raise ValueError("赔率必须可转换为大于 1 的十进制赔率")
        raw[key] = 1.0 / decimal
    total = sum(raw.values())
    return {key: value / total for key, value in raw.items()}


def _has_theoretical_positioning(bundle: PrematchFactBundleV1 | None, cutoff: datetime) -> bool:
    if bundle is None:
        return False
    ratings: dict[str, list[PrematchFactV1]] = defaultdict(list)
    for fact in bundle.facts:
        if (
            fact.fact_type == "team_strength_rating"
            and fact.authentication_status == "authenticated"
            and fact.subject in {"home", "away"}
            and fact.observed_at <= cutoff
            and fact.received_at <= cutoff
        ):
            try:
                valid_from = datetime.fromisoformat(str(fact.value["valid_from"]))
                valid_until = datetime.fromisoformat(str(fact.value["valid_until"]))
                if (
                    valid_from.tzinfo is None or valid_from.utcoffset() is None
                    or valid_until.tzinfo is None or valid_until.utcoffset() is None
                    or not valid_from <= cutoff <= valid_until
                ):
                    continue
                provider = str(fact.value["provider_id"])
                method = str(fact.value["method_id"])
                float(fact.value["rating"])
            except (KeyError, TypeError, ValueError):
                continue
            key = f"{fact.source_ref}:{provider}:{method}:{valid_from.isoformat()}:{valid_until.isoformat()}"
            ratings[key].append(fact)
    return any({item.subject for item in items} == {"home", "away"} for items in ratings.values())


def _pass(market: str, mode: str, reason: str, *, conflicts: list[str] | None = None,
          missing: list[str] | None = None) -> MarketAssessmentV1:
    return MarketAssessmentV1(
        market=market, status="pass", input_mode=mode, pass_reasons=[reason],
        conflicts=conflicts or [], missing_inputs=missing or [],
    )


def _one_x_two(rows: list[dict[str, Any]], mode: str, config: CalibrationConfig,
               conflicts: list[str], positioned: bool) -> MarketAssessmentV1:
    policy = config.formal_draft_policy
    assert policy is not None
    if conflicts:
        return _pass("one_x_two", mode, "unresolved_market_conflicts", conflicts=conflicts)
    latest = _latest_by_provider([
        row for row in rows
        if row.get("provider_id") in policy.eligible_provider_ids and row.get("odds_format") == "decimal"
    ])
    if len(latest) < policy.one_x_two_min_providers:
        return _pass("one_x_two", mode, "insufficient_independent_providers", missing=["three_exact_decimal_providers"])
    probabilities = {
        row["provider_id"]: _probabilities(row["normalized_prices"], ("home", "draw", "away"), "decimal")
        for row in latest
    }
    provider_winners = [max(values, key=values.get) for values in probabilities.values()]
    votes = Counter(provider_winners)
    winner, agreeing = sorted(votes.items(), key=lambda item: (-item[1], item[0]))[0]
    medians = {key: median(values[key] for values in probabilities.values()) for key in ("home", "draw", "away")}
    ranking = sorted(medians, key=lambda key: (-medians[key], key))
    gap = medians[ranking[0]] - medians[ranking[1]]
    if agreeing < policy.one_x_two_min_agreeing_providers or winner != ranking[0]:
        return _pass("one_x_two", mode, "provider_direction_has_no_majority")
    if gap < policy.directional_probability_gap_min:
        return _pass("one_x_two", mode, "insufficient_directional_separation")
    degradation = [] if positioned else ["theoretical_positioning_unavailable"]
    return MarketAssessmentV1(
        market="one_x_two", status="degraded" if degradation else "assessed", input_mode=mode,
        ranking=ranking, provider_ids=sorted(probabilities),
        observation_ids=[row["observation_id"] for row in latest],
        evidence_refs=[f"market-observation:{row['observation_id']}" for row in latest],
        degradation_reasons=degradation,
        metrics={"median_probabilities": medians, "top_gap": gap, "agreeing_providers": agreeing},
    )


def _asian(rows: list[dict[str, Any]], mode: str, config: CalibrationConfig,
           conflicts: list[str], positioned: bool) -> MarketAssessmentV1:
    policy = config.formal_draft_policy
    assert policy is not None
    if conflicts:
        return _pass("asian_handicap", mode, "unresolved_market_conflicts", conflicts=conflicts)
    latest = _latest_by_provider([
        row for row in rows
        if row.get("provider_id") in policy.eligible_provider_ids
        and row.get("odds_format") == "hong_kong" and row.get("normalized_line") is not None
    ])
    if len(latest) < policy.asian_min_providers:
        return _pass("asian_handicap", mode, "insufficient_independent_providers", missing=["two_exact_same_line_providers"])
    line_counts = Counter(float(row["normalized_line"]) for row in latest)
    line, count = sorted(line_counts.items(), key=lambda item: (-item[1], item[0]))[0]
    if count < policy.asian_min_providers or count / len(latest) < policy.asian_min_line_coverage:
        return _pass("asian_handicap", mode, "insufficient_same_line_coverage")
    selected = [row for row in latest if float(row["normalized_line"]) == line]
    probabilities = {
        row["provider_id"]: _probabilities(row["normalized_prices"], ("home", "away"), "hong_kong")
        for row in selected
    }
    provider_winners = [max(values, key=values.get) for values in probabilities.values()]
    votes = Counter(provider_winners)
    winner, agreeing = sorted(votes.items(), key=lambda item: (-item[1], item[0]))[0]
    medians = {key: median(values[key] for values in probabilities.values()) for key in ("home", "away")}
    ordered = sorted(medians, key=lambda key: (-medians[key], key))
    gap = medians[ordered[0]] - medians[ordered[1]]
    if agreeing < policy.asian_min_agreeing_providers or winner != ordered[0]:
        return _pass("asian_handicap", mode, "provider_direction_has_no_majority")
    if gap < policy.directional_probability_gap_min:
        return _pass("asian_handicap", mode, "insufficient_directional_separation")
    ranking = ["home_handicap" if item == "home" else "away_handicap" for item in ordered]
    degradation = [] if positioned else ["theoretical_positioning_unavailable"]
    return MarketAssessmentV1(
        market="asian_handicap", status="degraded" if degradation else "assessed", input_mode=mode,
        ranking=ranking, line=line, provider_ids=sorted(probabilities),
        observation_ids=[row["observation_id"] for row in selected],
        evidence_refs=[f"market-observation:{row['observation_id']}" for row in selected],
        degradation_reasons=degradation,
        metrics={"median_probabilities": medians, "top_gap": gap, "line_coverage": count / len(latest), "agreeing_providers": agreeing},
    )


def _purity(values: list[float]) -> float | None:
    changes = [right - left for left, right in zip(values, values[1:])]
    nonzero = [change for change in changes if change]
    if not changes:
        return None
    if not nonzero:
        return 1.0
    direction = 1 if sum(nonzero) >= 0 else -1
    return sum(change * direction > 0 for change in nonzero) / len(nonzero)


def _total_goals(rows: list[dict[str, Any]], mode: str, config: CalibrationConfig,
                 conflicts: list[str]) -> MarketAssessmentV1:
    if conflicts:
        return _pass("total_goals", mode, "unresolved_market_conflicts", conflicts=conflicts)
    policy = config.total_goals_evidence_policy
    draft_policy = config.formal_draft_policy
    assert policy is not None
    assert draft_policy is not None
    groups: dict[tuple[str, float, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("provider_id") in draft_policy.eligible_provider_ids and row.get("normalized_line") is not None:
            groups[(row["provider_id"], float(row["normalized_line"]), row["odds_format"])].append(row)
    qualified: list[tuple[str, float, str, str, list[dict[str, Any]], float]] = []
    for (provider, line, odds_format), values in groups.items():
        values.sort(
            key=lambda item: (datetime.fromisoformat(str(item["observed_at"])), item["observation_id"])
        )
        if len(values) < policy.anchor_min_exact_nodes:
            continue
        for side in ("over", "under"):
            prices = [float(item["normalized_prices"][side]) for item in values]
            change = prices[-1] - prices[0]
            purity = _purity(prices)
            if change <= -policy.target_water_fall_min and purity is not None and purity >= policy.trend_purity_min:
                qualified.append((provider, line, odds_format, side, values, purity))
    sides = {item[3] for item in qualified}
    if len(sides) > 1:
        return _pass("total_goals", mode, "qualified_opposite_series")
    if not qualified:
        return _pass("total_goals", mode, "insufficient_exact_series")
    side = qualified[0][3]
    comparable: dict[tuple[float, str], list[tuple[str, float, str, str, list[dict[str, Any]], float]]] = defaultdict(list)
    for item in qualified:
        comparable[(item[1], item[2])].append(item)
    confirmed = next((items for _, items in sorted(comparable.items()) if len({item[0] for item in items}) >= 2), None)
    if confirmed is None:
        return _pass("total_goals", mode, "insufficient_independent_exact_series")
    observations = [row for item in confirmed for row in item[4]]
    return MarketAssessmentV1(
        market="total_goals", status="assessed", input_mode=mode, ranking=[side], line=confirmed[0][1],
        provider_ids=sorted({item[0] for item in confirmed}),
        observation_ids=[row["observation_id"] for row in observations],
        evidence_refs=[f"market-observation:{row['observation_id']}" for row in observations],
        metrics={"trend_purity_min": min(item[5] for item in confirmed)},
    )


def _observation_hash(rows: dict[str, list[dict[str, Any]]]) -> str:
    return sha256_json({market: values for market, values in sorted(rows.items())})


def _active_fact_bundle(root: Path, match_id: str, cutoff: datetime) -> PrematchFactBundleV1 | None:
    events = [event for event in read_ledger(root / FACT_LEDGER) if event.payload.get("match_id") == match_id]
    for event in reversed(events):
        path = root / str(event.payload["bundle_path"])
        bundle = PrematchFactBundleV1.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        if _hash_model(bundle, "bundle_sha256") != bundle.bundle_sha256 or event.payload.get("bundle_sha256") != bundle.bundle_sha256:
            raise ValueError(f"FactBundle 内容哈希或导入事件绑定不一致：{path}")
        if bundle.as_of == cutoff:
            return bundle
    return None


def import_fact_bundle(root: Path, match_path: Path, source: Path) -> tuple[Path, PrematchFactBundleV1]:
    document = MatchDocument.load(match_path)
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    if receipt is None:
        raise ValueError("请先运行 agent start 生成 AnalysisReceipt")
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    raw.setdefault("schema_version", 1)
    raw.setdefault("bundle_sha256", "0" * 64)
    provisional = PrematchFactBundleV1.model_validate(raw)
    if provisional.match_id != document.metadata.match_id or provisional.as_of != receipt.as_of:
        raise ValueError("FactBundle 必须绑定当前比赛和 AnalysisReceipt as_of")
    if receipt.as_of >= document.metadata.kickoff_at:
        raise ValueError("FactBundle 只能在开赛前导入")
    for fact in provisional.facts:
        if fact.observed_at > receipt.as_of or fact.received_at > receipt.as_of:
            raise ValueError(f"事实晚于分析截止时间：{fact.fact_id}")
    expected = _hash_model(provisional, "bundle_sha256")
    if provisional.bundle_sha256 not in {"0" * 64, expected}:
        raise ValueError("FactBundle 内容哈希不一致")
    payload = provisional.model_dump(mode="json")
    payload["bundle_sha256"] = expected
    bundle = PrematchFactBundleV1.model_validate(payload)
    target = root / "raw" / "matches" / document.metadata.match_id / "prematch-fact-bundles" / f"{expected}.yml"
    ledger = root / FACT_LEDGER
    existing = next((event for event in read_ledger(ledger) if event.payload.get("bundle_sha256") == expected), None)
    if existing is not None:
        if not target.is_file():
            raise ValueError("FactBundle 导入事件已存在但内容文件缺失")
        stored = PrematchFactBundleV1.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
        if stored.model_dump(mode="json") != bundle.model_dump(mode="json") or _hash_model(stored, "bundle_sha256") != stored.bundle_sha256:
            raise ValueError("已导入 FactBundle 内容与事件哈希不一致")
        return target, bundle
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    with RepositoryTransaction(root, files=[target, ledger], directories=[], operation="import-prematch-facts") as transaction:
        atomic_write_text(target, yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        append_payloads(ledger, [{
            "event_type": "prematch_fact_bundle_imported", "match_id": bundle.match_id,
            "as_of": bundle.as_of.isoformat(), "bundle_sha256": expected,
            "bundle_path": target.relative_to(root).as_posix(),
        }], recorded_at=now, actor="lcz", event_id_factory=lambda item, _: f"facts:import:{bundle.match_id}:{expected}")
        transaction.commit()
    return target, bundle


def compile_draft(root: Path, match_path: Path) -> tuple[Path, Path, AnalysisDraftInputV3, DraftBuildReceiptV1]:
    document = MatchDocument.load(match_path)
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    if receipt is None or receipt.schema_version != 8 or receipt.calibration_contract_version != 8:
        raise ValueError("agent build-draft 仅适用于 Contract 8 / AnalysisReceipt V8")
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if now >= document.metadata.kickoff_at or receipt.as_of >= document.metadata.kickoff_at or document.metadata.score is not None:
        raise ValueError("比赛已开赛或赛果已知，禁止构建赛前草稿")
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ValueError("只有 draft/tracking 比赛可以构建草稿")
    ruleset = load_ruleset(root, f"{receipt.ruleset_id}@{receipt.ruleset_version}", allow_proposal=receipt.ruleset_origin == "proposal")
    config = CalibrationConfig.model_validate(ruleset.calibration_config or {})
    if config.schema_version != 8:
        raise ValueError("Contract 8 必须使用 calibration schema 8")
    rows = {
        market: prediction_eligible_market_observations(root, match_id=document.metadata.match_id, market=ledger_market, cutoff=receipt.as_of)
        for market, ledger_market in (("one_x_two", "european_odds"), ("asian_handicap", "asian_handicap"), ("total_goals", "total_goals"))
    }
    conflicts = {
        market: sorted(observation_conflict_ids(
            root, match_id=document.metadata.match_id, market=ledger_market,
            cutoff=receipt.as_of, prediction_eligible_only=True,
        ))
        for market, ledger_market in (("one_x_two", "european_odds"), ("asian_handicap", "asian_handicap"), ("total_goals", "total_goals"))
    }
    bundle = _active_fact_bundle(root, document.metadata.match_id, receipt.as_of)
    positioned = _has_theoretical_positioning(bundle, receipt.as_of)
    mode = "full_context" if positioned else "market_only"
    identity_valid = RecordIntegrity(document.metadata.record_integrity) == RecordIntegrity.COMPLETE
    gate = FormalAnalysisGateV2(
        lifecycle_status="ready" if identity_valid else "pass",
        identity_status="valid" if identity_valid else "conflicted",
        cutoff_status="valid",
        reasons=[] if identity_valid else ["record_integrity_incomplete"],
        evidence_refs=[f"analysis-receipt:{sha256_json(receipt.model_dump(mode='json'))}"],
    )
    assessments: dict[str, MarketAssessmentV1] = {
        "one_x_two": _one_x_two(rows["one_x_two"], mode, config, conflicts["one_x_two"], positioned),
        "asian_handicap": _asian(rows["asian_handicap"], mode, config, conflicts["asian_handicap"], positioned),
        "fixed_handicap_1x2": _pass("fixed_handicap_1x2", mode, "no_independent_structured_market"),
        "total_goals": _total_goals(rows["total_goals"], mode, config, conflicts["total_goals"]),
        "score": _pass("score", mode, "no_released_score_rule"),
    }
    one = assessments["one_x_two"]
    asian = assessments["asian_handicap"]
    if one.status != "pass" and asian.status != "pass":
        divergence = (one.ranking[0] == "home" and asian.ranking[0] == "away_handicap") or (one.ranking[0] == "away" and asian.ranking[0] == "home_handicap")
        if divergence:
            for item in (one, asian):
                item.status = "degraded"
                item.degradation_reasons = sorted(set([*item.degradation_reasons, "unexplained_asian_european_divergence"]))
    if gate.lifecycle_status == "pass":
        assessments = {market: _pass(market, mode, "global_formal_gate_failed") for market in MARKETS}
    observation_hash = _observation_hash(rows)
    receipt_hash = sha256_json(receipt.model_dump(mode="json"))
    hypotheses = {
        market: {
            "supporting_hypothesis": "冻结证据支持当前确定性市场排序。",
            "counter_hypothesis": "机构分歧或新增赛前证据可能削弱当前排序。",
            "invalidation_condition": "输入哈希、冲突状态或截止时间发生变化。",
        }
        for market in MARKETS
    }
    raw = {
        "schema_version": 3, "match_id": document.metadata.match_id, "as_of": receipt.as_of.isoformat(),
        "analysis_input_mode": mode, "compiler_version": COMPILER_VERSION,
        "calibration_config_sha256": receipt.calibration_config_sha256,
        "analysis_receipt_sha256": receipt_hash, "market_observations_sha256": observation_hash,
        "fact_bundle_sha256": bundle.bundle_sha256 if bundle else None,
        "formal_gate": gate.model_dump(mode="json"),
        "market_assessments": {key: value.model_dump(mode="json") for key, value in assessments.items()},
        "hypotheses": hypotheses, "candidate_sha256": "0" * 64,
    }
    candidate_sha = sha256_json(raw)
    raw["candidate_sha256"] = candidate_sha
    candidate = AnalysisDraftInputV3.model_validate(raw)
    receipt_raw = {
        "schema_version": 1, "match_id": document.metadata.match_id, "built_at": now,
        "as_of": receipt.as_of, "ruleset_id": receipt.ruleset_id, "ruleset_version": receipt.ruleset_version,
        "ruleset_sha256": receipt.ruleset_sha256, "calibration_config_sha256": receipt.calibration_config_sha256,
        "analysis_receipt_sha256": receipt_hash, "market_observations_sha256": observation_hash,
        "fact_bundle_sha256": bundle.bundle_sha256 if bundle else None, "compiler_version": COMPILER_VERSION,
        "candidate_sha256": candidate_sha, "receipt_sha256": "0" * 64,
    }
    build_receipt = DraftBuildReceiptV1.model_validate(receipt_raw)
    receipt_raw["receipt_sha256"] = _hash_model(build_receipt, "receipt_sha256")
    build_receipt = DraftBuildReceiptV1.model_validate(receipt_raw)
    base = root / "raw" / "matches" / document.metadata.match_id / "analysis-draft-candidates"
    candidate_path = base / f"{candidate_sha}.yml"
    build_path = base / f"{candidate_sha}.receipt.yml"
    if candidate_path.exists() or build_path.exists():
        if not candidate_path.is_file() or not build_path.is_file():
            raise ValueError("草稿候选产物不完整，拒绝覆盖；请先审计事务恢复记录")
        stored_candidate = AnalysisDraftInputV3.model_validate(
            yaml.safe_load(candidate_path.read_text(encoding="utf-8")) or {}
        )
        stored_receipt = DraftBuildReceiptV1.model_validate(
            yaml.safe_load(build_path.read_text(encoding="utf-8")) or {}
        )
        if stored_candidate.model_dump(mode="json") != candidate.model_dump(mode="json"):
            raise ValueError("内容寻址草稿候选与当前确定性结果不一致")
        if _hash_model(stored_receipt, "receipt_sha256") != stored_receipt.receipt_sha256:
            raise ValueError("草稿构建回执内容哈希不一致")
        if (
            stored_receipt.candidate_sha256 != candidate_sha
            or stored_receipt.analysis_receipt_sha256 != receipt_hash
            or stored_receipt.market_observations_sha256 != observation_hash
            or stored_receipt.fact_bundle_sha256 != (bundle.bundle_sha256 if bundle else None)
        ):
            raise ValueError("草稿构建回执未绑定当前候选输入")
        return candidate_path, build_path, stored_candidate, stored_receipt
    with RepositoryTransaction(root, files=[candidate_path, build_path], directories=[], operation="build-formal-draft") as transaction:
        atomic_write_text(candidate_path, yaml.safe_dump(candidate.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        atomic_write_text(build_path, yaml.safe_dump(build_receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        transaction.commit()
    return candidate_path, build_path, candidate, build_receipt


def accept_draft(root: Path, match_path: Path, candidate_sha: str, approved_by: str) -> tuple[Path, Path, DraftAcceptanceReceiptV1]:
    if approved_by != "lcz":
        raise ValueError("正式草稿候选只能由 lcz 确认")
    document = MatchDocument.load(match_path)
    candidate_path = root / "raw" / "matches" / document.metadata.match_id / "analysis-draft-candidates" / f"{candidate_sha}.yml"
    if not candidate_path.is_file():
        raise ValueError("草稿候选不存在")
    candidate = AnalysisDraftInputV3.model_validate(yaml.safe_load(candidate_path.read_text(encoding="utf-8")) or {})
    _, _, current, _ = compile_draft(root, match_path)
    if current.candidate_sha256 != candidate.candidate_sha256 or candidate.candidate_sha256 != candidate_sha:
        raise ValueError("草稿候选已过期；请重新运行 agent build-draft")
    target = root / "raw" / "matches" / document.metadata.match_id / "analysis-draft-input.yml"
    acceptance_path = target.with_name("analysis-draft-acceptance.yml")
    if target.exists() or acceptance_path.exists():
        if not target.is_file() or not acceptance_path.is_file():
            raise ValueError("正式草稿接受产物不完整，拒绝覆盖；请先审计事务恢复记录")
        stored_draft = AnalysisDraftInputV3.model_validate(
            yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        )
        stored_acceptance = DraftAcceptanceReceiptV1.model_validate(
            yaml.safe_load(acceptance_path.read_text(encoding="utf-8")) or {}
        )
        if stored_draft.model_dump(mode="json") != candidate.model_dump(mode="json"):
            raise ValueError("比赛已接受另一份正式草稿候选")
        if _hash_model(stored_acceptance, "receipt_sha256") != stored_acceptance.receipt_sha256:
            raise ValueError("正式草稿接受回执内容哈希不一致")
        if (
            stored_acceptance.candidate_sha256 != candidate_sha
            or stored_acceptance.draft_input_sha256 != sha256_json(candidate.model_dump(mode="json"))
            or stored_acceptance.approved_by != "lcz"
        ):
            raise ValueError("正式草稿接受回执未绑定当前候选")
        return target, acceptance_path, stored_acceptance
    now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
    if now >= document.metadata.kickoff_at:
        raise ValueError("比赛已开赛，禁止接受赛前草稿")
    draft_hash = sha256_json(candidate.model_dump(mode="json"))
    raw = {
        "schema_version": 1, "match_id": document.metadata.match_id,
        "candidate_sha256": candidate_sha, "accepted_at": now, "approved_by": "lcz",
        "draft_input_sha256": draft_hash, "receipt_sha256": "0" * 64,
    }
    acceptance = DraftAcceptanceReceiptV1.model_validate(raw)
    raw["receipt_sha256"] = _hash_model(acceptance, "receipt_sha256")
    acceptance = DraftAcceptanceReceiptV1.model_validate(raw)
    with RepositoryTransaction(root, files=[target, acceptance_path], directories=[], operation="accept-formal-draft") as transaction:
        atomic_write_text(target, yaml.safe_dump(candidate.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        atomic_write_text(acceptance_path, yaml.safe_dump(acceptance.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
        transaction.commit()
    return target, acceptance_path, acceptance


def validate_draft_acceptance(
    draft: AnalysisDraftInputV3, acceptance: DraftAcceptanceReceiptV1
) -> list[str]:
    errors: list[str] = []
    if _hash_model(acceptance, "receipt_sha256") != acceptance.receipt_sha256:
        errors.append("Contract 8 草稿人工确认回执内容哈希不一致")
    if acceptance.match_id != draft.match_id:
        errors.append("Contract 8 草稿人工确认回执比赛身份不一致")
    if acceptance.candidate_sha256 != draft.candidate_sha256:
        errors.append("Contract 8 草稿人工确认回执未绑定候选哈希")
    if acceptance.draft_input_sha256 != sha256_json(draft.model_dump(mode="json")):
        errors.append("Contract 8 草稿人工确认回执未绑定 Draft Input 内容")
    if acceptance.approved_by != "lcz":
        errors.append("Contract 8 草稿人工确认者必须为 lcz")
    return errors


def render_deterministic_analysis_v3(
    document: MatchDocument,
    receipt: AnalysisReceipt,
    draft: AnalysisDraftInputV3,
    bundle: EvaluationBundleV3,
    config: CalibrationConfig,
) -> str:
    from .agent_workflow import AnalysisTrace, render_analysis_trace
    from .case_retrieval import parse_case_receipt
    from .scenarios import parse_scenarios

    reasoning = document.sections["prematch-reasoning"]
    scenarios = parse_scenarios(reasoning, required=True)
    cases = parse_case_receipt(reasoning, required=True)
    assert scenarios is not None and cases is not None
    loaded = [*receipt.required_documents, *receipt.conditional_documents]
    applied = [item.document_id for item in receipt.required_documents]
    if not applied:
        raise ValueError("Contract 8 确定性正文缺少可采用的必需规则文档")
    excluded = [
        {"rule_id": item.document_id, "reason": "确定性市场编译未触发该条件文档"}
        for item in receipt.conditional_documents
    ]
    evidence_refs = sorted({
        ref
        for assessment in draft.market_assessments.values()
        for ref in assessment.evidence_refs
    })
    source_refs = evidence_refs or [f"formal-draft-candidate:{draft.candidate_sha256}"]
    triggered = sorted(item.rule_id for item in bundle.events if item.triggered)
    trace = AnalysisTrace.model_validate({
        "schema_version": 2,
        "ruleset_id": receipt.ruleset_id,
        "ruleset_version": receipt.ruleset_version,
        "data_cutoff_at": receipt.as_of,
        "applied_rule_ids": applied,
        "excluded_rules": excluded,
        "source_refs": source_refs,
        "scenario_instance_ids": [item.scenario_instance_id for item in scenarios.instances],
        "case_ids": [item.case_id for item in cases.selected_cases],
        "ruleset_origin": receipt.ruleset_origin,
        "deterministic_rule_ids": [item.rule_id for item in config.rules],
        "disposition_rule_ids": triggered,
        "control_rule_ids": [item.rule_id for item in config.rules if item.effect == "control"],
        "profile_chain": bundle.profile_chain,
        "evaluation_bundle_sha256": bundle.bundle_sha256,
    })

    def describe(market: str) -> str:
        item = draft.market_assessments[market]
        if item.status == "pass":
            return "pass（" + "；".join(item.pass_reasons) + "）"
        ranking = " > ".join(item.ranking)
        suffix = "；降级原因：" + "；".join(item.degradation_reasons) if item.degradation_reasons else ""
        return f"{item.status}；排序：{ranking}{suffix}"

    body = "\n\n".join([
        "### 一、澳盘时序梳理与盘路定性\n\n"
        f"亚洲让球市场：{describe('asian_handicap')}。仅使用截止时间前、同盘口档位、香港盘格式且预测合格的结构化观测。",
        "### 二、胜平负欧赔走势\n\n"
        f"胜平负市场：{describe('one_x_two')}。各机构赔率先独立去除返还率，再按跨机构中位隐含概率和多数方向编译。",
        "### 三、凯利指数交叉验证\n\n"
        "凯利仅由冻结校准规则独立求值；未满足阈值或缺少可追溯输入时不改变确定性市场排序。",
        "### 四、大小球辅助参考\n\n"
        f"总进球市场：{describe('total_goals')}。不跨机构、盘口档位或赔率格式拼接趋势。比分市场：{describe('score')}。",
        "### 五、综合权重推演\n\n"
        f"- 胜平负优先级：{describe('one_x_two')}\n"
        f"- 亚洲让球优先级：{describe('asian_handicap')}\n"
        f"- 固定让球胜平负优先级：{describe('fixed_handicap_1x2')}\n"
        f"- 总进球：{describe('total_goals')}\n"
        f"- 比分权重：{describe('score')}\n"
        f"- 校准规则处置：触发 {len(triggered)} 条，均以冻结 disposition 为准。",
        "### 六、后市观测清单\n\n"
        "- 正向强化信号：仅接受截止时间前进入同一内容哈希闭包的结构化观测。\n"
        "- 风险预警信号：任一输入变化、来源冲突或候选过期均使当前草稿失效。",
        render_analysis_trace(trace),
    ])
    if {item.document_id for item in loaded} != set(applied) | {item["rule_id"] for item in excluded}:
        raise ValueError("Contract 8 确定性正文未处置全部加载规则文档")
    return set_analysis_content(reasoning, body)


def evaluate_draft_v3(
    root: Path,
    match_path: Path,
    draft: AnalysisDraftInputV3,
    receipt: AnalysisReceipt,
    config: CalibrationConfig,
) -> EvaluationBundleV3:
    document = MatchDocument.load(match_path)
    _, _, current, _ = compile_draft(root, match_path)
    if current.model_dump(mode="json") != draft.model_dump(mode="json"):
        raise ValueError("Contract 8 Draft Input 与当前截止前观测、事实或配置不一致")
    features = feature_snapshot(document.metadata, receipt.as_of)
    profile, chain, applicable = resolve_profile(config, document.metadata.competition_code)
    events: list[MachineRuleEvent] = []
    for rule in config.rules:
        target_market = rule.target_market or "handicap"
        target_selection = rule.target_selection or "pass"
        if rule.rule_id not in applicable:
            events.append(MachineRuleEvent(
                rule_id=rule.rule_id, triggered=False, not_triggered_reason="not_applicable",
                applicability="not_applicable", effect=rule.effect, target_market=target_market,
                target_selection=target_selection,
            ))
            continue
        triggered, reason, observations = evaluate(rule.rule_id, features, rule.thresholds)
        ids = _source_ids(features, rule.rule_id)
        events.append(MachineRuleEvent(
            rule_id=rule.rule_id, triggered=triggered,
            not_triggered_reason=None if triggered else reason,
            applicability="applicable", effect=rule.effect, target_market=target_market,
            target_selection=target_selection, source_snapshot_ids=ids if triggered else [],
            source_provider_ids=["macau"] if triggered and ids else [],
            correlation_keys=["macau:odds-kelly"] if triggered and "kelly" in rule.rule_id else [],
            threshold_observations=observations,
            supporting_evidence=[f"feature:{name}" for name in rule.feature_ids] if triggered else [],
            counter_evidence=["需要人工处置并保留反证"] if triggered else [],
        ))
    draft_hash = stable_sha256(draft.model_dump(mode="json"))
    feature_hash = stable_sha256(features)
    raw = {
        "schema_version": 3, "match_id": document.metadata.match_id,
        "cutoff_at": receipt.as_of, "ruleset_version": receipt.ruleset_version,
        "calibration_config_sha256": receipt.calibration_config_sha256,
        "draft_input_sha256": draft_hash,
        "market_observations_sha256": draft.market_observations_sha256,
        "feature_snapshot_sha256": feature_hash, "profile_chain": chain,
        "competition_profile": profile, "formal_gate": draft.formal_gate.model_dump(mode="json"),
        "market_assessments": {key: value.model_dump(mode="json") for key, value in draft.market_assessments.items()},
        "features": features, "events": [item.model_dump(mode="json") for item in events],
        "bundle_sha256": "0" * 64,
    }
    provisional = EvaluationBundleV3.model_validate(raw)
    raw["bundle_sha256"] = _hash_model(provisional, "bundle_sha256")
    return EvaluationBundleV3.model_validate(raw)


def build_outlook_v6(
    draft: AnalysisDraftInputV3,
    bundle: EvaluationBundleV3,
    dispositions: list[ReasoningDisposition],
) -> AnalysisOutlook:
    by_id = {item.rule_id: item for item in dispositions}
    if len(by_id) != len(dispositions):
        raise ValueError("同一规则不得重复处置")
    triggered = {item.rule_id for item in bundle.events if item.triggered}
    if set(by_id) - triggered:
        raise ValueError("只能处置已触发规则")
    missing = triggered - set(by_id)
    if missing:
        raise ValueError("触发规则缺少人工处置：" + ", ".join(sorted(missing)))
    baseline = {
        market: list(item.ranking)
        for market, item in draft.market_assessments.items()
        if item.status != "pass" and len(item.ranking) >= 2
    }
    ranking_events: list[dict[str, Any]] = []
    calibration_events: list[CalibrationEvent] = []
    source_dimension_by_market = {
        "one_x_two": ["european_odds"],
        "asian_handicap": ["asian_handicap_market"],
        "fixed_handicap_1x2": ["asian_handicap_market"],
        "total_goals": ["total_goals_market"],
    }
    for event in bundle.events:
        decision = by_id.get(event.rule_id)
        ranking = list(baseline.get(event.target_market, []))
        proposed = list(ranking)
        if event.triggered and event.effect == "ranking" and event.target_selection in proposed:
            index = proposed.index(event.target_selection)
            if index > 1:
                proposed[index - 1], proposed[index] = proposed[index], proposed[index - 1]
            if decision and decision.disposition.disposition == "adopted":
                ranking_events.append({**event.model_dump(mode="json"), "disposition": "adopted"})
        calibration_events.append(CalibrationEvent.model_validate({
            "rule_id": event.rule_id, "contract_version": 8, "triggered": event.triggered,
            "not_triggered_reason": event.not_triggered_reason, "applicability": event.applicability,
            "effect": event.effect, "target_market": event.target_market,
            "target_selection": event.target_selection,
            "source_dimensions": source_dimension_by_market.get(event.target_market, []) if event.triggered else [],
            "source_provider_ids": event.source_provider_ids, "source_snapshot_ids": event.source_snapshot_ids,
            "correlation_keys": event.correlation_keys, "threshold_observations": event.threshold_observations,
            "before_ranking": ranking, "proposed_ranking": proposed,
            "final_ranking": proposed if decision and decision.disposition.disposition == "adopted" else ranking,
            "adjustment_level": 1 if event.triggered and event.effect == "ranking" and proposed != ranking else 0,
            "supporting_evidence": event.supporting_evidence, "counter_evidence": event.counter_evidence,
            "decision": decision.disposition.model_dump(mode="json") if decision else None,
        }))
    final = apply_governed_rankings(baseline, ranking_events, adopted_only=True)
    assessments = {key: value.model_dump(mode="json") for key, value in draft.market_assessments.items()}
    statuses = {key: value.status for key, value in draft.market_assessments.items()}
    pass_reasons = {key: value.pass_reasons for key, value in draft.market_assessments.items() if value.status == "pass"}
    all_pass = all(value == "pass" for value in statuses.values())
    missing_reasons = sorted({
        reason for item in draft.market_assessments.values()
        for reason in [*item.pass_reasons, *item.degradation_reasons]
    })
    one = draft.market_assessments["one_x_two"]
    asian = draft.market_assessments["asian_handicap"]
    total = draft.market_assessments["total_goals"]
    total_signal = None
    if total.status != "pass":
        total_signal = {
            "side": total.ranking[0], "provider_ids": total.provider_ids,
            "observation_ids": total.observation_ids, "line": total.line,
        }
    payload: dict[str, Any] = {
        "schema_version": 6, "data_mode": "pass" if all_pass else "degraded",
        "missing_reasons": [] if all_pass else missing_reasons,
        "pass_reasons": missing_reasons if all_pass else [],
        "competition_profile": bundle.competition_profile, "calibration_contract_version": 8,
        "analysis_input_mode": draft.analysis_input_mode, "profile_chain": bundle.profile_chain,
        "evaluation_bundle_sha256": bundle.bundle_sha256,
        "formal_gate": draft.formal_gate.model_dump(mode="json"), "market_assessments": assessments,
        "market_statuses": statuses, "market_pass_reasons": pass_reasons,
        "calibration_events": [item.model_dump(mode="json") for item in calibration_events],
        "experimental_rankings": baseline, "final_rankings": final,
        "score_candidates": [], "total_goals_candidate_pool": [], "score_candidate_pool": [],
        "outcome_risk_pool": [], "total_goals_signal": total_signal,
    }
    if one.status != "pass":
        payload["one_x_two"] = {"choices": final["one_x_two"][:2]}
    if asian.status != "pass":
        payload["asian_handicap"] = {
            "line_display": str(asian.line), "home_line": asian.line,
            "ranking": {"choices": final["asian_handicap"]},
        }
    return AnalysisOutlook.model_validate(payload)


def validate_outlook_bundle_v3(
    root: Path,
    match_path: Path,
    receipt: AnalysisReceipt,
    config: CalibrationConfig,
    outlook: AnalysisOutlook,
) -> list[str]:
    document = MatchDocument.load(match_path)
    base = root / "raw" / "matches" / document.metadata.match_id
    draft_path = base / "analysis-draft-input.yml"
    acceptance_path = base / "analysis-draft-acceptance.yml"
    dispositions_path = base / "reasoning-dispositions.yml"
    bundle_path = base / f"rule-evaluation-{outlook.evaluation_bundle_sha256}.yml"
    try:
        draft = AnalysisDraftInputV3.model_validate(yaml.safe_load(draft_path.read_text(encoding="utf-8")) or {})
        acceptance = DraftAcceptanceReceiptV1.model_validate(
            yaml.safe_load(acceptance_path.read_text(encoding="utf-8")) or {}
        )
        acceptance_errors = validate_draft_acceptance(draft, acceptance)
        if acceptance_errors:
            return acceptance_errors
        actual = EvaluationBundleV3.model_validate(yaml.safe_load(bundle_path.read_text(encoding="utf-8")) or {})
        expected = evaluate_draft_v3(root, match_path, draft, receipt, config)
        if actual.model_dump(mode="json") != expected.model_dump(mode="json"):
            return ["Contract 8 评估 Bundle 与当前冻结输入不一致"]
        if outlook.evaluation_bundle_sha256 != expected.bundle_sha256:
            return ["AnalysisOutlook V6 未绑定当前 Contract 8 Bundle"]
        dispositions_raw = yaml.safe_load(dispositions_path.read_text(encoding="utf-8")) or {}
        records = dispositions_raw.get("dispositions", []) if isinstance(dispositions_raw, dict) else dispositions_raw
        dispositions = [ReasoningDisposition.model_validate(item) for item in records]
        rebuilt = build_outlook_v6(draft, expected, dispositions)
        if rebuilt.model_dump(mode="json") != outlook.model_dump(mode="json"):
            return ["AnalysisOutlook V6 与冻结 Draft、Bundle 或 dispositions 不一致"]
    except Exception as exc:
        return [str(exc)]
    return []
