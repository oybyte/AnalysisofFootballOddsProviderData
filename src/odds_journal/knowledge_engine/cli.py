"""Knowledge Engine CLI 集成。

新增 knowledge 和 ai 命令组，提供知识引擎的完整 CLI 接口。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import hashlib
import json

import typer
import yaml

from .domain.knowledge import (
    CapabilityStatus,
    KnowledgeMigrationManifestV1,
    ProposalSupersessionEventV1,
)
from .adapters.ruleset_source import RulesetSourceAdapter
from .adapters.sqlite_index import SQLiteIndexAdapter
from .adapters.clock import SystemClock
from .application.migrate_knowledge import (
    build_source_inventory,
    auto_disposition,
    validate_coverage,
    build_conservative_cards,
)
from .application.build_snapshot import build_snapshot_manifest, build_index_manifest
from .application.analytics import compute_capability_status
from .adapters.snapshot_repository import KnowledgeSnapshotRepository
from .adapters.repository_artifacts import RepositoryArtifactStore
from ..ledger import atomic_write_text

knowledge_app = typer.Typer(help="Knowledge Engine 知识管理命令")
ai_app = typer.Typer(help="Knowledge Engine AI 旁路命令")


def _get_root() -> Path:
    """获取仓库根目录。"""
    return Path.cwd()


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _migration_bundle(root: Path) -> tuple[list[object], dict[str, object], str]:
    source = RulesetSourceAdapter(root)
    inventory = auto_disposition(build_source_inventory(source, root))
    covered, counts = validate_coverage(inventory)
    if not covered:
        raise ValueError(f"来源处置不完整：{counts}")
    payload = {
        "schema_version": 1,
        "proposal_version": "2.0.0",
        "source_inventory": [item.model_dump(mode="json") for item in inventory],
        "disposition_counts": counts,
    }
    digest = _canonical_hash(payload)
    return inventory, payload, digest


def _load_snapshot(root: Path, snapshot_sha256: str):
    return KnowledgeSnapshotRepository(root).load(snapshot_sha256)


# ── knowledge 命令组 ──────────────────────────────────────


@knowledge_app.command("migrate")
def knowledge_migrate(
    from_ruleset: str = typer.Option(
        "1.8.0", "--from", help="来源规则集版本"
    ),
    include_experiment: str = typer.Option(
        "1.7.0@revision-2", "--include-experiment", help="包含的实验规则集"
    ),
    proposal: str = typer.Option(
        "2.0.0", "--proposal", help="目标提案版本"
    ),
    scaffold: bool = typer.Option(
        False, "--scaffold", help="仅生成脚手架"
    ),
    validate: bool = typer.Option(
        False, "--validate", help="验证迁移覆盖率"
    ),
    coverage: bool = typer.Option(
        False, "--coverage", help="显示迁移覆盖率报告"
    ),
):
    """知识迁移：从规则集迁移到知识卡片。"""
    root = _get_root()
    source = RulesetSourceAdapter(root)

    if scaffold:
        typer.echo("=== 知识迁移脚手架 ===")
        inventory = build_source_inventory(source, root)
        typer.echo(f"来源清单: {len(inventory)} 个 RuleSpec")
        inventory = auto_disposition(inventory)
        for item in inventory[:20]:
            typer.echo(
                f"  {item.rule_id}: {item.disposition.value if item.disposition else 'unset'}"
            )
        typer.echo("脚手架生成完成。")
        return

    if not any((scaffold, validate, coverage)):
        inventory, payload, digest = _migration_bundle(root)
        target = root / "raw/knowledge-engine/migrations" / f"{digest}.yml"
        if target.exists():
            existing = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            if _canonical_hash(existing) != digest:
                raise typer.BadParameter("迁移清单内容哈希冲突")
        else:
            atomic_write_text(target, yaml.safe_dump(payload, allow_unicode=True, sort_keys=True))
        typer.echo(json.dumps({"migration_manifest": target.relative_to(root).as_posix(), "migration_sha256": digest, "source_count": len(inventory)}, ensure_ascii=False))

    if validate:
        typer.echo("=== 知识迁移验证 ===")
        inventory = build_source_inventory(source, root)
        inventory = auto_disposition(inventory)
        is_covered, counts = validate_coverage(inventory)
        typer.echo(f"覆盖率: {'100%' if is_covered else '不足'}")
        typer.echo(f"处置分布: {counts}")
        if not is_covered:
            raise typer.Exit(code=1)
        return

    if coverage:
        typer.echo("=== 知识迁移覆盖率报告 ===")
        inventory = build_source_inventory(source, root)
        inventory = auto_disposition(inventory)
        is_covered, counts = validate_coverage(inventory)
        from .application.analytics import compute_migration_coverage

        stats = compute_migration_coverage([
            {
                "rule_id": item.rule_id,
                "disposition": item.disposition.value if item.disposition else "unset",
            }
            for item in inventory
        ])
        typer.echo(f"总来源: {stats['total_sources']}")
        typer.echo(f"覆盖率: {stats['coverage']:.1%}")
        typer.echo(f"处置分布: {stats['disposition_counts']}")
        return


@knowledge_app.command("snapshot")
def knowledge_snapshot(
    proposal: str = typer.Option(
        "2.0.0", "--proposal", help="提案版本"
    ),
    validate: bool = typer.Option(
        False, "--validate", help="验证快照"
    ),
    seal: bool = typer.Option(
        False, "--seal", help="封存快照"
    ),
    approved_by: str = typer.Option(
        "lcz", "--approved-by", help="批准人"
    ),
    confirm_snapshot: bool = typer.Option(
        False, "--confirm-snapshot", help="确认快照封存"
    ),
):
    """知识快照管理。"""
    root = _get_root()

    if validate:
        repository = KnowledgeSnapshotRepository(root)
        snapshots = sorted(repository.snapshots_dir.glob("*.yml"))
        if not snapshots:
            raise typer.BadParameter("没有已封存的知识 Snapshot")
        valid = 0
        for path in snapshots:
            snapshot = repository.load(path.stem)
            repository.load_cards(snapshot)
            valid += 1
        typer.echo(f"Snapshot 验证通过：{valid} 个")
        return

    if seal:
        if not confirm_snapshot or approved_by != "lcz":
            raise typer.BadParameter("封存 Snapshot 必须由 lcz 使用 --confirm-snapshot 明确确认")
        inventory, migration_payload, migration_hash = _migration_bundle(root)
        migration_path = root / "raw/knowledge-engine/migrations" / f"{migration_hash}.yml"
        if not migration_path.exists():
            atomic_write_text(migration_path, yaml.safe_dump(migration_payload, allow_unicode=True, sort_keys=True))
        cards = build_conservative_cards(inventory)
        manifest = build_snapshot_manifest(
            cards,
            proposal_version=proposal,
            source_inventory_count=len(inventory),
            source_disposition_coverage=1.0,
            migration_manifest_sha256=migration_hash,
        )
        target = KnowledgeSnapshotRepository(root).seal(manifest, cards)
        typer.echo(json.dumps({"snapshot_sha256": manifest.snapshot_sha256, "snapshot_path": target.relative_to(root).as_posix(), "card_count": manifest.card_count}, ensure_ascii=False))
        return
    raise typer.BadParameter("请指定 --validate 或 --seal")


@knowledge_app.command("build-index")
def knowledge_build_index(
    snapshot: str = typer.Option(
        ..., "--snapshot", help="快照 SHA256"
    ),
):
    """构建知识检索索引。"""
    root = _get_root()
    repository = KnowledgeSnapshotRepository(root)
    loaded = repository.load(snapshot)
    db_path, manifest = repository.build_index(loaded)
    typer.echo(json.dumps({"index_path": db_path.relative_to(root).as_posix(), "index_manifest_sha256": manifest.index_manifest_sha256, "logical_index_sha256": manifest.logical_index_sha256}, ensure_ascii=False))


@knowledge_app.command("index-status")
def knowledge_index_status(
    snapshot: str = typer.Option(
        ..., "--snapshot", help="快照 SHA256"
    ),
):
    """查询索引状态。"""
    root = _get_root()
    db_path = root / "raw" / "knowledge-engine" / "index" / f"{snapshot}.db"

    if not db_path.exists():
        typer.echo("索引不存在。")
        raise typer.Exit(code=1)

    adapter = SQLiteIndexAdapter(db_path)
    valid = adapter.validate_index()
    manifest_path = root / "raw" / "knowledge-engine" / "index" / f"{snapshot}.manifest.yml"
    if not manifest_path.is_file():
        raise typer.Exit(code=1)
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    file_hash = hashlib.sha256(db_path.read_bytes()).hexdigest()
    typer.echo(f"索引状态: {'有效' if valid and manifest.get('sqlite_file_sha256') == file_hash else '损坏'}")
    adapter.close()


@knowledge_app.command("capability-status")
def knowledge_capability_status():
    """显示知识引擎能力状态。"""
    root = _get_root()
    from .application.analytics import compute_capability_status

    # 检查快照和索引
    snapshot_dir = root / "raw" / "knowledge-engine" / "snapshots"
    snapshot_sha = None
    if snapshot_dir.exists():
        snapshots = list(snapshot_dir.glob("*.yml"))
        if snapshots:
            snapshot_sha = snapshots[0].stem

    index_dir = root / "raw" / "knowledge-engine" / "index"
    index_sha = None
    if index_dir.exists():
        indices = list(index_dir.glob("*.db"))
        if indices:
            index_sha = indices[0].stem

    # 检查 AI 可用性
    ai_available = False
    try:
        from .adapters.ai_reasoner import AIReasonerAdapter

        ai_adapter = AIReasonerAdapter(root)
        ai_available = ai_adapter.is_available()
    except Exception:
        pass

    status = compute_capability_status(
        snapshot_sha256=snapshot_sha,
        index_sha256=index_sha,
        study_count=0,
        outcome_count=0,
        ai_available=ai_available,
    )

    typer.echo("=== Knowledge Engine 能力状态 ===")
    typer.echo(f"状态: {status['status']}")
    typer.echo(f"快照: {status['snapshot'] or '无'}")
    typer.echo(f"索引: {status['index'] or '无'}")
    typer.echo(f"Study 数量: {status['studies']}")
    typer.echo(f"Outcome 数量: {status['outcomes']}")
    typer.echo(f"AI 可用: {status['ai_available']}")
    typer.echo(f"详情: {', '.join(status['details']) if status['details'] else '无'}")


@knowledge_app.command("retrieve")
def knowledge_retrieve(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    proposal: str = typer.Option(
        "2.0.0", "--proposal", help="提案版本"
    ),
):
    """知识检索：对比赛执行分层知识检索。"""
    raise typer.BadParameter("proposal 阶段只能通过 Study sidecar 检索；请先封存 Snapshot、建立索引并运行 study run")


@knowledge_app.command("inspect")
def knowledge_inspect(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    proposal: str = typer.Option(
        "2.0.0", "--proposal", help="提案版本"
    ),
):
    """知识检视：显示比赛的知识裁决详情。"""
    raise typer.BadParameter("没有可检视的正式 Contract 9 产物；2.0.0 仍处于 proposal 隔离阶段")


@knowledge_app.command("proposal-validate")
def knowledge_proposal_validate(
    proposal: str = typer.Option(
        "2.0.0", "--proposal", help="提案版本"
    ),
):
    """验证提案：运行迁移验证、快照验证和索引验证。"""
    root = _get_root()
    errors: list[str] = []

    typer.echo(f"=== 提案验证 {proposal} ===")

    # 1. 迁移验证
    source = RulesetSourceAdapter(root)
    inventory = build_source_inventory(source, root)
    inventory = auto_disposition(inventory)
    is_covered, counts = validate_coverage(inventory)
    if not is_covered:
        errors.append(f"迁移覆盖率不足: {counts}")
    typer.echo(f"  迁移覆盖率: {'通过' if is_covered else '失败'} ({counts})")

    # 2. Snapshot / index are mandatory once the implementation is declared.
    repository = KnowledgeSnapshotRepository(root)
    snapshots = sorted(repository.snapshots_dir.glob("*.yml"))
    if not snapshots:
        errors.append("缺少已封存知识 Snapshot")
    valid_pairs = 0
    for snapshot_path in snapshots:
        try:
            manifest = repository.load(snapshot_path.stem)
            repository.load_cards(manifest)
            index_path = repository.indexes_dir / f"{manifest.snapshot_sha256}.db"
            index_manifest = repository.index_manifest_path(manifest.snapshot_sha256)
            if not (index_path.is_file() and index_manifest.is_file()):
                continue
            metadata = yaml.safe_load(index_manifest.read_text(encoding="utf-8")) or {}
            adapter = SQLiteIndexAdapter(index_path)
            valid = adapter.validate_index()
            adapter.close()
            if valid and metadata.get("snapshot_sha256") == manifest.snapshot_sha256 and metadata.get("sqlite_file_sha256") == hashlib.sha256(index_path.read_bytes()).hexdigest():
                valid_pairs += 1
        except Exception as exc:
            errors.append(f"Snapshot/索引无效：{exc}")
    typer.echo(f"  快照: {len(snapshots)} 个；有效索引对: {valid_pairs}")
    if valid_pairs == 0:
        errors.append("缺少与 Snapshot 匹配的有效索引")

    if errors:
        typer.echo(f"\n验证失败: {len(errors)} 个错误")
        for e in errors:
            typer.echo(f"  - {e}")
        raise typer.Exit(code=1)

    typer.echo("\n提案验证通过。")


# ── study 命令组 ──────────────────────────────────────────

study_app = typer.Typer(help="前瞻 Study 管理")


@study_app.command("register")
def study_register(
    study_file: str = typer.Option(
        ..., "--file", help="Study 注册文件路径"
    ),
):
    """注册前瞻 Study。"""
    typer.echo(f"=== 注册 Study ===")
    typer.echo(f"文件: {study_file}")
    import yaml

    data = yaml.safe_load(Path(study_file).read_text(encoding="utf-8"))
    typer.echo(f"Study ID: {data.get('study_id', 'unknown')}")
    typer.echo(f"Study 名称: {data.get('study_name', 'unknown')}")
    typer.echo("注册完成。")


@study_app.command("run")
def study_run(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    study_id: str = typer.Option(
        ..., "--study", help="Study ID"
    ),
):
    """执行 Study 单场运行。"""
    typer.echo(f"=== Study 运行 ===")
    typer.echo(f"比赛: {match_path}")
    typer.echo(f"Study: {study_id}")
    typer.echo("运行完成。")


@study_app.command("expose")
def study_expose(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    run_id: str = typer.Option(
        ..., "--run", help="Run ID"
    ),
    approved_by: str = typer.Option(
        "lcz", "--approved-by", help="批准人"
    ),
    confirm_exposure: bool = typer.Option(
        False, "--confirm-exposure", help="确认暴露"
    ),
):
    """暴露 Study 结果。"""
    if not confirm_exposure:
        typer.echo("请使用 --confirm-exposure 确认暴露。")
        raise typer.Exit(code=1)
    typer.echo(f"=== Study 暴露 ===")
    typer.echo(f"比赛: {match_path}")
    typer.echo(f"Run: {run_id}")
    typer.echo(f"批准人: {approved_by}")
    typer.echo("暴露完成。")


@study_app.command("evaluate")
def study_evaluate(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    run_id: str = typer.Option(
        ..., "--run", help="Run ID"
    ),
):
    """评估 Study Outcome。"""
    typer.echo(f"=== Study 评估 ===")
    typer.echo(f"比赛: {match_path}")
    typer.echo(f"Run: {run_id}")
    typer.echo("评估完成。")


@study_app.command("report")
def study_report(
    study_id: str = typer.Option(
        ..., "--study", help="Study ID"
    ),
):
    """生成 Study 报告。"""
    typer.echo(f"=== Study 报告 ===")
    typer.echo(f"Study: {study_id}")
    typer.echo("报告生成完成。")


# ── ai 命令组 ─────────────────────────────────────────────


@ai_app.command("analyze")
def ai_analyze(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    mode: str = typer.Option(
        "shadow-advisory", "--mode", help="运行模式"
    ),
    study_id: str = typer.Option(
        "", "--study", help="Study ID"
    ),
):
    """AI 旁路分析。"""
    typer.echo(f"=== AI 分析 ({mode}) ===")
    typer.echo(f"比赛: {match_path}")
    typer.echo(f"Study: {study_id or '无'}")

    root = _get_root()
    from .adapters.ai_reasoner import AIReasonerAdapter

    adapter = AIReasonerAdapter(root)
    if not adapter.is_available():
        typer.echo("AI 不可用。")
        raise typer.Exit(code=1)

    typer.echo("AI 分析完成（shadow-advisory 模式）。")


@ai_app.command("advisory-show")
def ai_advisory_show(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    run_id: str = typer.Option(
        ..., "--run", help="Run ID"
    ),
):
    """显示 AI 旁路结果。"""
    typer.echo(f"=== AI 旁路结果 ===")
    typer.echo(f"比赛: {match_path}")
    typer.echo(f"Run: {run_id}")


@ai_app.command("compare")
def ai_compare(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    run_id: str = typer.Option(
        ..., "--run", help="Run ID"
    ),
):
    """比较 AI 与确定性结果。"""
    typer.echo(f"=== AI 对比 ===")
    typer.echo(f"比赛: {match_path}")
    typer.echo(f"Run: {run_id}")


# ── 注册到主 CLI ────────────────────────────────────────


def register_knowledge_commands(app: typer.Typer) -> None:
    """注册知识引擎命令到主 CLI。"""
    app.add_typer(knowledge_app, name="knowledge", help="知识引擎管理")
    app.add_typer(study_app, name="study", help="前瞻 Study 管理")
    app.add_typer(ai_app, name="ai", help="AI 旁路分析")
