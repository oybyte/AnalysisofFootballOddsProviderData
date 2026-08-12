"""Read RuleSpecs from the active immutable experiment snapshot only."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..domain.knowledge import MigrationDisposition, SourceInventoryItem


def read_rule_spec_inventory(
    root: Path,
    seen: set[str] | None = None,
) -> list[SourceInventoryItem]:
    """从活动实验不可变 snapshot 的 rule-specs 读取来源清单。

    解析每个 YAML 文件，提取 rule_id、track、effect、market_scope 等字段。
    所有 rule-spec 默认处置为 advisory（995 advisory + 1 research_only）。
    """
    import yaml

    if seen is None:
        seen = set()

    from ...experiments import active_experiment

    active = active_experiment(root)
    if active is None or active.ruleset_version != "1.7.0":
        raise ValueError("知识迁移需要已验证的 football-analysis@1.7.0 活动实验快照")
    specs_dir = root / active.snapshot_path / "rule-specs"
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
            ruleset_version=f"1.7.0@revision-{active.experiment_revision}",
            file_path=str(spec_file.relative_to(root)),
            file_sha256=file_sha256,
            reliability="experimental",
            markets=tuple([market_scope] if market_scope else ["cross_market"]),
            disposition=disposition,
            target_card_id=f"card-{rule_id}",
            reason=(
                f"active_snapshot={active.snapshot_path}; proposal_sha256={active.proposal_sha256}; "
                f"track={track}; evaluator={evaluator_kind}"
            ),
        ))

    return inventory
