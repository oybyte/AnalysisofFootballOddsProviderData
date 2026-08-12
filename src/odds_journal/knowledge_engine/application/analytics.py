"""Knowledge Engine 分析统计模块。

提供迁移覆盖、检索性能、知识适用性、市场裁决、概率评分和 exposure 分层分析。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def compute_migration_coverage(
    inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算迁移覆盖率。"""
    counts: dict[str, int] = {}
    for item in inventory:
        key = item.get("disposition", "unset")
        counts[key] = counts.get(key, 0) + 1

    total = len(inventory)
    covered = total - counts.get("unset", 0)
    coverage = covered / total if total > 0 else 0

    return {
        "total_sources": total,
        "disposition_counts": counts,
        "coverage": coverage,
        "fully_covered": coverage >= 1.0,
    }


def compute_retrieval_performance(
    retrieval_logs: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算检索性能统计。"""
    if not retrieval_logs:
        return {"sample_count": 0}

    times = [log.get("retrieval_time_ms", 0) for log in retrieval_logs]
    fts5_counts = [log.get("fts5_query_count", 0) for log in retrieval_logs]
    card_counts = [
        len(log.get("retrieved_decision_cards", []))
        for log in retrieval_logs
    ]

    return {
        "sample_count": len(retrieval_logs),
        "avg_retrieval_time_ms": sum(times) / len(times) if times else 0,
        "max_retrieval_time_ms": max(times) if times else 0,
        "avg_fts5_queries": sum(fts5_counts) / len(fts5_counts) if fts5_counts else 0,
        "avg_decision_cards": sum(card_counts) / len(card_counts) if card_counts else 0,
    }


def compute_market_adjudication_stats(
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算市场裁决统计。"""
    if not outcomes:
        return {"sample_count": 0}

    market_stats: dict[str, dict[str, int]] = {}
    for outcome in outcomes:
        for market, decision in outcome.get("market_outcomes", {}).items():
            if market not in market_stats:
                market_stats[market] = {"correct": 0, "wrong": 0, "pass": 0, "total": 0}
            stats = market_stats[market]
            stats["total"] += 1
            status = decision.get("status", "")
            if status == "pass":
                stats["pass"] += 1
            elif decision.get("correct"):
                stats["correct"] += 1
            else:
                stats["wrong"] += 1

    result: dict[str, Any] = {"sample_count": len(outcomes), "markets": {}}
    for market, stats in market_stats.items():
        assessed = stats["total"] - stats["pass"]
        accuracy = stats["correct"] / assessed if assessed > 0 else 0
        result["markets"][market] = {
            **stats,
            "accuracy": accuracy,
            "pass_rate": stats["pass"] / stats["total"] if stats["total"] > 0 else 0,
        }

    return result


def compute_probability_scoring(
    forecasts: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算 Brier Score 和 Log Loss。"""
    if not forecasts or not results:
        return {"sample_count": 0}

    import math

    brier_scores: list[float] = []
    log_losses: list[float] = []

    keys = ("study_id", "match_id", "run_id", "snapshot_sha256")
    result_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for result in results:
        key = tuple(result.get(item) for item in keys)
        if any(value is None for value in key):
            raise ValueError("概率评分结果缺少 study/match/run/snapshot 联结键")
        if key in result_by_key:
            raise ValueError(f"概率评分结果重复：{key}")
        result_by_key[key] = result

    used: set[tuple[Any, ...]] = set()
    for forecast in forecasts:
        key = tuple(forecast.get(item) for item in keys)
        if any(value is None for value in key):
            raise ValueError("概率预测缺少 study/match/run/snapshot 联结键")
        result = result_by_key.get(key)
        if result is None:
            raise ValueError(f"概率预测没有匹配 Outcome：{key}")
        used.add(key)
        if not forecast.get("forecast_valid"):
            continue
        probs = forecast.get("baseline_probabilities", {})
        actual = result.get("result_one_x_two", "")
        if actual not in probs:
            continue

        # Brier Score
        brier = sum(
            (probs[k] - (1.0 if k == actual else 0.0)) ** 2
            for k in probs
        )
        brier_scores.append(brier)

        # Log Loss
        p = probs[actual]
        if p > 0:
            log_losses.append(-math.log(p))

    if len(used) != len(result_by_key):
        unmatched = sorted(set(result_by_key) - used)
        raise ValueError(f"Outcome 没有匹配预测：{unmatched[:3]}")
    return {
        "sample_count": len(brier_scores),
        "avg_brier_score": sum(brier_scores) / len(brier_scores) if brier_scores else 0,
        "avg_log_loss": sum(log_losses) / len(log_losses) if log_losses else 0,
    }


def compute_exposure_stratification(
    exposure_events: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    """计算 exposure 分层统计。"""
    exposed_ids = {e.get("match_id") for e in exposure_events}

    exposed_outcomes = [o for o in outcomes if o.get("match_id") in exposed_ids]
    blind_outcomes = [o for o in outcomes if o.get("match_id") not in exposed_ids]

    return {
        "total_outcomes": len(outcomes),
        "exposed_count": len(exposed_outcomes),
        "blind_count": len(blind_outcomes),
        "exposure_rate": len(exposed_outcomes) / len(outcomes) if outcomes else 0,
    }


def compute_capability_status(
    snapshot_sha256: str | None,
    index_sha256: str | None,
    study_count: int,
    outcome_count: int,
    ai_available: bool,
) -> dict[str, Any]:
    """计算能力状态。"""
    status = "implemented_disabled"
    details: list[str] = []

    if snapshot_sha256 and index_sha256:
        status = "shadow_ready"
        details.append("snapshot_and_index_ready")

    if status == "shadow_ready" and study_count > 0:
        status = "study_active"
        details.append(f"studies_active: {study_count}")

    if status == "study_active" and outcome_count >= 60:
        details.append(f"outcomes: {outcome_count} >= 60")
        status = "release_eligible"

    if ai_available:
        details.append("ai_available")

    return {
        "status": status,
        "details": details,
        "snapshot": snapshot_sha256,
        "index": index_sha256,
        "studies": study_count,
        "outcomes": outcome_count,
        "ai_available": ai_available,
    }
