from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

import odds_journal.rules_release as release_module
from odds_journal.aliases import AliasStore
from odds_journal.analysis_workflow import restart_analysis
from odds_journal.analysis_context import prepare_analysis_context
from odds_journal.case_retrieval import parse_case_receipt, retrieve_cases
from odds_journal.cases import _case_relative_path, latest_cases
from odds_journal.evidence import EvidencePayload, append_evidence, build_evidence_report
from odds_journal.markdown import MatchDocument
from odds_journal.models import EvaluationValue, PrimaryMarket, Selection
from odds_journal.review_context import (
    REVIEW_RECEIPT_START,
    parse_review_receipt,
    prepare_review_context,
    set_review_content,
    validate_review_receipt,
)
from odds_journal.rules import active_ruleset, load_ruleset
from odds_journal.rules_release import release_ruleset, validate_ruleset_proposal
from odds_journal.scenarios import RESOLUTIONS_START, set_no_scenario
from odds_journal.services import (
    ServiceError,
    finish_match,
    lock_match,
    parse_datetime,
    review_match,
)
from odds_journal.validation import validate_document

from .test_analysis_context import factual_match, fill_analysis
from .test_markdown_lock import prepare_match


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _copy_proposal_inputs(root: Path) -> None:
    repository = repository_root()
    shutil.copytree(
        repository / "knowledge/rule-proposals",
        root / "knowledge/rule-proposals",
    )
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    shutil.copy2(
        repository / "reports/历史资料提取覆盖报告.json",
        reports / "历史资料提取覆盖报告.json",
    )
    evidence = root / "knowledge/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repository / "knowledge/evidence/rule-evidence.jsonl",
        evidence / "rule-evidence.jsonl",
    )


def _activate_v2(project_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _copy_proposal_inputs(project_root)
    extraction = project_root / "knowledge/extraction/doubao-2026-07-28"
    extraction.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        repository_root()
        / "knowledge/extraction/doubao-2026-07-28/text-inventory.jsonl",
        extraction / "text-inventory.jsonl",
    )
    monkeypatch.setattr(
        release_module,
        "validate_ruleset_proposal",
        lambda root, version: {root / "proposal": []},
    )
    release_ruleset(
        project_root,
        "1.1.0",
        approved_by="test-reviewer",
        effective_at=parse_datetime("2026-07-29T15:00:00+08:00"),
    )


def test_repository_proposal_is_detailed_and_valid() -> None:
    root = repository_root()
    results = validate_ruleset_proposal(root, "1.1.0")
    assert all(not errors for errors in results.values())
    documents = sorted(
        (root / "knowledge/rule-proposals/football-analysis/1.1.0").glob("**/*.md")
    )
    assert len(documents) == 21
    for path in documents:
        text = path.read_text(encoding="utf-8")
        assert len(text.splitlines()) >= 130
        assert "claim-doubao-2026-07-28" in text
        assert "## 判断矩阵" in text
        assert "## 反例" in text


