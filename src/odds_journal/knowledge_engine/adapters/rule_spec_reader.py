"""Knowledge Engine RuleSpec 文件适配器。

从 1.7.0 rule-specs/ 目录读取 YAML 文件，解析为 SourceInventoryItem。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..domain.knowledge import MigrationDisposition, SourceInventoryItem


def read_rule_spec_inventory(
    root: Path,
    seen: set[str] | None = None,
) -> list[SourceInventoryItem]:
    """从 1.7.0 rule-specs/ 目录读取 RuleSpec 来源清单。

    解析每个 YAML 文件，提取 rule_id、track、effect、market_scope 等字段。
    所有 rule-spec 默认处置为 advisory（995 advisory + 1 research_only）。
    """
    import yaml

    if seen is None:
        seen = set()

    specs_dir = (
        root / "knowledge/rule-proposals/football-analysis/1.7.0/rule-specs"
    )
    if not specs_dir.is_dir():
        return []

    inventory: list[SourceInventoryItem] = []
    for spec_file in sorted(specs_dir.glob("*.yml")):
        data = yaml.safe_load(spec_file.read_text(encoding="utf-8")) or {}
        rule_id = data.get("rule_id", spec_file.stem)
        if rule_id in seen:
            continue
        seen.add(rule_id)

        track = data.get("track", "advisory")
        market_scope = data.get("market_scope", "cross_market")
        evaluator_kind = data.get("evaluator", {}).get("kind", "unknown")

        disposition = MigrationDisposition.ADVISORY
        if track == "research_only":
            disposition = MigrationDisposition.RESEARCH

        file_sha256 = hashlib.sha256(spec_file.read_bytes()).hexdigest()

        inventory.append(SourceInventoryItem(
            rule_id=rule_id,
            document_id=rule_id,
            document_type="rule-spec",
            ruleset_id="football-analysis",
            ruleset_version="1.7.0",
            file_path=str(spec_file.relative_to(root)),
            file_sha256=file_sha256,
            reliability="experimental",
            markets=tuple([market_scope] if market_scope else ["cross_market"]),
            disposition=disposition,
            target_card_id=f"card-{rule_id}",
            reason=f"1.7.0 rule-spec: track={track}, evaluator={evaluator_kind}",
        ))

    return inventory