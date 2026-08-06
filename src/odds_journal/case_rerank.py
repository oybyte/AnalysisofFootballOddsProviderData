from __future__ import annotations

"""Deterministic, candidate-closed case reranking for AI research only."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .case_retrieval import CaseRetrievalReceipt, parse_case_receipt
from .ledger import atomic_write_text, sha256_json
from .markdown import MatchDocument


class CaseRerankConfigV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    enabled: bool = False
    approved_by: Literal["lcz"] | None = None
    profile: Literal["strict_validation", "exploratory_research"]
    algorithm_version: Literal["candidate-closed-deterministic-v1"] = "candidate-closed-deterministic-v1"

    @model_validator(mode="after")
    def gated(self) -> "CaseRerankConfigV1":
        if self.enabled and self.approved_by != "lcz":
            raise ValueError("启用案例重排必须由 lcz 批准")
        return self


class CaseRerankReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    match_id: str
    case_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile: Literal["strict_validation", "exploratory_research"]
    algorithm_version: Literal["candidate-closed-deterministic-v1"]
    candidate_ids: list[str]
    reranked_case_ids: list[str]
    feature_vectors: dict[str, dict[str, int]]
    rerank_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def closed_candidates(self) -> "CaseRerankReceiptV1":
        if set(self.candidate_ids) != set(self.reranked_case_ids) or len(self.candidate_ids) != len(set(self.candidate_ids)):
            raise ValueError("案例重排必须保持候选集合封闭且唯一")
        if set(self.feature_vectors) != set(self.candidate_ids):
            raise ValueError("案例重排必须冻结全部候选特征")
        return self


def _digest(item: CaseRerankReceiptV1) -> str:
    raw = item.model_dump(mode="json")
    raw["rerank_sha256"] = "0" * 64
    return sha256_json(raw)


def rerank(root: Path, path: Path, config_path: Path) -> tuple[Path, CaseRerankReceiptV1]:
    config = CaseRerankConfigV1.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
    if not config.enabled:
        raise ValueError("案例重排默认停用；必须使用经 lcz 批准的研究配置")
    document = MatchDocument.load(path)
    receipt = parse_case_receipt(document.sections["prematch-reasoning"], required=True)
    assert receipt is not None
    candidates = list(receipt.selected_cases)
    if config.profile == "strict_validation":
        candidates = [item for item in candidates if item.statistics_eligible and item.chronology == "prematch_verified"]
    candidate_ids = [f"{item.artifact_type}:{item.case_id}:{item.case_revision}" for item in candidates]
    vectors = {
        identity: {
            "scenario_overlap": len(item.scenario_type_ids),
            "chunk_coverage": len(item.chunk_ids),
            "statistics_eligible": int(item.statistics_eligible),
        }
        for identity, item in zip(candidate_ids, candidates)
    }
    # Stable tuple ordering is deterministic and never introduces a new case.
    ranked = sorted(candidate_ids, key=lambda item: (-vectors[item]["scenario_overlap"], -vectors[item]["chunk_coverage"], item))
    raw = {
        "match_id": document.metadata.match_id,
        "case_receipt_sha256": receipt.context_sha256,
        "profile": config.profile,
        "algorithm_version": config.algorithm_version,
        "candidate_ids": candidate_ids,
        "reranked_case_ids": ranked,
        "feature_vectors": vectors,
        "rerank_sha256": "0" * 64,
    }
    provisional = CaseRerankReceiptV1.model_validate(raw)
    item = provisional.model_copy(update={"rerank_sha256": _digest(provisional)})
    target = root / "raw" / "matches" / document.metadata.match_id / "case-rerank" / f"{item.rerank_sha256}.yml"
    if target.exists():
        existing = CaseRerankReceiptV1.model_validate(yaml.safe_load(target.read_text(encoding="utf-8")) or {})
        if existing != item:
            raise ValueError("已封存案例重排内容不一致")
        return target, existing
    atomic_write_text(target, yaml.safe_dump(item.model_dump(mode="json"), allow_unicode=True, sort_keys=False))
    return target, item
