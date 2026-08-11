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


def register_study(
    study_id: str,
    study_name: str,
    target_markets: tuple[str, ...],
    target_cohort_size: int,
    registered_by: str,
    store: ArtifactStorePort,
    studies_dir: Path,
) -> KnowledgeProspectiveStudyV1:
    """注册前瞻 Study。"""
    from datetime import timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).replace(microsecond=0)

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
) -> KnowledgeStudyRunV1:
    """执行 Study 单场运行。

    每个 study_id + match_id + snapshot_sha 只能有一个 primary run。
    Primary run 必须 run_at < kickoff_at。
    """
    from datetime import timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).replace(microsecond=0)

    if now >= kickoff_at:
        raise ValueError("Primary run 必须在开赛前执行")

    snapshot_sha = features.feature_sha256

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
        "run_type": "primary",
        "primary_run": True,
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

    return run


def expose_study(
    study: KnowledgeProspectiveStudyV1,
    run: KnowledgeStudyRunV1,
    candidate: KnowledgeDraftCandidateV1,
    exposed_by: str,
    reason: str,
    store: ArtifactStorePort,
) -> KnowledgeStudyExposureEventV1:
    """暴露 Study 结果。

    显式暴露后追加 Exposure Event，不可撤销。
    """
    from datetime import timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).replace(microsecond=0)

    raw = {
        "schema_version": 1,
        "event_id": f"exposure:{study.study_id}:{run.match_id}:{run.run_id}",
        "study_id": study.study_id,
        "match_id": run.match_id,
        "run_id": run.run_id,
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
) -> KnowledgeStudyOutcomeV1:
    """记录 Study Outcome。

    完赛只追加 Outcome，不更新卡片、Snapshot、索引或配置。
    """
    from datetime import timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).replace(microsecond=0)

    raw = {
        "schema_version": 1,
        "outcome_id": f"outcome:{study.study_id}:{run.match_id}:{run.run_id}",
        "study_id": study.study_id,
        "match_id": run.match_id,
        "run_id": run.run_id,
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
) -> KnowledgeStudyFailureV1:
    """记录 Study Failure。"""
    from datetime import timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).replace(microsecond=0)

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