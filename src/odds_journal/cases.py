from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .extraction import EXTRACTION_RELATIVE, load_media_inventory, load_text_inventory
from .ledger import atomic_write_text, latest_payloads, read_ledger
from .markdown import FRONT_MATTER_RE


CASE_SECTIONS = (
    "facts",
    "market-timeline",
    "source-prematch",
    "source-live",
    "result",
    "source-review",
    "lessons",
    "limitations",
)
CASE_MARKER_RE = re.compile(r"<!-- case-section:([a-z-]+) -->")


class LegacyCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    case_revision: int = Field(ge=1)
    title: str = Field(min_length=1)
    competition_code: str | None = None
    home_team_id: str | None = None
    away_team_id: str | None = None
    kickoff_at: datetime | None = None
    fixture_fingerprint: str = Field(min_length=1)
    source_effective_at: datetime
    chronology: Literal["prematch_verified", "mixed", "postmatch_only", "unknown"]
    completeness: Literal["complete", "partial", "fragment"]
    statistics_eligible: bool = False
    source_atom_ids: list[str] = Field(default_factory=list)
    media_ids: list[str] = Field(default_factory=list)
    scenario_instance_ids: list[str] = Field(default_factory=list)
    result_known: bool
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["draft", "approved"] = "draft"
    sections: dict[str, str]

    @field_validator("kickoff_at", "source_effective_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("案例时间必须包含时区")
        return value

    @field_validator("source_atom_ids", "media_ids", "scenario_instance_ids")
    @classmethod
    def unique_values(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("案例引用列表存在重复")
        return value

    @model_validator(mode="after")
    def validate_case(self) -> "LegacyCase":
        if set(self.sections) != set(CASE_SECTIONS):
            raise ValueError("案例正文必须包含全部固定章节")
        if self.statistics_eligible and self.chronology != "prematch_verified":
            raise ValueError("只有 prematch_verified 案例可以进入统计")
        if self.home_team_id and self.away_team_id and self.home_team_id == self.away_team_id:
            raise ValueError("案例主客队不能相同")
        return self


def _case_hash_data(case: LegacyCase | dict) -> dict:
    if isinstance(case, LegacyCase):
        data = case.model_dump(mode="json")
    else:
        data = json.loads(json.dumps(case, ensure_ascii=False, default=str))
    data["sections"] = {
        name: content.replace("\r\n", "\n").replace("\r", "\n").strip()
        for name, content in data.get("sections", {}).items()
    }
    data["projection_sha256"] = "0" * 64
    return data


def calculate_projection_sha256(case: LegacyCase | dict) -> str:
    payload = json.dumps(_case_hash_data(case), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def case_from_payload(payload: dict) -> LegacyCase:
    raw = dict(payload)
    raw["sections"] = {
        str(name): str(content).replace("\r\n", "\n").replace("\r", "\n").strip()
        for name, content in (raw.get("sections") or {}).items()
    }
    raw.setdefault("projection_sha256", "0" * 64)
    draft = LegacyCase.model_validate(raw)
    return draft.model_copy(update={"projection_sha256": calculate_projection_sha256(draft)})


def _case_relative_path(case: LegacyCase) -> Path:
    year = str(case.kickoff_at.year) if case.kickoff_at else "unknown"
    return Path("knowledge/cases/legacy") / year / f"{case.case_id}.md"


def render_case(case: LegacyCase) -> str:
    metadata = case.model_dump(mode="json", exclude={"sections"})
    header = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    titles = {
        "facts": "一、可确认事实",
        "market-timeline": "二、图片和盘口时间线",
        "source-prematch": "三、原文赛前判断",
        "source-live": "四、原文临场追加",
        "result": "五、实际赛果",
        "source-review": "六、原文赛后复盘",
        "lessons": "七、本项目提炼教训",
        "limitations": "八、冲突、缺失与时间边界",
    }
    body = [f"# {case.title}\n\n"]
    for name in CASE_SECTIONS:
        body.append(f"<!-- case-section:{name} -->\n## {titles[name]}\n\n")
        body.append(case.sections[name].strip() + "\n\n")
    return f"---\n{header}\n---\n" + "".join(body).rstrip() + "\n"


def load_case(path: Path) -> LegacyCase:
    text = path.read_text(encoding="utf-8")
    front = FRONT_MATTER_RE.match(text)
    if not front:
        raise ValueError(f"案例缺少 Front Matter：{path}")
    raw = yaml.safe_load(front.group(1)) or {}
    body = text[front.end() :]
    markers = list(CASE_MARKER_RE.finditer(body))
    if [item.group(1) for item in markers] != list(CASE_SECTIONS):
        raise ValueError(f"案例章节顺序无效：{path}")
    sections: dict[str, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
        content = body[marker.end() : end]
        lines = content.lstrip("\r\n").splitlines()
        if lines and lines[0].startswith("## "):
            lines = lines[1:]
        sections[marker.group(1)] = "\n".join(lines).strip()
    case = LegacyCase.model_validate({**raw, "sections": sections})
    expected = calculate_projection_sha256(case)
    if case.projection_sha256 != expected:
        raise ValueError(f"案例投影哈希无效：{path}")
    return case


def latest_cases(root: Path) -> dict[str, LegacyCase]:
    ledger = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    events = read_ledger(ledger)
    latest = latest_payloads(events, lambda item: str(item.get("case_id")))
    return {case_id: case_from_payload(payload) for case_id, payload in latest.items()}


def rebuild_cases(root: Path) -> list[Path]:
    cases = latest_cases(root)
    atom_ids = {item.atom_id for item in load_text_inventory(root)}
    media_ids = {item.media_id for item in load_media_inventory(root)}
    paths: list[Path] = []
    for case in cases.values():
        missing_atoms = sorted(set(case.source_atom_ids) - atom_ids)
        missing_media = sorted(set(case.media_ids) - media_ids)
        if missing_atoms or missing_media:
            raise ValueError(
                f"案例 {case.case_id} 引用不存在；atoms={missing_atoms[:5]} media={missing_media[:5]}"
            )
        path = root / _case_relative_path(case)
        atomic_write_text(path, render_case(case))
        paths.append(path)
    return sorted(paths)


def validate_cases(root: Path) -> dict[Path, list[str]]:
    results: dict[Path, list[str]] = {}
    expected = latest_cases(root)
    found: set[str] = set()
    base = root / "knowledge/cases/legacy"
    for path in sorted(base.glob("**/*.md")) if base.exists() else []:
        try:
            case = load_case(path)
            found.add(case.case_id)
            current = expected.get(case.case_id)
            errors: list[str] = []
            if current is None:
                errors.append("案例投影没有对应 case event")
            elif case != current:
                errors.append("案例投影与最新 case event 不一致")
            if path.relative_to(root) != _case_relative_path(case):
                errors.append("案例路径与 kickoff_at 年份不一致")
            results[path] = errors
        except Exception as exc:
            results[path] = [str(exc)]
    for case_id, case in expected.items():
        if case_id not in found:
            path = root / _case_relative_path(case)
            results.setdefault(path, []).append("缺少有效案例投影，请运行 case rebuild")
    return results
