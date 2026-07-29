from __future__ import annotations

from pathlib import Path

import pytest

from odds_journal.analysis_context import AnalysisReceipt, RECEIPT_END, RECEIPT_START
from odds_journal.markdown import MatchDocument
from odds_journal.scenarios import (
    ScenarioObservation,
    ResolutionCollection,
    ScenarioResolution,
    add_live_scenario,
    add_resolution,
    add_scenario,
    parse_resolutions,
    parse_scenarios,
    revise_scenario,
    scenario_hash,
    set_resolution_collection,
    validate_scenario_workflow,
)
from odds_journal.services import finish_match, parse_datetime

from .test_analysis_context import factual_match


def _v2_receipt(match_id: str) -> str:
    receipt = AnalysisReceipt.model_validate(
        {
            "schema_version": 2,
            "match_id": match_id,
            "prepared_at": "2026-07-30T17:31:00+08:00",
            "as_of": "2026-07-30T17:30:00+08:00",
            "ruleset_id": "football-analysis",
            "ruleset_version": "1.1.0",
            "ruleset_sha256": "1" * 64,
            "markets": ["handicap"],
            "query": {},
            "filters": {},
            "index_schema_version": 3,
            "chunker_version": 2,
            "prematch_facts_sha256": "2" * 64,
            "retrieval_contract_version": 2,
            "trusted_instruction": {
                "document_id": "ai-analysis-instruction",
                "source_path": "ai/analysis_prompt.md",
                "effective_at": "2026-07-29T12:00:00+08:00",
                "reliability": "established",
                "content_sha256": "3" * 64,
                "chunk_ids": ["instruction-1"],
            },
            "required_documents": [],
            "conditional_documents": [],
            "excluded_documents": [],
            "context_sha256": "4" * 64,
        }
    )
    import yaml

    payload = yaml.safe_dump(receipt.model_dump(mode="json"), allow_unicode=True, sort_keys=False)
    return f"{RECEIPT_START}\n### 规则检索回执\n\n```yaml\n{payload}```\n{RECEIPT_END}"


def _observation(identity: str = "scenario-static-1") -> ScenarioObservation:
    return ScenarioObservation(
        scenario_instance_id=identity,
        scenario_type_id="static-line-water-movement",
        detected_at=parse_datetime("2026-07-30T17:31:00+08:00"),
        as_of=parse_datetime("2026-07-30T17:30:00+08:00"),
        market="handicap",
        observed_facts=["盘口未变，上盘水位下降"],
        hypothesis_a="赔付保护",
        hypothesis_b="热度吸引",
        selected_interpretation="证据不足，继续观察",
        pass_condition="缺少多机构交叉验证",
    )


def _prepared_v2_match(root: Path) -> Path:
    path = factual_match(root)
    document = MatchDocument.load(path)
    reasoning = document.sections["prematch-reasoning"]
    reasoning = reasoning.replace("<!-- analysis-content:start -->", _v2_receipt(document.metadata.match_id) + "\n\n<!-- analysis-content:start -->")
    document.replace_section("prematch-reasoning", reasoning)
    document.save()
    return path


def test_scenario_add_and_revise_before_lock(project_root: Path) -> None:
    path = _prepared_v2_match(project_root)
    add_scenario(path, _observation())
    first = parse_scenarios(MatchDocument.load(path).sections["prematch-reasoning"], required=True)
    assert first is not None and len(first.instances) == 1
    original_hash = scenario_hash(first)

    revised = _observation().model_copy(update={"selected_interpretation": "暂偏向赔付保护"})
    revise_scenario(path, revised.scenario_instance_id, revised)
    second = parse_scenarios(MatchDocument.load(path).sections["prematch-reasoning"], required=True)
    assert second is not None and second.instances[0].selected_interpretation == "暂偏向赔付保护"
    assert scenario_hash(second) != original_hash


def test_scenario_times_and_unknown_type_are_rejected() -> None:
    with pytest.raises(ValueError, match="不得早于"):
        _observation().model_copy(
            update={"detected_at": parse_datetime("2026-07-30T17:29:00+08:00")}
        ).model_validate(
            _observation().model_copy(
                update={"detected_at": parse_datetime("2026-07-30T17:29:00+08:00")}
            ).model_dump()
        )
    with pytest.raises(ValueError, match="unclassified"):
        ScenarioObservation.model_validate(
            {**_observation().model_dump(), "scenario_type_id": "invented-pattern"}
        )


def test_locked_match_only_accepts_live_scenario(project_root: Path) -> None:
    path = _prepared_v2_match(project_root)
    add_scenario(path, _observation())
    document = MatchDocument.load(path)
    document.metadata = document.metadata.model_copy(
        update={
            "status": "locked",
            "data_cutoff_at": parse_datetime("2026-07-30T17:40:00+08:00"),
            "locked_at": parse_datetime("2026-07-30T17:40:00+08:00"),
            "prematch_lock_sha256": document.prematch_hash(),
            "primary_market": "handicap",
            "primary_selection": "home_handicap",
            "confidence": 0.5,
        }
    )
    document.save()

    with pytest.raises(ValueError, match="锁定后"):
        revise_scenario(path, "scenario-static-1", _observation())
    live = _observation("scenario-live-1").model_copy(
        update={
            "detected_at": parse_datetime("2026-07-30T18:00:00+08:00"),
            "as_of": parse_datetime("2026-07-30T18:00:00+08:00"),
        }
    )
    add_live_scenario(path, live)
    assert "scenario-live-1" in MatchDocument.load(path).sections["live-update"]


def test_reviewed_v2_requires_resolution_for_every_scenario(project_root: Path) -> None:
    path = _prepared_v2_match(project_root)
    add_scenario(path, _observation())
    document = MatchDocument.load(path)
    lock_time = parse_datetime("2026-07-30T17:40:00+08:00")
    document.metadata = document.metadata.model_copy(
        update={
            "status": "finished",
            "data_cutoff_at": lock_time,
            "locked_at": lock_time,
            "prematch_lock_sha256": document.prematch_hash(),
            "primary_market": "handicap",
            "primary_selection": "home_handicap",
            "confidence": 0.5,
            "score": "1-0",
            "result_1x2": "home",
            "total_goals": 1,
            "result_recorded_at": parse_datetime("2026-07-30T21:00:00+08:00"),
        }
    )
    document.save()
    resolution = ScenarioResolution(
        scenario_resolution_id="resolution-static-1",
        scenario_instance_id="scenario-static-1",
        resolved_at=parse_datetime("2026-07-30T21:10:00+08:00"),
        actual_development="主队一球取胜",
        winning_hypothesis="a",
        evidence_disposition="defer",
        review_note="等待复盘后决定是否进入证据台账",
    )
    with pytest.raises(ValueError, match="prepare-review"):
        add_resolution(path, resolution)
    document = MatchDocument.load(path)
    document.replace_section(
        "postmatch-review",
        set_resolution_collection(
            document.sections["postmatch-review"],
            ResolutionCollection(resolutions=[resolution]),
        ),
    )
    assert parse_resolutions(document.sections["postmatch-review"], required=True)
    document.metadata = document.metadata.model_copy(
        update={
            "status": "reviewed",
            "reviewed_at": parse_datetime("2026-07-30T21:20:00+08:00"),
        }
    )
    assert validate_scenario_workflow(document, require_v2=True) == []
