from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .analysis_context import parse_receipt
from .ledger import sha256_json
from .markdown import MatchDocument
from .models import MatchStatus, PrimaryMarket


SCENARIOS_START = "<!-- scenario-instances:start -->"
SCENARIOS_END = "<!-- scenario-instances:end -->"
RESOLUTIONS_START = "<!-- scenario-resolutions:start -->"
RESOLUTIONS_END = "<!-- scenario-resolutions:end -->"
SCENARIOS_RE = re.compile(
    rf"{re.escape(SCENARIOS_START)}\s*### 场景实例\s*```yaml\s*(.*?)\s*```\s*{re.escape(SCENARIOS_END)}",
    re.DOTALL,
)
RESOLUTIONS_RE = re.compile(
    rf"{re.escape(RESOLUTIONS_START)}\s*### 场景解析\s*```yaml\s*(.*?)\s*```\s*{re.escape(RESOLUTIONS_END)}",
    re.DOTALL,
)
SCENARIO_TYPES = {
    "static-line-water-movement",
    "line-rise-water-rise",
    "line-rise-water-fall",
    "line-drop-water-rise",
    "line-drop-water-fall",
    "operator-market-divergence",
    "asian-european-divergence",
    "handicap-total-goals-divergence",
    "favorite-line-mismatch",
    "late-market-reversal",
    "win-without-cover",
    "insufficient-or-conflicting-data",
    "unclassified",
}


class ScenarioObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_instance_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    scenario_type_id: str
    detected_at: datetime
    as_of: datetime
    market: Literal["one_x_two", "handicap", "total_goals", "pass"]
    observed_facts: list[str] = Field(min_length=1)
    matched_rule_ids: list[str] = Field(default_factory=list)
    hypothesis_a: str = Field(min_length=1)
    hypothesis_b: str = Field(min_length=1)
    supporting_evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    discriminating_triggers: list[str] = Field(default_factory=list)
    selected_interpretation: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    pass_condition: str = Field(min_length=1)

    @field_validator("detected_at", "as_of")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("场景时间必须包含时区")
        return value

    @field_validator(
        "observed_facts",
        "matched_rule_ids",
        "supporting_evidence",
        "counter_evidence",
        "discriminating_triggers",
    )
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("场景列表存在重复值")
        return value

    @model_validator(mode="after")
    def validate_observation(self) -> "ScenarioObservation":
        if self.scenario_type_id not in SCENARIO_TYPES:
            raise ValueError("未知场景类型；新型场景请使用 unclassified")
        if self.detected_at < self.as_of:
            raise ValueError("detected_at 不得早于 as_of 数据截止时间")
        if self.market == "pass" and self.confidence is not None:
            raise ValueError("pass 场景不填写 confidence")
        return self


class ScenarioCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    no_scenario_reason: str | None = None
    instances: list[ScenarioObservation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_collection(self) -> "ScenarioCollection":
        ids = [item.scenario_instance_id for item in self.instances]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario_instance_id 重复")
        if not self.instances and not self.no_scenario_reason:
            raise ValueError("没有场景时必须填写 no_scenario_reason")
        if self.instances and self.no_scenario_reason:
            raise ValueError("已有场景时不能填写 no_scenario_reason")
        return self


class RuleAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    relation: Literal["support", "counterexample", "ambiguous", "not_applicable"]
    rationale: str = Field(min_length=1)


class ScenarioResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_resolution_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    scenario_instance_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    resolved_at: datetime
    actual_development: str = Field(min_length=1)
    winning_hypothesis: Literal["a", "b", "neither", "unresolved"]
    rule_assessments: list[RuleAssessment] = Field(default_factory=list)
    evidence_disposition: Literal["link_after_review", "ineligible", "defer"]
    review_note: str = Field(min_length=1)

    @field_validator("resolved_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("resolved_at 必须包含时区")
        return value


class ResolutionCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    resolutions: list[ScenarioResolution] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> "ResolutionCollection":
        ids = [item.scenario_instance_id for item in self.resolutions]
        if len(ids) != len(set(ids)):
            raise ValueError("同一场景存在多个当前解析")
        return self


def _render_scenarios(collection: ScenarioCollection) -> str:
    body = yaml.safe_dump(collection.model_dump(mode="json"), allow_unicode=True, sort_keys=False).rstrip()
    return f"{SCENARIOS_START}\n### 场景实例\n\n```yaml\n{body}\n```\n{SCENARIOS_END}"


def _render_resolutions(collection: ResolutionCollection) -> str:
    body = yaml.safe_dump(collection.model_dump(mode="json"), allow_unicode=True, sort_keys=False).rstrip()
    return f"{RESOLUTIONS_START}\n### 场景解析\n\n```yaml\n{body}\n```\n{RESOLUTIONS_END}"


def parse_scenarios(reasoning: str, *, required: bool = False) -> ScenarioCollection | None:
    starts = reasoning.count(SCENARIOS_START)
    ends = reasoning.count(SCENARIOS_END)
    if starts == 0 and ends == 0:
        if required:
            raise ValueError("赛前推演缺少场景实例区块")
        return None
    if starts != 1 or ends != 1:
        raise ValueError("场景实例标记必须各出现一次")
    match = SCENARIOS_RE.search(reasoning)
    if not match:
        raise ValueError("场景实例区块格式无效")
    return ScenarioCollection.model_validate(yaml.safe_load(match.group(1)) or {})


def parse_resolutions(review: str, *, required: bool = False) -> ResolutionCollection | None:
    starts = review.count(RESOLUTIONS_START)
    ends = review.count(RESOLUTIONS_END)
    if starts == 0 and ends == 0:
        if required:
            raise ValueError("复盘缺少场景解析区块")
        return None
    if starts != 1 or ends != 1:
        raise ValueError("场景解析标记必须各出现一次")
    match = RESOLUTIONS_RE.search(review)
    if not match:
        raise ValueError("场景解析区块格式无效")
    return ResolutionCollection.model_validate(yaml.safe_load(match.group(1)) or {})


def scenario_hash(collection: ScenarioCollection) -> str:
    return sha256_json(collection.model_dump(mode="json"))


def set_scenario_collection(reasoning: str, collection: ScenarioCollection) -> str:
    rendered = _render_scenarios(collection)
    current = parse_scenarios(reasoning)
    if current is not None:
        return SCENARIOS_RE.sub(lambda _: rendered, reasoning, count=1)
    from .analysis_context import ANALYSIS_START

    position = reasoning.find(ANALYSIS_START)
    if position < 0:
        raise ValueError("赛前推演缺少 analysis-content 标记")
    return f"{reasoning[:position].rstrip()}\n\n{rendered}\n\n{reasoning[position:]}"


def set_resolution_collection(review: str, collection: ResolutionCollection) -> str:
    rendered = _render_resolutions(collection)
    current = parse_resolutions(review)
    if current is not None:
        return RESOLUTIONS_RE.sub(lambda _: rendered, review, count=1)
    review_content_start = "<!-- review-content:start -->"
    position = review.find(review_content_start)
    if position >= 0:
        return f"{review[:position].rstrip()}\n\n{rendered}\n\n{review[position:]}"
    return review.rstrip() + "\n\n" + rendered + "\n"


def add_scenario(path: Path, observation: ScenarioObservation) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ValueError("只有 draft/tracking 可以登记赛前场景")
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    if receipt is None or receipt.schema_version != 2:
        raise ValueError("登记场景前必须完成 v2 规则准备")
    collection = parse_scenarios(document.sections["prematch-reasoning"])
    existing = collection.instances if collection else []
    if any(item.scenario_instance_id == observation.scenario_instance_id for item in existing):
        raise ValueError(f"scenario_instance_id 已存在：{observation.scenario_instance_id}")
    collection = ScenarioCollection(instances=[*existing, observation])
    document.replace_section(
        "prematch-reasoning",
        set_scenario_collection(document.sections["prematch-reasoning"], collection),
    )
    document.save()
    return document


def revise_scenario(path: Path, scenario_id: str, observation: ScenarioObservation) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ValueError("锁定后不能修改赛前场景")
    collection = parse_scenarios(document.sections["prematch-reasoning"], required=True)
    assert collection is not None
    if observation.scenario_instance_id != scenario_id:
        raise ValueError("修订时不能改变 scenario_instance_id")
    if not any(item.scenario_instance_id == scenario_id for item in collection.instances):
        raise ValueError(f"场景不存在：{scenario_id}")
    instances = [observation if item.scenario_instance_id == scenario_id else item for item in collection.instances]
    document.replace_section(
        "prematch-reasoning",
        set_scenario_collection(document.sections["prematch-reasoning"], ScenarioCollection(instances=instances)),
    )
    document.save()
    return document


def set_no_scenario(path: Path, reason: str) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ValueError("锁定后不能修改赛前场景")
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    if receipt is None or receipt.schema_version != 2:
        raise ValueError("登记无场景结论前必须完成 v2 规则准备")
    collection = ScenarioCollection(no_scenario_reason=reason.strip())
    document.replace_section(
        "prematch-reasoning",
        set_scenario_collection(document.sections["prematch-reasoning"], collection),
    )
    document.save()
    return document


def add_live_scenario(path: Path, observation: ScenarioObservation) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) != MatchStatus.LOCKED:
        raise ValueError("只有 locked 比赛可以追加临场场景")
    if observation.detected_at < document.metadata.locked_at:
        raise ValueError("临场场景时间不得早于锁定时间")
    marker = f"<!-- live-scenario:{observation.scenario_instance_id} -->"
    if marker in document.sections["live-update"]:
        raise ValueError("临场场景 ID 已存在")
    payload = yaml.safe_dump(observation.model_dump(mode="json"), allow_unicode=True, sort_keys=False).rstrip()
    addition = (
        f"\n### {observation.detected_at:%Y-%m-%d %H:%M} 场景更新\n\n"
        f"{marker}\n```yaml\n{payload}\n```\n"
    )
    document.replace_section("live-update", document.sections["live-update"].rstrip() + addition)
    document.save()
    return document


def live_scenarios(document: MatchDocument) -> list[ScenarioObservation]:
    pattern = re.compile(r"<!-- live-scenario:([a-z0-9-]+) -->\s*```yaml\s*(.*?)\s*```", re.DOTALL)
    output: list[ScenarioObservation] = []
    for scenario_id, payload in pattern.findall(document.sections["live-update"]):
        observation = ScenarioObservation.model_validate(yaml.safe_load(payload) or {})
        if observation.scenario_instance_id != scenario_id:
            raise ValueError("临场场景标记与内容 ID 不一致")
        output.append(observation)
    return output


def add_resolution(path: Path, resolution: ScenarioResolution) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) != MatchStatus.FINISHED:
        raise ValueError("只有 finished 比赛可以填写场景解析")
    from .review_context import parse_review_receipt

    if parse_review_receipt(document.sections["postmatch-review"]) is None:
        raise ValueError("填写场景解析前必须先执行 prepare-review")
    prematch = parse_scenarios(document.sections["prematch-reasoning"], required=True)
    assert prematch is not None
    all_ids = {item.scenario_instance_id for item in prematch.instances} | {
        item.scenario_instance_id for item in live_scenarios(document)
    }
    if resolution.scenario_instance_id not in all_ids:
        raise ValueError("场景解析引用不存在的场景")
    collection = parse_resolutions(document.sections["postmatch-review"]) or ResolutionCollection()
    if any(item.scenario_instance_id == resolution.scenario_instance_id for item in collection.resolutions):
        raise ValueError("该场景已经填写解析")
    collection = ResolutionCollection(resolutions=[*collection.resolutions, resolution])
    document.replace_section(
        "postmatch-review",
        set_resolution_collection(document.sections["postmatch-review"], collection),
    )
    document.save()
    return document


