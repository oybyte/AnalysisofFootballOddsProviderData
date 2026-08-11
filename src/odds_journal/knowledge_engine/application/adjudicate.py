"""Knowledge Engine 裁决应用服务。

实现 Query Plan、Retrieval Receipt、Hypothesis Graph 和 Evaluation Bundle。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.decisions import (
    DecisionAuthorityContractV1,
    KnowledgeDraftCandidateV1,
    KnowledgeDraftBuildReceiptV1,
    KnowledgeEvaluationBundleV1,
)
from ..domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
from ..domain.retrieval import KnowledgeRetrievalReceiptV1, HypothesisGraphV1
from ..ports.knowledge import KnowledgeReasoner


def adjudicate(
    features: FeatureSnapshotV2,
    retrieval: KnowledgeRetrievalReceiptV1,
    baseline: PolicyKernelBaselineV1,
    authority: DecisionAuthorityContractV1,
    reasoner: KnowledgeReasoner,
) -> KnowledgeEvaluationBundleV1:
    """执行确定性知识裁决。

    实现独立来源、反证、冲突、权限和市场隔离。
    生成内容寻址 Candidate，不写正式 Match。
    """
    return reasoner.analyze(features, retrieval, baseline, authority)


def build_hypothesis_graph(
    match_id: str,
    market_assessments: dict[str, dict[str, Any]],
) -> HypothesisGraphV1:
    """构建假设图。"""
    hypotheses: dict[str, dict[str, str]] = {}
    for market, assessment in market_assessments.items():
        if assessment.get("status") == "pass":
            hypotheses[market] = {
                "supporting_hypothesis": "市场 pass，无法形成假设。",
                "counter_hypothesis": "不适用。",
                "invalidation_condition": "不适用。",
            }
        else:
            hypotheses[market] = {
                "supporting_hypothesis": f"确定性评估支持 {market} 排序。",
                "counter_hypothesis": "机构分歧或新增证据可能削弱当前排序。",
                "invalidation_condition": "输入哈希、冲突状态或截止时间发生变化。",
            }
    return HypothesisGraphV1(match_id=match_id, hypotheses=hypotheses)


def build_draft_candidate(
    features: FeatureSnapshotV2,
    retrieval: KnowledgeRetrievalReceiptV1,
    baseline: PolicyKernelBaselineV1,
    evaluation: KnowledgeEvaluationBundleV1,
    hypotheses: HypothesisGraphV1,
    now: datetime,
) -> KnowledgeDraftCandidateV1:
    """构建知识草稿候选。

    内容寻址，不直接写正式 Match。
    """
    import hashlib
    import json

    market_candidates: dict[str, dict[str, Any]] = {}
    for market, decision in evaluation.market_decisions.items():
        market_candidates[market] = {
            "status": decision.get("status", "pass"),
            "ranking": decision.get("ranking", []),
            "degraded": decision.get("degraded", False),
            "degradation_reasons": decision.get("degradation_reasons", []),
            "hypothesis": hypotheses.hypotheses.get(market, {}),
        }

    raw = {
        "schema_version": 1,
        "match_id": features.match_id,
        "as_of": features.as_of.isoformat(),
        "feature_sha256": features.feature_sha256,
        "retrieval_sha256": retrieval.retrieval_sha256,
        "baseline_sha256": baseline.policy_kernel_sha256,
        "evaluation_bundle_sha256": evaluation.bundle_sha256,
        "market_candidates": market_candidates,
        "contract_version": 9,
        "candidate_sha256": "0" * 64,
    }

    candidate_hash = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
    raw["candidate_sha256"] = candidate_hash

    return KnowledgeDraftCandidateV1.model_validate(raw)


def build_draft_receipt(
    match_id: str,
    as_of: datetime,
    built_at: datetime,
    snapshot: Any,
    index_manifest: Any,
    candidate: KnowledgeDraftCandidateV1,
) -> KnowledgeDraftBuildReceiptV1:
    """构建知识草稿构建回执。"""
    import hashlib
    import json

    raw = {
        "schema_version": 1,
        "match_id": match_id,
        "built_at": built_at.isoformat(),
        "as_of": as_of.isoformat(),
        "ruleset_id": "football-analysis",
        "ruleset_version": "2.0.0",
        "ruleset_sha256": "0" * 64,
        "snapshot_sha256": snapshot.snapshot_sha256 if hasattr(snapshot, "snapshot_sha256") else "0" * 64,
        "index_manifest_sha256": index_manifest.index_manifest_sha256 if hasattr(index_manifest, "index_manifest_sha256") else "0" * 64,
        "candidate_sha256": candidate.candidate_sha256,
        "compiler_version": "knowledge-engine-v1",
        "receipt_sha256": "0" * 64,
    }

    receipt_hash = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    raw["receipt_sha256"] = receipt_hash

    return KnowledgeDraftBuildReceiptV1.model_validate(raw)