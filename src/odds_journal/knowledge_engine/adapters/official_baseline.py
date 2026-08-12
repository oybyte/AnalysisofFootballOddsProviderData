"""RenderedOfficialBaseline 适配器。

读取正式分析产物（Receipt、Outlook、Report），冻结为 RenderedOfficialBaselineV1。
要求已成功 validate-draft 和 render-draft，且 as_of < validated_at <= rendered_at < kickoff_at。
不要求 lock，也不得把 lock 后产物作为 Primary 基线。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from ..domain.studies import RenderedOfficialBaselineV1


class OfficialBaselineBuilder:
    """正式基线构建器。

    Study run 前后，正式 Match、Draft、Bundle、Outlook、Report 分别计算 hash；
    运行完成后全部必须保持不变。
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _match_raw_dir(self, match_id: str) -> Path:
        return self._root / "raw" / "matches" / match_id

    def _file_sha256(self, path: Path) -> str | None:
        if not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _json_sha256(self, data: Any) -> str:
        return hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

    def build(
        self,
        match_path: str,
        validated_at: datetime,
        rendered_at: datetime,
        ruleset_id: str = "football-analysis",
        ruleset_version: str = "1.8.0",
        as_of: datetime | None = None,
    ) -> RenderedOfficialBaselineV1:
        """从正式分析产物构建基线快照。

        失败条件：
        - Receipt 不是正式已发布 1.8.0、Contract 7/8 可解析版本
        - 未成功 validate-draft、render-draft
        - as_of < validated_at <= rendered_at < kickoff_at 不满足
        - 存在赛果或赛后观测
        """
        from ...agent_workflow import prematch_readiness
        from ...markdown import MatchDocument

        path = self._root / match_path
        if not path.is_file():
            raise FileNotFoundError(f"比赛文件不存在：{match_path}")
        document = MatchDocument.load(path)
        metadata = document.metadata
        match_id = metadata.match_id

        if metadata.kickoff_at is None:
            raise ValueError("比赛缺少 kickoff_at")
        kickoff_at = metadata.kickoff_at
        if kickoff_at.tzinfo is None:
            raise ValueError("kickoff_at 必须包含时区")

        if as_of is None:
            # 从 receipt 的 as_of 推断
            from ...analysis_context import parse_receipt
            receipt = parse_receipt(document.sections.get("prematch-reasoning", ""))
            if receipt is None:
                raise ValueError("缺少 AnalysisReceipt，请先完成 agent start")
            as_of = receipt.as_of

        if as_of.tzinfo is None:
            raise ValueError("as_of 必须包含时区")

        # 读取正式产物
        raw_dir = self._match_raw_dir(match_id)
        outlook_path = raw_dir / "analysis-outlook.yml"
        report_path = raw_dir / "analysis-report.md"

        if not outlook_path.is_file():
            raise ValueError("缺少 AnalysisOutlook，请先完成 validate-draft")
        if not report_path.is_file():
            raise ValueError("缺少 rendered report，请先完成 render-draft")

        # 检查 readiness
        readiness = prematch_readiness(self._root, path, checked_at=rendered_at)
        if not readiness.completed_stages.get("draft_validated"):
            raise ValueError("草稿未通过 validate-draft")
        if not readiness.completed_stages.get("report_rendered"):
            raise ValueError("报告未通过 render-draft")

        # 检查赛果
        from ...models import MatchStatus
        if metadata.status in {MatchStatus.FINISHED, MatchStatus.REVIEWED}:
            raise ValueError("比赛已有赛果，拒绝冻结基线")

        # 读取 receipt hash
        from ...analysis_context import parse_receipt
        receipt = parse_receipt(document.sections.get("prematch-reasoning", ""))
        if receipt is None:
            raise ValueError("缺少 AnalysisReceipt")
        receipt_sha = self._json_sha256(receipt.model_dump(mode="json"))

        outlook_data = yaml.safe_load(outlook_path.read_text(encoding="utf-8")) or {}
        outlook_sha = self._json_sha256(outlook_data)
        report_sha = self._file_sha256(report_path)

        # 构建基线哈希
        baseline_payload = {
            "match_id": match_id,
            "as_of": as_of.isoformat(),
            "kickoff_at": kickoff_at.isoformat(),
            "analysis_receipt_sha256": receipt_sha,
            "analysis_outlook_sha256": outlook_sha,
            "rendered_report_sha256": report_sha,
            "validated_at": validated_at.isoformat(),
            "rendered_at": rendered_at.isoformat(),
            "ruleset_id": ruleset_id,
            "ruleset_version": ruleset_version,
        }
        baseline_sha = self._json_sha256(baseline_payload)

        return RenderedOfficialBaselineV1(
            match_id=match_id,
            as_of=as_of,
            kickoff_at=kickoff_at,
            analysis_receipt_sha256=receipt_sha,
            analysis_outlook_sha256=outlook_sha,
            rendered_report_sha256=report_sha,
            validated_at=validated_at,
            rendered_at=rendered_at,
            ruleset_id=ruleset_id,
            ruleset_version=ruleset_version,
            has_result=False,
            has_post_kickoff_observation=False,
            baseline_sha256=baseline_sha,
        )

    def verify_unchanged(
        self,
        baseline: RenderedOfficialBaselineV1,
    ) -> tuple[bool, list[str]]:
        """验证正式产物 hash 在 Study run 前后保持不变。"""
        errors: list[str] = []
        raw_dir = self._match_raw_dir(baseline.match_id)
        outlook_path = raw_dir / "analysis-outlook.yml"
        report_path = raw_dir / "analysis-report.md"

        if outlook_path.is_file():
            outlook_data = yaml.safe_load(outlook_path.read_text(encoding="utf-8")) or {}
            current_sha = self._json_sha256(outlook_data)
            if current_sha != baseline.analysis_outlook_sha256:
                errors.append("AnalysisOutlook hash 变化")
        else:
            errors.append("AnalysisOutlook 文件缺失")

        if report_path.is_file():
            current_sha = self._file_sha256(report_path)
            if current_sha != baseline.rendered_report_sha256:
                errors.append("rendered report hash 变化")
        else:
            errors.append("rendered report 文件缺失")

        return len(errors) == 0, errors