def validate_scenario_workflow(document: MatchDocument, *, require_v2: bool) -> list[str]:
    errors: list[str] = []
    try:
        collection = parse_scenarios(document.sections["prematch-reasoning"], required=require_v2)
        if collection:
            receipt = parse_receipt(document.sections["prematch-reasoning"])
            for item in collection.instances:
                if item.as_of > document.metadata.kickoff_at:
                    errors.append(f"场景截止时间晚于开赛：{item.scenario_instance_id}")
                if receipt and item.as_of != receipt.as_of:
                    errors.append(f"场景截止时间必须与规则回执一致：{item.scenario_instance_id}")
            if MatchStatus(document.metadata.status) in {MatchStatus.FINISHED, MatchStatus.REVIEWED}:
                resolutions = parse_resolutions(
                    document.sections["postmatch-review"],
                    required=require_v2 and MatchStatus(document.metadata.status) == MatchStatus.REVIEWED,
                )
                if MatchStatus(document.metadata.status) == MatchStatus.REVIEWED and resolutions:
                    expected = {item.scenario_instance_id for item in collection.instances} | {
                        item.scenario_instance_id for item in live_scenarios(document)
                    }
                    actual = {item.scenario_instance_id for item in resolutions.resolutions}
                    if expected != actual:
                        errors.append("reviewed 比赛没有解析全部赛前和临场场景")
    except Exception as exc:
        errors.append(str(exc))
    return errors
