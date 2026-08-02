from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .extraction import EXTRACTION_RELATIVE, LEGACY_CASE_SPECS, load_media_inventory, load_text_inventory
from .ledger import atomic_write_text, append_payloads, latest_payloads, read_ledger
from .markdown import FRONT_MATTER_RE


CASE_SECTIONS = (
    "facts", "market-timeline", "source-prematch", "source-live", "result",
    "source-review", "lessons", "limitations",
)
CASE_MARKER_RE = re.compile(r"<!-- case-section:([a-z-]+) -->")
SAFE_FILE_LABEL_RE = re.compile(r"^[^\\/:*?\"<>|\x00-\x1f]+$")
EXTERNAL_RESULT_SECTION = "### 外部补录赛果"
EXTERNAL_EVIDENCE_RELATIVE = Path("knowledge/evidence/user-results/2026-07-29")
CASE_FILE_LABELS = {
    "legacy-gimcheon-daejeon": "date-unknown_韩K联_金泉尚武_vs_大田市民",
    "legacy-pohang-jeonbuk": "date-unknown_韩K联_浦项制铁_vs_全北汽车",
    "legacy-seoul-ulsan": "date-unknown_韩K联_FC首尔_vs_蔚山HD",
    "legacy-incheon-bucheon": "date-unknown_韩K联_仁川联_vs_富川FC",
    "legacy-gwangju-jeju": "date-unknown_韩K联_FC光州_vs_济州SK",
    "legacy-anyang-gangwon": "date-unknown_韩K联_FC安养_vs_江原FC",
    "legacy-hjk-tps": "date-unknown_芬兰赛事_赫尔辛基_vs_TPS土尔库",
    "legacy-malmo-elfsborg": "date-unknown_瑞典超_马尔默_vs_埃尔夫斯堡",
    "legacy-gais-halmstad": "date-unknown_瑞典超_哥德堡盖斯_vs_哈姆斯塔德",
    "legacy-gremio-fluminense": "date-unknown_巴西甲_格雷米奥_vs_弗鲁米嫩塞",
    "legacy-flamengo-sao-paulo": "date-unknown_巴西甲_弗拉门戈_vs_圣保罗",
    "legacy-hacken-aik": "date-unknown_瑞典超_赫根_vs_AIK索尔纳",
    "legacy-rosenborg-fredrikstad": "date-unknown_挪超_罗森博格_vs_腓特烈斯塔",
}

LEGACY_IDENTITIES = {
    "legacy-gimcheon-daejeon": ("KOR-K1", "gimcheon-sangmu", "daejeon-hana-citizen"),
    "legacy-pohang-jeonbuk": ("KOR-K1", "pohang-steelers", "jeonbuk-hyundai-motors"),
    "legacy-seoul-ulsan": ("KOR-K1", "fc-seoul", "ulsan-hd"),
    "legacy-incheon-bucheon": ("KOR-K2", "incheon-united", "bucheon-fc-1995"),
    "legacy-gwangju-jeju": ("KOR-K1", "gwangju-fc", "jeju-sk"),
    "legacy-anyang-gangwon": ("KOR-K1", "fc-anyang", "gangwon-fc"),
    "legacy-hjk-tps": (None, "hjk-helsinki", "tps-turku"),
    "legacy-malmo-elfsborg": ("SWE-ALLSVENSKAN", "malmo-ff", "if-elfsborg"),
    "legacy-gais-halmstad": ("SWE-ALLSVENSKAN", "gais", "halmstad-bk"),
    "legacy-gremio-fluminense": ("BRA-SERIE-A", "gremio", "fluminense"),
    "legacy-flamengo-sao-paulo": ("BRA-SERIE-A", "flamengo", "sao-paulo"),
    "legacy-hacken-aik": ("SWE-ALLSVENSKAN", "hacken", "aik"),
    "legacy-rosenborg-fredrikstad": ("NOR-ELITESERIEN", "rosenborg", "fredrikstad"),
}

CASE_SECTION_TITLES = {
    "facts": "一、可确认事实", "market-timeline": "二、文字化盘口时间线",
    "source-prematch": "三、原文赛前判断", "source-live": "四、原文临场追加",
    "result": "五、实际赛果与外部补录", "source-review": "六、原文赛后复盘",
    "lessons": "七、本项目提炼教训", "limitations": "八、冲突、缺失与时间边界",
}


def _section_titles(schema_version: int) -> dict[str, str]:
    titles = dict(CASE_SECTION_TITLES)
    if schema_version == 1:
        titles["market-timeline"] = "二、图片和盘口时间线"
        titles["result"] = "五、实际赛果"
    return titles


def _case_file_stem(case: "LegacyCase") -> str:
    label = case.display_file_label or CASE_FILE_LABELS.get(case.case_id, case.case_id)
    fixture_date = case.kickoff_at.date() if case.kickoff_at else case.fixture_date
    if fixture_date is None:
        return label
    description = label.removeprefix("date-unknown_")
    return f"{fixture_date.isoformat()}_{description}"


class HandicapRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_line: str
    home_line: float
    home_settlement: Literal["full_win", "half_win", "push", "half_loss", "full_loss"]


class TotalGoalsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_line: str
    line: float
    total_goals: int = Field(ge=0)
    over_settlement: Literal["full_win", "half_win", "push", "half_loss", "full_loss"]
    under_settlement: Literal["full_win", "half_win", "push", "half_loss", "full_loss"]


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    binding_id: str = Field(min_length=1)


class FixtureFingerprintAlias(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    value: str = Field(min_length=1)


class CaseMaterialStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    material_stage: Literal[
        "prematch_early", "prematch_late", "live", "result_source", "postmatch_review"
    ]
    observed_at: datetime | None = None
    observed_at_note: str | None = None
    received_at: datetime
    source_path: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1)

    @field_validator("observed_at", "received_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("阶段材料时间必须包含时区")
        return value

    @model_validator(mode="after")
    def validate_observed_at(self) -> "CaseMaterialStage":
        if self.observed_at is None and not (self.observed_at_note or "").strip():
            raise ValueError("未知观察时间必须填写 observed_at_note")
        return self


class ResultRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal["source_material", "user_screenshot"]
    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)
    home_half_goals: int | None = Field(default=None, ge=0)
    away_half_goals: int | None = Field(default=None, ge=0)
    handicap: HandicapRecord | None = None
    total_goals_market: TotalGoalsRecord | None = None
    recorded_at: datetime
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("赛果记录时间必须包含时区")
        return value


