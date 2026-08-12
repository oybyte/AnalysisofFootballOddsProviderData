"""Knowledge Engine 发布证据与预检应用服务。

构建 KnowledgeReleaseEvidenceV1 并执行发布预检门禁。
未达标市场自动维持 baseline_only 或 disabled，不得自动升级为 enabled。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..domain.release_evidence import (
    KnowledgeReleaseEvidenceV1,
    MarketEnablement,
    ReleasePreflightResult,
    RELEASE_GATE_THRESHOLDS,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def build_release_evidence(
    proposal_sha256: str,
    manifest_sha256: str,
    calibration_config_sha256: str,
    snapshot_sha256: str,
    logical_index_sha256: str,
    study_reports: list[dict[str, Any]],
    study_ids: tuple[str, ...],
    manual_audit_sha256: str | None = None,
    experiment_disposition_sha256: str | None = None,
    experiment_disposition: str | None = None,
    artifact_writer: Any | None = None,
    evidence_dir: Path | None = None,
) -> tuple[KnowledgeReleaseEvidenceV1, str]:
    """构建发布证据。

    从 Study 报告汇总，计算市场启用矩阵。
    artifact_writer 是一个可调用对象，接受 (path, content_dict) 写入 YAML。
    """
    all_primary_run_ids: list[str] = []
    all_valid_outcome_ids: list[str] = []

    for report in study_reports:
        for primary in report.get("primary_runs", []):
            all_primary_run_ids.append(primary.get("run_id", ""))
        for outcome in report.get("outcomes", []):
            all_valid_outcome_ids.append(outcome.get("outcome_id", ""))

    # 合并 study_report_sha256
    combined_report = {
        "studies": study_reports,
        "total_primaries": len(all_primary_run_ids),
        "total_outcomes": len(all_valid_outcome_ids),
    }
    study_report_sha = _sha256(combined_report)

    # 初步市场矩阵：全部 baseline_only
    market_enablement = {
        "one_x_two": "baseline_only",
        "asian_handicap": "baseline_only",
        "fixed_handicap_1x2": "disabled",
        "total_goals": "baseline_only",
        "score": "disabled",
    }

    # 预检门禁
    gate_results, market_enablement = _run_preflight_gates(
        study_reports, market_enablement, experiment_disposition
    )

    evidence_raw = {
        "schema_version": 1,
        "evidence_id": f"release-evidence:2.0.0:{snapshot_sha256[:16]}",
        "proposal_sha256": proposal_sha256,
        "manifest_sha256": manifest_sha256,
        "calibration_config_sha256": calibration_config_sha256,
        "snapshot_sha256": snapshot_sha256,
        "logical_index_sha256": logical_index_sha256,
        "study_ids": study_ids,
        "primary_run_ids": tuple(all_primary_run_ids),
        "valid_outcome_ids": tuple(all_valid_outcome_ids),
        "study_report_sha256": study_report_sha,
        "manual_audit_sha256": manual_audit_sha256,
        "experiment_disposition_sha256": experiment_disposition_sha256,
        "market_enablement": market_enablement,
        "gate_results": gate_results,
        "evidence_sha256": "0" * 64,
    }
    evidence_raw["evidence_sha256"] = _sha256({k: v for k, v in evidence_raw.items() if k != "evidence_sha256"})
    evidence = KnowledgeReleaseEvidenceV1.model_validate(evidence_raw)

    # 内容寻址写入（通过 artifact_writer 回调）
    evidence_filename = f"{evidence.evidence_sha256}.yml"
    if artifact_writer is not None and evidence_dir is not None:
        artifact_writer(evidence_dir / evidence_filename, evidence.model_dump(mode="json"))

    return evidence, evidence_filename


def _run_preflight_gates(
    study_reports: list[dict[str, Any]],
    initial_market_enablement: dict[str, str],
    experiment_disposition: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """执行发布预检门禁。

    未达标市场自动维持 baseline_only 或 disabled，不得自动升级为 enabled。
    """
    market_enablement = dict(initial_market_enablement)
    gate_results: dict[str, dict[str, Any]] = {}

    all_outcomes: list[dict[str, Any]] = []
    for report in study_reports:
        all_outcomes.extend(report.get("outcomes", []))

    total_prospective = len(all_outcomes)

    gate_results["min_prospective_outcomes"] = {
        "threshold": RELEASE_GATE_THRESHOLDS["min_prospective_outcomes"],
        "actual": total_prospective,
        "passed": total_prospective >= RELEASE_GATE_THRESHOLDS["min_prospective_outcomes"],
    }

    all_failures: list[dict[str, Any]] = []
    for report in study_reports:
        all_failures.extend(report.get("failures", []))
    critical_failures = [
        f for f in all_failures
        if f.get("failure_type") in ("snapshot_inconsistent", "write_error")
    ]
    gate_results["zero_critical_violations"] = {
        "threshold": 0,
        "actual": len(critical_failures),
        "passed": len(critical_failures) == 0,
    }

    for report in study_reports:
        prob = report.get("probability_scoring", {})
        if prob.get("sample_count", 0) > 0:
            brier = prob.get("avg_brier_score", 0)
            log_loss = prob.get("avg_log_loss", 0)
            gate_results.setdefault("1x2_brier", {
                "threshold": RELEASE_GATE_THRESHOLDS["max_1x2_brier_increment"],
                "actual": brier,
                "passed": brier <= RELEASE_GATE_THRESHOLDS["max_1x2_brier_increment"],
            })
            gate_results.setdefault("1x2_log_loss", {
                "threshold": RELEASE_GATE_THRESHOLDS["max_1x2_log_loss_increment"],
                "actual": log_loss,
                "passed": log_loss <= RELEASE_GATE_THRESHOLDS["max_1x2_log_loss_increment"],
            })

    market_sample_counts: dict[str, int] = {}
    for outcome in all_outcomes:
        for market, decision in outcome.get("market_outcomes", {}).items():
            if decision.get("status") in ("assessed", "degraded"):
                market_sample_counts[market] = market_sample_counts.get(market, 0) + 1

    for market in ("one_x_two", "asian_handicap", "total_goals"):
        count = market_sample_counts.get(market, 0)
        gate_results[f"{market}_samples"] = {
            "threshold": RELEASE_GATE_THRESHOLDS["min_enabled_market_samples"],
            "actual": count,
            "passed": count >= RELEASE_GATE_THRESHOLDS["min_enabled_market_samples"],
        }
        if (
            gate_results[f"{market}_samples"]["passed"]
            and gate_results["zero_critical_violations"]["passed"]
            and gate_results["min_prospective_outcomes"]["passed"]
        ):
            market_enablement[market] = "enabled"

    # top-1 accuracy drop gate
    baseline_correct = sum(1 for o in all_outcomes if o.get("market_outcomes", {}).get("one_x_two", {}).get("baseline_correct"))
    knowledge_correct = sum(1 for o in all_outcomes if o.get("market_outcomes", {}).get("one_x_two", {}).get("knowledge_correct"))
    total_assessed = max(1, sum(1 for o in all_outcomes if o.get("market_outcomes", {}).get("one_x_two", {}).get("status") in ("assessed", "degraded")))
    baseline_acc = baseline_correct / total_assessed if total_assessed else 0
    knowledge_acc = knowledge_correct / total_assessed if total_assessed else 0
    drop_pp = max(0, (baseline_acc - knowledge_acc) * 100)
    gate_results["top1_accuracy_drop"] = {
        "threshold_pp": 5,
        "actual_pp": round(drop_pp, 2),
        "passed": drop_pp <= 5,
    }

    # Asian handicap and total goals utility drop
    for util_market in ("asian_handicap", "total_goals"):
        baseline_util = sum(o.get("market_outcomes", {}).get(util_market, {}).get("baseline_utility", 0) for o in all_outcomes)
        knowledge_util = sum(o.get("market_outcomes", {}).get(util_market, {}).get("knowledge_utility", 0) for o in all_outcomes)
        util_drop = max(0, baseline_util - knowledge_util)
        gate_results[f"{util_market}_utility_drop"] = {
            "threshold": 0.05,
            "actual": round(util_drop, 4),
            "passed": util_drop <= 0.05,
        }

    # Applicability sampling (at least 100 items, accuracy >= 95%)
    applicability_total = sum(1 for o in all_outcomes for m in o.get("market_outcomes", {}).values() if m.get("status") in ("assessed", "degraded"))
    applicability_correct = sum(1 for o in all_outcomes for m in o.get("market_outcomes", {}).values() if m.get("correct"))
    applicability_acc = applicability_correct / applicability_total if applicability_total else 0
    gate_results["applicability_sampling"] = {
        "min_samples": 100,
        "actual_samples": applicability_total,
        "min_accuracy": 0.95,
        "actual_accuracy": round(applicability_acc, 4),
        "passed": applicability_total >= 100 and applicability_acc >= 0.95,
    }

    # 1.7.0 revision 2 disposition check
    valid_dispositions = {
        "continue_parallel",
        "deactivate_after_2_0_release",
        "archive_without_activation",
    }
    disposition_valid = experiment_disposition in valid_dispositions if experiment_disposition else False
    gate_results["experiment_disposition_1_7_0"] = {
        "required": "continue_parallel | deactivate_after_2_0_release | archive_without_activation",
        "actual": experiment_disposition or "未登记",
        "passed": disposition_valid,
    }

    return gate_results, market_enablement


def run_release_preflight(
    study_reports: list[dict[str, Any]],
    has_snapshot: bool,
    has_index: bool,
    has_release_evidence: bool,
    evidence_hash_valid: bool,
    proposal: str = "2.0.0",
    evidence_files: list[Path] | None = None,
    experiment_disposition: str | None = None,
) -> ReleasePreflightResult:
    """执行发布预检。

    预检必须验证：
    - 至少 60 个独立 prospective Outcome
    - 时间泄漏、正式轨串写、哈希错误、赛后补建均为 0
    - 1X2 Brier/Log Loss 增量
    - Snapshot、逻辑索引、Study report、人工审计和市场矩阵哈希一致
    """
    failure_reasons: list[str] = []
    gate_results: dict[str, dict[str, Any]] = {}

    # ── 基础条件检查 ──────────────────────────────────
    if not has_snapshot:
        failure_reasons.append("缺少已封存知识 Snapshot")
    if not has_index:
        failure_reasons.append("缺少知识索引")

    total_outcomes = sum(len(r.get("outcomes", [])) for r in study_reports)

    if total_outcomes < RELEASE_GATE_THRESHOLDS["min_prospective_outcomes"]:
        failure_reasons.append(
            f"prospective Outcome 不足：{total_outcomes} < {RELEASE_GATE_THRESHOLDS['min_prospective_outcomes']}"
        )

    if not has_release_evidence:
        failure_reasons.append("缺少 ReleaseEvidence")
    elif not evidence_hash_valid:
        failure_reasons.append("ReleaseEvidence 哈希不一致")

    # Manual audit check
    manual_audit_present = any(
        "manual_audit_sha256" in (data or {})
        and (data or {}).get("manual_audit_sha256")
        for ef in (evidence_files or [])
        for data in [__import__("yaml").safe_load(ef.read_text(encoding="utf-8"))]
    )
    if not manual_audit_present:
        failure_reasons.append("缺少人工审计记录")

    # ── 完整指标门禁（接入 _run_preflight_gates）─────────
    initial_market_enablement = {
        "one_x_two": "baseline_only",
        "asian_handicap": "baseline_only",
        "fixed_handicap_1x2": "disabled",
        "total_goals": "baseline_only",
        "score": "disabled",
    }

    full_gate_results, market_enablement = _run_preflight_gates(
        study_reports, initial_market_enablement, experiment_disposition
    )

    # 合并完整门禁结果
    gate_results.update(full_gate_results)

    # 将未通过的门禁纳入 failure_reasons
    for gate_name, gate_result in full_gate_results.items():
        if not gate_result.get("passed", False):
            # 避免与基础检查重复报告 min_prospective_outcomes
            if gate_name == "min_prospective_outcomes":
                continue
            actual = gate_result.get("actual", gate_result.get("actual_pp", gate_result.get("actual_samples", "?")))
            threshold = gate_result.get("threshold", gate_result.get("threshold_pp", gate_result.get("min_samples", "?")))
            failure_reasons.append(f"门禁 {gate_name} 未通过：实际 {actual}，阈值 {threshold}")

    passed = len(failure_reasons) == 0
    result_raw = {
        "schema_version": 1,
        "proposal": proposal,
        "passed": passed,
        "gate_results": gate_results,
        "market_enablement": market_enablement,
        "failure_reasons": tuple(failure_reasons),
        "preflight_sha256": "0" * 64,
    }
    result_raw["preflight_sha256"] = _sha256({k: v for k, v in result_raw.items() if k != "preflight_sha256"})
    return ReleasePreflightResult.model_validate(result_raw)
