from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .aliases import AliasStore
from .markdown import MatchDocument, metadata_to_yaml
from .models import (
    Evaluation,
    EvaluationValue,
    MatchMetadata,
    MatchStatus,
    HandicapResult,
    PrimaryMarket,
    Result1X2,
    Selection,
)
from .paths import match_files
from .validation import validate_document


class ServiceError(ValueError):
    pass


def parse_datetime(value: str, timezone: str = "Asia/Shanghai") -> datetime:
    if value == "now":
        return datetime.now(ZoneInfo(timezone)).replace(microsecond=0)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ServiceError("时间必须是 ISO 8601，例如 2026-07-30T18:30:00+08:00") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed


def _safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", value).strip().rstrip(".")


def _default_match_id(kickoff: datetime, code: str, home_id: str, away_id: str) -> str:
    code_slug = re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-")
    return f"{kickoff:%Y%m%d}-{code_slug}-{home_id}-{away_id}"


def create_match(
    root: Path,
    *,
    kickoff: datetime,
    timezone: str,
    competition_code: str,
    competition: str,
    home_team_id: str,
    home_team: str,
    away_team_id: str,
    away_team: str,
    match_id: str | None = None,
    supersedes_match_id: str | None = None,
) -> Path:
    aliases = AliasStore(root)
    if not aliases.has_competition(competition_code):
        raise ServiceError(f"未知联赛代码：{competition_code}")
    if not aliases.has_team(home_team_id):
        raise ServiceError(f"未知主队 ID：{home_team_id}")
    if not aliases.has_team(away_team_id):
        raise ServiceError(f"未知客队 ID：{away_team_id}")

    match_id = match_id or _default_match_id(kickoff, competition_code, home_team_id, away_team_id)
    existing = {MatchDocument.load(path).metadata.match_id for path in match_files(root)}
    if match_id in existing:
        raise ServiceError(f"match_id 已存在：{match_id}")
    if supersedes_match_id and supersedes_match_id not in existing:
        raise ServiceError(f"前序比赛不存在：{supersedes_match_id}")

    local_kickoff = kickoff.astimezone(ZoneInfo(timezone))
    metadata = MatchMetadata(
        match_id=match_id,
        supersedes_match_id=supersedes_match_id,
        kickoff_at=kickoff,
        timezone=timezone,
        competition_code=competition_code,
        competition=competition,
        season=local_kickoff.year,
        home_team_id=home_team_id,
        home_team=home_team,
        away_team_id=away_team_id,
        away_team=away_team,
        status=MatchStatus.TRACKING,
        analysis_started_at=datetime.now(ZoneInfo(timezone)).replace(microsecond=0),
    )
    directory = root / "matches" / f"{local_kickoff:%Y}" / f"{local_kickoff:%m}"
    directory.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(
        f"{local_kickoff:%Y-%m-%d}_{competition}_{home_team}_vs_{away_team}.md"
    )
    path = directory / filename
    if path.exists():
        raise ServiceError(f"比赛文件已存在：{path}")

    template = (root / "templates" / "match.md").read_text(encoding="utf-8")
    body = template.replace("{{home_team}}", home_team).replace("{{away_team}}", away_team)
    path.write_text(
        f"---\n{metadata_to_yaml(metadata)}\n---\n{body}",
        encoding="utf-8",
        newline="\n",
    )
    (root / "assets" / "matches" / match_id).mkdir(parents=True, exist_ok=True)
    (root / "raw" / "matches" / match_id).mkdir(parents=True, exist_ok=True)
    return path


def lock_match(
    path: Path,
    *,
    at: datetime,
    market: PrimaryMarket,
    selection: Selection,
    secondary: Selection | None,
    confidence: float | None,
) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ServiceError("只有 draft/tracking 可以锁定")
    document.metadata.primary_market = market
    document.metadata.primary_selection = selection
    document.metadata.secondary_selection = secondary
    document.metadata.confidence = confidence
    document.metadata.data_cutoff_at = at
    document.metadata.locked_at = at
    document.metadata.prematch_lock_sha256 = document.prematch_hash()
    document.metadata.status = MatchStatus.LOCKED
    errors = validate_document(document, AliasStore(find_root_from_path(path)))
    if errors:
        raise ServiceError("；".join(errors))
    document.save()
    return document


def finish_match(
    path: Path,
    *,
    score: str,
    result_1x2: Result1X2,
    handicap_result: HandicapResult | None,
    recorded_at: datetime,
    key_events: str | None,
) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) != MatchStatus.LOCKED:
        raise ServiceError("只有 locked 比赛可以录入赛果")
    pre_transition_errors = validate_document(document, AliasStore(find_root_from_path(path)))
    if pre_transition_errors:
        raise ServiceError("；".join(pre_transition_errors))
    match = re.fullmatch(r"(\d+)-(\d+)", score)
    if not match:
        raise ServiceError("比分必须使用 H-A 格式，例如 2-1")
    total = int(match.group(1)) + int(match.group(2))
    document.metadata.score = score
    document.metadata.result_1x2 = result_1x2
    document.metadata.handicap_result = handicap_result
    document.metadata.total_goals = total
    document.metadata.result_recorded_at = recorded_at
    document.metadata.key_events = key_events
    document.metadata.status = MatchStatus.FINISHED
    body = (
        "## 五、实际赛果\n\n"
        f"- 最终比分：{score}\n"
        f"- 胜平负结果：{result_1x2}\n"
        f"- 让球结果：{handicap_result or '未记录'}\n"
        f"- 总进球：{total}\n"
        f"- 关键事件：{key_events or '无'}\n"
        f"- 记录时间：{recorded_at.isoformat()}\n"
    )
    document.replace_section("result", body)
    document.save()
    return document


def void_match(path: Path, *, reason: str) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) in {MatchStatus.FINISHED, MatchStatus.REVIEWED, MatchStatus.VOID}:
        raise ServiceError("当前状态不能转为 void")
    if document.metadata.prematch_lock_sha256:
        pre_transition_errors = validate_document(document, AliasStore(find_root_from_path(path)))
        if pre_transition_errors:
            raise ServiceError("；".join(pre_transition_errors))
    document.metadata.void_reason = reason.strip()
    document.metadata.status = MatchStatus.VOID
    document.replace_section("result", f"## 五、实际赛果\n\n- 比赛无效原因：{reason.strip()}\n")
    document.save()
    return document


def review_match(
    path: Path,
    *,
    reviewed_at: datetime,
    primary: EvaluationValue,
    handicap: EvaluationValue,
    total_goals_range: EvaluationValue,
    score_range: EvaluationValue,
    confidence_calibration: EvaluationValue,
    changed_main: bool | None,
) -> MatchDocument:
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) != MatchStatus.FINISHED:
        raise ServiceError("只有 finished 比赛可以完成复盘")
    document.metadata.evaluation = Evaluation(
        primary=primary,
        handicap=handicap,
        total_goals_range=total_goals_range,
        score_range=score_range,
        confidence_calibration=confidence_calibration,
    )
    document.metadata.live_update_changed_main = changed_main
    document.metadata.reviewed_at = reviewed_at
    document.metadata.status = MatchStatus.REVIEWED
    errors = validate_document(document, AliasStore(find_root_from_path(path)))
    if errors:
        raise ServiceError("；".join(errors))
    document.save()
    return document


def find_root_from_path(path: Path) -> Path:
    current = path.resolve().parent
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise ServiceError("无法从比赛文件定位项目根目录")