class LegacyCase(BaseModel):
    """Versioned historical case projection with backward-compatible parsing."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2, 3] = 1
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]+$")
    case_revision: int = Field(ge=1)
    title: str = Field(min_length=1)
    display_file_label: str | None = None
    competition_code: str | None = None
    home_team_id: str | None = None
    away_team_id: str | None = None
    kickoff_at: datetime | None = None
    fixture_date: date | None = None
    fixture_fingerprint: str = Field(min_length=1)
    fixture_fingerprint_version: int = Field(default=1, ge=1)
    fixture_fingerprint_aliases: list[FixtureFingerprintAlias] = Field(default_factory=list)
    source_effective_at: datetime | None = None
    source_archived_at: datetime | None = None
    revision_effective_at: datetime | None = None
    chronology: Literal["prematch_verified", "mixed", "postmatch_only", "unknown"]
    completeness: Literal["complete", "partial", "fragment"]
    statistics_eligible: bool = False
    source_atom_ids: list[str] = Field(default_factory=list)
    media_ids: list[str] = Field(default_factory=list)
    scenario_instance_ids: list[str] = Field(default_factory=list)
    result_known: bool
    prematch_analysis_present: bool = False
    source_review_present: bool = False
    external_result_present: bool = False
    result_record: ResultRecord | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    material_stages: list[CaseMaterialStage] = Field(default_factory=list)
    projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["draft", "approved"] = "draft"
    sections: dict[str, str]

    @field_validator("kickoff_at", "source_effective_at", "source_archived_at", "revision_effective_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("案例时间必须包含时区")
        return value

    @field_validator("source_atom_ids", "media_ids", "scenario_instance_ids", "evidence_ids")
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
        if self.kickoff_at and self.fixture_date and self.kickoff_at.date() != self.fixture_date:
            raise ValueError("fixture_date 必须与 kickoff_at 的日期一致")
        if self.schema_version == 2 and self.result_known != (self.result_record is not None):
            raise ValueError("V2 案例的 result_known 必须与 result_record 一致")
        if self.external_result_present and not self.result_record:
            raise ValueError("外部补录赛果必须提供 result_record")
        if self.schema_version < 3 and self.source_effective_at is None:
            raise ValueError("V1/V2 案例必须包含 source_effective_at")
        if self.schema_version == 3:
            if not self.source_archived_at or not self.revision_effective_at:
                raise ValueError("V3 案例必须包含 source_archived_at 和 revision_effective_at")
            if self.source_effective_at is not None:
                raise ValueError("V3 案例不再使用 source_effective_at")
            if self.evidence_ids:
                raise ValueError("V3 案例必须使用 evidence_refs")
            identities = [(item.evidence_id, item.binding_id) for item in self.evidence_refs]
            if len(identities) != len(set(identities)):
                raise ValueError("V3 案例 evidence_refs 存在重复")
        if self.display_file_label is not None:
            if not SAFE_FILE_LABEL_RE.fullmatch(self.display_file_label.strip()):
                raise ValueError("display_file_label 含有非法文件名字符")
            if not any("\u4e00" <= character <= "\u9fff" for character in self.display_file_label):
                raise ValueError("display_file_label 必须包含中文名称")
        material_ids = [item.material_id for item in self.material_stages]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("案例 material_id 重复")
        return self


LegacyCaseV2 = LegacyCase
LegacyCaseV3 = LegacyCase


def _case_hash_data(case: LegacyCase | dict) -> dict:
    data = case.model_dump(mode="json") if isinstance(case, LegacyCase) else json.loads(json.dumps(case, ensure_ascii=False, default=str))
    # These fields were introduced after existing revisions were frozen. Empty
    # defaults must not change their historical projection hashes.
    if data.get("display_file_label") is None:
        data.pop("display_file_label", None)
    if data.get("fixture_date") is None:
        data.pop("fixture_date", None)
    if not data.get("material_stages"):
        data.pop("material_stages", None)
    if data.get("schema_version", 1) == 1:
        for key in ("prematch_analysis_present", "source_review_present", "external_result_present", "result_record", "evidence_ids"):
            data.pop(key, None)
    if data.get("schema_version", 1) < 3:
        for key in (
            "fixture_fingerprint_version", "fixture_fingerprint_aliases",
            "source_archived_at", "revision_effective_at", "evidence_refs",
        ):
            data.pop(key, None)
        if data.get("result_record"):
            data["result_record"].pop("evidence_refs", None)
    data["sections"] = {name: content.replace("\r\n", "\n").replace("\r", "\n").strip() for name, content in data.get("sections", {}).items()}
    data["projection_sha256"] = "0" * 64
    return data


def calculate_projection_sha256(case: LegacyCase | dict) -> str:
    payload = json.dumps(_case_hash_data(case), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def case_from_payload(payload: dict) -> LegacyCase:
    raw = dict(payload)
    raw["sections"] = {str(name): str(content).replace("\r\n", "\n").replace("\r", "\n").strip() for name, content in (raw.get("sections") or {}).items()}
    raw.setdefault("projection_sha256", "0" * 64)
    draft = LegacyCase.model_validate(raw)
    return draft.model_copy(update={"projection_sha256": calculate_projection_sha256(draft)})


def _case_relative_path(case: LegacyCase) -> Path:
    fixture_date = case.kickoff_at.date() if case.kickoff_at else case.fixture_date
    year = str(fixture_date.year) if fixture_date else "unknown"
    return Path("knowledge/cases/legacy") / year / f"{_case_file_stem(case)}.md"


def revision_relative_path(
    case_id: str,
    revision: int,
    kickoff_at: datetime | None = None,
    display_file_label: str | None = None,
    fixture_date: date | None = None,
) -> Path:
    stem = display_file_label or CASE_FILE_LABELS.get(case_id, case_id)
    case_date = kickoff_at.date() if kickoff_at is not None else fixture_date
    if case_date is not None:
        stem = f"{case_date.isoformat()}_{stem.removeprefix('date-unknown_')}"
    return Path("knowledge/cases/legacy/_revisions") / f"{stem}__revision-{revision}.md"


def _revision_relative_path(case: LegacyCase) -> Path:
    return revision_relative_path(
        case.case_id, case.case_revision, case.kickoff_at, case.display_file_label
        , case.fixture_date
    )


def render_case(case: LegacyCase) -> str:
    metadata = case.model_dump(mode="json", exclude={"sections"})
    if metadata.get("display_file_label") is None:
        metadata.pop("display_file_label", None)
    if metadata.get("fixture_date") is None:
        metadata.pop("fixture_date", None)
    if not metadata.get("material_stages"):
        metadata.pop("material_stages", None)
    if case.schema_version == 1:
        for key in ("prematch_analysis_present", "source_review_present", "external_result_present", "result_record", "evidence_ids"):
            metadata.pop(key, None)
    if case.schema_version < 3:
        for key in (
            "fixture_fingerprint_version", "fixture_fingerprint_aliases",
            "source_archived_at", "revision_effective_at", "evidence_refs",
        ):
            metadata.pop(key, None)
        if metadata.get("result_record"):
            metadata["result_record"].pop("evidence_refs", None)
    header = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    titles = _section_titles(case.schema_version)
    body = [f"# {case.title}\n\n"]
    for name in CASE_SECTIONS:
        body.append(f"<!-- case-section:{name} -->\n## {titles[name]}\n\n{case.sections[name].strip()}\n\n")
    return f"---\n{header}\n---\n" + "".join(body).rstrip() + "\n"


def load_case(path: Path) -> LegacyCase:
    text = path.read_text(encoding="utf-8")
    front = FRONT_MATTER_RE.match(text)
    if not front:
        raise ValueError(f"案例缺少 Front Matter：{path}")
    raw = yaml.safe_load(front.group(1)) or {}
    schema_version = int(raw.get("schema_version", 1))
    expected_titles = _section_titles(schema_version)
    body = text[front.end():]
    markers = list(CASE_MARKER_RE.finditer(body))
    if [item.group(1) for item in markers] != list(CASE_SECTIONS):
        raise ValueError(f"案例章节顺序无效：{path}")
    sections: dict[str, str] = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(body)
        lines = body[marker.end():end].lstrip("\r\n").splitlines()
        expected_heading = f"## {expected_titles[marker.group(1)]}"
        if not lines or lines[0] != expected_heading:
            raise ValueError(f"案例章节标题无效：{path} / {marker.group(1)}")
        lines = lines[1:]
        sections[marker.group(1)] = "\n".join(lines).strip()
    case = LegacyCase.model_validate({**raw, "sections": sections})
    if case.projection_sha256 != calculate_projection_sha256(case):
        raise ValueError(f"案例投影哈希无效：{path}")
    return case


def case_events(root: Path):
    return read_ledger(root / EXTRACTION_RELATIVE / "case-events.jsonl")


def latest_cases(root: Path) -> dict[str, LegacyCase]:
    latest = latest_payloads(case_events(root), lambda item: str(item.get("case_id")))
    return {case_id: case_from_payload(payload) for case_id, payload in latest.items()}


def case_id_for_fixture(root: Path, fixture_fingerprint: str) -> str:
    matches = [
        case.case_id
        for case in latest_cases(root).values()
        if case.fixture_fingerprint == fixture_fingerprint
        or fixture_fingerprint in {item.value for item in case.fixture_fingerprint_aliases}
    ]
    if len(matches) != 1:
        raise ValueError(f"赛事指纹未能唯一定位案例：{fixture_fingerprint}")
    return matches[0]


def fixture_fingerprint_v2(
    competition_code: str | None,
    home_team_id: str,
    away_team_id: str,
    kickoff_at: datetime,
) -> str:
    if kickoff_at.tzinfo is None or kickoff_at.utcoffset() is None:
        raise ValueError("赛事指纹要求带时区的开赛时间")
    from datetime import timezone

    data = {
        "away_team_id": away_team_id,
        "competition_code": competition_code or "unknown",
        "home_team_id": home_team_id,
        "kickoff_at_utc": kickoff_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def case_at(root: Path, case_id: str, as_of: datetime) -> tuple[LegacyCase, object] | None:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of 必须包含时区")
    eligible = [
        event for event in case_events(root)
        if event.payload.get("case_id") == case_id and event.recorded_at <= as_of
    ]
    if not eligible:
        return None
    event = max(eligible, key=lambda item: int(item.payload["case_revision"]))
    return case_from_payload(event.payload), event


def historical_case(root: Path, case_id: str, revision: int, content_sha256: str | None = None) -> Path | None:
    revisions = root / "knowledge/cases/legacy/_revisions"
    if not revisions.exists():
        return None
    for path in sorted(revisions.glob(f"*__revision-{revision}.md")):
        if content_sha256 and hashlib.sha256(path.read_bytes()).hexdigest() != content_sha256:
            continue
        try:
            case = load_case(path)
        except ValueError:
            continue
        if case.case_id == case_id and case.case_revision == revision:
            return path
    return None


def _validate_references(root: Path, case: LegacyCase) -> None:
    if not case.source_atom_ids and not case.media_ids:
        return
    atom_ids = {item.atom_id for item in load_text_inventory(root)}
    media_ids = {item.media_id for item in load_media_inventory(root)}
    missing_atoms = sorted(set(case.source_atom_ids) - atom_ids)
    missing_media = sorted(set(case.media_ids) - media_ids)
    if missing_atoms or missing_media:
        raise ValueError(f"案例 {case.case_id} 引用不存在；atoms={missing_atoms[:5]} media={missing_media[:5]}")


def rebuild_cases(root: Path) -> list[Path]:
    paths: list[Path] = []
    for case in latest_cases(root).values():
        _validate_references(root, case)
        path = root / _case_relative_path(case)
        rendered = render_case(case)
        atomic_write_text(path, rendered)
        revision = root / _revision_relative_path(case)
        if revision.exists() and revision.read_text(encoding="utf-8") != rendered:
            raise ValueError(f"不可变案例版本内容不一致：{revision}")
        if not revision.exists():
            atomic_write_text(revision, rendered)
        paths.append(path)
    return sorted(paths)


def rename_case_paths(root: Path) -> list[Path]:
    """Replace legacy technical filenames while preserving bytes and revision contents."""
    moved: list[Path] = []
    for case in latest_cases(root).values():
        old_revision_dir = root / "knowledge/cases/legacy/_revisions" / case.case_id
        if old_revision_dir.exists():
            for source in sorted(old_revision_dir.glob("v*.md")):
                revision = int(source.stem[1:])
                target = root / revision_relative_path(case.case_id, revision, case.kickoff_at)
                if target.exists() and target.read_bytes() != source.read_bytes():
                    raise ValueError(f"目标审计投影已存在且内容不同：{target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    source.replace(target)
                    moved.append(target)
                else:
                    source.unlink()
            old_revision_dir.rmdir()
        canonical = root / _case_relative_path(case)
        old_canonical = root / "knowledge/cases/legacy/unknown" / f"{case.case_id}.md"
        if old_canonical.exists() and old_canonical != canonical:
            canonical.parent.mkdir(parents=True, exist_ok=True)
            if not canonical.exists():
                old_canonical.replace(canonical)
                moved.append(canonical)
                continue
            if canonical.read_bytes() == old_canonical.read_bytes():
                old_canonical.unlink()
                continue
            old_case = load_case(old_canonical)
            if old_case.case_id != case.case_id or old_case.case_revision >= case.case_revision:
                raise ValueError(f"目标案例文件已存在且内容不同：{canonical}")
            historical = historical_case(root, old_case.case_id, old_case.case_revision)
            if historical is None or historical.read_bytes() != old_canonical.read_bytes():
                raise ValueError(f"旧案例版本未被完整归档：{old_canonical}")
            old_canonical.unlink()
    for case in latest_cases(root).values():
        for source in sorted((root / "knowledge/cases/legacy/_revisions").glob("*__revision-*.md")):
            try:
                archived = load_case(source)
            except ValueError:
                continue
            if archived.case_id != case.case_id:
                continue
            target = root / revision_relative_path(case.case_id, archived.case_revision, case.kickoff_at)
            if source == target:
                continue
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise ValueError(f"目标审计投影已存在且内容不同：{target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                source.replace(target)
                moved.append(target)
            else:
                source.unlink()
    return moved


def write_case_directory(root: Path) -> Path:
    cases = sorted(latest_cases(root).values(), key=lambda item: item.title)
    groups = {
        "全部案例": cases,
        "有原文复盘": [item for item in cases if item.source_review_present],
        "外部补录赛果": [item for item in cases if item.external_result_present],
        "待原文复盘": [item for item in cases if not item.source_review_present],
    }
    lines = [
        "# 历史案例目录",
        "",
        "已确认开赛日期的案例按年份目录保存；尚未确认日期的案例保存在 `unknown/`。未通过历史再认证的案例仅供学习与检索；已认证案例可按研究门禁进入历史规则回归。",
        "",
    ]
    for title, items in groups.items():
        lines.extend([f"## {title}（{len(items)}）", ""])
        if not items:
            lines.extend(["无。", ""])
            continue
        for case in items:
            score = "未记录"
            if case.result_record:
                score = f"{case.result_record.home_goals}-{case.result_record.away_goals}"
            elif case.result_known:
                score = "原始资料已记录"
            relative = _case_relative_path(case).relative_to("knowledge/cases/legacy").as_posix()
            lines.append(f"- [{case.title}]({relative})：赛果 {score}；原文复盘 {'有' if case.source_review_present else '无'}；外部补录 {'是' if case.external_result_present else '否'}。")
        lines.append("")
    lines.extend(["## 查阅说明", "", "可使用球队名称、比分、盘口、结算类型或来源轮次进行全文检索。图片只作为证据索引，案例正文以文字化数据为准。", ""])
    path = root / "knowledge/cases/legacy/README.md"
    atomic_write_text(path, "\n".join(lines))
    return path


def _result_section(case: LegacyCase) -> str:
    source = case.sections["result"].split(EXTERNAL_RESULT_SECTION, 1)[0].strip()
    record = case.result_record
    if not record or record.source_kind != "user_screenshot":
        return source
    home_half = "" if record.home_half_goals is None else f"；半场 {record.home_half_goals}-{record.away_half_goals}"
    lines = [source, "", EXTERNAL_RESULT_SECTION, "", f"- 全场：{record.home_goals}-{record.away_goals}{home_half}"]
    if record.handicap:
        lines.append(f"- 主队让球：{record.handicap.display_line}，结算 {record.handicap.home_settlement}")
    if record.total_goals_market:
        total = record.total_goals_market
        lines.append(f"- 总进球：{total.display_line}，总数 {total.total_goals}，大球 {total.over_settlement}，小球 {total.under_settlement}")
    lines.append(f"- 外部证据：{', '.join(record.evidence_ids)}")
    return "\n".join(lines).strip()


def _source_result_record(case: LegacyCase) -> ResultRecord | None:
    if not case.result_known:
        return None
    match = re.search(r"(\d+)\s*[-:：]\s*(\d+)", case.sections["result"])
    if not match:
        return None
    return ResultRecord(
        source_kind="source_material",
        home_goals=int(match.group(1)),
        away_goals=int(match.group(2)),
        recorded_at=case.source_effective_at,
    )


def migrate_cases_to_v2(root: Path, *, recorded_at: datetime, actor: str = "codex") -> list[Path]:
    events = case_events(root)
    latest_event: dict[str, object] = {}
    for event in events:
        latest_event[str(event.payload["case_id"])] = event
    latest = latest_cases(root)
    for case in latest.values():
        current = root / _case_relative_path(case)
        revision = root / _revision_relative_path(case)
        if not revision.exists():
            if not current.exists():
                atomic_write_text(current, render_case(case))
            atomic_write_text(revision, current.read_text(encoding="utf-8"))
    payloads: list[dict] = []
    for case in latest.values():
        if case.schema_version == 2:
            continue
        review_missing = case.sections["source-review"].startswith("原始资料未提供明确")
        prematch_missing = case.sections["source-prematch"].startswith("未找到可确认")
        payload = case.model_dump(mode="json")
        payload.update({
            "schema_version": 2,
            "case_revision": case.case_revision + 1,
            "prematch_analysis_present": not prematch_missing,
            "source_review_present": not review_missing,
            "external_result_present": False,
            "result_record": (_source_result_record(case).model_dump(mode="json") if _source_result_record(case) else None),
            "evidence_ids": [],
            "_supersedes_event_id": latest_event[case.case_id].event_id,
        })
        payloads.append(payload)
    ledger = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    append_payloads(ledger, payloads, recorded_at=recorded_at, actor=actor, event_id_factory=lambda item, _: f"case:v2:{item['case_id']}")
    paths = rebuild_cases(root)
    write_case_directory(root)
    return paths


def _resolve_evidence_refs(
    root: Path,
    *,
    case_id: str,
    evidence_ids: list[str],
    assertion_type: str | None = None,
) -> list[EvidenceRef]:
    from .evidence_registry import active_binding, evidence_records

    records = evidence_records(root)
    refs: list[EvidenceRef] = []
    for evidence_id in evidence_ids:
        record = records.get(evidence_id)
        if record is None:
            raise ValueError(f"证据不存在：{evidence_id}")
        bindings = [
            item for item in record.bindings
            if item.case_id == case_id and item.status == "active"
            and (assertion_type is None or item.assertion_type == assertion_type)
        ]
        if len(bindings) != 1:
            raise ValueError(f"证据无法唯一解析活动 binding：{case_id} / {evidence_id}")
        active_binding(root, evidence_id, bindings[0].binding_id, case_id=case_id)
        refs.append(EvidenceRef(evidence_id=evidence_id, binding_id=bindings[0].binding_id))
    return refs


def _merged_evidence_refs(*groups: list[EvidenceRef]) -> list[dict]:
    merged: dict[tuple[str, str], EvidenceRef] = {}
    for reference in (item for group in groups for item in group):
        merged[(reference.evidence_id, reference.binding_id)] = reference
    return [item.model_dump(mode="json") for _, item in sorted(merged.items())]


def append_external_results(
    root: Path,
    records: dict[str, ResultRecord],
    *,
    recorded_at: datetime,
    actor: str = "codex",
) -> list[Path]:
    events = case_events(root)
    latest_event = {str(event.payload["case_id"]): event for event in events}
    latest = latest_cases(root)
    payloads: list[dict] = []
    for case_id, record in records.items():
        case = latest.get(case_id)
        if case is None:
            raise ValueError(f"历史案例不存在：{case_id}")
        if case.schema_version != 2:
            raise ValueError(f"案例尚未迁移到 V2：{case_id}")
        if case.external_result_present and case.result_record == record:
            continue
        payload = case.model_dump(mode="json")
        references = _resolve_evidence_refs(
            root, case_id=case_id, evidence_ids=record.evidence_ids, assertion_type="result"
        ) if case.schema_version == 3 else []
        updated_record = record.model_copy(
            update={"evidence_ids": [], "evidence_refs": references}
        ) if case.schema_version == 3 else record
        payload.update({
            "case_revision": case.case_revision + 1,
            "result_known": True,
            "external_result_present": True,
            "result_record": updated_record.model_dump(mode="json"),
            "evidence_ids": sorted(set(case.evidence_ids) | set(record.evidence_ids)) if case.schema_version < 3 else [],
            "evidence_refs": (
                _merged_evidence_refs(case.evidence_refs, references)
                if case.schema_version == 3 else []
            ),
            "_supersedes_event_id": latest_event[case_id].event_id,
        })
        draft = case_from_payload({key: value for key, value in payload.items() if key != "_supersedes_event_id"})
        payload["sections"]["result"] = _result_section(draft)
        payloads.append(payload)
    ledger = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    append_payloads(
        ledger,
        payloads,
        recorded_at=recorded_at,
        actor=actor,
        event_id_factory=lambda item, _: f"case:external-result:{item['case_id']}:v{item['case_revision']}",
    )
    paths = rebuild_cases(root)
    write_case_directory(root)
    return paths


def _validate_case_evidence_refs(root: Path, case: LegacyCase) -> None:
    from .evidence_registry import active_binding

    references = [*case.evidence_refs]
    if case.result_record:
        references.extend(case.result_record.evidence_refs)
    for stage in case.material_stages:
        references.extend(stage.evidence_refs)
    for reference in references:
        active_binding(root, reference.evidence_id, reference.binding_id, case_id=case.case_id)


def _fixture_values(case: LegacyCase) -> set[str]:
    return {
        case.fixture_fingerprint,
        *(item.value for item in case.fixture_fingerprint_aliases),
    }


def import_legacy_case(root: Path, case: LegacyCase, *, actor: str = "codex") -> Path:
    """Create one V3 legacy case atomically from its first immutable revision."""
    if case.schema_version != 3:
        raise ValueError("case import 只接受 V3 案例")
    if case.case_revision != 1:
        raise ValueError("case import 的 case_revision 必须为 1")
    if not case.display_file_label:
        raise ValueError("case import 必须提供 display_file_label")
    if case.status != "draft" or case.statistics_eligible:
        raise ValueError("新导入案例必须是 draft 且不得进入统计")
    fixture_date = case.kickoff_at.date() if case.kickoff_at else case.fixture_date
    if fixture_date is None or case.revision_effective_at is None:
        raise ValueError("case import 必须提供赛日和 revision_effective_at")
    if case.kickoff_at is not None and case.kickoff_at >= case.revision_effective_at:
        raise ValueError("case import 仅接受已结束的历史比赛")
    if fixture_date > case.revision_effective_at.date():
        raise ValueError("case import 的赛日不得晚于导入修订时间")
    existing = latest_cases(root)
    if case.case_id in existing:
        raise ValueError(f"案例已存在：{case.case_id}")
    values = _fixture_values(case)
    for current in existing.values():
        overlap = values & _fixture_values(current)
        if overlap:
            raise ValueError(f"赛事指纹已存在或与历史别名冲突：{sorted(overlap)[0]}")
    _validate_references(root, case)
    _validate_case_evidence_refs(root, case)

    from .transaction import RepositoryTransaction

    ledger = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    canonical = root / _case_relative_path(case)
    revision = root / _revision_relative_path(case)
    with RepositoryTransaction(
        root,
        files=[
            ledger,
            canonical,
            revision,
            root / "knowledge/cases/legacy/README.md",
            root / "knowledge/cases/legacy/REVISION_MANIFEST.yml",
        ],
        directories=[root / "knowledge/cases/legacy/_revisions"],
        operation="case-import",
    ) as transaction:
        append_payloads(
            ledger,
            [case.model_dump(mode="json")],
            recorded_at=case.revision_effective_at,
            actor=actor,
            event_id_factory=lambda item, _: f"case:import:{item['case_id']}:v1",
        )
        rebuild_cases(root)
        write_case_directory(root)
        write_revision_manifest(root)
        validation = validate_cases(root)
        errors = [error for values in validation.values() for error in values]
        if errors:
            raise ValueError("案例导入校验失败：" + "；".join(errors[:10]))
        transaction.commit()
    return root / _case_relative_path(case)


_STAGE_SECTIONS = {
    "prematch_early": "source-prematch",
    "prematch_late": "source-prematch",
    "live": "source-live",
    "result_source": "result",
    "postmatch_review": "source-review",
}


def _render_stage(stage: CaseMaterialStage) -> str:
    observed = stage.observed_at.isoformat() if stage.observed_at else f"未知（{stage.observed_at_note}）"
    lines = [
        f"### {stage.material_stage}｜观察时间：{observed}",
        "",
        f"- material_id: `{stage.material_id}`",
        f"- 接收时间：{stage.received_at.isoformat()}",
        f"- 来源：`{stage.source_path}`",
    ]
    if stage.evidence_refs:
        lines.append(
            "- 证据：" + ", ".join(
                f"`{item.evidence_id}` / `{item.binding_id}`" for item in stage.evidence_refs
            )
        )
    if stage.conflicts:
        lines.append("- 冲突：" + "；".join(stage.conflicts))
    lines.extend(["", stage.content.strip()])
    return "\n".join(lines)


def append_case_stage(
    root: Path,
    *,
    case_id: str,
    stage: CaseMaterialStage,
    recorded_at: datetime,
    actor: str = "codex",
) -> Path:
    case = latest_cases(root).get(case_id)
    if case is None:
        raise ValueError(f"历史案例不存在：{case_id}")
    if case.schema_version != 3:
        raise ValueError("结构化阶段追加只支持 V3 案例")
    if stage.material_id in {item.material_id for item in case.material_stages}:
        raise ValueError(f"material_id 已存在：{stage.material_id}")
    for reference in stage.evidence_refs:
        from .evidence_registry import active_binding

        active_binding(root, reference.evidence_id, reference.binding_id, case_id=case_id)

    section = _STAGE_SECTIONS[stage.material_stage]
    events = case_events(root)
    latest_event = {str(event.payload["case_id"]): event for event in events}
    payload = case.model_dump(mode="json")
    sections = dict(payload["sections"])
    rendered = _render_stage(stage)
    sections[section] = f"{sections[section].rstrip()}\n\n---\n\n{rendered}"
    stages = [*payload["material_stages"], stage.model_dump(mode="json")]
    payload.update({
        "case_revision": case.case_revision + 1,
        "revision_effective_at": recorded_at.isoformat(),
        "sections": sections,
        "material_stages": stages,
        "prematch_analysis_present": case.prematch_analysis_present or stage.material_stage.startswith("prematch"),
        "source_review_present": case.source_review_present or stage.material_stage == "postmatch_review",
        "evidence_refs": _merged_evidence_refs(case.evidence_refs, stage.evidence_refs),
        "_supersedes_event_id": latest_event[case_id].event_id,
    })
    from .transaction import RepositoryTransaction

    ledger = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    with RepositoryTransaction(
        root,
        files=[ledger, root / _case_relative_path(case), root / _revision_relative_path(case)],
        directories=[root / "knowledge/cases/legacy/_revisions"],
        operation="case-append-stage",
    ) as transaction:
        append_payloads(
            ledger,
            [payload],
            recorded_at=recorded_at,
            actor=actor,
            event_id_factory=lambda item, _: f"case:stage:{item['case_id']}:{item['case_revision']}",
        )
        rebuild_cases(root)
        write_case_directory(root)
        write_revision_manifest(root)
        validation = validate_cases(root)
        errors = [error for values in validation.values() for error in values]
        if errors:
            raise ValueError("阶段追加校验失败：" + "；".join(errors[:10]))
        transaction.commit()
    return root / _case_relative_path(latest_cases(root)[case_id])


def append_case_material(
    root: Path,
    *,
    case_id: str,
    section: str,
    content: str,
    recorded_at: datetime,
    source_atom_ids: list[str] | None = None,
    media_ids: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    actor: str = "codex",
) -> Path | None:
    """Append distinct material to the one canonical case document for a fixture."""
    if section not in CASE_SECTIONS:
        raise ValueError(f"未知案例章节：{section}")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise ValueError("追加内容不能为空")
    events = case_events(root)
    latest_event = {str(event.payload["case_id"]): event for event in events}
    case = latest_cases(root).get(case_id)
    if case is None:
        raise ValueError(f"历史案例不存在：{case_id}")
    # A new append must never overwrite an unarchived current projection.
    previous_revision = root / _revision_relative_path(case)
    previous_rendered = render_case(case)
    if previous_revision.exists():
        if previous_revision.read_text(encoding="utf-8") != previous_rendered:
            raise ValueError(f"不可变案例版本内容不一致：{previous_revision}")
    else:
        atomic_write_text(previous_revision, previous_rendered)
    current_path = root / _case_relative_path(case)
    if not current_path.exists():
        atomic_write_text(current_path, previous_rendered)
    if normalized in case.sections[section].replace("\r\n", "\n").replace("\r", "\n"):
        return None
    payload = case.model_dump(mode="json")
    sections = dict(payload["sections"])
    sections[section] = f"{sections[section].rstrip()}\n\n---\n\n### 追加记录（{recorded_at.isoformat()}）\n\n{normalized}"
    references = _resolve_evidence_refs(
        root, case_id=case_id, evidence_ids=evidence_ids or []
    ) if case.schema_version == 3 else []
    payload.update({
        "case_revision": case.case_revision + 1,
        "revision_effective_at": recorded_at.isoformat() if case.schema_version == 3 else case.revision_effective_at,
        "sections": sections,
        "source_atom_ids": sorted(set(case.source_atom_ids) | set(source_atom_ids or [])),
        "media_ids": sorted(set(case.media_ids) | set(media_ids or [])),
        "evidence_ids": sorted(set(case.evidence_ids) | set(evidence_ids or [])) if case.schema_version < 3 else [],
        "evidence_refs": (
            _merged_evidence_refs(case.evidence_refs, references)
            if case.schema_version == 3 else []
        ),
        "_supersedes_event_id": latest_event[case_id].event_id,
    })
    ledger = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    append_payloads(
        ledger,
        [payload],
        recorded_at=recorded_at,
        actor=actor,
        event_id_factory=lambda item, _: f"case:append:{item['case_id']}:{item['case_revision']}",
    )
    rebuild_cases(root)
    write_case_directory(root)
    return root / _case_relative_path(latest_cases(root)[case_id])


def update_case_kickoff(
    root: Path,
    *,
    case_id: str,
    kickoff_at: datetime,
    evidence_ids: list[str],
    recorded_at: datetime,
    actor: str = "codex",
    correction_reason: str | None = None,
) -> Path:
    """Record independently supplied kickoff evidence and relocate the canonical case."""
    if kickoff_at.tzinfo is None or kickoff_at.utcoffset() is None:
        raise ValueError("开赛时间必须包含时区")
    if not evidence_ids:
        raise ValueError("确认开赛时间必须关联至少一条证据")
    events = case_events(root)
    latest_event = {str(event.payload["case_id"]): event for event in events}
    case = latest_cases(root).get(case_id)
    if case is None:
        raise ValueError(f"历史案例不存在：{case_id}")
    references = _resolve_evidence_refs(
        root, case_id=case_id, evidence_ids=evidence_ids, assertion_type="kickoff"
    ) if case.schema_version == 3 else []
    if case.schema_version == 3:
        from .evidence_registry import active_binding

        for reference in references:
            binding = active_binding(root, reference.evidence_id, reference.binding_id, case_id=case_id)
            if datetime.fromisoformat(str(binding.asserted_value.get("kickoff_at"))) != kickoff_at:
                raise ValueError(f"证据开赛时间与写入值不一致：{reference.binding_id}")
    if case.kickoff_at is not None and case.kickoff_at != kickoff_at and not correction_reason:
        raise ValueError(f"案例已记录不同开赛时间：{case.kickoff_at.isoformat()}；更正必须提供 correction_reason")
    if case.kickoff_at == kickoff_at:
        return root / _case_relative_path(case)
    prior_kickoff = case.kickoff_at

    old_path = root / _case_relative_path(case)
    old_revision = root / _revision_relative_path(case)
    old_rendered = render_case(case)
    if old_revision.exists() and old_revision.read_text(encoding="utf-8") != old_rendered:
        raise ValueError(f"不可变案例版本内容不一致：{old_revision}")
    if not old_revision.exists():
        atomic_write_text(old_revision, old_rendered)

    payload = case.model_dump(mode="json")
    sections = dict(payload["sections"])
    if prior_kickoff is not None:
        sections["limitations"] = (
            f"{sections['limitations'].rstrip()}\n\n---\n\n"
            f"### 开赛时间更正（{recorded_at.isoformat()}）\n\n"
            f"- 原记录：{prior_kickoff.isoformat()}\n"
            f"- 更正为：{kickoff_at.isoformat()}\n"
            f"- 原因：{correction_reason}\n"
            f"- 证据：{', '.join(evidence_ids)}"
        )
    payload.update({
        "case_revision": case.case_revision + 1,
        "kickoff_at": kickoff_at.isoformat(),
        "sections": sections,
        "evidence_ids": sorted(set(case.evidence_ids) | set(evidence_ids)) if case.schema_version < 3 else [],
        "evidence_refs": (
            _merged_evidence_refs(case.evidence_refs, references)
            if case.schema_version == 3 else []
        ),
        "_supersedes_event_id": latest_event[case_id].event_id,
    })
    append_payloads(
        root / EXTRACTION_RELATIVE / "case-events.jsonl",
        [payload],
        recorded_at=recorded_at,
        actor=actor,
        event_id_factory=lambda item, _: f"case:kickoff:{item['case_id']}:v{item['case_revision']}",
    )
    new_case = latest_cases(root)[case_id]
    new_path = root / _case_relative_path(new_case)
    rebuild_cases(root)
    if old_path != new_path and old_path.exists():
        old_case = load_case(old_path)
        historical = historical_case(root, old_case.case_id, old_case.case_revision)
        if old_case.case_id != case_id or historical is None or historical.read_bytes() != old_path.read_bytes():
            raise ValueError(f"旧案例路径无法安全迁移：{old_path}")
        old_path.unlink()
    write_case_directory(root)
    return new_path


def archive_user_kickoff_evidence(
    root: Path,
    records: list[dict[str, object]],
    *,
    recorded_at: datetime,
) -> Path:
    """Archive user schedule screenshots with the identified fixture/date mappings."""
    source_dir = Path(r"C:\Users\lcz\AppData\Local\Temp")
    relative = Path("knowledge/evidence/user-kickoffs/2026-07-30")
    destination = root / relative
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / "MANIFEST.yml"
    existing = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    by_evidence_id = {
        str(item["evidence_id"]): item
        for item in (existing or {}).get("records", [])
    }
    for record in records:
        source_name = str(record["source_basename"])
        target_name = str(record["archived_name"])
        source = source_dir / source_name
        target = destination / target_name
        if not target.exists():
            if not source.exists():
                raise ValueError(f"用户开赛时间截图已不存在：{source}")
            shutil.copyfile(source, target)
        by_evidence_id[str(record["evidence_id"])] = {
            **record,
            "archived_path": (relative / target_name).as_posix(),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "recorded_at": recorded_at.isoformat(),
            "identity_basis": "user-provided-context-and-visible-schedule",
        }
    atomic_write_text(
        manifest_path,
        yaml.safe_dump({"schema_version": 1, "evidence_type": "user_schedule_screenshot", "records": list(by_evidence_id.values())}, allow_unicode=True, sort_keys=False),
    )
    return manifest_path


def _settlement(total: int, line: float, *, over: bool) -> str:
    half = line % 1 == 0.5
    quarter = line % 1 in {0.25, 0.75}
    if half:
        won = total > line if over else total < line
        return "full_win" if won else "full_loss"
    if not quarter:
        if total == line:
            return "push"
        won = total > line if over else total < line
        return "full_win" if won else "full_loss"
    lower, upper = (line - 0.25, line + 0.25)
    first = _settlement(total, lower, over=over)
    second = _settlement(total, upper, over=over)
    return _combine_settlements(first, second)


def _combine_settlements(first: str, second: str) -> str:
    if first == second:
        return first
    pair = frozenset((first, second))
    if pair == frozenset(("full_win", "push")):
        return "half_win"
    if pair == frozenset(("full_loss", "push")):
        return "half_loss"
    raise ValueError(f"无法合并盘口结算：{first} / {second}")


def _handicap_settlement(home_margin: int, home_line: float) -> str:
    if home_line % 1 in {0.25, 0.75}:
        first = _handicap_settlement(home_margin, home_line - 0.25)
        second = _handicap_settlement(home_margin, home_line + 0.25)
        return _combine_settlements(first, second)
    value = home_margin + home_line
    if value > 0:
        return "full_win"
    if value < 0:
        return "full_loss"
    return "push"


def archive_user_result_evidence(root: Path, *, recorded_at: datetime) -> dict[str, str]:
    """Copy user-provided screenshots once and produce a durable evidence manifest."""
    source_dir = Path(r"C:\Users\lcz\AppData\Local\Temp")
    specs = [
        ("user-result-20260729-brazil-serie-a", "codex-clipboard-0b001af9-68f1-464c-9db7-cdfb6cf2045b.png", "brazil-serie-a-results.png", ["legacy-flamengo-sao-paulo", "legacy-gremio-fluminense"], "截图显示弗拉门戈 1-1 圣保罗、格雷米奥 1-1 弗鲁米嫩塞，半场均为 0-0。"),
        ("user-result-20260729-kleague", "codex-clipboard-05558c83-8078-4699-8a3b-d54e23e042be.png", "k-league-gwangju-jeju.png", ["legacy-gwangju-jeju"], "截图显示 FC光州 1-2 济州SK，半场 1-1。"),
        ("user-result-20260729-sweden-gais", "codex-clipboard-62f3b6d5-0ab5-431b-9129-9cb0c73a0be8.png", "sweden-gais-halmstad.png", ["legacy-gais-halmstad"], "截图显示 哥德堡盖斯 1-1 哈姆斯塔德，半场 0-0。"),
        ("user-result-20260729-sweden-malmo", "codex-clipboard-628f4be8-7330-4065-ad94-f21f0f6b3660.png", "sweden-malmo-elfsborg.png", ["legacy-malmo-elfsborg"], "截图显示 马尔默 1-2 埃尔夫斯堡，半场 1-2。"),
    ]
    destination = root / EXTERNAL_EVIDENCE_RELATIVE
    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for evidence_id, original_name, archived_name, case_ids, visible_text in specs:
        source = source_dir / original_name
        target = destination / archived_name
        if not target.exists():
            if not source.exists():
                raise ValueError(f"用户赛果截图已不存在：{source}")
            shutil.copyfile(source, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        rows.append({
            "evidence_id": evidence_id,
            "source_basename": original_name,
            "archived_path": (EXTERNAL_EVIDENCE_RELATIVE / archived_name).as_posix(),
            "sha256": digest,
            "recorded_at": recorded_at.isoformat(),
            "case_ids": case_ids,
            "identity_basis": "user-provided-context",
            "visible_text": visible_text,
        })
    manifest = {"schema_version": 1, "evidence_type": "user_screenshot", "records": rows}
    atomic_write_text(destination / "MANIFEST.yml", yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    return {row["evidence_id"]: row["sha256"] for row in rows}


def apply_user_result_evidence(root: Path, *, recorded_at: datetime, actor: str = "codex") -> list[Path]:
    archive_user_result_evidence(root, recorded_at=recorded_at)
    def record(evidence_id: str, home: int, away: int, half_home: int, half_away: int, handicap_display: str, handicap_line: float, total_display: str, total_line: float) -> ResultRecord:
        total = home + away
        return ResultRecord(
            source_kind="user_screenshot", home_goals=home, away_goals=away,
            home_half_goals=half_home, away_half_goals=half_away,
            handicap=HandicapRecord(display_line=handicap_display, home_line=handicap_line, home_settlement=_handicap_settlement(home - away, handicap_line)),
            total_goals_market=TotalGoalsRecord(display_line=total_display, line=total_line, total_goals=total, over_settlement=_settlement(total, total_line, over=True), under_settlement=_settlement(total, total_line, over=False)),
            recorded_at=recorded_at, evidence_ids=[evidence_id],
        )
    return append_external_results(root, {
        "legacy-flamengo-sao-paulo": record("user-result-20260729-brazil-serie-a", 1, 1, 0, 0, "主让 1", -1.0, "2.5", 2.5),
        "legacy-gremio-fluminense": record("user-result-20260729-brazil-serie-a", 1, 1, 0, 0, "平手", 0.0, "2.5", 2.5),
        "legacy-gwangju-jeju": record("user-result-20260729-kleague", 1, 2, 1, 1, "主让 0.5", -0.5, "2/2.5", 2.25),
        "legacy-gais-halmstad": record("user-result-20260729-sweden-gais", 1, 1, 0, 0, "主让 1.5", -1.5, "3", 3.0),
        "legacy-malmo-elfsborg": record("user-result-20260729-sweden-malmo", 1, 2, 1, 2, "主让 0.5/1", -0.75, "2.5/3", 2.75),
    }, recorded_at=recorded_at, actor=actor)


def expand_case_text(root: Path, *, recorded_at: datetime, actor: str = "codex") -> list[Path]:
    """Rebuild source-derived sections from their complete immutable atoms without truncation."""
    atoms = {item.atom_id: item for item in load_text_inventory(root)}
    events = case_events(root)
    latest_event = {str(event.payload["case_id"]): event for event in events}
    payloads: list[dict] = []
    for case in latest_cases(root).values():
        spec = LEGACY_CASE_SPECS.get(case.case_id)
        if not spec:
            continue
        selected = sorted((atoms[item] for item in case.source_atom_ids if item in atoms), key=lambda item: (item.source_path, item.byte_start))
        prematch: list[str] = []
        review: list[str] = []
        timeline: list[str] = []
        for atom in selected:
            text = (root / atom.source_path).read_bytes()[atom.byte_start:atom.byte_end].decode("utf-8").strip()
            if not text:
                continue
            if atom.round_no in spec["review_rounds"]:
                review.append(text)
            else:
                prematch.append(text)
            if any(term in text for term in ("初盘", "中盘", "临场", "水位", "盘口", "欧赔")):
                timeline.append(text)
        sections = dict(case.sections)
        sections["source-prematch"] = "\n\n".join(prematch) or "未找到可确认的独立赛前判断。"
        sections["source-review"] = "\n\n".join(review) or "原始资料未提供明确赛后复盘。"
        sections["market-timeline"] = "\n\n".join(timeline) or "原始资料未保留可确认的完整盘口时间线。"
        if all(sections[name] == case.sections[name] for name in ("source-prematch", "source-review", "market-timeline")):
            continue
        payload = case.model_dump(mode="json")
        payload.update({
            "case_revision": case.case_revision + 1,
            "sections": sections,
            "_supersedes_event_id": latest_event[case.case_id].event_id,
        })
        draft = case_from_payload({key: value for key, value in payload.items() if key != "_supersedes_event_id"})
        payload["sections"]["result"] = _result_section(draft)
        payloads.append(payload)
    ledger = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    append_payloads(
        ledger,
        payloads,
        recorded_at=recorded_at,
        actor=actor,
        event_id_factory=lambda item, _: f"case:full-text:{item['case_id']}:v{item['case_revision']}",
    )
    paths = rebuild_cases(root)
    write_case_directory(root)
    return paths


def migrate_cases_to_v3(
    root: Path,
    *,
    recorded_at: datetime,
    dry_run: bool = False,
    actor: str = "codex",
) -> dict[str, int]:
    """Append one consolidated V3 revision for every current legacy case."""
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("迁移时间必须包含时区")
    from .evidence_registry import active_binding, evidence_records, validate_evidence_registry

    registry_errors = validate_evidence_registry(root)
    if registry_errors:
        raise ValueError("证据注册表无效：" + "；".join(registry_errors))
    registry = evidence_records(root)
    source_manifest = yaml.safe_load(
        (root / "knowledge/sources/doubao-2026-07-28/MANIFEST.yml").read_text(encoding="utf-8")
    )
    source_archived_at = datetime.fromisoformat(str(source_manifest["archived_at"]))
    events = case_events(root)
    latest_event = {str(event.payload["case_id"]): event for event in events}
    payloads: list[dict] = []
    skipped = 0
    for case_id, case in sorted(latest_cases(root).items()):
        if case.schema_version == 3:
            skipped += 1
            continue
        previous = latest_event[case_id]
        if recorded_at < previous.recorded_at:
            raise ValueError(f"迁移时间早于案例上一事件：{case_id}")
        competition_code, home_team_id, away_team_id = LEGACY_IDENTITIES[case_id]
        if case.kickoff_at is None:
            raise ValueError(f"V3 迁移要求已确认开赛时间：{case_id}")
        refs: list[EvidenceRef] = []
        for evidence_id in case.evidence_ids:
            record = registry.get(evidence_id)
            if record is None:
                raise ValueError(f"案例引用未登记证据：{case_id} / {evidence_id}")
            active = [item for item in record.bindings if item.case_id == case_id and item.status == "active"]
            if not active:
                continue
            if len(active) != 1:
                raise ValueError(f"证据无法唯一解析 binding：{case_id} / {evidence_id}")
            if recorded_at < record.recorded_at:
                raise ValueError(f"迁移时间早于引用证据：{case_id} / {evidence_id}")
            active_binding(root, evidence_id, active[0].binding_id, case_id=case_id)
            refs.append(EvidenceRef(evidence_id=evidence_id, binding_id=active[0].binding_id))
        result_record = case.result_record
        if result_record is not None:
            result_refs = [item for item in refs if registry[item.evidence_id].evidence_type == "result_screenshot"]
            result_record = result_record.model_copy(update={"evidence_ids": [], "evidence_refs": result_refs})
        old_aliases = [FixtureFingerprintAlias(version=1, value=case.fixture_fingerprint)]
        old_aliases.extend(case.fixture_fingerprint_aliases)
        fingerprint = fixture_fingerprint_v2(
            competition_code, home_team_id, away_team_id, case.kickoff_at
        )
        sections = dict(case.sections)
        sections["limitations"] = (
            f"{sections['limitations'].rstrip()}\n\n---\n\n"
            f"### 案例契约 V3 迁移（{recorded_at.isoformat()}）\n\n"
            f"- 原始资料实际归档时间：{source_archived_at.isoformat()}\n"
            "- revision 生效时间改为对应 case event 的 recorded_at。\n"
            "- 球队和赛事身份仅补充可确认项；无法确认的赛事编码保持为空。\n"
            "- 外部证据改用 evidence_id 与 binding_id 联合引用。"
        )
        payload = case.model_dump(mode="json")
        payload.update({
            "schema_version": 3,
            "case_revision": case.case_revision + 1,
            "competition_code": competition_code,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "fixture_fingerprint": fingerprint,
            "fixture_fingerprint_version": 2,
            "fixture_fingerprint_aliases": [item.model_dump(mode="json") for item in old_aliases],
            "source_effective_at": None,
            "source_archived_at": source_archived_at.isoformat(),
            "revision_effective_at": recorded_at.isoformat(),
            "evidence_ids": [],
            "evidence_refs": [item.model_dump(mode="json") for item in refs],
            "result_record": result_record.model_dump(mode="json") if result_record else None,
            "sections": sections,
            "_supersedes_event_id": previous.event_id,
        })
        payloads.append(payload)
    result = {"migrated": len(payloads), "skipped": skipped}
    if dry_run or not payloads:
        return result
    from .transaction import RepositoryTransaction

    ledger_path = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    current_files = [root / _case_relative_path(case) for case in latest_cases(root).values()]
    current_files.extend([
        root / "knowledge/cases/legacy/README.md",
        root / "knowledge/cases/legacy/REVISION_MANIFEST.yml",
    ])
    with RepositoryTransaction(
        root,
        files=[ledger_path, *current_files],
        directories=[root / "knowledge/cases/legacy/_revisions"],
        operation="case-migrate-v3",
    ) as transaction:
        append_payloads(
            ledger_path,
            payloads,
            recorded_at=recorded_at,
            actor=actor,
            event_id_factory=lambda item, _: f"case:v3:{item['case_id']}:v{item['case_revision']}",
        )
        rebuild_cases(root)
        write_case_directory(root)
        write_revision_manifest(root)
        validation = validate_cases(root)
        errors = [error for values in validation.values() for error in values]
        if errors:
            raise ValueError("V3 临时状态校验失败：" + "；".join(errors[:10]))
        transaction.commit()
    return result


def write_revision_manifest(root: Path) -> Path:
    revision_root = root / "knowledge/cases/legacy/_revisions"
    records = []
    for path in sorted(revision_root.glob("*.md")):
        case = load_case(path)
        records.append({
            "case_id": case.case_id,
            "case_revision": case.case_revision,
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    target = root / "knowledge/cases/legacy/REVISION_MANIFEST.yml"
    atomic_write_text(target, yaml.safe_dump({"schema_version": 1, "records": records}, allow_unicode=True, sort_keys=False))
    return target


def validate_cases(root: Path) -> dict[Path, list[str]]:
    results: dict[Path, list[str]] = {}
    ledger_path = root / EXTRACTION_RELATIVE / "case-events.jsonl"
    try:
        events = case_events(root)
    except Exception as exc:
        return {ledger_path: [str(exc)]}
    expected = latest_cases(root)
    event_errors: list[str] = []
    by_case: dict[str, list] = {}
    for event in events:
        by_case.setdefault(str(event.payload.get("case_id")), []).append(event)
    for case_id, items in by_case.items():
        ordered = sorted(items, key=lambda item: int(item.payload.get("case_revision", 0)))
        for index, event in enumerate(ordered, start=1):
            revision = int(event.payload.get("case_revision", 0))
            if revision != index:
                event_errors.append(f"{case_id} revision 不连续：期望 {index}，实际 {revision}")
            expected_supersedes = ordered[index - 2].event_id if index > 1 else None
            if event.supersedes_event_id != expected_supersedes:
                event_errors.append(f"{case_id} revision {revision} supersedes 关系无效")
            try:
                case = case_from_payload(event.payload)
                if case.schema_version == 3 and case.revision_effective_at != event.recorded_at:
                    event_errors.append(f"{case_id} revision {revision} 生效时间与事件不一致")
                if index > 1 and event.recorded_at < ordered[index - 2].recorded_at:
                    event_errors.append(f"{case_id} revision {revision} recorded_at 倒序")
            except Exception as exc:
                event_errors.append(f"{case_id} revision {revision} payload 无效：{exc}")
    results[ledger_path] = event_errors

    identities: dict[str, list[str]] = {}
    for case in expected.values():
        for value in [case.fixture_fingerprint, *(item.value for item in case.fixture_fingerprint_aliases)]:
            identities.setdefault(value, []).append(case.case_id)
    for value, case_ids in identities.items():
        if len(set(case_ids)) > 1:
            for case_id in case_ids:
                results.setdefault(root / _case_relative_path(expected[case_id]), []).append(
                    f"fixture_fingerprint 重复或历史别名冲突：{value}"
                )

    revision_map: dict[tuple[str, int], list[Path]] = {}
    revisions = root / "knowledge/cases/legacy/_revisions"
    for path in sorted(revisions.glob("*.md")) if revisions.exists() else []:
        try:
            case = load_case(path)
            revision_map.setdefault((case.case_id, case.case_revision), []).append(path)
        except Exception as exc:
            results[path] = [str(exc)]
    expected_revision_keys: set[tuple[str, int]] = set()
    for event in events:
        case = case_from_payload(event.payload)
        key = (case.case_id, case.case_revision)
        expected_revision_keys.add(key)
        paths = revision_map.get(key, [])
        if len(paths) != 1:
            results.setdefault(revisions, []).append(
                f"{case.case_id} revision {case.case_revision} 投影数量应为1，实际 {len(paths)}"
            )
            continue
        try:
            if load_case(paths[0]) != case:
                results.setdefault(paths[0], []).append("revision 内容与 case event payload 不一致")
        except Exception as exc:
            results.setdefault(paths[0], []).append(str(exc))
    for key, paths in revision_map.items():
        if key not in expected_revision_keys:
            for path in paths:
                results.setdefault(path, []).append("孤儿 revision：没有对应 case event")
        if len(paths) > 1:
            for path in paths:
                results.setdefault(path, []).append("重复 revision 投影")

    revision_manifest = root / "knowledge/cases/legacy/REVISION_MANIFEST.yml"
    if revision_manifest.exists():
        manifest_errors: list[str] = []
        manifest = yaml.safe_load(revision_manifest.read_text(encoding="utf-8")) or {}
        records = manifest.get("records") or []
        manifest_keys: set[tuple[str, int]] = set()
        for record in records:
            key = (str(record.get("case_id")), int(record.get("case_revision", 0)))
            manifest_keys.add(key)
            path = root / str(record.get("path"))
            if not path.is_file():
                manifest_errors.append(f"revision manifest 文件不存在：{record.get('path')}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
                manifest_errors.append(f"revision manifest 哈希不一致：{record.get('path')}")
        if manifest_keys != expected_revision_keys:
            manifest_errors.append("revision manifest 与 case event 版本集合不一致")
        results[revision_manifest] = manifest_errors

    found: set[str] = set()
    base = root / "knowledge/cases/legacy"
    for path in sorted(base.glob("**/*.md")) if base.exists() else []:
        if "_revisions" in path.parts or path.name == "README.md":
            continue
        try:
            case = load_case(path)
            found.add(case.case_id)
            errors: list[str] = []
            if expected.get(case.case_id) != case:
                errors.append("案例投影与最新 case event 不一致")
            if path.relative_to(root) != _case_relative_path(case):
                errors.append("案例路径与 kickoff_at 年份不一致")
            revisions_for_case = revision_map.get((case.case_id, case.case_revision), [])
            if len(revisions_for_case) != 1 or revisions_for_case[0].read_bytes() != path.read_bytes():
                errors.append("缺少与当前案例一致的不可变版本投影")
            try:
                _validate_references(root, case)
                if case.schema_version == 3:
                    from .evidence_registry import active_binding

                    for reference in case.evidence_refs:
                        active_binding(root, reference.evidence_id, reference.binding_id, case_id=case.case_id)
            except Exception as exc:
                errors.append(str(exc))
            results.setdefault(path, []).extend(errors)
        except Exception as exc:
            results.setdefault(path, []).append(str(exc))
    for case_id, case in expected.items():
        if case_id not in found:
            results.setdefault(root / _case_relative_path(case), []).append("缺少有效案例投影，请运行 case rebuild")
    return results
