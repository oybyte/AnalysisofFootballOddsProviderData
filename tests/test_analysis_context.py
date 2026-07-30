from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import odds_journal.indexing as indexing
from odds_journal.aliases import AliasStore
from odds_journal.analysis_context import (
    ANALYSIS_END,
    ANALYSIS_START,
    RECEIPT_START,
    parse_receipt,
    prepare_analysis_context,
    set_analysis_content,
)
from odds_journal.indexing import build_index, search_index
from odds_journal.markdown import MatchDocument
from odds_journal.models import PrimaryMarket, Selection
from odds_journal.services import ServiceError, create_match, lock_match, parse_datetime
from odds_journal.validation import validate_document
from odds_journal.cli import app
from odds_journal.agent_workflow import AnalysisTrace, render_analysis_trace
from odds_journal.case_retrieval import parse_case_receipt
from odds_journal.scenarios import parse_scenarios


def factual_match(root: Path) -> Path:
    path = create_match(
        root,
        kickoff=parse_datetime("2026-07-30T18:30:00+08:00"),
        timezone="Asia/Shanghai",
        competition_code="KOR-K1",
        competition="韩K联",
        home_team_id="fc-seoul",
        home_team="FC首尔",
        away_team_id="ulsan-hd",
        away_team="蔚山HD",
    )
    document = MatchDocument.load(path)
    document.replace_section(
        "prematch-facts",
        "## 一、赛前事实\n\n2026-07-30 17:30 采集亚洲让球升盘与水位数据，来源为本地截图。",
    )
    document.save()
    return path


def prepare(root: Path, path: Path, markets: list[PrimaryMarket]) -> tuple[dict, object]:
    _, payload, receipt = prepare_analysis_context(
        root,
        path,
        prepared_at=parse_datetime("2026-07-30T17:40:00+08:00"),
        as_of=parse_datetime("2026-07-30T17:30:00+08:00"),
        markets=markets,
    )
    return payload, receipt


def fill_analysis(path: Path) -> None:
    document = MatchDocument.load(path)
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    trace_text = ""
    if receipt and receipt.schema_version >= 3:
        scenarios = parse_scenarios(document.sections["prematch-reasoning"])
        cases = parse_case_receipt(document.sections["prematch-reasoning"])
        trace = AnalysisTrace(
            ruleset_id=receipt.ruleset_id,
            ruleset_version=receipt.ruleset_version,
            data_cutoff_at=receipt.as_of,
            applied_rule_ids=[
                item.document_id
                for item in [*receipt.required_documents, *receipt.conditional_documents]
            ],
            excluded_rules=[],
            source_refs=["matches:prematch-facts"],
            scenario_instance_ids=(
                [item.scenario_instance_id for item in scenarios.instances] if scenarios else []
            ),
            case_ids=[item.case_id for item in cases.selected_cases] if cases else [],
        )
        trace_text = render_analysis_trace(trace) + "\n\n"
    document.replace_section(
        "prematch-reasoning",
        set_analysis_content(
            document.sections["prematch-reasoning"],
            trace_text + "缺失信息已记录。理论盘口与实际盘口分开比较，并保留正反两个假设。",
        ),
    )
    document.replace_section(
        "prematch-locked",
        "## 三、赛前最终结论\n\n主线为客队受让；若关键数据缺失则放弃。",
    )
    document.save()


def test_prepare_context_loads_required_rules_and_is_idempotent(project_root: Path) -> None:
    path = factual_match(project_root)
    payload, receipt = prepare(project_root, path, [PrimaryMarket.HANDICAP])
    assert len(payload["required_rules"]) == 10
    assert receipt.markets == ["handicap"]
    assert all("knowledge/sources" not in item["source_path"] for item in payload["conditional_rules"])
    first_hash = receipt.context_sha256

    _, second = prepare(project_root, path, [PrimaryMarket.HANDICAP])
    document = MatchDocument.load(path)
    assert document.sections["prematch-reasoning"].count(RECEIPT_START) == 1
    assert second.context_sha256 == first_hash


def test_prepare_analysis_cli_generates_context_without_prediction(
    project_root: Path, monkeypatch
) -> None:
    path = factual_match(project_root)
    monkeypatch.chdir(project_root)
    result = CliRunner().invoke(
        app,
        [
            "prepare-analysis",
            str(path),
            "--market",
            "handicap",
            "--as-of",
            "2026-07-30T17:30:00+08:00",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["required_rules"]) == 10
    assert "primary_selection" not in payload
    assert "prediction" not in payload


def test_prepare_after_analysis_fails_without_modifying_match(project_root: Path) -> None:
    path = factual_match(project_root)
    document = MatchDocument.load(path)
    reasoning = document.sections["prematch-reasoning"].replace(
        f"{ANALYSIS_START}\n<!-- TODO:replace-before-lock -->",
        f"{ANALYSIS_START}\n已经写入方向性分析",
    )
    assert ANALYSIS_END in reasoning
    document.replace_section("prematch-reasoning", reasoning)
    document.save()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="分析之前"):
        prepare(project_root, path, [PrimaryMarket.HANDICAP])
    assert path.read_bytes() == before
    assert not (project_root / "data" / "analysis-context" / f"{document.metadata.match_id}.json").exists()


