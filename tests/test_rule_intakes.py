from __future__ import annotations

from pathlib import Path

import pytest

from odds_journal.ledger import read_ledger
from odds_journal.rule_intakes import (
    ATOM_LEDGER,
    DISPOSITION_LEDGER,
    INTAKE_LEDGER,
    RuleEvaluatorV1,
    RuleSpecV1,
    atomize_intake,
    ingest_intake,
    scaffold_intake_rules,
)
from odds_journal.experiments import ExperimentRuntimeConfigV6, _read_config


def _proposal(root: Path) -> None:
    target = root / "knowledge/rule-proposals/football-analysis/1.7.0"
    target.mkdir(parents=True)


def test_intake_is_hash_idempotent_and_atomization_does_not_reappend(tmp_path: Path) -> None:
    source = tmp_path / "intake.md"
    source.write_text("# 新规则\n\n2.5 球同档位水位需要人工确认。\n", encoding="utf-8")
    first = ingest_intake(tmp_path, source)
    second = ingest_intake(tmp_path, source)
    assert second.import_status == "duplicate"
    first_atoms = atomize_intake(tmp_path, first.intake_id)
    second_atoms = atomize_intake(tmp_path, first.intake_id)
    assert [item.atom_id for item in first_atoms] == [item.atom_id for item in second_atoms]
    assert len(read_ledger(tmp_path / INTAKE_LEDGER)) == 1
    assert len(read_ledger(tmp_path / ATOM_LEDGER)) == len(first_atoms)
    assert len(read_ledger(tmp_path / DISPOSITION_LEDGER)) == len(first_atoms)


def test_scaffold_merges_multiple_intakes_into_one_content_addressed_build(tmp_path: Path) -> None:
    _proposal(tmp_path)
    sources = []
    for index in range(2):
        source = tmp_path / f"intake-{index}.md"
        source.write_text(f"规则 {index}：赛前盘口差异需要人工确认。\n", encoding="utf-8")
        intake = ingest_intake(tmp_path, source)
        atomize_intake(tmp_path, intake.intake_id)
        scaffold_intake_rules(tmp_path, intake.intake_id)
        sources.append(intake)
    build = (tmp_path / "knowledge/rule-proposals/football-analysis/1.7.0/rule-build.yml").read_text(encoding="utf-8")
    assert all(item.intake_id in build for item in sources)
    assert build.count("rule_spec_sha256") == 2


def test_advisory_spec_cannot_become_prediction_output_or_override() -> None:
    with pytest.raises(ValueError, match="advisory"):
        RuleSpecV1(
            rule_id="advisory-test", rule_revision=1, track="advisory", effect="total_goals_pool",
            market_scope="total_goals", applies_to_profiles=["global"], source_atoms=["rule-atom-1234567890abcdef12345678"],
            evaluator=RuleEvaluatorV1(kind="manual_review", config={"question": "确认"}),
            time_gate="prematch", failure_mode="insufficient_data",
        )
    with pytest.raises(ValueError, match="不支持配置"):
        RuleEvaluatorV1(kind="threshold_series", config={
            "market": "total_goals", "price_key": "over_water", "operator": "<=", "threshold": 0.7,
            "minimum_exact_nodes": 3, "free_text": "not allowed",
        })


def test_contract_six_delegates_the_legacy_prediction_inventory() -> None:
    root = Path(__file__).resolve().parents[1]
    config, _ = _read_config(root / "knowledge/rule-proposals/football-analysis/1.7.0")
    assert isinstance(config, ExperimentRuntimeConfigV6)
    assert [item.rule_id for item in config.rules] == [item.rule_id for item in config.legacy.rules]
    assert len(config.applicable_rule_specs("UNKNOWN")) > 0
