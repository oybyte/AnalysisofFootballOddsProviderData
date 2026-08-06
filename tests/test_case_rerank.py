from __future__ import annotations

import pytest

from odds_journal.case_rerank import CaseRerankConfigV1, CaseRerankReceiptV1


def test_rerank_is_disabled_without_explicit_lcz_approval() -> None:
    with pytest.raises(ValueError, match="lcz"):
        CaseRerankConfigV1(enabled=True, profile="strict_validation")
    assert CaseRerankConfigV1(profile="exploratory_research").enabled is False


def test_rerank_receipt_cannot_expand_candidate_set() -> None:
    raw = {
        "match_id": "fixture", "case_receipt_sha256": "a" * 64,
        "profile": "strict_validation", "algorithm_version": "candidate-closed-deterministic-v1",
        "candidate_ids": ["match:a:1"], "reranked_case_ids": ["match:a:1", "match:b:1"],
        "feature_vectors": {"match:a:1": {"scenario_overlap": 1}}, "rerank_sha256": "b" * 64,
    }
    with pytest.raises(ValueError, match="候选集合"):
        CaseRerankReceiptV1.model_validate(raw)
