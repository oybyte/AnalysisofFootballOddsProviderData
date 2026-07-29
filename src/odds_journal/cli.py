from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Annotated
from zoneinfo import ZoneInfo

import typer

from .aliases import AliasError, AliasStore
from .analysis_context import prepare_analysis_context
from .exporting import export_matches
from .indexing import build_index, search_index, search_results_json
from .models import EvaluationValue, HandicapResult, PrimaryMarket, Result1X2, Selection
from .paths import find_project_root
from .reporting import build_match_index, build_statistics
from .services import (
    ServiceError,
    create_match,
    finish_match,
    lock_match,
    parse_datetime,
    review_match,
    void_match,
)
from .validation import validate_all, validate_document
from .markdown import MatchDocument
from .rules import validate_rules


app = typer.Typer(help="足球盘口学习与比赛分析日志")
aliases_app = typer.Typer(help="维护球队和联赛标准别名")
app.add_typer(aliases_app, name="aliases")


@app.callback()
def configure_console() -> None:
    """Use UTF-8 consistently on Windows, including redirected JSON output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def _fail(exc: Exception) -> None:
    typer.echo(f"错误：{exc}", err=True)
    raise typer.Exit(1)


@aliases_app.command("add-team")
def add_team(
    team_id: Annotated[str, typer.Option("--id")],
    name: Annotated[str, typer.Option("--name")],
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
) -> None:
    try:
        AliasStore(find_project_root()).add_team(team_id, name, alias or [])
        typer.echo(f"已新增球队：{team_id}")
    except (AliasError, RuntimeError) as exc:
        _fail(exc)


@aliases_app.command("add-competition")
def add_competition(
    code: Annotated[str, typer.Option("--code")],
    name: Annotated[str, typer.Option("--name")],
    alias: Annotated[list[str] | None, typer.Option("--alias")] = None,
) -> None:
    try:
        AliasStore(find_project_root()).add_competition(code, name, alias or [])
        typer.echo(f"已新增联赛：{code}")
    except (AliasError, RuntimeError) as exc:
        _fail(exc)


@app.command("new")
def new_match(
    kickoff: Annotated[str, typer.Option("--kickoff")],
    competition_code: Annotated[str, typer.Option("--competition-code")],
    competition: Annotated[str, typer.Option("--competition")],
    home_id: Annotated[str, typer.Option("--home-id")],
    home: Annotated[str, typer.Option("--home")],
    away_id: Annotated[str, typer.Option("--away-id")],
    away: Annotated[str, typer.Option("--away")],
    timezone: Annotated[str, typer.Option("--timezone")] = "Asia/Shanghai",
    match_id: Annotated[str | None, typer.Option("--match-id")] = None,
    supersedes: Annotated[str | None, typer.Option("--supersedes")] = None,
) -> None:
    try:
        root = find_project_root()
        path = create_match(
            root,
            kickoff=parse_datetime(kickoff, timezone),
            timezone=timezone,
            competition_code=competition_code,
            competition=competition,
            home_team_id=home_id,
            home_team=home,
            away_team_id=away_id,
            away_team=away,
            match_id=match_id,
            supersedes_match_id=supersedes,
        )
        typer.echo(f"已创建：{path}")
    except (ServiceError, RuntimeError) as exc:
        _fail(exc)


@app.command("validate")
def validate(
    path: Annotated[Path | None, typer.Argument()] = None,
    all_matches: Annotated[bool, typer.Option("--all")] = False,
    rules_only: Annotated[bool, typer.Option("--rules")] = False,
) -> None:
    try:
        root = find_project_root(path)
        if rules_only:
            results = validate_rules(root)
        elif all_matches or path is None:
            results = validate_all(root)
        else:
            document = MatchDocument.load(path)
            results = {path: validate_document(document, AliasStore(root))}
        failed = False
        for item, errors in results.items():
            if errors:
                failed = True
                typer.echo(f"[失败] {item}")
                for error in errors:
                    typer.echo(f"  - {error}")
            else:
                typer.echo(f"[通过] {item}")
        if failed:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        _fail(exc)


@app.command("prepare-analysis")
def prepare_analysis(
    path: Annotated[Path, typer.Argument()],
    ruleset: Annotated[str | None, typer.Option("--ruleset")] = None,
    market: Annotated[list[PrimaryMarket] | None, typer.Option("--market")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    limit_rules: Annotated[int, typer.Option("--limit-rules", min=0, max=100)] = 20,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        root = find_project_root(path)
        document = MatchDocument.load(path)
        now = datetime.now(ZoneInfo(document.metadata.timezone)).replace(microsecond=0)
        if as_of is None and now > document.metadata.kickoff_at:
            raise ServiceError("比赛已开赛；历史准备必须显式提供不晚于开赛时间的 --as-of")
        cutoff = parse_datetime(as_of, document.metadata.timezone) if as_of else now
        context_path, payload, receipt = prepare_analysis_context(
            root,
            path,
            prepared_at=now,
            as_of=cutoff,
            ruleset_spec=ruleset,
            markets=market,
            limit_rules=limit_rules,
        )
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        typer.echo(f"分析规则上下文已生成：{context_path}")
        typer.echo(
            f"规则集 {receipt.ruleset_id}@{receipt.ruleset_version}；"
            f"必需规则 {len(receipt.required_documents)}；"
            f"条件规则 {len(receipt.conditional_documents)}"
        )
        typer.echo("尚未生成比赛预测；请先阅读上下文，再填写赛前推演。")
    except Exception as exc:
        _fail(exc)


@app.command("lock")
def lock(
    path: Annotated[Path, typer.Argument()],
    market: Annotated[PrimaryMarket, typer.Option("--market")],
    selection: Annotated[Selection, typer.Option("--selection")],
    at: Annotated[str, typer.Option("--at")] = "now",
    secondary: Annotated[Selection | None, typer.Option("--secondary")] = None,
    confidence: Annotated[float | None, typer.Option("--confidence")] = None,
) -> None:
    try:
        document = MatchDocument.load(path)
        lock_match(
            path,
            at=parse_datetime(at, document.metadata.timezone),
            market=market,
            selection=selection,
            secondary=secondary,
            confidence=confidence,
        )
        typer.echo("赛前内容已锁定。建议立即执行 git add/commit。")
    except Exception as exc:
        _fail(exc)


@app.command("finish")
def finish(
    path: Annotated[Path, typer.Argument()],
    score: Annotated[str, typer.Option("--score")],
    result_1x2: Annotated[Result1X2, typer.Option("--result-1x2")],
    handicap_result: Annotated[HandicapResult | None, typer.Option("--handicap-result")] = None,
    recorded_at: Annotated[str, typer.Option("--recorded-at")] = "now",
    key_events: Annotated[str | None, typer.Option("--key-events")] = None,
) -> None:
    try:
        document = MatchDocument.load(path)
        finish_match(
            path,
            score=score,
            result_1x2=result_1x2,
            handicap_result=handicap_result,
            recorded_at=parse_datetime(recorded_at, document.metadata.timezone),
            key_events=key_events,
        )
        typer.echo("赛果已记录。")
    except Exception as exc:
        _fail(exc)


@app.command("void")
def mark_void(
    path: Annotated[Path, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    try:
        void_match(path, reason=reason)
        typer.echo("比赛已标记为 void。")
    except Exception as exc:
        _fail(exc)


@app.command("review")
def review(
    path: Annotated[Path, typer.Argument()],
    primary: Annotated[EvaluationValue, typer.Option("--primary")],
    handicap: Annotated[EvaluationValue, typer.Option("--handicap")] = EvaluationValue.NOT_APPLICABLE,
    total_goals_range: Annotated[EvaluationValue, typer.Option("--total-goals-range")] = EvaluationValue.NOT_APPLICABLE,
    score_range: Annotated[EvaluationValue, typer.Option("--score-range")] = EvaluationValue.NOT_APPLICABLE,
    confidence_calibration: Annotated[EvaluationValue, typer.Option("--confidence-calibration")] = EvaluationValue.NOT_APPLICABLE,
    reviewed_at: Annotated[str, typer.Option("--reviewed-at")] = "now",
    changed_main: Annotated[bool | None, typer.Option("--changed-main/--unchanged-main")] = None,
) -> None:
    try:
        document = MatchDocument.load(path)
        review_match(
            path,
            reviewed_at=parse_datetime(reviewed_at, document.metadata.timezone),
            primary=primary,
            handicap=handicap,
            total_goals_range=total_goals_range,
            score_range=score_range,
            confidence_calibration=confidence_calibration,
            changed_main=changed_main,
        )
        typer.echo("复盘已完成。")
    except Exception as exc:
        _fail(exc)


@app.command("export")
def export_command(
    skip_invalid: Annotated[bool, typer.Option("--skip-invalid")] = False,
) -> None:
    try:
        count, diagnostics = export_matches(find_project_root(), skip_invalid=skip_invalid)
        typer.echo(f"已导出 {count} 场比赛。")
        for message in diagnostics:
            typer.echo(f"跳过：{message}")
    except Exception as exc:
        _fail(exc)


@app.command("build-index")
def build_index_command() -> None:
    try:
        path, count = build_index(find_project_root())
        typer.echo(f"索引已生成：{path}（{count} 个片段）")
    except Exception as exc:
        _fail(exc)


@app.command("search")
def search(
    query: Annotated[str, typer.Argument()],
    competition_code: Annotated[str | None, typer.Option("--competition-code")] = None,
    team_id: Annotated[str | None, typer.Option("--team-id")] = None,
    section_type: Annotated[str | None, typer.Option("--section-type")] = None,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    exclude_match_id: Annotated[str | None, typer.Option("--exclude-match-id")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        results = search_index(
            find_project_root(),
            query,
            competition_code=competition_code,
            team_id=team_id,
            section_type=section_type,
            as_of=parse_datetime(as_of) if as_of else None,
            exclude_match_id=exclude_match_id,
            limit=limit,
        )
        if json_output:
            typer.echo(search_results_json(results))
            return
        for result in results:
            typer.echo(
                f"[{result.section_type}] {result.source_path} "
                f"effective_at={result.effective_at or '-'} score={result.score:.3f}"
            )
            typer.echo(result.content[:300].replace("\n", " "))
            typer.echo("")
    except Exception as exc:
        _fail(exc)


@app.command("stats")
def stats() -> None:
    try:
        root = find_project_root()
        index_path = build_match_index(root)
        markdown_path, json_path, payload = build_statistics(root)
        typer.echo(f"比赛索引：{index_path}")
        typer.echo(f"统计报告：{markdown_path} / {json_path}")
        typer.echo(f"有效复盘比赛：{payload['reviewed_matches']}")
    except Exception as exc:
        _fail(exc)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
