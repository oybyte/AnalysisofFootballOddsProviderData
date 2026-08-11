"""Knowledge Engine AI 旁路应用服务。

接入现有 Provider、预算、出站和 Prompt 哈希治理。
AI 输入仅包含白名单事实、知识、案例和证据 ID。
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
from ..ports.knowledge import ArtifactStorePort


def run_ai_advisory(
    match_id: str,
    study_id: str,
    run_id: str,
    features: FeatureSnapshotV2,
    retrieval: KnowledgeRetrievalReceiptV1,
    baseline: PolicyKernelBaselineV1,
    ai_reasoner: Any,
    store: ArtifactStorePort,
) -> AIAdvisoryReceiptV1:
    """运行 AI 旁路提示。

    对不可信文本转义并隔离 Prompt 指令。
    实现 unavailable/failed/not_run 封存。
    """
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=8))

    if not ai_reasoner.is_available():
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

    input_receipt_sha256 = "0" * 64
    ai_candidate_sha256 = None
    if result.get("status") == "success":
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

    status = result.get("status", "failed")
    advisory_status = (
        "completed" if status == "success"
        else "unavailable" if status == "unavailable"
        else "failed" if status == "failed"
        else "not_run"
    )

    return AIAdvisoryReceiptV1(
        receipt_id=f"ai-advisory:{match_id}:{study_id}:{run_id}",
        match_id=match_id,
        study_id=study_id,
        run_id=run_id,
        input_receipt_sha256=input_receipt_sha256,
        ai_candidate_sha256=ai_candidate_sha256,
        advisory_status=advisory_status,
        completed_at=datetime.now(tz).replace(microsecond=0) if advisory_status == "completed" else None,
        advisory_receipt_sha256="0" * 64,
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