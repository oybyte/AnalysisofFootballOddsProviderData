"""Knowledge Engine 前瞻 Study 应用服务。

实现 Study 注册、运行、暴露、评估和报告。
所有事件写入统一 KnowledgeStudyLedgerEventV1 台账，artifact 与 event 在同一事务。
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
    RenderedOfficialBaselineV1,
    KnowledgeStudyLedgerEventV1,
    StudyEventType,
    StudyState,
)
from ..ports.knowledge import ArtifactStorePort
from ..ports.knowledge import ClockPort
from ..domain.snapshot import KnowledgeSnapshotManifestV1


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _artifact_path(root: Path, content: dict, subdir: str) -> Path:
    """预计算内容寻址 artifact 路径（不写入）。"""
    content_hash = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return root / "raw" / "knowledge-engine" / subdir / f"{content_hash}.yml"


def register_study(
    study_id: str,
    study_name: str,
    target_markets: tuple[str, ...],
    target_cohort_size: int,
    registered_by: str,
    store: ArtifactStorePort,
    studies_dir: Path,
    clock: ClockPort,
    ledger: Any | None = None,
) -> KnowledgeProspectiveStudyV1:
    """注册前瞻 Study。

    写入 artifact 和统一台账事件（同一事务语义）。
    """
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
    raw["study_sha256"] = _sha256(raw)
    study = KnowledgeProspectiveStudyV1.model_validate(raw)

    # 存储注册 artifact
    store.write_artifact(
        f"study:{study_id}",
        study.model_dump(mode="json"),
        subdir=f"studies/{study_id}",
    )

    # 追加台账事件
    if ledger is not None:
        ledger.append(
            event_type=StudyEventType.STUDY_REGISTERED,
            event_id=f"study-registered:{study_id}",
            aggregate_id=f"study:{study_id}",
            idempotency_key=f"study-registered:{study_id}",
            recorded_at=now,
            payload=study.model_dump(mode="json"),
        )

    return study


def run_study(
    study: KnowledgeProspectiveStudyV1,
    match_id: str,
    kickoff_at: datetime,
    features: FeatureSnapshotV2,
    baseline: PolicyKernelBaselineV1,
    official_baseline: RenderedOfficialBaselineV1 | OfficialBaselineSnapshotV1 | None,
    candidate: KnowledgeDraftCandidateV1 | None,
    store: ArtifactStorePort,
    runs_dir: Path,
    snapshot: KnowledgeSnapshotManifestV1,
    clock: ClockPort,
    existing_primary_claims: tuple[KnowledgeStudyPrimaryClaimV1, ...] = (),
    run_type: str = "primary",
    ledger: Any | None = None,
    retrieval: KnowledgeRetrievalReceiptV1 | None = None,
    evaluation: KnowledgeEvaluationBundleV1 | None = None,
    root: Path | None = None,
) -> KnowledgeStudyRunV1:
    """执行 Study 单场运行。

    固定流程：
    正式 validate/render -> Read RenderedOfficialBaseline
    -> Compile FeatureSnapshot -> Freeze PolicyKernelBaseline
    -> Read sealed Snapshot/index -> Retrieve Knowledge
    -> Deterministic adjudication -> Write Run artifact + Primary Claim event

    每个 study_id + match_id + snapshot_sha 只能有一个 primary run。
    Primary run 必须 run_at < kickoff_at。
    """
    now = clock.now()

    if run_type not in {"primary", "counterfactual"}:
        raise ValueError("未知 Study run_type")
    if run_type == "primary" and now >= kickoff_at:
        raise ValueError("Primary run 必须在开赛前执行")
    if run_type == "primary" and official_baseline is None:
        raise ValueError("Primary run 必须绑定有效 OfficialBaseline")
    if run_type == "primary" and candidate is None:
        raise ValueError("Primary run 必须有确定性 Candidate")

    # 检查 RenderedOfficialBaseline 有效性
    if run_type == "primary" and isinstance(official_baseline, RenderedOfficialBaselineV1):
        if official_baseline.has_result:
            raise ValueError("基线存在赛果，拒绝 Primary")
        if official_baseline.has_post_kickoff_observation:
            raise ValueError("基线存在赛后观测，拒绝 Primary")

    snapshot_sha = snapshot.snapshot_sha256
    if candidate is not None and candidate.feature_sha256 != features.feature_sha256:
        raise ValueError("Candidate 与 FeatureSnapshot 不一致")
    if any(
        claim.study_id == study.study_id and claim.match_id == match_id and claim.snapshot_sha256 == snapshot_sha
        for claim in existing_primary_claims
    ):
        raise ValueError("该 Study/Match/Snapshot 已存在 Primary Claim")

    # ledger 幂等检查
    if ledger is not None and run_type == "primary":
        if ledger.has_primary_claim(study.study_id, match_id, snapshot_sha):
            raise ValueError("台账已存在 Primary Claim")

    run_id = f"{study.study_id}:{match_id}:{snapshot_sha[:16]}"

    raw = {
        "schema_version": 1,
        "run_id": run_id,
        "study_id": study.study_id,
        "match_id": match_id,
        "run_at": now.isoformat(),
        "kickoff_at": kickoff_at.isoformat(),
        "snapshot_sha256": snapshot_sha,
        "official_baseline_sha256": (
            getattr(official_baseline, "baseline_sha256", None)
            or getattr(official_baseline, "snapshot_sha256", None)
            or "0" * 64
            if official_baseline
            else "0" * 64
        ),
        "policy_baseline_sha256": baseline.policy_kernel_sha256,
        "candidate_sha256": candidate.candidate_sha256 if candidate else None,
        "run_type": run_type,
        "primary_run": run_type == "primary",
        "run_status": "completed" if candidate else "not_run",
        "run_sha256": "0" * 64,
    }
    raw["run_sha256"] = _sha256(raw)
    run = KnowledgeStudyRunV1.model_validate(raw)

    # 预计算 Primary Claim 数据（用于事务文件列表）
    claim_raw = None
    if run_type == "primary" and ledger is not None and candidate is not None:
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
        claim_raw["claim_sha256"] = _sha256(claim_raw)

    # 事务包装：artifact 与 event 必须处于同一 RepositoryTransaction
    # 使用 transaction_factory 回调避免 application 层直接导入 odds_journal.transaction
    if root is not None and hasattr(store, "_root"):
        # 预计算所有将写入的文件路径
        tx_files: list[Path] = []
        run_artifact_path = _artifact_path(root, run.model_dump(mode="json"), f"studies/{study.study_id}/runs")
        tx_files.append(run_artifact_path)
        if retrieval is not None:
            tx_files.append(_artifact_path(root, retrieval.model_dump(mode="json"), f"studies/{study.study_id}/runs/{match_id}"))
        if evaluation is not None:
            tx_files.append(_artifact_path(root, evaluation.model_dump(mode="json"), f"studies/{study.study_id}/runs/{match_id}"))
        if claim_raw is not None and ledger is not None:
            tx_files.append(ledger._ledger_path(StudyEventType.PRIMARY_CLAIMED))

        tx_dirs = [
            root / "raw" / "knowledge-engine" / f"studies/{study.study_id}/runs",
            root / "knowledge" / "knowledge-studies",
        ]

        # 通过 store 适配器获取事务上下文（避免 application 层直接导入事务模块）
        tx_context = store._begin_transaction(tx_files, tx_dirs, "study-run") if hasattr(store, "_begin_transaction") else None
        if tx_context is not None:
            with tx_context as tx:
                store.write_artifact(f"run:{run_id}", run.model_dump(mode="json"), subdir=f"studies/{study.study_id}/runs")
                if retrieval is not None:
                    store.write_artifact(f"retrieval:{run_id}", retrieval.model_dump(mode="json"), subdir=f"studies/{study.study_id}/runs/{match_id}")
                if evaluation is not None:
                    store.write_artifact(f"evaluation:{run_id}", evaluation.model_dump(mode="json"), subdir=f"studies/{study.study_id}/runs/{match_id}")
                if claim_raw is not None:
                    ledger.append(
                        event_type=StudyEventType.PRIMARY_CLAIMED,
                        event_id=f"primary-claim:{study.study_id}:{match_id}:{snapshot_sha[:16]}",
                        aggregate_id=f"study:{study.study_id}:match:{match_id}",
                        idempotency_key=f"primary:{study.study_id}:{match_id}:{snapshot_sha[:16]}",
                        recorded_at=now,
                        payload=claim_raw,
                    )
                tx.commit()
        else:
            _write_study_artifacts(store, ledger, run_id, study, match_id, run, retrieval, evaluation, claim_raw, now, snapshot_sha)
    else:
        _write_study_artifacts(store, ledger, run_id, study, match_id, run, retrieval, evaluation, claim_raw, now, snapshot_sha)

    return run


def _write_study_artifacts(
    store: ArtifactStorePort,
    ledger: Any,
    run_id: str,
    study: KnowledgeProspectiveStudyV1,
    match_id: str,
    run: KnowledgeStudyRunV1,
    retrieval: KnowledgeRetrievalReceiptV1 | None,
    evaluation: KnowledgeEvaluationBundleV1 | None,
    claim_raw: dict[str, Any] | None,
    now: datetime,
    snapshot_sha: str,
) -> None:
    """写入 Study artifacts 和 ledger（无事务模式）。"""
    store.write_artifact(f"run:{run_id}", run.model_dump(mode="json"), subdir=f"studies/{study.study_id}/runs")
    if retrieval is not None:
        store.write_artifact(f"retrieval:{run_id}", retrieval.model_dump(mode="json"), subdir=f"studies/{study.study_id}/runs/{match_id}")
    if evaluation is not None:
        store.write_artifact(f"evaluation:{run_id}", evaluation.model_dump(mode="json"), subdir=f"studies/{study.study_id}/runs/{match_id}")
    if claim_raw is not None and ledger is not None:
        ledger.append(
            event_type=StudyEventType.PRIMARY_CLAIMED,
            event_id=f"primary-claim:{study.study_id}:{match_id}:{snapshot_sha[:16]}",
            aggregate_id=f"study:{study.study_id}:match:{match_id}",
            idempotency_key=f"primary:{study.study_id}:{match_id}:{snapshot_sha[:16]}",
            recorded_at=now,
            payload=claim_raw,
        )


def expose_study(
    study: KnowledgeProspectiveStudyV1,
    run: KnowledgeStudyRunV1,
    candidate: KnowledgeDraftCandidateV1,
    exposed_by: str,
    reason: str,
    store: ArtifactStorePort,
    clock: ClockPort,
    ledger: Any | None = None,
) -> KnowledgeStudyExposureEventV1:
    """暴露 Study 结果。显式暴露后追加 Exposure Event，不可撤销。"""
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
    raw["exposure_sha256"] = _sha256(raw)
    event = KnowledgeStudyExposureEventV1.model_validate(raw)

    if ledger is not None:
        ledger.append(
            event_type=StudyEventType.EXPOSED,
            event_id=f"exposure:{study.study_id}:{run.match_id}:{run.run_id}",
            aggregate_id=f"study:{study.study_id}:match:{run.match_id}",
            idempotency_key=f"exposure:{study.study_id}:{run.match_id}:{run.run_id}",
            recorded_at=now,
            payload=raw,
        )
    else:
        store.append_event(
            "knowledge/knowledge-studies/exposure-events.jsonl",
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
    ledger: Any | None = None,
    supersedes_event_id: str | None = None,
) -> KnowledgeStudyOutcomeV1:
    """记录 Study Outcome。完赛只追加 Outcome，不更新卡片、Snapshot、索引或配置。

    Outcome 只能 supersede，不得原地修改。
    """
    now = clock.now()

    outcome_id = f"outcome:{study.study_id}:{run.match_id}:{run.run_id}"
    if supersedes_event_id:
        outcome_id = f"outcome:{study.study_id}:{run.match_id}:{now.strftime('%Y%m%dT%H%M%S')}"

    raw = {
        "schema_version": 1,
        "outcome_id": outcome_id,
        "study_id": study.study_id,
        "match_id": run.match_id,
        "run_id": run.run_id,
        "final_score": final_score,
        "result_one_x_two": result_one_x_two,
        "result_handicap": result_handicap,
        "total_goals": total_goals,
        "market_outcomes": market_outcomes,
        "supersedes_event_id": supersedes_event_id,
        "recorded_at": now.isoformat(),
        "outcome_sha256": "0" * 64,
    }
    raw["outcome_sha256"] = _sha256(raw)
    outcome = KnowledgeStudyOutcomeV1.model_validate(raw)

    if ledger is not None:
        ledger.append(
            event_type=StudyEventType.OUTCOME_RECORDED,
            event_id=outcome_id,
            aggregate_id=f"study:{study.study_id}:match:{run.match_id}",
            idempotency_key=outcome_id,
            recorded_at=now,
            payload=raw,
            supersedes_event_id=supersedes_event_id,
        )
    else:
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
    ledger: Any | None = None,
) -> KnowledgeStudyFailureV1:
    """记录 Study Failure。"""
    now = clock.now()

    failure_id = f"failure:{study.study_id}:{match_id}:{now.strftime('%Y%m%dT%H%M%S')}"

    raw = {
        "schema_version": 1,
        "failure_id": failure_id,
        "study_id": study.study_id,
        "match_id": match_id,
        "run_id": run_id,
        "failure_type": failure_type,
        "failure_message": message,
        "failure_context": context,
        "recorded_at": now.isoformat(),
        "failure_sha256": "0" * 64,
    }
    raw["failure_sha256"] = _sha256(raw)
    failure = KnowledgeStudyFailureV1.model_validate(raw)

    if ledger is not None:
        ledger.append(
            event_type=StudyEventType.FAILURE_RECORDED,
            event_id=failure_id,
            aggregate_id=f"study:{study.study_id}:match:{match_id}",
            idempotency_key=failure_id,
            recorded_at=now,
            payload=raw,
        )
    else:
        store.append_event(
            "knowledge/knowledge-studies/failure-events.jsonl",
            failure.model_dump(mode="json"),
        )

    return failure
