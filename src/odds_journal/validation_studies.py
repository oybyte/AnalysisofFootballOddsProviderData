from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ledger import append_payloads, atomic_write_text, read_ledger


STUDIES_DIR = Path("knowledge/validation/studies")
VALIDATION_CASES_PATH = Path("knowledge/validation/validation-cases.jsonl")


class TimeWindow(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "TimeWindow":
        for value in (self.start, self.end):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("验证时间窗口必须包含时区")
        if self.start >= self.end:
            raise ValueError("验证时间窗口 start 必须早于 end")
        return self


class ValidationStudy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    study_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    rule_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["frozen"] = "frozen"
    frozen_at: datetime
    target_definition: str = Field(min_length=1)
    denominator_definition: str = Field(min_length=1)
    baseline_definition: str = Field(min_length=1)
    baseline_rate: float = Field(ge=0, le=1)
    cohort_case_ids: list[str] = Field(min_length=1)
    leagues_or_seasons: list[str] = Field(default_factory=list)
    time_windows: list[TimeWindow] = Field(default_factory=list)
    approved_by: str = Field(min_length=1)

    @field_validator("frozen_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("frozen_at 必须包含时区")
        return value

    @field_validator("cohort_case_ids", "leagues_or_seasons")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("验证研究列表中存在重复值")
        return value

    @model_validator(mode="after")
    def disjoint_windows(self) -> "ValidationStudy":
        ordered = sorted(self.time_windows, key=lambda item: item.start)
        if any(left.end > right.start for left, right in zip(ordered, ordered[1:])):
            raise ValueError("验证研究时间窗口必须互不重叠")
        return self


class ValidationCasePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    validation_case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    study_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    case_id: str
    case_cluster_id: str
    evidence_ref: str = Field(min_length=1)
    observed_at: datetime
    relation: Literal["support", "counterexample", "ambiguous", "not_applicable"]
    eligibility: Literal["eligible", "ineligible"]
    ineligibility_reasons: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at 必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_eligibility(self) -> "ValidationCasePayload":
        if self.eligibility == "ineligible" and not self.ineligibility_reasons:
            raise ValueError("ineligible 验证案例必须说明原因")
        if self.eligibility == "eligible" and self.relation in {"ambiguous", "not_applicable"}:
            raise ValueError("ambiguous/not_applicable 不能进入合格分母")
        return self


def study_path(root: Path, study_id: str) -> Path:
    return root / STUDIES_DIR / f"{study_id}.yml"


def register_study(root: Path, study: ValidationStudy) -> Path:
    path = study_path(root, study.study_id)
    if path.exists():
        raise ValueError(f"冻结验证研究已存在，不允许覆盖：{study.study_id}")
    atomic_write_text(
        path,
        yaml.safe_dump(study.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
    )
    return path


def load_study(root: Path, study_id: str) -> ValidationStudy:
    path = study_path(root, study_id)
    if not path.exists():
        raise ValueError(f"验证研究不存在：{study_id}")
    return ValidationStudy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def append_validation_case(
    root: Path, payload: ValidationCasePayload, *, actor: str, recorded_at: datetime
) -> None:
    study = load_study(root, payload.study_id)
    if payload.case_id not in study.cohort_case_ids:
        raise ValueError("验证案例不在预先冻结的 cohort 中")
    events = read_ledger(root / VALIDATION_CASES_PATH)
    if any(
        ValidationCasePayload.model_validate(event.payload).validation_case_id
        == payload.validation_case_id
        for event in events
    ):
        raise ValueError(f"validation_case_id 已存在：{payload.validation_case_id}")
    append_payloads(
        root / VALIDATION_CASES_PATH,
        [payload.model_dump(mode="json")],
        recorded_at=recorded_at,
        actor=actor,
        event_id_factory=lambda item, index: f"validation-case:{payload.validation_case_id}",
    )


def _wilson_lower(successes: int, total: int, z: float = 1.96) -> float | None:
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


def build_validation_report(root: Path) -> tuple[Path, dict]:
    studies = {
        path.stem: ValidationStudy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        for path in sorted((root / STUDIES_DIR).glob("*.yml"))
    }
    grouped: dict[str, list[ValidationCasePayload]] = defaultdict(list)
    for event in read_ledger(root / VALIDATION_CASES_PATH):
        item = ValidationCasePayload.model_validate(event.payload)
        grouped[item.study_id].append(item)
    records: dict[str, dict] = {}
    for study_id, study in studies.items():
        eligible = [item for item in grouped[study_id] if item.eligibility == "eligible"]
        by_cluster: dict[str, list[ValidationCasePayload]] = defaultdict(list)
        for item in eligible:
            by_cluster[item.case_cluster_id].append(item)
        successes = sum(
            any(item.relation == "support" for item in items)
            and not any(item.relation == "counterexample" for item in items)
            for items in by_cluster.values()
        )
        total = len(by_cluster)
        estimate = successes / total if total else None
        lower = _wilson_lower(successes, total)
        diversity = len(study.leagues_or_seasons) >= 2 or len(study.time_windows) >= 2
        gates = {
            "minimum_30_independent_cases": total >= 30,
            "league_season_or_time_window_diversity": diversity,
            "comparison_baseline_defined": True,
            "point_estimate_five_points_above_baseline": (
                estimate is not None and estimate >= study.baseline_rate + 0.05
            ),
            "wilson_95_lower_not_below_baseline": (
                lower is not None and lower >= study.baseline_rate
            ),
            "human_approval": bool(study.approved_by),
        }
        records[study_id] = {
            "rule_id": study.rule_id,
            "cohort_size": len(study.cohort_case_ids),
            "recorded_cases": len(grouped[study_id]),
            "eligible_independent_cases": total,
            "supporting_independent_cases": successes,
            "baseline_rate": study.baseline_rate,
            "point_estimate": estimate,
            "wilson_95_lower": lower,
            "gates": gates,
            "promotion_candidate": all(gates.values()),
        }
    payload = {"schema_version": 1, "studies": records}
    path = root / "reports/验证研究报告.json"
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path, payload


def validate_validation_studies(root: Path) -> dict[Path, list[str]]:
    results: dict[Path, list[str]] = {}
    studies: dict[str, ValidationStudy] = {}
    for path in sorted((root / STUDIES_DIR).glob("*.yml")):
        try:
            study = ValidationStudy.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
            if path.stem != study.study_id:
                raise ValueError("研究文件名必须等于 study_id")
            studies[study.study_id] = study
            results[path] = []
        except Exception as exc:
            results[path] = [str(exc)]
    ledger_path = root / VALIDATION_CASES_PATH
    errors: list[str] = []
    try:
        seen: set[str] = set()
        for event in read_ledger(ledger_path):
            item = ValidationCasePayload.model_validate(event.payload)
            if item.validation_case_id in seen:
                errors.append(f"validation_case_id 重复：{item.validation_case_id}")
            seen.add(item.validation_case_id)
            study = studies.get(item.study_id)
            if study is None:
                errors.append(f"验证案例引用不存在的研究：{item.validation_case_id}")
            elif item.case_id not in study.cohort_case_ids:
                errors.append(f"验证案例不在冻结 cohort：{item.validation_case_id}")
    except Exception as exc:
        errors.append(str(exc))
    if ledger_path.exists() or studies:
        results[ledger_path] = errors
    return results
