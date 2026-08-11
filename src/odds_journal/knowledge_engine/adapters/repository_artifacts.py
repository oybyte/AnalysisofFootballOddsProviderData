"""Knowledge Engine 产物存储适配器。

提供内容寻址写入、追加事件、幂等键、事务和恢复。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class RepositoryArtifactStore:
    """仓库产物存储适配器。

    校验路径不得越出受管目录，不跟随越界符号链接。
    相同 ID、相同内容返回原产物；相同 ID、不同内容拒绝覆盖。
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def _validate_path(self, path: Path) -> Path:
        resolved = (self._root / path).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError:
            raise ValueError(f"产物路径越出受管目录：{path}")
        return resolved

    def write_artifact(
        self,
        artifact_id: str,
        content: dict[str, Any],
        subdir: str = "knowledge-engine",
    ) -> str:
        import yaml

        content_hash = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        rel_path = f"raw/knowledge-engine/{subdir}/{content_hash}.yml"
        target = self._validate_path(Path(rel_path))
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            existing = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            existing_hash = hashlib.sha256(
                json.dumps(existing, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            if existing_hash != content_hash:
                raise ValueError(
                    f"内容寻址冲突：相同 ID {artifact_id}，不同内容"
                )
            # 相同内容，幂等返回
            return rel_path

        from ...ledger import atomic_write_text

        payload = content.copy()
        payload["_artifact_id"] = artifact_id
        payload["_content_sha256"] = content_hash
        atomic_write_text(
            target,
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        )
        return rel_path

    def read_artifact(self, path: str) -> dict[str, Any]:
        import yaml

        target = self._validate_path(Path(path))
        if not target.is_file():
            raise FileNotFoundError(f"产物不存在：{path}")
        return yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    def append_event(
        self,
        ledger_path: str,
        event: dict[str, Any],
    ) -> None:
        from ...ledger import append_payloads

        target = self._validate_path(Path(ledger_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        append_payloads(target, [event])

    def validate_path(self, path: str) -> bool:
        try:
            self._validate_path(Path(path))
            return True
        except ValueError:
            return False