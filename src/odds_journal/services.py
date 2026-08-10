from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .aliases import AliasStore
from .markdown import MatchDocument, metadata_to_yaml
from .models import (
    AnalysisDataMode,
    AnalysisOutlook,
    Evaluation,
    EvaluationValue,
    MatchMetadata,
    MatchStatus,
    HandicapResult,
    MatchSettlement,
    MarketSnapshot,
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
    schema_version: int = 1,
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
        schema_version=schema_version,
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


def set_market_snapshots(path: Path, snapshots: list[MarketSnapshot]) -> MatchDocument:
    document = MatchDocument.load(path)
    if document.metadata.schema_version != 2:
        raise ServiceError("结构化盘口快照仅适用于 Match V2")
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ServiceError("只有 draft/tracking 可以更新赛前盘口快照")
    from .analysis_context import analysis_is_placeholder, parse_receipt

    if not analysis_is_placeholder(document.sections["prematch-reasoning"]):
        raise ServiceError("已有实质分析；请先执行 analysis restart")
    if parse_receipt(document.sections["prematch-reasoning"]) is not None:
        raise ServiceError("已有规则回执；更新快照前请执行 analysis restart")
    if len({item.snapshot_id for item in snapshots}) != len(snapshots):
        raise ServiceError("snapshot_id 不能重复")
    document.metadata.market_snapshots = snapshots
    document.save()
    return document


def lock_match(
    path: Path,
    *,
    at: datetime,
    market: PrimaryMarket,
    selection: Selection,
    secondary: Selection | None,
    confidence: float | None,
    analysis_outlook: AnalysisOutlook | None = None,
    require_current: bool = True,
) -> MatchDocument:
    from .analysis_context import parse_receipt, validate_analysis_receipt

    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ServiceError("只有 draft/tracking 可以锁定")
    if document.metadata.schema_version == 2:
        if analysis_outlook is None:
            raise ServiceError("V2 比赛必须通过 --outlook-file 提供结构化四层结论")
        selected_status = None
        if analysis_outlook.schema_version == 6 and market != PrimaryMarket.PASS:
            selected_status = analysis_outlook.market_statuses.get({
                PrimaryMarket.ONE_X_TWO: "one_x_two",
                PrimaryMarket.HANDICAP: "asian_handicap",
                PrimaryMarket.TOTAL_GOALS: "total_goals",
            }[PrimaryMarket(market)])
        degraded_selection = str(selected_status) == "degraded" if selected_status is not None else AnalysisDataMode(analysis_outlook.data_mode) == AnalysisDataMode.DEGRADED
        if degraded_selection:
            if confidence is not None and confidence > 0.69:
                raise ServiceError("degraded 分析置信度不得超过 0.69")
    receipt_errors = validate_analysis_receipt(
        find_root_from_path(path),
        document,
        lock_at=at,
        market=market,
        require_current=require_current,
    )
    if receipt_errors:
        raise ServiceError("；".join(receipt_errors))
    receipt = parse_receipt(document.sections["prematch-reasoning"])
    if receipt and receipt.schema_version >= 2:
        from .case_retrieval import validate_case_receipt
        from .scenarios import validate_scenario_workflow
        from .validation import validate_v2_reasoning_order

        v2_errors = [
            *validate_scenario_workflow(document, require_v2=True),
            *validate_case_receipt(find_root_from_path(path), document, require_current=require_current),
            *validate_v2_reasoning_order(document.sections["prematch-reasoning"], require_complete=True),
        ]
        if v2_errors:
            raise ServiceError("；".join(dict.fromkeys(v2_errors)))
    if receipt and receipt.schema_version >= 3:
        from .agent_workflow import validate_analysis_draft

        draft_errors = validate_analysis_draft(
            find_root_from_path(path), document, outlook=analysis_outlook,
            require_current=require_current,
        )
        if draft_errors:
            raise ServiceError("；".join(draft_errors))
    document.metadata.primary_market = market
    document.metadata.primary_selection = selection
    document.metadata.secondary_selection = secondary
    document.metadata.confidence = confidence
    document.metadata.analysis_outlook = analysis_outlook
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
    result_1x2: Result1X2 | None,
    handicap_result: HandicapResult | None,
    recorded_at: datetime,
    key_events: str | None,
    result_source: str | None = None,
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
    home_goals = int(match.group(1))
    away_goals = int(match.group(2))
    total = home_goals + away_goals
    derived_1x2 = (
        Result1X2.HOME
        if home_goals > away_goals
        else Result1X2.AWAY
        if home_goals < away_goals
        else Result1X2.DRAW
    )
    if document.metadata.schema_version == 2:
        if result_1x2 is not None or handicap_result is not None:
            raise ServiceError("V2 赛果由锁定盘口自动结算，不接受人工结果参数")
        if not result_source or not result_source.strip():
            raise ServiceError("V2 录入赛果必须提供 --source")
        outlook = document.metadata.analysis_outlook
        if outlook is None:
            raise ServiceError("V2 比赛缺少锁定的四层结论")
        if AnalysisDataMode(outlook.data_mode) != AnalysisDataMode.PASS:
            from .settlement import (
                score_candidate_hit,
                settle_asian_handicap,
                settle_fixed_handicap_1x2,
                settle_total_goals,
                total_goals_range_hit,
            )

            asian_selection = Selection(outlook.asian_handicap.ranking.choices[0]) if outlook.asian_handicap else None
            total_signal = outlook.total_goals_signal
            document.metadata.settlement = MatchSettlement(
                asian_selection=asian_selection,
                asian_result=settle_asian_handicap(
                    home_goals,
                    away_goals,
                    outlook.asian_handicap.home_line,
                    asian_selection,
                ) if outlook.asian_handicap and asian_selection else None,
                fixed_handicap_result=settle_fixed_handicap_1x2(
                    home_goals,
                    away_goals,
                    outlook.fixed_handicap_1x2.home_line,
                ) if outlook.fixed_handicap_1x2 else None,
                total_goals_result=settle_total_goals(
                    home_goals, away_goals, total_signal.line, total_signal.side,
                ) if total_signal else None,
                total_goals_range_hit=(
                    total_goals_range_hit(home_goals, away_goals, outlook.total_goals.minimum, outlook.total_goals.maximum)
                    if outlook.total_goals is not None else None
                ),
                score_candidate_hit=(
                    score_candidate_hit(home_goals, away_goals, outlook.score_candidates)
                    if outlook.score_candidates else None
                ),
            )
        else:
            document.metadata.settlement = MatchSettlement()
    elif result_1x2 is None:
        raise ServiceError("V1 比赛必须提供 --result-1x2")
    elif Result1X2(result_1x2) != derived_1x2:
        raise ServiceError("result_1x2 与比分不一致")
    document.metadata.score = score
    document.metadata.result_1x2 = derived_1x2
    document.metadata.handicap_result = handicap_result
    document.metadata.total_goals = total
    document.metadata.result_recorded_at = recorded_at
    document.metadata.result_source = result_source.strip() if result_source else None
    document.metadata.key_events = key_events
    document.metadata.status = MatchStatus.FINISHED
    body = (
        "## 五、实际赛果\n\n"
        f"- 最终比分：{score}\n"
        f"- 胜平负结果：{derived_1x2.value}\n"
        f"- 让球结果：{handicap_result or '见自动结算'}\n"
        f"- 总进球：{total}\n"
        f"- 自动结算：{document.metadata.settlement.model_dump(mode='json') if document.metadata.settlement else 'V1 人工记录'}\n"
        f"- 赛果来源：{result_source or 'V1 未要求'}\n"
        f"- 关键事件：{key_events or '无'}\n"
        f"- 记录时间：{recorded_at.isoformat()}\n"
    )
    document.replace_section("result", body)
    document.save()
    try:
        from .experiments import score_experiment_advisory_outcome, score_experiment_outcome, score_experiment_research

        score_experiment_outcome(find_root_from_path(path), path)
        score_experiment_advisory_outcome(find_root_from_path(path), path)
        score_experiment_research(find_root_from_path(path), path)
    except Exception as exc:
        from .experiments import record_experiment_failure

        record_experiment_failure(
            find_root_from_path(path),
            match_id=document.metadata.match_id,
            stage="finish",
            reason=str(exc),
            recorded_at=recorded_at,
        )
    return document


def finish_historical_match(
    path: Path,
    *,
    score: str,
    recorded_at: datetime,
    key_events: str | None,
    result_source: str,
) -> MatchDocument:
    """Close an unlocked historical record without inventing a prematch lock."""
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        raise ServiceError("只有 draft/tracking 比赛可以进行历史赛果完结")
    if any((document.metadata.locked_at, document.metadata.prematch_lock_sha256, document.metadata.settlement)):
        raise ServiceError("已存在锁定或自动结算信息，应使用普通 finish")
    source = result_source.strip()
    if not source:
        raise ServiceError("历史赛果完结必须提供 --source")
    match = re.fullmatch(r"(\d+)-(\d+)", score)
    if not match:
        raise ServiceError("比分必须使用 H-A 格式，例如 2-1")
    home_goals = int(match.group(1))
    away_goals = int(match.group(2))
    result = (
        Result1X2.HOME if home_goals > away_goals
        else Result1X2.AWAY if home_goals < away_goals
        else Result1X2.DRAW
    )
    document.metadata.score = score
    document.metadata.result_1x2 = result
    document.metadata.handicap_result = None
    document.metadata.total_goals = home_goals + away_goals
    document.metadata.result_recorded_at = recorded_at
    document.metadata.result_source = source
    document.metadata.key_events = key_events
    document.metadata.status = MatchStatus.HISTORICAL_FINISHED
    document.replace_section(
        "result",
        "## 五、历史赛果（未锁定）\n\n"
        f"- 最终比分：{score}\n"
        f"- 胜平负结果：{result.value}\n"
        f"- 总进球：{home_goals + away_goals}\n"
        f"- 赛果来源：{source}\n"
        f"- 关键事件：{key_events or '无'}\n"
        f"- 记录时间：{recorded_at.isoformat()}\n"
        "- 审计说明：赛前未锁定；本记录仅保存经确认的历史赛果，不产生预测结算或正式复盘评价。\n",
    )
    errors = validate_document(document, AliasStore(find_root_from_path(path)))
    if errors:
        raise ServiceError("；".join(errors))
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
    from .analysis_context import parse_receipt

    receipt = parse_receipt(document.sections["prematch-reasoning"])
    if receipt and receipt.schema_version >= 2:
        from .review_context import parse_review_content, validate_review_receipt
        from .scenarios import validate_scenario_workflow

        errors = [
            *validate_review_receipt(find_root_from_path(path), document),
            *validate_scenario_workflow(document, require_v2=True),
        ]
        if "TODO:replace-before-review" in parse_review_content(
            document.sections["postmatch-review"]
        ):
            errors.append("复盘正文仍包含待填写标记")
        if errors:
            raise ServiceError("；".join(dict.fromkeys(errors)))
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
