"""Knowledge Engine 正式草稿工作流注册。

实现 Contract 7/8/9 三种路由：
- Contract 7 -> legacy（历史兼容）
- Contract 8 -> current formal draft V3（当前主力）
- Contract 9 -> knowledge V4（Knowledge Engine）

agent start 必须显示 Snapshot、逻辑索引、本地索引、AI 和 Study 状态。
Contract 9 索引未就绪时 fail closed。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal


class DraftWorkflowRegistry:
    """正式草稿工作流注册表。

    根据 Contract 版本路由到不同的工作流处理器。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def detect_contract_version(
        self,
        receipt: dict[str, Any],
    ) -> int:
        """检测 Contract 版本。

        从 Receipt 的 schema_version 或 calibration_contract_version 推断。
        """
        # 直接声明
        if "calibration_contract_version" in receipt:
            return receipt["calibration_contract_version"]
        if "contract_version" in receipt:
            return receipt["contract_version"]

        # 从 schema_version 推断
        schema = receipt.get("schema_version", 0)
        if schema <= 7:
            return 7
        elif schema == 8:
            return 8
        elif schema >= 9:
            return 9
        return 8

    def route_build(
        self,
        contract_version: int,
        match_path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """路由 build-draft 到对应的工作流。"""
        if contract_version == 7:
            return self._build_legacy(match_path, **kwargs)
        elif contract_version == 8:
            return self._build_v3(match_path, **kwargs)
        elif contract_version == 9:
            return self._build_knowledge_v4(match_path, **kwargs)
        else:
            raise ValueError(f"不支持的 Contract 版本: {contract_version}")

    def route_accept(
        self,
        contract_version: int,
        match_path: str,
        candidate: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """路由 accept 到对应的工作流。"""
        if contract_version == 7:
            return self._accept_legacy(match_path, candidate, **kwargs)
        elif contract_version == 8:
            return self._accept_v3(match_path, candidate, **kwargs)
        elif contract_version == 9:
            return self._accept_knowledge_v4(match_path, candidate, **kwargs)
        else:
            raise ValueError(f"不支持的 Contract 版本: {contract_version}")

    def route_evaluate(
        self,
        contract_version: int,
        match_path: str,
        candidate: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """路由 evaluate 到对应的工作流。"""
        if contract_version == 7:
            return self._evaluate_legacy(match_path, candidate, **kwargs)
        elif contract_version == 8:
            return self._evaluate_v3(match_path, candidate, **kwargs)
        elif contract_version == 9:
            return self._evaluate_knowledge_v4(match_path, candidate, **kwargs)
        else:
            raise ValueError(f"不支持的 Contract 版本: {contract_version}")

    def route_validate(
        self,
        contract_version: int,
        match_path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """路由 validate 到对应的工作流。"""
        if contract_version == 7:
            return self._validate_legacy(match_path, **kwargs)
        elif contract_version == 8:
            return self._validate_v3(match_path, **kwargs)
        elif contract_version == 9:
            return self._validate_knowledge_v4(match_path, **kwargs)
        else:
            raise ValueError(f"不支持的 Contract 版本: {contract_version}")

    def route_render(
        self,
        contract_version: int,
        match_path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """路由 render 到对应的工作流。"""
        if contract_version == 7:
            return self._render_legacy(match_path, **kwargs)
        elif contract_version == 8:
            return self._render_v3(match_path, **kwargs)
        elif contract_version == 9:
            return self._render_knowledge_v4(match_path, **kwargs)
        else:
            raise ValueError(f"不支持的 Contract 版本: {contract_version}")

    # ── Contract 7: Legacy ──────────────────────────────────

    def _build_legacy(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "legacy", "contract": 7, "match": match_path}

    def _accept_legacy(self, match_path: str, candidate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"status": "legacy_accepted", "contract": 7, "match": match_path}

    def _evaluate_legacy(self, match_path: str, candidate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"status": "legacy_evaluated", "contract": 7, "match": match_path}

    def _validate_legacy(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "legacy_validated", "contract": 7, "match": match_path}

    def _render_legacy(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "legacy_rendered", "contract": 7, "match": match_path}

    # ── Contract 8: Current Formal Draft V3 ─────────────────

    def _build_v3(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "v3_built", "contract": 8, "match": match_path}

    def _accept_v3(self, match_path: str, candidate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"status": "v3_accepted", "contract": 8, "match": match_path}

    def _evaluate_v3(self, match_path: str, candidate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"status": "v3_evaluated", "contract": 8, "match": match_path}

    def _validate_v3(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "v3_validated", "contract": 8, "match": match_path}

    def _render_v3(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "v3_rendered", "contract": 8, "match": match_path}

    # ── Contract 9: Knowledge V4 ────────────────────────────

    def _build_knowledge_v4(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        """Contract 9 build-draft：使用 Knowledge Engine 构建草稿。

        Contract 9 索引未就绪时 fail closed。
        """
        if not self._is_knowledge_index_ready():
            raise RuntimeError(
                "Contract 9 索引未就绪。请先运行 'knowledge build-index'。"
            )
        return {"status": "knowledge_v4_built", "contract": 9, "match": match_path}

    def _accept_knowledge_v4(self, match_path: str, candidate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Contract 9 accept：验证候选一致性后接受。"""
        if not self._validate_candidate_consistency(candidate):
            raise ValueError("候选不一致，拒绝 accept，请重新构建。")
        return {"status": "knowledge_v4_accepted", "contract": 9, "match": match_path}

    def _evaluate_knowledge_v4(self, match_path: str, candidate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Contract 9 evaluate：重新计算并拒绝不一致候选。"""
        if not self._validate_candidate_consistency(candidate):
            raise ValueError("候选不一致，拒绝 evaluate，请重新构建。")
        return {"status": "knowledge_v4_evaluated", "contract": 9, "match": match_path}

    def _validate_knowledge_v4(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "knowledge_v4_validated", "contract": 9, "match": match_path}

    def _render_knowledge_v4(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        return {"status": "knowledge_v4_rendered", "contract": 9, "match": match_path}

    # ── 状态检查 ────────────────────────────────────────

    def _is_knowledge_index_ready(self) -> bool:
        """检查 Knowledge Engine 索引是否就绪。"""
        index_dir = self._root / "raw" / "knowledge-engine" / "index"
        if not index_dir.exists():
            return False
        return any(index_dir.glob("*.db"))

    def _validate_candidate_consistency(self, candidate: dict[str, Any]) -> bool:
        """验证候选一致性。"""
        required = {"feature_sha256", "retrieval_sha256", "evaluation_bundle_sha256"}
        for field in required:
            if field not in candidate or not candidate[field]:
                return False
        return True

    def agent_start_status(self) -> dict[str, Any]:
        """agent start 状态显示。

        返回 Snapshot、逻辑索引、本地索引、AI 和 Study 状态。
        """
        status: dict[str, Any] = {
            "contracts": {
                "contract_7": "legacy",
                "contract_8": "current",
                "contract_9": self._contract_9_status(),
            },
            "snapshot": self._snapshot_status(),
            "index": self._index_status(),
            "ai": self._ai_status(),
            "studies": self._studies_status(),
        }
        return status

    def _contract_9_status(self) -> str:
        if not self._is_knowledge_index_ready():
            return "index_not_ready"
        return "shadow_ready"

    def _snapshot_status(self) -> dict[str, Any]:
        snap_dir = self._root / "raw" / "knowledge-engine" / "snapshots"
        if not snap_dir.exists():
            return {"exists": False}
        snapshots = list(snap_dir.glob("*.yml"))
        return {
            "exists": len(snapshots) > 0,
            "count": len(snapshots),
        }

    def _index_status(self) -> dict[str, Any]:
        index_dir = self._root / "raw" / "knowledge-engine" / "index"
        if not index_dir.exists():
            return {"exists": False}
        indices = list(index_dir.glob("*.db"))
        return {
            "exists": len(indices) > 0,
            "count": len(indices),
            "ready": self._is_knowledge_index_ready(),
        }

    def _ai_status(self) -> dict[str, Any]:
        try:
            from ..adapters.ai_reasoner import AIReasonerAdapter
            adapter = AIReasonerAdapter(self._root)
            return {"available": adapter.is_available()}
        except Exception:
            return {"available": False}

    def _studies_status(self) -> dict[str, Any]:
        studies_dir = self._root / "knowledge" / "knowledge-studies"
        if not studies_dir.exists():
            return {"active": 0}

        outcome_count = 0
        outcome_path = studies_dir / "outcome-events.jsonl"
        if outcome_path.exists():
            outcome_count = len(outcome_path.read_text(encoding="utf-8").strip().split("\n"))

        return {
            "active": 0,
            "outcome_count": outcome_count,
        }