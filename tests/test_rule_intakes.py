from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from odds_journal.ledger import read_ledger
from odds_journal.rule_intakes import (
    ATOM_LEDGER,
    DISPOSITION_LEDGER,
    INTAKE_LEDGER,
    RuleEvaluatorV1,
    RuleSpecV1,
    atomize_intake,
    consolidate_intake_rules,
    ingest_intake,
    scaffold_intake_rules,
    set_atom_disposition,
    set_rule_disposition,
)
from odds_journal.ledger import sha256_json
from odds_journal.analytics import analytics_path, build_analytics
from odds_journal.experiments import (
    ExperimentAnalysisReceipt,
    ExperimentResearchBundle,
    ExperimentRuntimeConfigV6,
    _finalize,
    _read_config,
    experiment_report,
    score_experiment_research,
)
from odds_journal.markdown import MatchDocument
from odds_journal.models import PrimaryMarket, Selection
from odds_journal.services import finish_match, lock_match, parse_datetime

from .test_markdown_lock import prepare_match


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


def test_scaffold_removes_deferred_rule_from_build_and_generated_specs(tmp_path: Path) -> None:
    _proposal(tmp_path)
    source = tmp_path / "intake.md"
    source.write_text("赛前盘口差异需要人工确认。\n", encoding="utf-8")
    intake = ingest_intake(tmp_path, source)
    atom = atomize_intake(tmp_path, intake.intake_id)[0]
    rule_id = f"advisory-intake-{atom.atom_id[-12:]}"
    scaffold_intake_rules(tmp_path, intake.intake_id)

    set_rule_disposition(tmp_path, rule_id, "deferred", reason="暂不进入实验")
    scaffold_intake_rules(tmp_path, intake.intake_id)

    build = (tmp_path / "knowledge/rule-proposals/football-analysis/1.7.0/rule-build.yml").read_text(encoding="utf-8")
    assert rule_id not in build
    assert not (tmp_path / "knowledge/rule-proposals/football-analysis/1.7.0/rule-specs" / f"{rule_id}.yml").exists()


def test_scaffold_syncs_contract_six_build_hash(tmp_path: Path) -> None:
    proposal = tmp_path / "knowledge/rule-proposals/football-analysis/1.7.0"
    proposal.mkdir(parents=True)
    (proposal / "manifest.yml").write_text(
        "calibration_contract_version: 6\ncalibration_config_path: calibration/football-analysis-v6.yml\n",
        encoding="utf-8",
    )
    calibration = proposal / "calibration"
    calibration.mkdir()
    config = calibration / "football-analysis-v6.yml"
    config.write_text(
        "schema_version: 6\nrule_build_path: rule-build.yml\nrule_build_sha256: " + "0" * 64 + "\n",
        encoding="utf-8",
    )
    source = tmp_path / "intake.md"
    source.write_text("赛前盘口差异需要人工确认。\n", encoding="utf-8")
    intake = ingest_intake(tmp_path, source)
    atomize_intake(tmp_path, intake.intake_id)

    scaffold_intake_rules(tmp_path, intake.intake_id)

    from odds_journal.rules import sha256_file
    import yaml
    assert yaml.safe_load(config.read_text(encoding="utf-8"))["rule_build_sha256"] == sha256_file(proposal / "rule-build.yml")
    assert yaml.safe_load((proposal / "manifest.yml").read_text(encoding="utf-8"))["calibration_config_sha256"] == sha256_file(config)


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


