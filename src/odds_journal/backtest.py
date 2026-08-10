from __future__ import annotations

import hashlib
import json
import random
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
from .settlement import score_candidate_hit, settle_asian_handicap, settle_total_goals, total_goals_range_hit
from .rule_engine.evaluation import AnalysisDraftInput, EvaluationBundle, ReasoningDisposition, build_outlook
from .rule_engine.evaluation_v5 import AnalysisDraftInputV2, EvaluationBundleV2, build_outlook_v5
from .formal_draft import AnalysisDraftInputV3, EvaluationBundleV3, build_outlook_v6


MARKETS = ("asian_handicap", "european_odds", "kelly_index", "total_goals", "score")
PHASES = ("opening", "mid", "late")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class BacktestMarketEligibilityV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market: Literal["asian_handicap", "european_odds", "kelly_index", "total_goals", "score"]
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
    frozen_draft_path: str | None = None
    frozen_draft_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    frozen_dispositions_path: str | None = None
    frozen_dispositions_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    frozen_evaluation_path: str | None = None
    frozen_evaluation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


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
    status: Literal["assessed", "degraded", "pass"]
    selection: str | None = None
    frozen_decision: dict[str, Any] = Field(default_factory=dict)
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


def _write_once(path: Path, content: str, label: str) -> None:
    """Keep sealed replay stages append-only while allowing exact retries."""
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"{label} 已封存且内容不同；请创建新的 backtest_id")
        return
    atomic_write_text(path, content)


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


def _frozen_file(root: Path, path: Path) -> tuple[str | None, str | None]:
    if not path.is_file():
        return None, None
    return path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()


