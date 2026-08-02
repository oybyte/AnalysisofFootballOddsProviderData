from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from odds_journal.historical_certification import (
    HistoricalCaseCertification,
    HistoricalCertificationManifest,
    HistoricalMarketNode,
    _validate_atom_ids,
)
from odds_journal.validation_studies import ValidationCasePayload, ValidationStudy


TZ = ZoneInfo("Asia/Shanghai")


def node(phase: str, hour: int) -> HistoricalMarketNode:
    return HistoricalMarketNode(
        node_id=f"node-{phase}",
        phase=phase,
        observed_at=datetime(2026, 7, 28, hour, tzinfo=TZ),
        provider="macau",
        market="handicap",
        line="-0.75",
        odds_format="hong_kong",
        raw_value="主 0.88 / 客 0.94",
        source_atom_id="doubao-2026-07-28-text-a00001",
    )


def certified_case() -> HistoricalCaseCertification:
    return HistoricalCaseCertification(
        certification_id="certified-case-1",
        case_id="legacy-rosenborg-fredrikstad",
        expected_case_revision=6,
        decision="certified",
        kickoff_at=datetime(2026, 7, 28, 20, tzinfo=TZ),
        result_observed_at=datetime(2026, 7, 28, 22, tzinfo=TZ),
        prematch_atom_ids=["doubao-2026-07-28-text-a00001"],
        postmatch_atom_ids=["doubao-2026-07-28-text-a00002"],
        result_atom_ids=["doubao-2026-07-28-text-a00003"],
        market_snapshots=[node("opening", 10), node("mid", 14), node("late", 18)],
        review_reason="赛前盘口节点和赛后赛果均可回溯。",
    )


def test_certification_requires_three_prematch_phases() -> None:
    data = certified_case().model_dump()
    data["market_snapshots"] = data["market_snapshots"][:2]
    with pytest.raises(ValueError, match="opening/mid/late"):
        HistoricalCaseCertification.model_validate(data)


def test_certification_rejects_post_kickoff_node() -> None:
    data = certified_case().model_dump()
    data["market_snapshots"][2]["observed_at"] = datetime(2026, 7, 28, 21, tzinfo=TZ)
    with pytest.raises(ValueError, match="早于开赛"):
        HistoricalCaseCertification.model_validate(data)


def test_certification_manifest_rejects_duplicate_case() -> None:
    item = certified_case()
    with pytest.raises(ValueError, match="重复案例"):
        HistoricalCertificationManifest(
            batch_id="batch-1",
            source_family_id="doubao-2026-07-28",
            cases=[item, item.model_copy(update={"certification_id": "certified-case-2"})],
        )


def test_atom_validation_accepts_new_source_inventory_fields(tmp_path: Path) -> None:
    inventory = tmp_path / "knowledge/extraction/doubao-football-history-2026-08-02/text-inventory.jsonl"
    inventory.parent.mkdir(parents=True)
    inventory.write_text(
        json.dumps(
            {
                "atom_id": "doubao-football-history-2026-08-02-text-a000001",
                "source_family_id": "doubao-football-history-2026-08-02",
                "unit_no": 1,
                "canonical_text": "历史原文",
                "duplicate_of": None,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    _validate_atom_ids(
        tmp_path,
        "doubao-football-history-2026-08-02",
        ["doubao-football-history-2026-08-02-text-a000001"],
    )


def test_historical_validation_payload_requires_auditable_fields() -> None:
    with pytest.raises(ValueError, match="必须记录认证"):
        ValidationCasePayload(
            validation_case_id="legacy-validation-1",
            study_id="historical-study-1",
            case_id="legacy-rosenborg-fredrikstad",
            case_cluster_id="legacy-rosenborg-fredrikstad",
            evidence_ref="certification:certified-case-1",
            observed_at=datetime(2026, 7, 29, 12, tzinfo=TZ),
            relation="not_applicable",
            eligibility="ineligible",
            ineligibility_reasons=["未达到阈值"],
            summary="保留未触发记录。",
            case_type="certified_legacy_case",
        )


def test_v3_study_accepts_certified_legacy_case_path() -> None:
    study = ValidationStudy(
        schema_version=3,
        study_id="historical-study-1",
        rule_id="deep-line-stable-cover-v1",
        proposal_sha256="a" * 64,
        status="frozen_template",
        frozen_at=datetime(2026, 8, 2, 12, tzinfo=TZ),
        target_definition="实验规则触发后的表现。",
        denominator_definition="完成历史再认证且满足规则输入的案例。",
        baseline_definition="同市场基础排序表现。",
        baseline_rate=0.33,
        approved_by="lcz",
        primary_market="handicap",
        enrollment_requirements=["三节点"],
        support_definition="支持。",
        counterexample_definition="反例。",
        ambiguous_definition="模糊。",
        not_applicable_definition="不适用。",
        cluster_key="case_id",
        minimum_independent_cases=30,
        allowed_case_types=["certified_legacy_case"],
    )
    assert study.allowed_case_types == ["certified_legacy_case"]
