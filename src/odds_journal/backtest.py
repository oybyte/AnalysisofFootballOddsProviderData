from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .cases import fixture_fingerprint_v2
from .ledger import atomic_write_text, read_ledger, sha256_json
from .markdown import MatchDocument
from .observations import (
    MARKET_OBSERVATION_LEDGER, MATCH_RESULT_LEDGER, market_feature_snapshot,
    observation_conflict_ids, prediction_eligible_market_observations,
)
from .paths import match_files
from .rules import load_ruleset


MARKETS = ("asian_handicap", "european_odds", "kelly_index", "total_goals")
PHASES = ("opening", "mid", "late")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class BacktestMarketEligibilityV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market: Literal["asian_handicap", "european_odds", "kelly_index", "total_goals"]
    phase: Literal["opening", "mid", "late"]
    as_of: str
    status: Literal["eligible", "partial", "ineligible"]
    observation_ids: list[str] = Field(default_factory=list)
    source_sha256s: list[str] = Field(default_factory=list)
    conflict_resolution_event_ids: list[str] = Field(default_factory=list)
    feature_snapshot_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reasons: list[str] = Field(default_factory=list)


class BacktestFixtureEligibilityV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    match_id: str
    fixture_fingerprint: str
    kickoff_at: str
    sample_relation: Literal["out_of_sample", "in_sample", "unknown"] = "unknown"
    status: Literal["eligible", "partial", "ineligible"]
    markets: list[BacktestMarketEligibilityV1]
    reasons: list[str] = Field(default_factory=list)
    frozen_outlook_path: str | None = None
    frozen_outlook_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class BacktestDatasetManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    backtest_id: str
    mode: Literal["historical_reproduction", "counterfactual_current_rules"]
    ruleset: str
    ruleset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_algorithm_version: str = "market-feature-snapshot-v2"
    fixtures: list[BacktestFixtureEligibilityV1]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeterministicReplayPredictionV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    match_id: str
    fixture_fingerprint: str
    market: str
    phase: str
    as_of: str
    status: Literal["assessed", "pass"]
    selection: str | None = None
    source_observation_ids: list[str] = Field(default_factory=list)
    feature_snapshot_sha256: str | None = None
    prediction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BacktestPredictionManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predictions: list[DeterministicReplayPredictionV1]
    prediction_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BacktestLabelManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    prediction_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    labels: list[dict[str, Any]]
    label_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BacktestOutcomeManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    prediction_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcomes: list[dict[str, Any]]
    outcome_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _finalize(model, value: dict[str, Any], key: str):
    value[key] = "0" * 64
    value[key] = _hash(value)
    return model.model_validate(value)


def _observations(root: Path, match_id: str, market: str, cutoff, mode: str) -> list[dict[str, Any]]:
    if mode == "historical_reproduction":
        return prediction_eligible_market_observations(root, match_id=match_id, market=market, cutoff=cutoff)
    conflicts = observation_conflict_ids(root, match_id=match_id, market=market)
    rows = []
    for event in read_ledger(root / MARKET_OBSERVATION_LEDGER) if (root / MARKET_OBSERVATION_LEDGER).exists() else []:
        row = event.payload
        if row.get("match_id") == match_id and row.get("market") == market and row.get("time_precision") == "exact" and row.get("retrospective_validation_eligible") == "eligible" and row.get("observed_at") and row.get("observation_id") not in conflicts:
            from datetime import datetime
            if datetime.fromisoformat(row["observed_at"]) <= cutoff:
                rows.append(row)
    return sorted(rows, key=lambda item: (item["observed_at"], item["observation_id"]))


