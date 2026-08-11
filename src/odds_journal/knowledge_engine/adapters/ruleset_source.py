"""Knowledge Engine 规则集来源适配器。

接入现有 rules 模块加载已发布规则集和提案。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class RulesetSourceAdapter:
    """规则集来源适配器。

    proposal 模式只允许显式指定 2.0.0。
    正式模式只加载 Receipt 引用的已发布 Snapshot。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def load_ruleset(
        self,
        ruleset_id: str,
        version: str,
        *,
        allow_proposal: bool = False,
    ) -> dict[str, Any]:
        from ...rules import load_ruleset

        ruleset = load_ruleset(
            self._root,
            f"{ruleset_id}@{version}",
            allow_proposal=allow_proposal,
        )
        return {
            "ruleset_id": ruleset.manifest.ruleset_id,
            "ruleset_version": ruleset.manifest.ruleset_version,
            "content_sha256": ruleset.content_sha256,
            "document_ids": list(ruleset.documents),
            "required_document_ids": ruleset.manifest.required_document_ids,
            "conditional_document_ids": ruleset.manifest.conditional_document_ids,
            "published": ruleset.manifest.published,
            "origin": ruleset.origin,
        }

    def load_ruleset_documents(
        self,
        ruleset_id: str,
        version: str,
        *,
        allow_proposal: bool = False,
    ) -> list[dict[str, Any]]:
        from ...rules import load_ruleset

        ruleset = load_ruleset(
            self._root,
            f"{ruleset_id}@{version}",
            allow_proposal=allow_proposal,
        )
        return [
            {
                "document_id": doc.metadata.document_id,
                "title": doc.metadata.title,
                "document_type": doc.metadata.document_type,
                "reliability": doc.metadata.reliability,
                "status": doc.metadata.status,
                "markets": doc.metadata.markets,
                "content_sha256": doc.content_sha256,
                "body": doc.body,
            }
            for doc in ruleset.documents.values()
        ]

    def load_calibration_config(
        self,
        ruleset_id: str,
        version: str,
        *,
        allow_proposal: bool = False,
    ) -> dict[str, Any] | None:
        from ...rules import load_ruleset

        ruleset = load_ruleset(
            self._root,
            f"{ruleset_id}@{version}",
            allow_proposal=allow_proposal,
        )
        return ruleset.calibration_config

    def get_active_ruleset(self) -> dict[str, str]:
        from ...rules import active_ruleset

        active = active_ruleset(self._root)
        return {
            "ruleset_id": active.ruleset_id,
            "ruleset_version": active.ruleset_version,
        }