def test_schema_four_proposal_hash_covers_calibration_yaml(tmp_path: Path) -> None:
    source = repository_root() / "knowledge/rule-proposals/football-analysis/1.2.0"
    target = tmp_path / "proposal"
    shutil.copytree(source, target)
    before = release_module._proposal_sha256(target)
    config = target / "calibration/low-stability-v1.yml"
    config.write_text(config.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")
    assert release_module._proposal_sha256(target) != before


def test_repository_active_ruleset_is_published_v1_1() -> None:
    root = repository_root()
    active = active_ruleset(root)
    ruleset = load_ruleset(root)
    assert active.ruleset_version == "1.1.0"
    assert ruleset.manifest.schema_version == 3
    assert ruleset.manifest.published
    assert len(ruleset.required) == 13
    assert len(ruleset.conditional) == 8


def test_release_failure_keeps_old_active_and_can_resume(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_proposal_inputs(project_root)
    rules_root = project_root / "knowledge/rulesets/football-analysis"
    active_path = rules_root / "active.yml"
    active_before = active_path.read_bytes()
    v1_hashes = {
        path.relative_to(rules_root / "1.0.0").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (rules_root / "1.0.0").glob("**/*")
        if path.is_file()
    }
    monkeypatch.setattr(
        release_module,
        "validate_ruleset_proposal",
        lambda root, version: {root / "proposal": []},
    )
    monkeypatch.setattr(
        release_module,
        "build_index",
        lambda root: (_ for _ in ()).throw(RuntimeError("index failed")),
    )
    with pytest.raises(RuntimeError, match="index failed"):
        release_ruleset(
            project_root,
            "1.1.0",
            approved_by="test-reviewer",
            effective_at=parse_datetime("2026-07-29T15:00:00+08:00"),
        )
    target = rules_root / "1.1.0"
    assert target.exists()
    assert active_path.read_bytes() == active_before
    detached_hashes = {
        path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in target.glob("**/*")
        if path.is_file()
    }

    monkeypatch.setattr(release_module, "build_index", lambda root: (root / "index", 0))
    release_ruleset(
        project_root,
        "1.1.0",
        approved_by="test-reviewer",
        effective_at=parse_datetime("2026-07-29T16:00:00+08:00"),
    )
    active = yaml.safe_load(active_path.read_text(encoding="utf-8"))
    assert active["ruleset_version"] == "1.1.0"
    assert detached_hashes == {
        path.relative_to(target).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in target.glob("**/*")
        if path.is_file()
    }
    assert v1_hashes == {
        path.relative_to(rules_root / "1.0.0").as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (rules_root / "1.0.0").glob("**/*")
        if path.is_file()
    }


def test_v2_full_lifecycle_and_frozen_case_receipt(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _activate_v2(project_root, monkeypatch)
    path = factual_match(project_root)
    prepared_at = parse_datetime("2026-07-30T17:40:00+08:00")
    as_of = parse_datetime("2026-07-30T17:30:00+08:00")
    _, payload, receipt = prepare_analysis_context(
        project_root,
        path,
        prepared_at=prepared_at,
        as_of=as_of,
        markets=[PrimaryMarket.HANDICAP],
    )
    assert receipt.schema_version == 3
    assert len(payload["required_rules"]) == 13
    set_no_scenario(path, "当前资料不足以识别稳定的可复用盘路结构")
    retrieve_cases(project_root, path, prepared_at=prepared_at)

    document = MatchDocument.load(path)
    document.replace_section(
        "prematch-facts",
        document.sections["prematch-facts"] + "\n补充：17:30 前未发现可核验伤停变化。",
    )
    document.save()
    prepare_analysis_context(
        project_root,
        path,
        prepared_at=parse_datetime("2026-07-30T17:45:00+08:00"),
        as_of=as_of,
        markets=[PrimaryMarket.HANDICAP],
    )
    assert parse_case_receipt(MatchDocument.load(path).sections["prematch-reasoning"]) is None
    retrieve_cases(project_root, path, prepared_at=parse_datetime("2026-07-30T17:46:00+08:00"))

    cases = project_root / "knowledge/cases/legacy/unknown"
    cases.mkdir(parents=True, exist_ok=True)
    source_case = latest_cases(repository_root())["legacy-seoul-ulsan"]
    shutil.copy2(
        repository_root() / _case_relative_path(source_case),
        cases / "legacy-seoul-ulsan.md",
    )
    with pytest.raises(ServiceError, match="语料已变化"):
        lock_match(
            path,
            at=parse_datetime("2026-07-30T18:00:00+08:00"),
            market=PrimaryMarket.HANDICAP,
            selection=Selection.AWAY_HANDICAP,
            secondary=None,
            confidence=0.6,
        )
    _, _, refreshed_cases = retrieve_cases(
        project_root,
        path,
        prepared_at=parse_datetime("2026-07-30T17:50:00+08:00"),
    )
    assert any(item.case_id == "legacy-seoul-ulsan" for item in refreshed_cases.selected_cases)
    fill_analysis(path)
    lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.AWAY_HANDICAP,
        secondary=Selection.DRAW,
        confidence=0.62,
    )

    source_case = latest_cases(repository_root())["legacy-hjk-tps"]
    shutil.copy2(repository_root() / _case_relative_path(source_case), cases / "legacy-hjk-tps.md")
    locked = MatchDocument.load(path)
    assert validate_document(locked, AliasStore(project_root)) == []

    finish_match(
        path,
        score="1-1",
        result_1x2="draw",
        handicap_result="away_handicap",
        recorded_at=parse_datetime("2026-07-30T21:00:00+08:00"),
        key_events="无红牌",
    )
    prepare_review_context(
        project_root,
        path,
        prepared_at=parse_datetime("2026-07-30T21:10:00+08:00"),
    )
    review_document = MatchDocument.load(path)
    review = review_document.sections["postmatch-review"]
    assert review.index(REVIEW_RECEIPT_START) < review.index(RESOLUTIONS_START)

    original_result = review_document.sections["result"]
    review_document.replace_section("result", original_result + "\n篡改")
    assert any(
        "赛果正文" in error
        for error in validate_review_receipt(project_root, review_document)
    )
    review_document.replace_section("result", original_result)
    review_document.replace_section(
        "postmatch-review",
        set_review_content(
            review_document.sections["postmatch-review"],
            "主线判断与赛果一致；本场未识别稳定场景，不据此提升任何经验规则。",
        ),
    )
    review_document.save()
    review_match(
        path,
        reviewed_at=parse_datetime("2026-07-30T21:20:00+08:00"),
        primary=EvaluationValue.CORRECT,
        handicap=EvaluationValue.CORRECT,
        total_goals_range=EvaluationValue.NOT_APPLICABLE,
        score_range=EvaluationValue.PARTIAL,
        confidence_calibration=EvaluationValue.PARTIAL,
        changed_main=False,
    )
    reviewed = MatchDocument.load(path)
    assert validate_document(reviewed, AliasStore(project_root)) == []

    ruleset = load_ruleset(project_root, "football-analysis@1.1.0")
    rule = ruleset.documents["dual-hypothesis-evidence"]
    append_evidence(
        project_root,
        EvidencePayload(
            evidence_id="ev-v2-lifecycle",
            rule_id=rule.metadata.document_id,
            observed_ruleset_version="1.1.0",
            rule_content_sha256=rule.content_sha256,
            case_type="match",
            case_id=reviewed.metadata.match_id,
            case_cluster_id=reviewed.metadata.match_id,
            market="handicap",
            target_definition="是否完整保留双向假设与反证",
            baseline_definition="未使用双向假设的分析流程",
            relation="support",
            eligibility="eligible",
            summary="流程字段完整，作为方法执行证据记录。",
            reviewed_by="test-reviewer",
        ),
        recorded_at=parse_datetime("2026-07-30T21:30:00+08:00"),
    )
    _, _, report = build_evidence_report(project_root)
    assert report["rules"]["dual-hypothesis-evidence"]["eligible_independent_cases"] == 1


def test_restart_archives_reasoning_and_conclusion(project_root: Path) -> None:
    path = prepare_match(project_root)
    before = MatchDocument.load(path)
    facts = before.sections["prematch-facts"]
    old_reasoning = before.sections["prematch-reasoning"]
    old_conclusion = before.sections["prematch-locked"]
    archive = restart_analysis(
        path,
        reason="赛前事实来源发生变化",
        restarted_at=parse_datetime("2026-07-30T17:55:00+08:00"),
    )
    archived = archive.read_text(encoding="utf-8")
    assert old_reasoning.strip() in archived
    assert old_conclusion.strip() in archived
    restarted = MatchDocument.load(path)
    assert restarted.sections["prematch-facts"] == facts
    assert "rules-retrieval:start" not in restarted.sections["prematch-reasoning"]
    assert "TODO:replace-before-lock" in restarted.sections["prematch-reasoning"]
    assert "TODO:replace-before-lock" in restarted.sections["prematch-locked"]


def test_locked_v1_receipt_survives_v2_activation(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = prepare_match(project_root)
    lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.AWAY_HANDICAP,
        secondary=None,
        confidence=0.6,
    )
    _activate_v2(project_root, monkeypatch)
    locked = MatchDocument.load(path)
    assert validate_document(locked, AliasStore(project_root)) == []