def test_experiment_report_accepts_generated_advisory_ids(tmp_path: Path) -> None:
    match_base = tmp_path / "raw/matches/test-match"
    match_base.mkdir(parents=True)
    receipt = {
        "schema_version": 4, "receipt_id": "r", "match_id": "test-match",
        "prepared_at": "2026-08-05T12:00:00+08:00", "as_of": "2026-08-05T12:00:00+08:00",
        "kickoff_at": "2026-08-05T13:00:00+08:00", "official_ruleset_version": "1.5.0",
        "official_analysis_receipt_sha256": "0" * 64, "market_snapshots_sha256": "0" * 64,
        "experiment_ruleset_version": "1.7.0", "experiment_revision": 1, "proposal_sha256": "1" * 64,
        "snapshot_path": "missing", "calibration_config_sha256": "2" * 64, "precedence_sha256": "3" * 64,
        "profile_chain": ["global"], "applicable_rule_ids": [], "applicable_advisory_ids": [],
        "applicable_research_ids": [], "rule_build_sha256": "4" * 64,
        "receipt_sha256": "5" * 64,
    }
    import yaml
    (match_base / "experiment-analysis-receipt.yml").write_text(yaml.safe_dump(receipt), encoding="utf-8")
    bundle = {
        "schema_version": 2, "match_id": "test-match", "competition_code": "UNKNOWN",
        "experiment_ruleset_version": "1.7.0", "proposal_sha256": "1" * 64,
        "cutoff_at": "2026-08-05T12:00:00+08:00", "experiment_receipt_sha256": "5" * 64,
        "official_outlook_sha256": "6" * 64, "feature_snapshot_sha256": "7" * 64,
        "profile_chain": ["global"], "events": [{"advisory_id": "advisory-intake-abcdef123456", "pack_id": "rule-intake",
        "status": "triggered", "severity": "warning", "requires_ai_confirmation": True, "reason": "test"}], "bundle_sha256": "8" * 64,
    }
    (match_base / "experimental-advisories.yml").write_text(yaml.safe_dump(bundle), encoding="utf-8")
    assert experiment_report(tmp_path, "1.7.0")["advisories"]["advisory-intake-abcdef123456"]["triggered"] == 1


def test_semantic_atomizer_skips_front_matter_governance_and_headings(tmp_path: Path) -> None:
    source = tmp_path / "intake.md"
    source.write_text(
        "---\ntitle: staged\n---\n\n# 规则\n\n## 治理状态\n\n- 不得生效。\n\n## 用户提交原文\n\n### 观察项\n\n**规则名称**：仅标题\n\n1. **编号标题**\n\n同档位时序需要人工复核。\n",
        encoding="utf-8",
    )
    intake = ingest_intake(tmp_path, source)
    atoms = atomize_intake(tmp_path, intake.intake_id)
    assert len(atoms) == 1
    assert atoms[0].source_line_start == 19
    assert atoms[0].statement == "同档位时序需要人工复核。"


def test_consolidation_reconciles_atoms_and_retires_superseded_specs(tmp_path: Path) -> None:
    _proposal(tmp_path)
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("市场独立证据需要人工复核。\n", encoding="utf-8")
    second.write_text("赛后赔付趋势只能研究相关性。\n", encoding="utf-8")
    first_intake, second_intake = ingest_intake(tmp_path, first), ingest_intake(tmp_path, second)
    first_atom = atomize_intake(tmp_path, first_intake.intake_id)[0]
    second_atom = atomize_intake(tmp_path, second_intake.intake_id)[0]
    old_rule_id = f"advisory-intake-{first_atom.atom_id[-12:]}"
    scaffold_intake_rules(tmp_path, first_intake.intake_id)
    set_atom_disposition(tmp_path, second_atom.atom_id, "research_only", reason="仅赛后相关性研究")
    spec = RuleSpecV1(
        rule_id="research-payout-trend-causality-v1", rule_revision=1,
        track="research_only", effect="outcome_risk_pool", market_scope="cross_market",
        applies_to_profiles=["global"], source_atoms=[first_atom.atom_id, second_atom.atom_id],
        evaluator=RuleEvaluatorV1(kind="postmatch_only", config={"outcome_measure": "correlation"}),
        required_inputs=["auditable_price_series", "postmatch_result"], time_gate="postmatch",
        failure_mode="not_applicable", invalidation_conditions=["缺少独立结构化来源"],
    ).model_dump(mode="json")
    consolidation = {
        "consolidation_id": "payout-causality-v1", "rule_id": spec["rule_id"],
        "source_atoms": [first_atom.atom_id, second_atom.atom_id], "superseded_rule_ids": [old_rule_id],
        "rule_spec": spec, "merge_reason": "将重复提示收敛为赛后研究项", "consolidation_sha256": "0" * 64,
    }
    consolidation["consolidation_sha256"] = sha256_json({**consolidation, "consolidation_sha256": "0" * 64})
    manifest = {"schema_version": 1, "proposal_version": "1.7.0", "consolidations": [consolidation], "manifest_sha256": "0" * 64}
    manifest["manifest_sha256"] = sha256_json({**manifest, "manifest_sha256": "0" * 64})
    proposal = tmp_path / "knowledge/rule-proposals/football-analysis/1.7.0"
    (proposal / "rule-consolidations.yml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")

    consolidate_intake_rules(tmp_path)

    build = yaml.safe_load((proposal / "rule-build.yml").read_text(encoding="utf-8"))
    assert build["consolidation_manifest_sha256"] == manifest["manifest_sha256"]
    assert old_rule_id not in {item["rule_id"] for item in build["generated_rule_specs"]}
    assert spec["rule_id"] in {item["rule_id"] for item in build["generated_rule_specs"]}
    assert {item["atom_id"] for item in build["selected_atoms"]} == {first_atom.atom_id, second_atom.atom_id}
    assert not (proposal / "rule-specs" / f"{old_rule_id}.yml").exists()
    assert (proposal / "rule-specs" / f"{spec['rule_id']}.yml").exists()
    report = experiment_report(tmp_path, "1.7.0")
    assert report["rule_specs"][spec["rule_id"]] == {
        "consolidation_id": "payout-causality-v1",
        "source_atom_count": 2,
        "superseded_rule_ids": [old_rule_id],
        "research_only": True,
    }