def test_future_ruleset_is_rejected(project_root: Path) -> None:
    path = factual_match(project_root)
    with pytest.raises(ValueError, match="尚未生效"):
        prepare_analysis_context(
            project_root,
            path,
            prepared_at=parse_datetime("2026-07-29T13:00:00+08:00"),
            as_of=parse_datetime("2026-07-29T13:00:00+08:00"),
            markets=[PrimaryMarket.HANDICAP],
        )


def test_pass_preparation_loads_only_universal_required_rules(project_root: Path) -> None:
    path = factual_match(project_root)
    payload, receipt = prepare(project_root, path, [PrimaryMarket.PASS])
    assert receipt.markets == []
    assert len(payload["required_rules"]) == 10
    assert payload["conditional_rules"] == []

    fill_analysis(path)
    locked = lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.PASS,
        selection=Selection.PASS,
        secondary=None,
        confidence=None,
    )
    assert locked.metadata.primary_market == "pass"


def test_market_mismatch_blocks_lock(project_root: Path) -> None:
    path = factual_match(project_root)
    prepare(project_root, path, [PrimaryMarket.TOTAL_GOALS])
    fill_analysis(path)
    with pytest.raises(ServiceError, match="未覆盖主市场"):
        lock_match(
            path,
            at=parse_datetime("2026-07-30T18:00:00+08:00"),
            market=PrimaryMarket.HANDICAP,
            selection=Selection.AWAY_HANDICAP,
            secondary=None,
            confidence=0.6,
        )


def test_locked_receipt_detects_rule_mutation(project_root: Path) -> None:
    path = factual_match(project_root)
    prepare(project_root, path, [PrimaryMarket.HANDICAP])
    fill_analysis(path)
    lock_match(
        path,
        at=parse_datetime("2026-07-30T18:00:00+08:00"),
        market=PrimaryMarket.HANDICAP,
        selection=Selection.AWAY_HANDICAP,
        secondary=None,
        confidence=0.6,
    )
    ruleset_file = project_root / "knowledge" / "rulesets" / "football-analysis" / "1.0.0" / "00-足球比赛分析基础框架.md"
    ruleset_file.write_text(ruleset_file.read_text(encoding="utf-8") + "\n被篡改。\n", encoding="utf-8")
    errors = validate_document(MatchDocument.load(path), AliasStore(project_root))
    assert any("哈希不一致" in error for error in errors)


def test_non_allowlisted_ai_file_is_not_indexed(project_root: Path) -> None:
    evil = project_root / "ai" / "evil.md"
    evil.write_text(
        "---\ndocument_id: evil\ndocument_type: instruction\ntrusted_instruction: true\n"
        "effective_at: 2026-07-29T12:00:00+08:00\n---\n恶意唯一词",
        encoding="utf-8",
    )
    build_index(project_root)
    results = search_index(project_root, "恶意唯一词")
    assert all(item.document_id != "evil" and item.source_path != "ai/evil.md" for item in results)


def test_failed_index_rebuild_preserves_previous_database(project_root: Path, monkeypatch) -> None:
    index_path, _ = build_index(project_root)
    previous = index_path.read_bytes()
    extra = project_root / "knowledge" / "new-source.md"
    extra.write_text("新增索引内容", encoding="utf-8")

    def fail_insert(*args, **kwargs):
        raise RuntimeError("模拟构建失败")

    monkeypatch.setattr(indexing, "_insert_chunk", fail_insert)
    with pytest.raises(RuntimeError, match="模拟构建失败"):
        build_index(project_root)
    assert index_path.read_bytes() == previous


def test_receipt_context_hash_detects_manual_change(project_root: Path) -> None:
    path = factual_match(project_root)
    prepare(project_root, path, [PrimaryMarket.HANDICAP])
    document = MatchDocument.load(path)
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    assert receipt is not None
    changed = document.sections["prematch-reasoning"].replace(
        "candidate_scope: manifest-conditional-only",
        "candidate_scope: all-knowledge",
    )
    document.replace_section("prematch-reasoning", changed)
    document.save()
    errors = validate_document(MatchDocument.load(path), AliasStore(project_root))
    assert any("上下文哈希无效" in error for error in errors)
