"""Knowledge Engine AI 旁路应用服务。

接入现有 Provider、预算、出站和 Prompt 哈希治理。
AI 输入仅包含白名单事实、知识、案例和证据 ID。
AI V2 仅绑定已封存的 Study Run。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain.ai_v2 import (
    AIAdvisoryInputReceiptV1,
    AIAnalysisCandidateV1,
    AICandidateComparisonV1,
    AIAdvisoryReceiptV1,
)
from ..domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
from ..domain.retrieval import KnowledgeRetrievalReceiptV1
from ..domain.decisions import KnowledgeDraftCandidateV1
from ..domain.studies import StudyEventType
from ..ports.knowledge import ArtifactStorePort


# 固定失败枚举
AI_FAILURE_TYPES = (
    "unavailable",
    "network_denied",
    "timeout",
    "budget_exceeded",
    "schema_error",
    "input_hash_mismatch",
    "provider_error",
)


def _map_failure_type(reason: str, status: str) -> str:
    """将 AI reason 映射到固定失败枚举。"""
    reason_lower = (reason or "").lower()
    if "network" in reason_lower or "denied" in reason_lower:
        return "network_denied"
    if "timeout" in reason_lower:
        return "timeout"
    if "budget" in reason_lower:
        return "budget_exceeded"
    if "schema" in reason_lower:
        return "schema_error"
    if "hash" in reason_lower or "mismatch" in reason_lower:
        return "input_hash_mismatch"
    if "provider" in reason_lower:
        return "provider_error"
    if status == "unavailable":
        return "unavailable"
    return "provider_error"


def run_ai_advisory(
    match_id: str,
    study_id: str,
    run_id: str,
    features: FeatureSnapshotV2,
    retrieval: KnowledgeRetrievalReceiptV1,
    baseline: PolicyKernelBaselineV1,
    ai_reasoner: Any,
    store: ArtifactStorePort,
    ledger: Any | None = None,
    clock: Any | None = None,
) -> AIAdvisoryReceiptV1:
    """运行 AI 旁路提示。

    对不可信文本转义并隔离 Prompt 指令。
    实现固定失败枚举封存：unavailable/network_denied/timeout/budget_exceeded/
    schema_error/input_hash_mismatch/provider_error。
    AI failure 不得让 Study Run 伪装为成功。
    """
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = (clock.now() if clock else datetime.now(tz)).replace(microsecond=0)

    if not ai_reasoner.is_available():
        # 记录 unavailable 失败
        if ledger is not None:
            _record_ai_failure_event(
                ledger, match_id, study_id, run_id,
                "unavailable", "AI provider not available", now,
            )
        return AIAdvisoryReceiptV1(
            receipt_id=f"ai-advisory:{match_id}:{study_id}:{run_id}",
            match_id=match_id,
            study_id=study_id,
            run_id=run_id,
            input_receipt_sha256="0" * 64,
            advisory_status="unavailable",
            advisory_receipt_sha256="0" * 64,
        )

    result = ai_reasoner.generate_advisory(
        features, retrieval, baseline, study_id, run_id,
    )

    status = result.get("status", "failed")
    input_receipt_sha256 = "0" * 64
    ai_candidate_sha256 = None

    if status == "success":
        input_data = result.get("input_receipt", {})
        input_receipt_sha256 = input_data.get("input_receipt_sha256", "0" * 64)
        candidate_data = result.get("candidate", {})
        ai_candidate_sha256 = candidate_data.get("candidate_sha256")

        # 存储产物
        store.write_artifact(
            f"ai-input:{match_id}:{study_id}:{run_id}",
            input_data,
            subdir=f"ai-v2/{match_id}",
        )
        store.write_artifact(
            f"ai-candidate:{match_id}:{study_id}:{run_id}",
            candidate_data,
            subdir=f"ai-v2/{match_id}",
        )

        # 记录成功事件
        if ledger is not None:
            advisory_payload = {
                "match_id": match_id,
                "study_id": study_id,
                "run_id": run_id,
                "input_receipt_sha256": input_receipt_sha256,
                "ai_candidate_sha256": ai_candidate_sha256,
                "status": "completed",
                "input_tokens": candidate_data.get("input_tokens", 0),
                "output_tokens": candidate_data.get("output_tokens", 0),
            }
            ledger.append(
                event_type=StudyEventType.AI_ADVISORY_RECORDED,
                event_id=f"ai-advisory:{match_id}:{study_id}:{run_id}",
                aggregate_id=f"study:{study_id}:match:{match_id}",
                idempotency_key=f"ai-advisory:{match_id}:{study_id}:{run_id}",
                recorded_at=now,
                payload=advisory_payload,
            )

        advisory_status = "completed"
    else:
        # 记录失败事件
        reason = result.get("reason", "unknown")
        failure_type = _map_failure_type(reason, status)
        if ledger is not None:
            _record_ai_failure_event(
                ledger, match_id, study_id, run_id,
                failure_type, reason, now,
            )
        advisory_status = (
            "unavailable" if status == "unavailable"
            else "failed"
        )

    return AIAdvisoryReceiptV1(
        receipt_id=f"ai-advisory:{match_id}:{study_id}:{run_id}",
        match_id=match_id,
        study_id=study_id,
        run_id=run_id,
        input_receipt_sha256=input_receipt_sha256,
        ai_candidate_sha256=ai_candidate_sha256,
        advisory_status=advisory_status,
        completed_at=now if advisory_status == "completed" else None,
        advisory_receipt_sha256="0" * 64,
    )


def _record_ai_failure_event(
    ledger: Any,
    match_id: str,
    study_id: str,
    run_id: str,
    failure_type: str,
    reason: str,
    now: Any,
) -> None:
    """记录 AI 失败事件到台账。"""
    payload = {
        "match_id": match_id,
        "study_id": study_id,
        "run_id": run_id,
        "failure_type": failure_type,
        "reason": reason,
        "status": "failed",
    }
    ledger.append(
        event_type=StudyEventType.FAILURE_RECORDED,
        event_id=f"ai-failure:{match_id}:{study_id}:{run_id}:{now.strftime('%Y%m%dT%H%M%S')}",
        aggregate_id=f"study:{study_id}:match:{match_id}",
        idempotency_key=f"ai-failure:{match_id}:{study_id}:{run_id}:{now.strftime('%Y%m%dT%H%M%S')}",
        recorded_at=now,
        payload=payload,
    )


def compare_candidates(
    match_id: str,
    study_id: str,
    run_id: str,
    deterministic: KnowledgeDraftCandidateV1,
    ai_candidate: AIAnalysisCandidateV1 | None,
) -> AICandidateComparisonV1:
    """比较 AI 与确定性结果。"""
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=8))

    agreement: dict[str, bool] = {}
    divergence_markets: list[str] = []
    divergence_details: dict[str, str] = {}

    if ai_candidate is None:
        return AICandidateComparisonV1(
            comparison_id=f"compare:{match_id}:{study_id}:{run_id}",
            match_id=match_id,
            study_id=study_id,
            run_id=run_id,
            deterministic_candidate_sha256=deterministic.candidate_sha256,
            ai_candidate_sha256="0" * 64,
            compared_at=datetime.now(tz).replace(microsecond=0),
            comparison_sha256="0" * 64,
        )

    det_markets = deterministic.market_candidates
    ai_markets = ai_candidate.parsed_output.get("market_assessments", {})

    for market in det_markets:
        det_status = det_markets[market].get("status", "")
        ai_status = ai_markets.get(market, {}).get("status", "")
        agreement[market] = det_status == ai_status
        if not agreement[market]:
            divergence_markets.append(market)
            divergence_details[market] = (
                f"deterministic: {det_status}, ai: {ai_status}"
            )

    return AICandidateComparisonV1(
        comparison_id=f"compare:{match_id}:{study_id}:{run_id}",
        match_id=match_id,
        study_id=study_id,
        run_id=run_id,
        deterministic_candidate_sha256=deterministic.candidate_sha256,
        ai_candidate_sha256=ai_candidate.candidate_sha256,
        agreement=agreement,
        divergence_markets=tuple(divergence_markets),
        divergence_details=divergence_details,
        compared_at=datetime.now(tz).replace(microsecond=0),
        comparison_sha256="0" * 64,
    )