def test_research_outcome_is_idempotent_and_projects_only_to_research_analytics(project_root: Path) -> None:
    path = prepare_match(project_root)
    lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.AWAY_HANDICAP,
        secondary=Selection.DRAW,
        confidence=0.62,
    )
    document = MatchDocument.load(path)
    raw_base = project_root / "raw/matches" / document.metadata.match_id
    receipt = _finalize(
        ExperimentAnalysisReceipt,
        {
            "schema_version": 4,
            "receipt_id": "experiment-receipt-test-match",
            "match_id": document.metadata.match_id,
            "prepared_at": datetime(2026, 7, 30, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            "as_of": datetime(2026, 7, 30, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            "kickoff_at": document.metadata.kickoff_at,
            "official_ruleset_version": "1.5.0",
            "official_analysis_receipt_sha256": "0" * 64,
            "market_snapshots_sha256": "1" * 64,
            "experiment_ruleset_version": "1.7.0",
            "experiment_revision": 3,
            "proposal_sha256": "2" * 64,
            "snapshot_path": "knowledge/rule-proposals/football-analysis/1.7.0",
            "calibration_config_sha256": "3" * 64,
            "precedence_sha256": "4" * 64,
            "profile_chain": ["global"],
            "applicable_rule_ids": [],
            "applicable_research_ids": ["research-payout-trend-causality-v1"],
            "rule_build_sha256": "5" * 64,
        },
        "receipt_sha256",
    )
    (raw_base / "experiment-analysis-receipt.yml").write_text(
        yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    bundle = _finalize(
        ExperimentResearchBundle,
        {
            "match_id": document.metadata.match_id,
            "experiment_receipt_sha256": receipt.receipt_sha256,
            "proposal_sha256": "2" * 64,
            "cutoff_at": datetime(2026, 7, 30, 19, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            "events": [{
                "rule_id": "research-payout-trend-causality-v1",
                "status": "not_applicable",
                "reason": "research_only 不产生赛前预测或提示结论",
            }],
        },
        "bundle_sha256",
    )
    (raw_base / "experimental-research.yml").write_text(
        yaml.safe_dump(bundle.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    finish_match(
        path,
        score="2-1",
        result_1x2="home",
        handicap_result="home_handicap",
        recorded_at=parse_datetime("2026-07-30T21:00:00+08:00"),
        key_events="无",
    )
    first = score_experiment_research(project_root, path)
    second = score_experiment_research(project_root, path)
    assert first is not None and second is not None
    assert first[1].outcome_sha256 == second[1].outcome_sha256
    assert [item.model_dump() for item in first[1].events] == [{
        "rule_id": "research-payout-trend-causality-v1",
        "status": "recorded",
        "reason": "赛前价格模式与赛后结果已封存；仅供人工相关性研究",
    }]

    build_analytics(project_root)
    with sqlite3.connect(analytics_path(project_root)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM experimental_research_events").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM analysis_runs").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM formal_outlook_market_statuses").fetchone() == (0,)
