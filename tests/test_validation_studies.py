from __future__ import annotations

from pathlib import Path

import pytest

from odds_journal.services import parse_datetime
from odds_journal.validation_studies import (
    ValidationCasePayload,
    ValidationStudy,
    append_validation_case,
    build_validation_report,
    register_study,
)


def study() -> ValidationStudy:
    return ValidationStudy(
        study_id="water-threshold-study-1",
        rule_id="water-threshold-operator-style",
        proposal_sha256="a" * 64,
        frozen_at=parse_datetime("2026-07-30T12:00:00+08:00"),
        target_definition="锁定方向是否打出",
        denominator_definition="赛前时间边界完整的独立比赛",
        baseline_definition="同市场无信号方向命中率",
        baseline_rate=0.5,
        cohort_case_ids=[f"case-{index}" for index in range(30)],
        leagues_or_seasons=["KOR-K1-2026", "SWE-ALL-2026"],
        approved_by="lcz",
    )


def test_validation_case_must_belong_to_frozen_cohort(project_root: Path) -> None:
    register_study(project_root, study())
    payload = ValidationCasePayload(
        validation_case_id="outside-case",
        study_id="water-threshold-study-1",
        case_id="not-frozen",
        case_cluster_id="not-frozen",
        evidence_ref="evidence:test",
        observed_at=parse_datetime("2026-07-30T13:00:00+08:00"),
        relation="support",
        eligibility="eligible",
        summary="测试",
    )
    with pytest.raises(ValueError, match="cohort"):
        append_validation_case(
            project_root,
            payload,
            actor="lcz",
            recorded_at=parse_datetime("2026-07-30T14:00:00+08:00"),
        )


def test_promotion_report_uses_independent_clusters(project_root: Path) -> None:
    register_study(project_root, study())
    for index in range(30):
        payload = ValidationCasePayload(
            validation_case_id=f"validation-{index}",
            study_id="water-threshold-study-1",
            case_id=f"case-{index}",
            case_cluster_id=f"case-{index}",
            evidence_ref=f"evidence:{index}",
            observed_at=parse_datetime("2026-07-30T13:00:00+08:00"),
            relation="support",
            eligibility="eligible",
            summary="预注册样本",
        )
        append_validation_case(
            project_root,
            payload,
            actor="lcz",
            recorded_at=parse_datetime("2026-07-30T14:00:00+08:00"),
        )
    _, report = build_validation_report(project_root)
    record = report["studies"]["water-threshold-study-1"]
    assert record["eligible_independent_cases"] == 30
    assert record["promotion_candidate"] is True