def build_inventory(root: Path, *, mode: Literal["historical_reproduction", "counterfactual_current_rules"], ruleset_name: str, backtest_id: str | None = None, proposal: bool = False) -> tuple[Path, BacktestDatasetManifestV1]:
    ruleset = load_ruleset(root, ruleset_name, allow_proposal=proposal)
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
            if market == "score":
                # Score candidates are frozen Outlook outputs, not an independent
                # market-observation series.  They remain separately visible and
                # never borrow a total-goals observation as their own evidence.
                market_rows.append(BacktestMarketEligibilityV1(
                    market=market, phase="late", as_of=(meta.kickoff_at - timedelta(minutes=5)).isoformat(),
                    status="partial", reasons=["derived_from_frozen_outlook_only"],
                ))
                continue
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
        base = root / "raw" / "matches" / meta.match_id
        draft_path, draft_hash = _frozen_file(root, base / "analysis-draft-input.yml")
        dispositions_path, dispositions_hash = _frozen_file(root, base / "reasoning-dispositions.yml")
        evaluation_path, evaluation_hash = (None, None)
        frozen_ruleset_mismatch = False
        if outlook_hash:
            outlook = yaml.safe_load(outlook_path.read_text(encoding="utf-8")) or {}
            bundle_hash = outlook.get("evaluation_bundle_sha256")
            if isinstance(bundle_hash, str):
                evaluation_path, evaluation_hash = _frozen_file(root, base / f"rule-evaluation-{bundle_hash}.yml")
                if evaluation_path:
                    frozen_bundle = yaml.safe_load((root / evaluation_path).read_text(encoding="utf-8")) or {}
                    frozen_ruleset_mismatch = (
                        str(frozen_bundle.get("ruleset_version"))
                        != ruleset.manifest.ruleset_version
                    )
        if frozen_ruleset_mismatch:
            outlook_hash = None
            draft_path = draft_hash = None
            dispositions_path = dispositions_hash = None
            evaluation_path = evaluation_hash = None
        frozen_inputs = (outlook_hash, draft_hash, dispositions_hash, evaluation_hash)
        reasons = (
            ["frozen_ruleset_mismatch"]
            if frozen_ruleset_mismatch
            else [] if all(frozen_inputs) else ["missing_complete_frozen_replay_inputs"]
        )
        entries.append(BacktestFixtureEligibilityV1(match_id=meta.match_id, fixture_fingerprint=fingerprint, kickoff_at=meta.kickoff_at.isoformat(), sample_relation="out_of_sample" if mode == "historical_reproduction" else "unknown", status=state, markets=market_rows, reasons=reasons, frozen_outlook_path=outlook_path.relative_to(root).as_posix() if outlook_hash else None, frozen_outlook_sha256=outlook_hash, frozen_draft_path=draft_path, frozen_draft_sha256=draft_hash, frozen_dispositions_path=dispositions_path, frozen_dispositions_sha256=dispositions_hash, frozen_evaluation_path=evaluation_path, frozen_evaluation_sha256=evaluation_hash))
    identifier = backtest_id or f"bt-{uuid4().hex[:12]}"
    raw = {"backtest_id": identifier, "mode": mode, "ruleset": ruleset_name, "ruleset_sha256": ruleset.content_sha256, "fixtures": [item.model_dump(mode="json") for item in entries]}
    manifest = _finalize(BacktestDatasetManifestV1, raw, "manifest_sha256")
    target = root / "raw/backtests" / identifier / "dataset-manifest.yml"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") != yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False):
        raise ValueError("backtest_id 已存在且 Manifest 内容不同")
    atomic_write_text(target, yaml.safe_dump(manifest.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    return target, manifest


def _load_frozen(root: Path, path: str | None, digest: str | None, label: str) -> dict[str, Any] | None:
    if path is None or digest is None:
        return None
    candidate = root / path
    if not candidate.is_file() or hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
        raise ValueError(f"冻结 {label} 缺失或哈希变化")
    value = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"冻结 {label} 顶层必须为对象")
    return value


def _reconstruct_outlook(root: Path, fixture: BacktestFixtureEligibilityV1) -> dict[str, Any] | None:
    """Rebuild an Outlook only from the manifest-bound prematch artifacts."""
    outlook = _load_frozen(root, fixture.frozen_outlook_path, fixture.frozen_outlook_sha256, "Outlook")
    draft_raw = _load_frozen(root, fixture.frozen_draft_path, fixture.frozen_draft_sha256, "Draft Input")
    dispositions_raw = _load_frozen(root, fixture.frozen_dispositions_path, fixture.frozen_dispositions_sha256, "dispositions")
    bundle_raw = _load_frozen(root, fixture.frozen_evaluation_path, fixture.frozen_evaluation_sha256, "EvaluationBundle")
    if not all((outlook, draft_raw, dispositions_raw, bundle_raw)):
        return None
    records = dispositions_raw.get("dispositions", [])
    if not isinstance(records, list):
        raise ValueError("冻结 dispositions 必须包含列表")
    dispositions = [ReasoningDisposition.model_validate(item) for item in records]
    contract = outlook.get("calibration_contract_version")
    if contract == 8:
        rebuilt = build_outlook_v6(
            AnalysisDraftInputV3.model_validate(draft_raw), EvaluationBundleV3.model_validate(bundle_raw), dispositions,
        )
    elif contract == 7:
        rebuilt = build_outlook_v5(
            AnalysisDraftInputV2.model_validate(draft_raw), EvaluationBundleV2.model_validate(bundle_raw), dispositions,
        )
    else:
        rebuilt = build_outlook(
            AnalysisDraftInput.model_validate(draft_raw), EvaluationBundle.model_validate(bundle_raw), dispositions,
        )
    value = rebuilt.model_dump(mode="json")
    # A frozen evaluation bundle is the replay feature/config boundary.  It must
    # recreate the locked decision exactly; current rules and Match postmortems
    # are intentionally never loaded here.
    comparison_keys = ["one_x_two", "asian_handicap", "total_goals", "score_candidates"]
    if contract in {7, 8}:
        comparison_keys.extend(["total_goals_signal", "market_statuses"])
    for key in comparison_keys:
        if value.get(key) != outlook.get(key):
            raise ValueError(f"冻结输入无法重建 Outlook：{fixture.match_id}:{key}")
    return value


def replay(root: Path, manifest_path: Path) -> tuple[Path, BacktestPredictionManifestV1]:
    manifest = BacktestDatasetManifestV1.model_validate(yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {})
    rows = []
    for fixture in manifest.fixtures:
        outlook = _reconstruct_outlook(root, fixture)
        for market in fixture.markets:
            selection = None
            frozen_decision: dict[str, Any] = {}
            if outlook and market.phase == "late":
                outlook_market = {
                    "european_odds": "one_x_two",
                    "asian_handicap": "asian_handicap",
                    "total_goals": "total_goals",
                    "score": "score",
                }.get(market.market)
                outlook_status = (outlook.get("market_statuses") or {}).get(outlook_market, "assessed")
                if market.market == "european_odds":
                    selection = ((outlook.get("one_x_two") or {}).get("choices") or [None])[0]
                    frozen_decision = {"selection": selection} if selection else {}
                elif market.market == "asian_handicap":
                    selection = (((outlook.get("asian_handicap") or {}).get("ranking") or {}).get("choices") or [None])[0]
                    asian = outlook.get("asian_handicap") or {}
                    frozen_decision = {"selection": selection, "home_line": asian.get("home_line")} if selection and isinstance(asian.get("home_line"), (int, float)) else {}
                elif market.market == "total_goals":
                    signal = outlook.get("total_goals_signal") or {}
                    if signal.get("side") in {"over", "under"} and isinstance(signal.get("line"), (int, float)):
                        selection = signal["side"]
                        frozen_decision = {"selection": selection, "line": signal["line"]}
                    else:
                        total = outlook.get("total_goals") or {}
                        if isinstance(total.get("minimum"), int) and isinstance(total.get("maximum"), int):
                            selection = "range"
                            frozen_decision = {"minimum": total["minimum"], "maximum": total["maximum"]}
                elif market.market == "score":
                    candidates = outlook.get("score_candidates") or []
                    if isinstance(candidates, list) and candidates and all(isinstance(item, str) for item in candidates):
                        selection = "candidates"
                        frozen_decision = {"candidates": candidates}
            # A replay is only assessed when both its frozen decision and the
            # phase-specific eligibility gate exist.  Score has no independent
            # observation line, but is explicitly marked as Outlook-derived.
            assessed = bool(selection and (market.status == "eligible" or (market.market == "score" and outlook)))
            decision_status = outlook_status if assessed and outlook_status == "degraded" else "assessed" if assessed else "pass"
            data = {"match_id": fixture.match_id, "fixture_fingerprint": fixture.fixture_fingerprint, "market": market.market, "phase": market.phase, "as_of": market.as_of, "status": decision_status, "selection": selection if assessed else None, "frozen_decision": frozen_decision if assessed else {}, "source_observation_ids": market.observation_ids, "feature_snapshot_sha256": market.feature_snapshot_sha256}
            rows.append(_finalize(DeterministicReplayPredictionV1, data, "prediction_sha256"))
    result = _finalize(BacktestPredictionManifestV1, {"dataset_manifest_sha256": manifest.manifest_sha256, "predictions": [row.model_dump(mode="json") for row in rows]}, "prediction_manifest_sha256")
    target = manifest_path.parent / "prediction-manifest.yml"
    _write_once(target, yaml.safe_dump(result.model_dump(mode="json"), allow_unicode=True, sort_keys=False), "Prediction Manifest")
    return target, result


def build_labels(root: Path, prediction_path: Path) -> tuple[Path, BacktestLabelManifestV1]:
    predictions = BacktestPredictionManifestV1.model_validate(yaml.safe_load(prediction_path.read_text(encoding="utf-8")) or {})
    labels = []
    results: dict[str, list[dict[str, Any]]] = {}
    for event in read_ledger(root / MATCH_RESULT_LEDGER) if (root / MATCH_RESULT_LEDGER).exists() else []:
        row = event.payload
        if row.get("period") == "full_time" and row.get("result_status") == "confirmed":
            results.setdefault(str(row.get("match_id")), []).append(row)
    for match_id in sorted({row.match_id for row in predictions.predictions}):
        candidates = results.get(match_id, [])
        scores = {str(item.get("score")) for item in candidates if item.get("score")}
        row = max(candidates, key=lambda item: str(item.get("observed_at", ""))) if len(scores) == 1 and candidates else None
        prediction_as_of = max(row.as_of for row in predictions.predictions if row.match_id == match_id)
        if row and row.get("score") and row.get("observed_at") and row["observed_at"] > prediction_as_of:
            labels.append({"match_id": match_id, "score": row["score"], "result_event_id": row.get("result_event_id"), "result_source_sha256": row.get("source_sha256"), "label_available_at": row["observed_at"], "status": "available"})
        else:
            reason = "conflicting_confirmed_results" if len(scores) > 1 else "result_not_confirmed_after_prediction"
            labels.append({"match_id": match_id, "status": "unavailable", "reason": reason})
    result = _finalize(BacktestLabelManifestV1, {"prediction_manifest_sha256": predictions.prediction_manifest_sha256, "labels": labels}, "label_manifest_sha256")
    target = prediction_path.parent / "label-manifest.yml"
    _write_once(target, yaml.safe_dump(result.model_dump(mode="json"), allow_unicode=True, sort_keys=False), "Label Manifest")
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
        if row.status in {"assessed", "degraded"} and label and row.market == "european_odds" and row.selection:
            home, away = (int(value) for value in str(label["score"]).split("-", 1))
            actual = "home" if home > away else "draw" if home == away else "away"
            outcome = "correct" if row.selection == actual else "incorrect"
        elif row.status in {"assessed", "degraded"} and label and row.market == "asian_handicap":
            home, away = (int(value) for value in str(label["score"]).split("-", 1))
            decision = row.frozen_decision
            line = decision.get("home_line")
            if row.selection in {"home_handicap", "away_handicap"} and isinstance(line, (int, float)):
                outcome = str(settle_asian_handicap(home, away, float(line), row.selection))
        elif row.status in {"assessed", "degraded"} and label and row.market == "total_goals":
            home, away = (int(value) for value in str(label["score"]).split("-", 1))
            decision = row.frozen_decision
            if row.selection in {"over", "under"} and isinstance(decision.get("line"), (int, float)):
                outcome = str(settle_total_goals(home, away, float(decision["line"]), row.selection))
            elif isinstance(decision.get("minimum"), int) and isinstance(decision.get("maximum"), int):
                outcome = "correct" if total_goals_range_hit(home, away, decision["minimum"], decision["maximum"]) else "incorrect"
        elif row.status in {"assessed", "degraded"} and label and row.market == "score":
            home, away = (int(value) for value in str(label["score"]).split("-", 1))
            candidates = row.frozen_decision.get("candidates")
            if isinstance(candidates, list) and all(isinstance(item, str) for item in candidates):
                outcome = "correct" if score_candidate_hit(home, away, candidates) else "incorrect"
        outcomes.append({"match_id": row.match_id, "fixture_fingerprint": row.fixture_fingerprint, "market": row.market, "phase": row.phase, "outcome": outcome})
    result = _finalize(BacktestOutcomeManifestV1, {"prediction_manifest_sha256": predictions.prediction_manifest_sha256, "label_manifest_sha256": labels.label_manifest_sha256, "outcomes": outcomes}, "outcome_manifest_sha256")
    target = prediction_path.parent / "outcome-manifest.yml"
    _write_once(target, yaml.safe_dump(result.model_dump(mode="json"), allow_unicode=True, sort_keys=False), "Outcome Manifest")
    return target, result


def report(root: Path, backtest_id: str) -> tuple[Path, dict[str, Any]]:
    base = root / "raw/backtests" / backtest_id
    outcomes = BacktestOutcomeManifestV1.model_validate(yaml.safe_load((base / "outcome-manifest.yml").read_text(encoding="utf-8")) or {})
    grouped: dict[str, dict[str, int]] = {}
    for item in outcomes.outcomes:
        bucket = grouped.setdefault(item["market"], {"evaluated": 0, "not_evaluated": 0, "correct": 0, "full_win": 0, "half_win": 0, "push": 0, "half_loss": 0, "full_loss": 0})
        if item["outcome"] == "not_evaluated":
            bucket["not_evaluated"] += 1
        else:
            bucket["evaluated"] += 1
            bucket["correct"] += int(item["outcome"] in {"correct", "full_win", "half_win"})
            if item["outcome"] in {"full_win", "half_win", "push", "half_loss", "full_loss"}:
                bucket[item["outcome"]] += 1
    # The three replay phases are views of one fixture.  The late phase is the
    # primary record; opening/mid stay descriptive and cannot triple the sample.
    late = [item for item in outcomes.outcomes if item["phase"] == "late" and item["outcome"] != "not_evaluated"]
    intervals: dict[str, dict[str, Any]] = {}
    for market in sorted({item["market"] for item in late}):
        clusters: dict[str, list[dict[str, Any]]] = {}
        for item in late:
            if item["market"] == market:
                clusters.setdefault(item["fixture_fingerprint"], []).append(item)
        cluster_scores = [int(any(item["outcome"] in {"correct", "full_win", "half_win"} for item in rows)) for rows in clusters.values()]
        if not cluster_scores:
            continue
        rng = random.Random(int(hashlib.sha256(f"{backtest_id}:{market}".encode()).hexdigest()[:16], 16))
        samples = sorted(sum(rng.choice(cluster_scores) for _ in cluster_scores) / len(cluster_scores) for _ in range(1000))
        intervals[market] = {"fixture_clusters": len(cluster_scores), "lower": samples[24], "upper": samples[974], "method": "fixture_cluster_bootstrap", "replications": 1000}
    payload = {"schema_version": 2, "backtest_id": backtest_id, "primary_phase": "late", "market_cluster_intervals": intervals, "markets": grouped, "exploratory": True, "significance_claim": "not_permitted"}
    target = root / "reports/backtest" / backtest_id / "replay-report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return target, payload