def build_inventory(root: Path, *, mode: Literal["historical_reproduction", "counterfactual_current_rules"], ruleset_name: str, backtest_id: str | None = None) -> tuple[Path, BacktestDatasetManifestV1]:
    ruleset = load_ruleset(root, ruleset_name)
    entries: list[BacktestFixtureEligibilityV1] = []
    seen: set[str] = set()
    for path in match_files(root):
        document = MatchDocument.load(path)
        meta = document.metadata
        fingerprint = fixture_fingerprint_v2(meta.competition_code, meta.home_team_id, meta.away_team_id, meta.kickoff_at)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        market_rows: list[BacktestMarketEligibilityV1] = []
        for market in MARKETS:
            all_rows = _observations(root, meta.match_id, market, meta.kickoff_at, mode)
            opening_at = __import__("datetime").datetime.fromisoformat(all_rows[0]["observed_at"]) if all_rows else None
            late_at = meta.kickoff_at - timedelta(minutes=5)
            midpoint = opening_at + (late_at - opening_at) / 2 if opening_at and opening_at < late_at else None
            anchors = {"opening": opening_at, "mid": midpoint, "late": late_at}
            for phase, anchor in anchors.items():
                candidates = [row for row in all_rows if anchor and __import__("datetime").datetime.fromisoformat(row["observed_at"]) <= anchor]
                status = "eligible" if candidates else ("partial" if all_rows else "ineligible")
                reason = [] if candidates else (["no_observation_before_anchor"] if all_rows else ["no_eligible_exact_observation"])
                feature = market_feature_snapshot(root, meta.match_id, anchor) if candidates and anchor else None
                market_rows.append(BacktestMarketEligibilityV1(
                    market=market, phase=phase, as_of=(anchor or meta.kickoff_at).isoformat(), status=status,
                    observation_ids=[row["observation_id"] for row in candidates], source_sha256s=sorted({row.get("source_sha256", "") for row in candidates if row.get("source_sha256")}),
                    feature_snapshot_sha256=feature["feature_snapshot_sha256"] if feature else None, reasons=reason,
                ))
        state = "eligible" if any(row.status == "eligible" for row in market_rows) else "partial" if any(row.status == "partial" for row in market_rows) else "ineligible"
        outlook_path = root / "raw" / "matches" / meta.match_id / "analysis-outlook.yml"
        outlook_hash = hashlib.sha256(outlook_path.read_bytes()).hexdigest() if outlook_path.is_file() else None
        reasons = [] if outlook_hash else ["missing_frozen_rule_outlook"]
        entries.append(BacktestFixtureEligibilityV1(match_id=meta.match_id, fixture_fingerprint=fingerprint, kickoff_at=meta.kickoff_at.isoformat(), sample_relation="out_of_sample" if mode == "historical_reproduction" else "unknown", status=state, markets=market_rows, reasons=reasons, frozen_outlook_path=outlook_path.relative_to(root).as_posix() if outlook_hash else None, frozen_outlook_sha256=outlook_hash))
    identifier = backtest_id or f"bt-{uuid4().hex[:12]}"
    raw = {"backtest_id": identifier, "mode": mode, "ruleset": ruleset_name, "ruleset_sha256": ruleset.content_sha256, "fixtures": [item.model_dump(mode="json") for item in entries]}
    manifest = _finalize(BacktestDatasetManifestV1, raw, "manifest_sha256")
    target = root / "raw/backtests" / identifier / "dataset-manifest.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") != yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False):
        raise ValueError("backtest_id 已存在且 Manifest 内容不同")
    atomic_write_text(target, yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    return target, manifest


def replay(root: Path, manifest_path: Path) -> tuple[Path, BacktestPredictionManifestV1]:
    manifest = BacktestDatasetManifestV1.model_validate(yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {})
    rows = []
    for fixture in manifest.fixtures:
        outlook = None
        if fixture.frozen_outlook_path and fixture.frozen_outlook_sha256:
            path = root / fixture.frozen_outlook_path
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != fixture.frozen_outlook_sha256:
                raise ValueError(f"冻结 Outlook 缺失或哈希变化：{fixture.match_id}")
            outlook = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for market in fixture.markets:
            selection = None
            if outlook and market.phase == "late":
                if market.market == "european_odds":
                    selection = ((outlook.get("one_x_two") or {}).get("choices") or [None])[0]
                elif market.market == "asian_handicap":
                    selection = (((outlook.get("asian_handicap") or {}).get("ranking") or {}).get("choices") or [None])[0]
            data = {"match_id": fixture.match_id, "fixture_fingerprint": fixture.fixture_fingerprint, "market": market.market, "phase": market.phase, "as_of": market.as_of, "status": "assessed" if selection else "pass", "selection": selection, "source_observation_ids": market.observation_ids, "feature_snapshot_sha256": market.feature_snapshot_sha256}
            rows.append(_finalize(DeterministicReplayPredictionV1, data, "prediction_sha256"))
    result = _finalize(BacktestPredictionManifestV1, {"dataset_manifest_sha256": manifest.manifest_sha256, "predictions": [row.model_dump(mode="json") for row in rows]}, "prediction_manifest_sha256")
    target = manifest_path.parent / "prediction-manifest.yml"
    atomic_write_text(target, yaml.safe_dump(result.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    return target, result


def build_labels(root: Path, prediction_path: Path) -> tuple[Path, BacktestLabelManifestV1]:
    predictions = BacktestPredictionManifestV1.model_validate(yaml.safe_load(prediction_path.read_text(encoding="utf-8")) or {})
    labels = []
    results = {}
    for event in read_ledger(root / MATCH_RESULT_LEDGER) if (root / MATCH_RESULT_LEDGER).exists() else []:
        row = event.payload
        if row.get("period") == "full_time" and row.get("result_status") == "confirmed":
            results[row.get("match_id")] = row
    for match_id in sorted({row.match_id for row in predictions.predictions}):
        row = results.get(match_id)
        if row and row.get("score") and row.get("observed_at"):
            labels.append({"match_id": match_id, "score": row["score"], "result_event_id": row.get("result_event_id"), "result_source_sha256": row.get("source_sha256"), "label_available_at": row["observed_at"], "status": "available"})
        else:
            labels.append({"match_id": match_id, "status": "unavailable"})
    result = _finalize(BacktestLabelManifestV1, {"prediction_manifest_sha256": predictions.prediction_manifest_sha256, "labels": labels}, "label_manifest_sha256")
    target = prediction_path.parent / "label-manifest.yml"
    atomic_write_text(target, yaml.safe_dump(result.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    return target, result


def evaluate(prediction_path: Path, label_path: Path) -> tuple[Path, BacktestOutcomeManifestV1]:
    predictions = BacktestPredictionManifestV1.model_validate(yaml.safe_load(prediction_path.read_text(encoding="utf-8")) or {})
    labels = BacktestLabelManifestV1.model_validate(yaml.safe_load(label_path.read_text(encoding="utf-8")) or {})
    if labels.prediction_manifest_sha256 != predictions.prediction_manifest_sha256:
        raise ValueError("标签不属于该 Prediction Manifest")
    available = {item["match_id"]: item for item in labels.labels if item.get("status") == "available"}
    outcomes = []
    for row in predictions.predictions:
        outcome = "not_evaluated"
        label = available.get(row.match_id)
        if row.status == "assessed" and label and row.market == "european_odds" and row.selection:
            home, away = (int(value) for value in str(label["score"]).split("-", 1))
            actual = "home" if home > away else "draw" if home == away else "away"
            outcome = "correct" if row.selection == actual else "incorrect"
        outcomes.append({"match_id": row.match_id, "market": row.market, "phase": row.phase, "outcome": outcome})
    result = _finalize(BacktestOutcomeManifestV1, {"prediction_manifest_sha256": predictions.prediction_manifest_sha256, "label_manifest_sha256": labels.label_manifest_sha256, "outcomes": outcomes}, "outcome_manifest_sha256")
    target = prediction_path.parent / "outcome-manifest.yml"
    atomic_write_text(target, yaml.safe_dump(result.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    return target, result


def report(root: Path, backtest_id: str) -> tuple[Path, dict[str, Any]]:
    base = root / "raw/backtests" / backtest_id
    outcomes = BacktestOutcomeManifestV1.model_validate(yaml.safe_load((base / "outcome-manifest.yml").read_text(encoding="utf-8")) or {})
    grouped: dict[str, dict[str, int]] = {}
    for item in outcomes.outcomes:
        bucket = grouped.setdefault(item["market"], {"evaluated": 0, "not_evaluated": 0, "correct": 0})
        if item["outcome"] == "not_evaluated":
            bucket["not_evaluated"] += 1
        else:
            bucket["evaluated"] += 1
            bucket["correct"] += int(item["outcome"] == "correct")
    payload = {"schema_version": 1, "backtest_id": backtest_id, "markets": grouped, "exploratory": True}
    target = root / "reports/backtest" / backtest_id / "replay-report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return target, payload
