"""Knowledge Engine 前瞻 Study 应用服务。

实现 Study 注册、运行、暴露、评估和报告。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
from ..domain.retrieval import KnowledgeRetrievalReceiptV1
from ..domain.decisions import KnowledgeDraftCandidateV1, KnowledgeEvaluationBundleV1
from ..domain.studies import (
    KnowledgeProspectiveStudyV1,
    KnowledgeStudyRunV1,
    KnowledgeStudyPrimaryClaimV1,
    KnowledgeStudyExposureEventV1,
    KnowledgeStudyOutcomeV1,
    KnowledgeStudyFailureV1,
    OfficialBaselineSnapshotV1,
)
from ..ports.knowledge import ArtifactStorePort
from ..ports.knowledge import ClockPort
from ..domain.snapshot import KnowledgeSnapshotManifestV1


def register_study(
    study_id: str,
    study_name: str,
    target_markets: tuple[str, ...],
    target_cohort_size: int,
    registered_by: str,
    store: ArtifactStorePort,
    studies_dir: Path,
    clock: ClockPort,
) -> KnowledgeProspectiveStudyV1:
    """注册前瞻 Study。"""
    now = clock.now()

    raw = {
        "schema_version": 1,
        "study_id": study_id,
        "study_name": study_name,
        "proposal_id": "football-analysis",
        "proposal_version": "2.0.0",
        "target_markets": target_markets,
        "target_cohort_size": target_cohort_size,
        "stop_conditions": (),
        "exclusion_conditions": (),
        "registered_at": now.isoformat(),
        "registered_by": registered_by,
        "status": "active",
        "study_sha256": "0" * 64,
    }

    raw["study_sha256"] = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    study = KnowledgeProspectiveStudyV1.model_validate(raw)

    # 存储注册
    store.write_artifact(
        f"study:{study_id}",
        study.model_dump(mode="json"),
        subdir=f"studies/{study_id}",
    )

    return study


def run_study(
    study: KnowledgeProspectiveStudyV1,
    match_id: str,
    kickoff_at: datetime,
    features: FeatureSnapshotV2,
    baseline: PolicyKernelBaselineV1,
    official_baseline: OfficialBaselineSnapshotV1 | None,
    candidate: KnowledgeDraftCandidateV1 | None,
    store: ArtifactStorePort,
    runs_dir: Path,
    snapshot: KnowledgeSnapshotManifestV1,
    clock: ClockPort,
    existing_primary_claims: tuple[KnowledgeStudyPrimaryClaimV1, ...] = (),
    run_type: str = "primary",
) -> KnowledgeStudyRunV1:
    """执行 Study 单场运行。

    每个 study_id + match_id + snapshot_sha 只能有一个 primary run。
    Primary run 必须 run_at < kickoff_at。
    """
    now = clock.now()

    if run_type not in {"primary", "counterfactual"}:
        raise ValueError("未知 Study run_type")
    if run_type == "primary" and now >= kickoff_at:
        raise ValueError("Primary run 必须在开赛前执行")
    if run_type == "primary" and (official_baseline is None or not official_baseline.baseline_valid):
        raise ValueError("Primary run 必须绑定有效 OfficialBaselineSnapshot")
    if run_type == "primary" and candidate is None:
        raise ValueError("Primary run 必须有确定性 Candidate")

    snapshot_sha = snapshot.snapshot_sha256
    if candidate is not None and candidate.feature_sha256 != features.feature_sha256:
        raise ValueError("Candidate 与 FeatureSnapshot 不一致")
    if any(
        claim.study_id == study.study_id and claim.match_id == match_id and claim.snapshot_sha256 == snapshot_sha
        for claim in existing_primary_claims
    ):
        raise ValueError("该 Study/Match/Snapshot 已存在 Primary Claim")

    run_id = f"{study.study_id}:{match_id}:{snapshot_sha[:16]}"

    raw = {
        "schema_version": 1,
        "run_id": run_id,
        "study_id": study.study_id,
        "match_id": match_id,
        "run_at": now.isoformat(),
        "kickoff_at": kickoff_at.isoformat(),
        "snapshot_sha256": snapshot_sha,
        "official_baseline_sha256": official_baseline.snapshot_sha256 if official_baseline else "0" * 64,
        "policy_baseline_sha256": baseline.policy_kernel_sha256,
        "candidate_sha256": candidate.candidate_sha256 if candidate else None,
        "run_type": run_type,
        "primary_run": run_type == "primary",
        "run_status": "completed" if candidate else "not_run",
        "run_sha256": "0" * 64,
    }

    raw["run_sha256"] = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    run = KnowledgeStudyRunV1.model_validate(raw)

    # 存储运行记录
    store.write_artifact(
        f"run:{run_id}",
        run.model_dump(mode="json"),
        subdir=f"studies/{study.study_id}/runs",
    )

    if run_type == "primary":
        claim_raw = {
            "schema_version": 1,
            "claim_id": f"primary:{study.study_id}:{match_id}:{snapshot_sha[:16]}",
            "study_id": study.study_id,
            "match_id": match_id,
            "run_id": run.run_id,
            "snapshot_sha256": snapshot_sha,
            "candidate_sha256": candidate.candidate_sha256,
            "claimed_at": now.isoformat(),
            "claim_sha256": "0" * 64,
        }
        claim_raw["claim_sha256"] = hashlib.sha256(json.dumps(claim_raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        claim = KnowledgeStudyPrimaryClaimV1.model_validate(claim_raw)
        store.write_artifact(f"primary:{claim.claim_id}", claim.model_dump(mode="json"), subdir=f"studies/{study.study_id}/primary")

    return run


def expose_study(
    study: KnowledgeProspectiveStudyV1,
    run: KnowledgeStudyRunV1,
    candidate: KnowledgeDraftCandidateV1,
    exposed_by: str,
    reason: str,
    store: ArtifactStorePort,
    clock: ClockPort,
) -> KnowledgeStudyExposureEventV1:
    """暴露 Study 结果。

    显式暴露后追加 Exposure Event，不可撤销。
    """
    now = clock.now()
    if exposed_by != "lcz":
        raise ValueError("Study 暴露必须由 lcz 批准")
    if run.run_type != "primary" or not run.primary_run or run.candidate_sha256 != candidate.candidate_sha256:
        raise ValueError("只能暴露已封存的 Primary Candidate")
    if now >= run.kickoff_at:
        raise ValueError("Study 暴露必须在开赛前执行")

    raw = {
        "schema_version": 1,
        "event_id": f"exposure:{study.study_id}:{run.match_id}:{run.run_id}",
        "study_id": study.study_id,
        "match_id": run.match_id,
        "run_id": run.run_id,
        "snapshot_sha256": run.snapshot_sha256,
        "candidate_sha256": candidate.candidate_sha256,
        "exposed_at": now.isoformat(),
        "exposed_by": exposed_by,
        "exposure_reason": reason,
        "exposure_sha256": "0" * 64,
    }

    raw["exposure_sha256"] = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    event = KnowledgeStudyExposureEventV1.model_validate(raw)

    store.append_event(
        f"knowledge/knowledge-studies/exposure-events.jsonl",
        event.model_dump(mode="json"),
    )

    return event


def record_outcome(
    study: KnowledgeProspectiveStudyV1,
    run: KnowledgeStudyRunV1,
    final_score: str,
    result_one_x_two: str | None,
    result_handicap: str | None,
    total_goals: int | None,
    market_outcomes: dict[str, dict[str, Any]],
    store: ArtifactStorePort,
    clock: ClockPort,
) -> KnowledgeStudyOutcomeV1:
    """记录 Study Outcome。

    完赛只追加 Outcome，不更新卡片、Snapshot、索引或配置。
    """
    now = clock.now()

    raw = {
        "schema_version": 1,
        "outcome_id": f"outcome:{study.study_id}:{run.match_id}:{run.run_id}",
        "study_id": study.study_id,
        "match_id": run.match_id,
        "run_id": run.run_id,
        "snapshot_sha256": run.snapshot_sha256,
        "final_score": final_score,
        "result_one_x_two": result_one_x_two,
        "result_handicap": result_handicap,
        "total_goals": total_goals,
        "market_outcomes": market_outcomes,
        "supersedes_event_id": None,
        "recorded_at": now.isoformat(),
        "outcome_sha256": "0" * 64,
    }

    raw["outcome_sha256"] = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    outcome = KnowledgeStudyOutcomeV1.model_validate(raw)

    store.append_event(
        "knowledge/knowledge-studies/outcome-events.jsonl",
        outcome.model_dump(mode="json"),
    )

    return outcome


def record_failure(
    study: KnowledgeProspectiveStudyV1,
    match_id: str,
    run_id: str | None,
    failure_type: str,
    message: str,
    context: dict[str, Any],
    store: ArtifactStorePort,
    clock: ClockPort,
) -> KnowledgeStudyFailureV1:
    """记录 Study Failure。"""
    now = clock.now()

    raw = {
        "schema_version": 1,
        "failure_id": f"failure:{study.study_id}:{match_id}:{now.strftime('%Y%m%dT%H%M%S')}",
        "study_id": study.study_id,
        "match_id": match_id,
        "run_id": run_id,
        "failure_type": failure_type,
        "failure_message": message,
        "failure_context": context,
        "recorded_at": now.isoformat(),
        "failure_sha256": "0" * 64,
    }

    raw["failure_sha256"] = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()

    failure = KnowledgeStudyFailureV1.model_validate(raw)

    store.append_event(
        "knowledge/knowledge-studies/failure-events.jsonl",
        failure.model_dump(mode="json"),
    )

    return failure
