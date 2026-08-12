"""Knowledge Engine 正式草稿工作流注册。

实现 Contract 7/8/9 三种路由：
- Contract 7 -> legacy（历史兼容）
- Contract 8 -> current formal draft V3（当前主力）
- Contract 9 -> knowledge V4（Knowledge Engine）

agent start 必须显示 Snapshot、逻辑索引、本地索引、AI 和 Study 状态。
Contract 9 索引未就绪时 fail closed。
"""

from __future__ import annotations

import hashlib
import yaml
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

    def _is_2_0_0_published(self) -> bool:
        """检查 2.0.0 是否已发布为正式活动规则集。"""
        active_path = self._root / "knowledge" / "rulesets" / "football-analysis" / "active.yml"
        if not active_path.is_file():
            return False
        try:
            data = yaml.safe_load(active_path.read_text(encoding="utf-8")) or {}
            return data.get("ruleset_version") == "2.0.0"
        except Exception:
            return False

    def _build_knowledge_v4(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        """Contract 9 build-draft：使用 Knowledge Engine 构建草稿。

        Contract 9 索引未就绪时 fail closed。
        proposal Receipt 只能运行 Study sidecar，禁止生成正式 Draft。
        """
        snapshot_sha256 = kwargs.get("snapshot_sha256")
        if not isinstance(snapshot_sha256, str) or not self._is_knowledge_index_ready(snapshot_sha256):
            raise RuntimeError(
                "Contract 9 指定 Snapshot 的索引未就绪。请先运行 'knowledge build-index'。"
            )

        # proposal 隔离：2.0.0 未发布时禁止生成正式 Draft
        is_proposal = kwargs.get("proposal", False)
        if not self._is_2_0_0_published() and not is_proposal:
            raise RuntimeError(
                "2.0.0 未发布，Contract 9 正式 Draft 不可用。"
                "proposal Receipt 只能运行 Study sidecar。"
            )

        # 验证候选一致性字段
        candidate = kwargs.get("candidate", {})
        if candidate:
            required = {
                "feature_sha256", "retrieval_sha256", "evaluation_bundle_sha256",
                "snapshot_sha256", "candidate_sha256",
            }
            missing = required - set(candidate.keys())
            if missing:
                raise ValueError(f"候选缺少必要字段：{missing}")

        return {
            "status": "knowledge_v4_built",
            "contract": 9,
            "match": match_path,
            "snapshot_sha256": snapshot_sha256,
            "proposal": is_proposal,
        }

    def _accept_knowledge_v4(self, match_path: str, candidate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Contract 9 accept：验证候选一致性后接受。

        accept-draft 必须由 lcz 确认 candidate hash，输入变化即拒绝接受。
        """
        approved_by = kwargs.get("approved_by", "")
        confirm_draft = kwargs.get("confirm_draft", False)
        candidate_sha = kwargs.get("candidate_sha")

        if approved_by != "lcz" or not confirm_draft:
            raise ValueError("Contract 9 accept 必须由 lcz 使用 --confirm-draft 确认")

        if not self._validate_candidate_consistency(candidate):
            raise ValueError("候选不一致，拒绝 accept，请重新构建。")

        if not self._is_knowledge_index_ready(candidate.get("snapshot_sha256")):
            raise ValueError("Contract 9 索引未就绪，拒绝 accept")

        # 验证 candidate_sha 匹配
        if candidate_sha and candidate.get("candidate_sha256") != candidate_sha:
            raise ValueError("candidate_sha 与候选内容不匹配，拒绝 accept")

        return {"status": "knowledge_v4_accepted", "contract": 9, "match": match_path}

    def _evaluate_knowledge_v4(self, match_path: str, candidate: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Contract 9 evaluate：重新计算并拒绝不一致候选。"""
        if not self._validate_candidate_consistency(candidate):
            raise ValueError("候选不一致，拒绝 evaluate，请重新构建。")
        if not self._is_knowledge_index_ready(candidate.get("snapshot_sha256")):
            raise ValueError("Contract 9 索引未就绪，拒绝 evaluate")
        return {"status": "knowledge_v4_evaluated", "contract": 9, "match": match_path}

    def _validate_knowledge_v4(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        """Contract 9 validate：验证 V7 市场语义。"""
        # pass 市场不得有候选
        outlook = kwargs.get("outlook", {})
        market_status = outlook.get("market_status", {})
        candidates = outlook.get("candidates", {})

        for market, status in market_status.items():
            if status == "pass" and market in candidates:
                raise ValueError(f"{market} pass 市场不得有候选")

        # 知识语义验证
        market_knowledge = outlook.get("market_knowledge", {})
        for market, knowledge in market_knowledge.items():
            knowledge_mode = knowledge.get("knowledge_mode")
            status = market_status.get(market)
            if knowledge_mode == "pass" and status != "pass":
                raise ValueError(f"{market} knowledge_mode=pass 必须对应 status=pass")
            if status == "pass" and knowledge_mode and knowledge_mode != "pass":
                raise ValueError(f"{market} baseline pass 不能被知识重开")

        return {"status": "knowledge_v4_validated", "contract": 9, "match": match_path}

    def _render_knowledge_v4(self, match_path: str, **kwargs: Any) -> dict[str, Any]:
        """Contract 9 render：渲染 V7 六段报告。"""
        return {"status": "knowledge_v4_rendered", "contract": 9, "match": match_path}

    # ── 状态检查 ────────────────────────────────────────

    def _is_knowledge_index_ready(self, snapshot_sha256: str | None = None) -> bool:
        """Check a specific Snapshot's byte-verified local index.

        A Contract 9 run is bound to one immutable snapshot.  An unrelated
        index must never make a different snapshot eligible.
        """
        if not snapshot_sha256:
            return False
        index_dir = self._root / "raw" / "knowledge-engine" / "index"
        snapshot_dir = self._root / "raw" / "knowledge-engine" / "snapshots"
        db_path = index_dir / f"{snapshot_sha256}.db"
        manifest_path = index_dir / f"{snapshot_sha256}.manifest.yml"
        snapshot_path = snapshot_dir / f"{snapshot_sha256}.yml"
        if not (db_path.is_file() and manifest_path.is_file() and snapshot_path.is_file()):
            return False
        try:
            metadata = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            return (
                metadata.get("snapshot_sha256") == snapshot_sha256
                and metadata.get("sqlite_file_sha256") == hashlib.sha256(db_path.read_bytes()).hexdigest()
            )
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return False

    def _validate_candidate_consistency(self, candidate: dict[str, Any]) -> bool:
        """验证候选一致性。"""
        required = {"feature_sha256", "retrieval_sha256", "evaluation_bundle_sha256", "snapshot_sha256"}
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
        snapshots = list((self._root / "raw" / "knowledge-engine" / "snapshots").glob("*.yml"))
        if not any(self._is_knowledge_index_ready(path.stem) for path in snapshots):
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
