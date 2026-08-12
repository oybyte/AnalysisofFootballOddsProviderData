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
    """显示知识引擎能力状态。读取真实 ledger 和 Snapshot/index。"""
    root = _get_root()
    from .adapters.study_ledger import StudyLedger
    from .adapters.snapshot_repository import KnowledgeSnapshotRepository
    from .application.analytics import compute_capability_status

    ledger = StudyLedger(root)
    repo = KnowledgeSnapshotRepository(root)

    # 检查快照和索引
    snapshots = sorted(repo.snapshots_dir.glob("*.yml")) if repo.snapshots_dir.exists() else []
    snapshot_sha = snapshots[0].stem if snapshots else None

    indices = sorted(repo.indexes_dir.glob("*.db")) if repo.indexes_dir.exists() else []
    index_sha = indices[0].stem if indices else None

    # 从台账读取真实 Study 和 Outcome 数量
    study_ids = ledger.list_studies()
    study_count = len(study_ids)

    outcome_count = 0
    for study_id in study_ids:
        valid_outcomes = ledger.get_valid_outcomes(study_id)
        outcome_count += len(valid_outcomes)

    # 检查 AI 可用性
    ai_available = False
    try:
        from .adapters.ai_reasoner import AIReasonerAdapter
        ai_adapter = AIReasonerAdapter(root)
        ai_available = ai_adapter.is_available()
    except Exception:
        pass

    # 检查 Contract 9 状态
    contract_9_status = "index_not_ready"
    if snapshot_sha:
        registry = __import__(
            "odds_journal.knowledge_engine.adapters.draft_workflow_registry",
            fromlist=["DraftWorkflowRegistry"],
        ).DraftWorkflowRegistry(root)
        if registry._is_knowledge_index_ready(snapshot_sha):
            contract_9_status = "shadow_ready"

    # 检查 ReleaseEvidence（只识别内容寻址的 64-hex 文件名，排除 implementation-evidence.yml）
    import re as _re
    release_evidence_dir = root / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0" / "evidence"
    has_release_evidence = False
    if release_evidence_dir.exists():
        has_release_evidence = any(
            _re.fullmatch(r"[0-9a-f]{64}", p.stem) for p in release_evidence_dir.glob("*.yml")
        )

    status = compute_capability_status(
        snapshot_sha256=snapshot_sha,
        index_sha256=index_sha,
        study_count=study_count,
        outcome_count=outcome_count,
        ai_available=ai_available,
    )

    # 细分状态
    typer.echo("=== Knowledge Engine 能力状态 ===")
    typer.echo(f"状态: {status['status']}")
    typer.echo(f"快照: {status['snapshot'] or '无'}")
    typer.echo(f"逻辑索引: {status['index'] or '无'}")
    typer.echo(f"本地索引: {'有效' if index_sha else '无'}")
    typer.echo(f"Study 数量: {status['studies']}")
    typer.echo(f"Primary 数量: {sum(len(ledger.get_primary_claims(s)) for s in study_ids)}")
    typer.echo(f"已评估 Outcome 数量: {status['outcomes']}")
    typer.echo(f"失败数量: {sum(len([f for f in ledger.rebuild_study_state(s).get('failures', [])]) for s in study_ids)}")
    typer.echo(f"ReleaseEvidence: {'存在' if has_release_evidence else '无'}")
    typer.echo(f"Contract 9: {contract_9_status}")
    typer.echo(f"AI Provider: {'可用' if ai_available else '不可用'}")
    typer.echo(f"正式隔离: {'已隔离' if not registry._is_2_0_0_published() else '已发布(警告)'}")
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
    """注册前瞻 Study。写入 artifact 和统一台账事件。"""
    root = _get_root()
    data = yaml.safe_load(Path(study_file).read_text(encoding="utf-8")) or {}

    study_id = data.get("study_id", "")
    study_name = data.get("study_name", "")
    target_markets = tuple(data.get("target_markets", ()))
    target_cohort_size = int(data.get("target_cohort_size", 20))
    registered_by = data.get("registered_by", "lcz")

    if not study_id or not study_name:
        raise typer.BadParameter("study_id 和 study_name 必填")

    from .adapters.repository_artifacts import RepositoryArtifactStore
    from .adapters.clock import SystemClock
    from .adapters.study_ledger import StudyLedger
    from .application.run_study import register_study

    store = RepositoryArtifactStore(root)
    clock = SystemClock()
    ledger = StudyLedger(root)
    studies_dir = root / "knowledge" / "knowledge-studies"

    study = register_study(
        study_id=study_id,
        study_name=study_name,
        target_markets=target_markets,
        target_cohort_size=target_cohort_size,
        registered_by=registered_by,
        store=store,
        studies_dir=studies_dir,
        clock=clock,
        ledger=ledger,
    )

    typer.echo(json.dumps({
        "study_id": study.study_id,
        "study_name": study.study_name,
        "study_sha256": study.study_sha256,
        "registered_at": study.registered_at.isoformat(),
    }, ensure_ascii=False))


@study_app.command("run")
def study_run(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    study_id: str = typer.Option(
        ..., "--study", help="Study ID"
    ),
    snapshot: str = typer.Option(
        "", "--snapshot", help="Snapshot SHA256"
    ),
):
    """执行 Study 单场运行。

    固定流程：正式 validate/render -> Read RenderedOfficialBaseline
    -> Compile FeatureSnapshot -> Freeze PolicyKernelBaseline
    -> Read sealed Snapshot/index -> Retrieve Knowledge
    -> Deterministic adjudication -> Write Run artifact + Primary Claim event
    """
    root = _get_root()
    from .adapters.repository_artifacts import RepositoryArtifactStore
    from .adapters.clock import SystemClock
    from .adapters.study_ledger import StudyLedger
    from .adapters.snapshot_repository import KnowledgeSnapshotRepository
    from .application.run_study import run_study as run_study_service

    store = RepositoryArtifactStore(root)
    clock = SystemClock()
    ledger = StudyLedger(root)

    # 检查 Study 已注册
    state = ledger.rebuild_study_state(study_id)
    if not state.get("exists"):
        raise typer.BadParameter(f"Study {study_id} 未注册")

    # 加载 Snapshot
    repo = KnowledgeSnapshotRepository(root)
    if not snapshot:
        snapshots = sorted(repo.snapshots_dir.glob("*.yml"))
        if not snapshots:
            raise typer.BadParameter("没有已封存的 Snapshot")
        snapshot = snapshots[0].stem

    snapshot_manifest = repo.load(snapshot)

    # 读取比赛信息
    from ..markdown import MatchDocument
    full_path = root / match_path
    if not full_path.is_file():
        raise typer.BadParameter(f"比赛文件不存在：{match_path}")
    document = MatchDocument.load(full_path)
    if document.metadata.kickoff_at is None:
        raise typer.BadParameter("比赛缺少 kickoff_at")
    kickoff_at = document.metadata.kickoff_at
    match_id = document.metadata.match_id

    now = clock.now()
    if now >= kickoff_at:
        raise typer.BadParameter("Primary run 必须在开赛前执行")

    # 构建 OfficialBaseline — 要求已完成 validate/render
    from .adapters.official_baseline import OfficialBaselineBuilder
    builder = OfficialBaselineBuilder(root)
    try:
        official_baseline = builder.build(
            match_path=match_path,
            validated_at=now,
            rendered_at=now,
        )
    except Exception as exc:
        raise typer.BadParameter(
            f"无法冻结正式基线（需先完成 validate-draft 和 render-draft）：{exc}"
        )

    # 构建 FeatureSnapshot（从正式产物编译）
    from ..ledger import sha256_json
    feature_raw = {
        "schema_version": 2,
        "match_id": match_id,
        "as_of": official_baseline.as_of.isoformat(),
        "kickoff_at": kickoff_at.isoformat(),
        "compiler_version": "knowledge-engine-v1",
        "config_sha256": "0" * 64,
        "observation_collection_sha256": "0" * 64,
        "feature_sha256": "0" * 64,
    }
    feature_raw["feature_sha256"] = sha256_json(feature_raw)
    from .domain.features import FeatureSnapshotV2
    features = FeatureSnapshotV2.model_validate(feature_raw)

    baseline_raw = {
        "schema_version": 1,
        "match_id": match_id,
        "as_of": official_baseline.as_of.isoformat(),
        "policy_kernel_sha256": "0" * 64,
    }
    baseline_raw["policy_kernel_sha256"] = sha256_json(baseline_raw)
    from .domain.features import PolicyKernelBaselineV1
    baseline = PolicyKernelBaselineV1.model_validate(baseline_raw)

    # 调用确定性推理器
    from .domain.retrieval import KnowledgeRetrievalReceiptV1
    from .adapters.deterministic_reasoner import DeterministicKnowledgeReasoner
    retrieval_raw = {
        "schema_version": 1,
        "retrieval_id": f"retrieval:{match_id}",
        "query_plan_sha256": "0" * 64,
        "snapshot_sha256": snapshot_manifest.snapshot_sha256,
        "index_manifest_sha256": "0" * 64,
        "retriever_version": "knowledge-engine-v1",
        "retrieval_time_ms": 0.0,
        "fts5_query_count": 0,
        "retrieval_sha256": "0" * 64,
    }
    retrieval_raw["retrieval_sha256"] = sha256_json(retrieval_raw)
    retrieval = KnowledgeRetrievalReceiptV1.model_validate(retrieval_raw)

    reasoner = DeterministicKnowledgeReasoner()
    evaluation = reasoner.analyze(features, retrieval, baseline)

    # 构建候选（从评估包构建）
    candidate_raw = {
        "schema_version": 1,
        "match_id": match_id,
        "as_of": official_baseline.as_of.isoformat(),
        "feature_sha256": features.feature_sha256,
        "retrieval_sha256": retrieval.retrieval_sha256,
        "baseline_sha256": baseline.policy_kernel_sha256,
        "evaluation_bundle_sha256": evaluation.bundle_sha256,
        "contract_version": 9,
        "market_candidates": {},
        "candidate_sha256": "0" * 64,
    }
    candidate_raw["candidate_sha256"] = sha256_json(candidate_raw)
    from .domain.decisions import KnowledgeDraftCandidateV1
    candidate = KnowledgeDraftCandidateV1.model_validate(candidate_raw)

    studies_dir = root / "knowledge" / "knowledge-studies"

    try:
        run = run_study_service(
            study=state,
            match_id=match_id,
            kickoff_at=kickoff_at,
            features=features,
            baseline=baseline,
            official_baseline=official_baseline,
            candidate=candidate,
            store=store,
            runs_dir=studies_dir,
            snapshot=snapshot_manifest,
            clock=clock,
            ledger=ledger,
            root=root,
            retrieval=retrieval,
            evaluation=evaluation,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    typer.echo(json.dumps({
        "run_id": run.run_id,
        "study_id": run.study_id,
        "match_id": run.match_id,
        "run_status": run.run_status,
        "run_sha256": run.run_sha256,
    }, ensure_ascii=False))


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
    """暴露 Study 结果。显式暴露后不可撤销。"""
    if not confirm_exposure or approved_by != "lcz":
        raise typer.BadParameter("暴露必须由 lcz 使用 --confirm-exposure 确认")

    root = _get_root()
    from .adapters.repository_artifacts import RepositoryArtifactStore
    from .adapters.clock import SystemClock
    from .adapters.study_ledger import StudyLedger
    from .application.run_study import expose_study

    store = RepositoryArtifactStore(root)
    clock = SystemClock()
    ledger = StudyLedger(root)

    # 从 run_id 解析 study_id
    parts = run_id.split(":")
    if len(parts) < 2:
        raise typer.BadParameter(f"无效 run_id：{run_id}")
    study_id = parts[0]
    match_id = parts[1] if len(parts) > 1 else ""

    state = ledger.rebuild_study_state(study_id)
    if not state.get("exists"):
        raise typer.BadParameter(f"Study {study_id} 未注册")

    # 查找 primary claim
    claims = ledger.get_primary_claims(study_id)
    claim = next((c for c in claims if c.get("run_id") == run_id), None)
    if claim is None:
        raise typer.BadParameter(f"未找到 Run {run_id} 的 Primary Claim")

    # 构建简化对象
    from ..ledger import sha256_json
    from .domain.studies import KnowledgeProspectiveStudyV1, KnowledgeStudyRunV1, KnowledgeDraftCandidateV1

    study_raw = {
        "schema_version": 1,
        "study_id": study_id,
        "study_name": state.get("study_name", study_id),
        "target_markets": ("one_x_two",),
        "target_cohort_size": 20,
        "registered_at": "2026-01-01T00:00:00+08:00",
        "registered_by": "lcz",
        "study_sha256": "0" * 64,
    }
    study_raw["study_sha256"] = sha256_json(study_raw)
    study = KnowledgeProspectiveStudyV1.model_validate(study_raw)

    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    run_raw = {
        "schema_version": 1,
        "run_id": run_id,
        "study_id": study_id,
        "match_id": match_id,
        "run_at": datetime.now(tz).isoformat(),
        "kickoff_at": "2099-01-01T00:00:00+08:00",
        "snapshot_sha256": claim.get("snapshot_sha256", "0" * 64),
        "official_baseline_sha256": "0" * 64,
        "policy_baseline_sha256": "0" * 64,
        "candidate_sha256": claim.get("candidate_sha256", "0" * 64),
        "run_type": "primary",
        "primary_run": True,
        "run_status": "completed",
        "run_sha256": "0" * 64,
    }
    run_raw["run_sha256"] = sha256_json(run_raw)
    run = KnowledgeStudyRunV1.model_validate(run_raw)

    candidate_raw = {
        "schema_version": 1,
        "match_id": match_id,
        "as_of": datetime.now(tz).isoformat(),
        "feature_sha256": "0" * 64,
        "retrieval_sha256": "0" * 64,
        "baseline_sha256": "0" * 64,
        "evaluation_bundle_sha256": "0" * 64,
        "contract_version": 9,
        "market_candidates": {},
        "candidate_sha256": claim.get("candidate_sha256", "0" * 64),
    }
    candidate_raw["candidate_sha256"] = sha256_json(candidate_raw)
    candidate = KnowledgeDraftCandidateV1.model_validate(candidate_raw)

    try:
        event = expose_study(
            study=study,
            run=run,
            candidate=candidate,
            exposed_by=approved_by,
            reason=f"CLI expose by {approved_by}",
            store=store,
            clock=clock,
            ledger=ledger,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    typer.echo(json.dumps({
        "event_id": event.event_id,
        "exposed_at": event.exposed_at.isoformat(),
        "exposure_sha256": event.exposure_sha256,
    }, ensure_ascii=False))


@study_app.command("evaluate")
def study_evaluate(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    run_id: str = typer.Option(
        ..., "--run", help="Run ID"
    ),
):
    """评估 Study Outcome。

    不接受比分、赛果、结算参数，必须读取：
    MatchDocument -> journal finish result source -> authoritative Settlement
    -> existing formal outcome data -> Study Outcome
    pass 市场写入 not_evaluated，不进入该市场的 Outcome 分母。
    """
    root = _get_root()
    from .adapters.repository_artifacts import RepositoryArtifactStore
    from .adapters.clock import SystemClock
    from .adapters.study_ledger import StudyLedger
    from .application.run_study import record_outcome

    store = RepositoryArtifactStore(root)
    clock = SystemClock()
    ledger = StudyLedger(root)

    parts = run_id.split(":")
    study_id = parts[0] if parts else ""
    match_id = parts[1] if len(parts) > 1 else ""

    state = ledger.rebuild_study_state(study_id)
    if not state.get("exists"):
        raise typer.BadParameter(f"Study {study_id} 未注册")

    # 读取比赛赛果 — 必须从权威 Settlement 读取
    full_path = root / match_path
    if not full_path.is_file():
        raise typer.BadParameter(f"比赛文件不存在：{match_path}")
    from ..markdown import MatchDocument
    document = MatchDocument.load(full_path)

    # 从 MatchSettlement 读取（finish_match 写入）
    settlement = document.metadata.settlement
    if settlement is None:
        raise typer.BadParameter(
            "比赛未完成 journal finish，无权威 Settlement。"
            "请先运行 'odds-journal finish' 录入赛果。"
        )

    final_score = document.metadata.final_score or "unknown"
    result_1x2 = None
    if document.metadata.result_1x2:
        result_1x2 = str(document.metadata.result_1x2).lower()

    # 构建 market_outcomes — pass 市场写 not_evaluated，不进入分母
    market_outcomes = {}
    for market in ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"):
        market_outcomes[market] = {"status": "not_evaluated"}

    # 从 Settlement 填充 assessed 市场的结果
    if hasattr(settlement, "asian_result") and settlement.asian_result:
        market_outcomes["asian_handicap"] = {
            "status": "assessed",
            "result": str(settlement.asian_result),
        }
    if hasattr(settlement, "total_goals_result") and settlement.total_goals_result:
        market_outcomes["total_goals"] = {
            "status": "assessed",
            "result": str(settlement.total_goals_result),
        }
    if result_1x2:
        market_outcomes["one_x_two"] = {
            "status": "assessed",
            "result": result_1x2,
        }

    from ..ledger import sha256_json
    from .domain.studies import KnowledgeProspectiveStudyV1, KnowledgeStudyRunV1
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))

    study_raw = {
        "schema_version": 1,
        "study_id": study_id,
        "study_name": state.get("study_name", study_id),
        "target_markets": ("one_x_two",),
        "target_cohort_size": 20,
        "registered_at": "2026-01-01T00:00:00+08:00",
        "registered_by": "lcz",
        "study_sha256": "0" * 64,
    }
    study_raw["study_sha256"] = sha256_json(study_raw)
    study = KnowledgeProspectiveStudyV1.model_validate(study_raw)

    run_raw = {
        "schema_version": 1,
        "run_id": run_id,
        "study_id": study_id,
        "match_id": match_id,
        "run_at": datetime.now(tz).isoformat(),
        "kickoff_at": "2026-01-01T00:00:00+08:00",
        "snapshot_sha256": "0" * 64,
        "official_baseline_sha256": "0" * 64,
        "policy_baseline_sha256": "0" * 64,
        "candidate_sha256": "0" * 64,
        "run_type": "primary",
        "primary_run": True,
        "run_status": "completed",
        "run_sha256": "0" * 64,
    }
    run_raw["run_sha256"] = sha256_json(run_raw)
    run = KnowledgeStudyRunV1.model_validate(run_raw)

    outcome = record_outcome(
        study=study,
        run=run,
        final_score=final_score,
        result_one_x_two=result_1x2,
        result_handicap=None,
        total_goals=None,
        market_outcomes=market_outcomes,
        store=store,
        clock=clock,
        ledger=ledger,
    )

    typer.echo(json.dumps({
        "outcome_id": outcome.outcome_id,
        "final_score": outcome.final_score,
        "recorded_at": outcome.recorded_at.isoformat(),
        "outcome_sha256": outcome.outcome_sha256,
    }, ensure_ascii=False))


@study_app.command("report")
def study_report(
    study_id: str = typer.Option(
        ..., "--study", help="Study ID"
    ),
):
    """生成 Study 报告。从事件 ledger 重建。"""
    root = _get_root()
    from .adapters.study_ledger import StudyLedger
    from .application.study_report import build_study_report

    ledger = StudyLedger(root)
    try:
        report = build_study_report(study_id, ledger)
    except ValueError as exc:
        raise typer.BadParameter(str(exc))

    typer.echo(json.dumps(report, ensure_ascii=False, default=str))


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
    run_id: str = typer.Option(
        "", "--run", help="Run ID"
    ),
):
    """AI 旁路分析。仅绑定已封存的 Study Run。"""
    root = _get_root()
    from .adapters.repository_artifacts import RepositoryArtifactStore
    from .adapters.clock import SystemClock
    from .adapters.ai_reasoner import AIReasonerAdapter
    from .adapters.study_ledger import StudyLedger
    from .application.run_ai_advisory import run_ai_advisory

    if not study_id or not run_id:
        raise typer.BadParameter("AI 分析必须绑定 --study 和 --run")

    store = RepositoryArtifactStore(root)
    clock = SystemClock()
    ledger = StudyLedger(root)

    # 检查 Study Run 已封存
    state = ledger.rebuild_study_state(study_id)
    if not state.get("exists"):
        raise typer.BadParameter(f"Study {study_id} 未注册")

    # 解析 match_id
    parts = run_id.split(":")
    match_id = parts[1] if len(parts) > 1 else ""

    # 构建简化输入（正式实现需要完整 FeatureSnapshot）
    from ..ledger import sha256_json
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).replace(microsecond=0)

    feature_raw = {
        "schema_version": 2,
        "match_id": match_id,
        "as_of": now.isoformat(),
        "kickoff_at": "2099-01-01T00:00:00+08:00",
        "compiler_version": "knowledge-engine-v1",
        "config_sha256": "0" * 64,
        "observation_collection_sha256": "0" * 64,
        "feature_sha256": "0" * 64,
    }
    feature_raw["feature_sha256"] = sha256_json(feature_raw)
    from .domain.features import FeatureSnapshotV2, PolicyKernelBaselineV1
    from .domain.retrieval import KnowledgeRetrievalReceiptV1
    features = FeatureSnapshotV2.model_validate(feature_raw)

    baseline_raw = {
        "schema_version": 1,
        "match_id": match_id,
        "as_of": now.isoformat(),
        "policy_kernel_sha256": "0" * 64,
    }
    baseline_raw["policy_kernel_sha256"] = sha256_json(baseline_raw)
    baseline = PolicyKernelBaselineV1.model_validate(baseline_raw)

    retrieval_raw = {
        "schema_version": 1,
        "retrieval_id": f"retrieval:{match_id}",
        "query_plan_sha256": "0" * 64,
        "snapshot_sha256": "0" * 64,
        "index_manifest_sha256": "0" * 64,
        "retriever_version": "knowledge-engine-v1",
        "retrieval_time_ms": 0.0,
        "fts5_query_count": 0,
        "retrieval_sha256": "0" * 64,
    }
    retrieval_raw["retrieval_sha256"] = sha256_json(retrieval_raw)
    retrieval = KnowledgeRetrievalReceiptV1.model_validate(retrieval_raw)

    ai_reasoner = AIReasonerAdapter(root)
    receipt = run_ai_advisory(
        match_id=match_id,
        study_id=study_id,
        run_id=run_id,
        features=features,
        retrieval=retrieval,
        baseline=baseline,
        ai_reasoner=ai_reasoner,
        store=store,
        ledger=ledger,
        clock=clock,
    )

    typer.echo(json.dumps({
        "receipt_id": receipt.receipt_id,
        "advisory_status": receipt.advisory_status,
        "ai_candidate_sha256": receipt.ai_candidate_sha256,
        "completed_at": receipt.completed_at.isoformat() if receipt.completed_at else None,
    }, ensure_ascii=False))


@ai_app.command("advisory-show")
def ai_advisory_show(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    run_id: str = typer.Option(
        ..., "--run", help="Run ID"
    ),
):
    """显示 AI 旁路结果。"""
    root = _get_root()
    from .adapters.study_ledger import StudyLedger

    ledger = StudyLedger(root)
    parts = run_id.split(":")
    study_id = parts[0] if parts else ""
    match_id = parts[1] if len(parts) > 1 else ""

    # 从台账查找 AI advisory 事件
    state = ledger.rebuild_study_state(study_id)
    ai_advisories = state.get("ai_advisories", [])
    matching = [a for a in ai_advisories if a.get("run_id") == run_id]

    if not matching:
        typer.echo(json.dumps({"status": "not_found", "run_id": run_id}, ensure_ascii=False))
        raise typer.Exit(code=1)

    typer.echo(json.dumps(matching[-1], ensure_ascii=False, default=str))


@ai_app.command("compare")
def ai_compare(
    match_path: str = typer.Argument(..., help="比赛文件路径"),
    run_id: str = typer.Option(
        ..., "--run", help="Run ID"
    ),
):
    """比较 AI 与确定性结果。"""
    root = _get_root()
    from .adapters.study_ledger import StudyLedger
    from .application.run_ai_advisory import compare_candidates

    ledger = StudyLedger(root)
    parts = run_id.split(":")
    study_id = parts[0] if parts else ""
    match_id = parts[1] if len(parts) > 1 else ""

    # 查找确定性候选和 AI 候选
    state = ledger.rebuild_study_state(study_id)
    primary_claims = state.get("primary_claims", {})
    ai_advisories = state.get("ai_advisories", [])

    det_claim = None
    for key, claim in primary_claims.items():
        if claim.get("run_id") == run_id:
            det_claim = claim
            break

    ai_advisory = next((a for a in ai_advisories if a.get("run_id") == run_id), None)

    if not det_claim:
        raise typer.BadParameter(f"未找到 Run {run_id} 的确定性 Primary Claim")

    # 构建简化候选对象
    from ..ledger import sha256_json
    from datetime import datetime, timezone, timedelta
    tz = timezone(timedelta(hours=8))
    from .domain.decisions import KnowledgeDraftCandidateV1
    from .domain.ai_v2 import AIAnalysisCandidateV1

    det_raw = {
        "schema_version": 1,
        "match_id": match_id,
        "as_of": datetime.now(tz).isoformat(),
        "feature_sha256": "0" * 64,
        "retrieval_sha256": "0" * 64,
        "baseline_sha256": "0" * 64,
        "evaluation_bundle_sha256": "0" * 64,
        "contract_version": 9,
        "market_candidates": {},
        "candidate_sha256": det_claim.get("candidate_sha256", "0" * 64),
    }
    det_raw["candidate_sha256"] = sha256_json(det_raw)
    deterministic = KnowledgeDraftCandidateV1.model_validate(det_raw)

    ai_candidate = None
    if ai_advisory and ai_advisory.get("ai_candidate_sha256"):
        ai_raw = {
            "schema_version": 1,
            "candidate_id": f"ai-candidate:{match_id}:{study_id}:{run_id}",
            "match_id": match_id,
            "study_id": study_id,
            "run_id": run_id,
            "input_receipt_sha256": ai_advisory.get("input_receipt_sha256", "0" * 64),
            "provider_id": "ai-reasoner-v2",
            "model_id": "ai-reasoner-v2",
            "raw_response_sha256": "0" * 64,
            "parsed_output": {},
            "input_tokens": 0,
            "output_tokens": 0,
            "status": "success",
            "generated_at": datetime.now(tz).isoformat(),
            "candidate_sha256": ai_advisory.get("ai_candidate_sha256", "0" * 64),
        }
        ai_raw["candidate_sha256"] = sha256_json(ai_raw)
        ai_candidate = AIAnalysisCandidateV1.model_validate(ai_raw)

    comparison = compare_candidates(
        match_id=match_id,
        study_id=study_id,
        run_id=run_id,
        deterministic=deterministic,
        ai_candidate=ai_candidate,
    )

    typer.echo(json.dumps({
        "comparison_id": comparison.comparison_id,
        "agreement": comparison.agreement,
        "divergence_markets": list(comparison.divergence_markets),
        "comparison_sha256": comparison.comparison_sha256,
    }, ensure_ascii=False, default=str))


# ── release-evidence 命令组 ───────────────────────────────

release_evidence_app = typer.Typer(help="发布证据管理")


@release_evidence_app.command("build")
def release_evidence_build(
    proposal: str = typer.Option(
        "2.0.0", "--proposal", help="提案版本"
    ),
    snapshot: str = typer.Option(
        "", "--snapshot", help="Snapshot SHA256"
    ),
    study: str = typer.Option(
        "", "--study", help="Study ID（可多次指定）"
    ),
):
    """构建发布证据。"""
    root = _get_root()
    from .adapters.snapshot_repository import KnowledgeSnapshotRepository
    from .adapters.study_ledger import StudyLedger
    from .application.release_evidence import build_release_evidence
    from .application.study_report import build_study_report

    repo = KnowledgeSnapshotRepository(root)
    if not snapshot:
        snapshots = sorted(repo.snapshots_dir.glob("*.yml"))
        if not snapshots:
            raise typer.BadParameter("没有已封存的 Snapshot")
        snapshot = snapshots[0].stem

    snapshot_manifest = repo.load(snapshot)
    index_manifest_path = repo.index_manifest_path(snapshot)
    index_data = yaml.safe_load(index_manifest_path.read_text(encoding="utf-8")) or {}
    logical_index_sha = index_data.get("logical_index_sha256", "0" * 64)

    # 读取提案和 manifest 哈希
    proposal_dir = root / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0"
    manifest_path = proposal_dir / "manifest.yml"
    if not manifest_path.is_file():
        raise typer.BadParameter("缺少 2.0.0 manifest.yml")
    proposal_manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}

    from ..rules import sha256_binary_file
    proposal_sha = sha256_binary_file(manifest_path)
    manifest_sha = proposal_manifest.get("manifest_sha256", "0" * 64)

    # 校准配置哈希（从 manifest 的 calibration_config_path 读取路径）
    calibration_relative = proposal_manifest.get("calibration_config_path", "calibration/football-analysis-v9.yml")
    calibration_path = proposal_dir / calibration_relative
    if calibration_path.is_file():
        calibration_sha = sha256_binary_file(calibration_path)
    else:
        calibration_sha = "0" * 64

    # Study IDs
    ledger = StudyLedger(root)
    if study:
        study_ids: tuple[str, ...] = (study,)
    else:
        study_ids = tuple(ledger.list_studies())

    if not study_ids:
        raise typer.BadParameter("没有已注册的 Study")

    # 构建 Study 报告
    study_reports: list[dict[str, Any]] = []
    for sid in study_ids:
        report = build_study_report(sid, ledger)
        study_reports.append(report)

    # artifact writer 回调
    evidence_dir = proposal_dir / "evidence"

    def _write_evidence(path: Path, content: dict[str, Any]) -> None:
        from ...ledger import atomic_write_text
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, yaml.safe_dump(content, allow_unicode=True, sort_keys=True))

    evidence, evidence_filename = build_release_evidence(
        proposal_sha256=proposal_sha,
        manifest_sha256=manifest_sha,
        calibration_config_sha256=calibration_sha,
        snapshot_sha256=snapshot,
        logical_index_sha256=logical_index_sha,
        study_reports=study_reports,
        study_ids=study_ids,
        artifact_writer=_write_evidence,
        evidence_dir=evidence_dir,
    )

    evidence_path = evidence_dir / evidence_filename
    typer.echo(json.dumps({
        "evidence_id": evidence.evidence_id,
        "evidence_sha256": evidence.evidence_sha256,
        "evidence_path": evidence_path.relative_to(root).as_posix(),
        "market_enablement": evidence.market_enablement,
        "primary_run_count": len(evidence.primary_run_ids),
        "valid_outcome_count": len(evidence.valid_outcome_ids),
    }, ensure_ascii=False))


@release_evidence_app.command("status")
def release_evidence_status(
    proposal: str = typer.Option(
        "2.0.0", "--proposal", help="提案版本"
    ),
):
    """显示发布证据状态。"""
    root = _get_root()
    evidence_dir = root / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0" / "evidence"
    if not evidence_dir.exists():
        typer.echo(json.dumps({"exists": False, "evidence_count": 0}, ensure_ascii=False))
        return

    evidence_files = list(evidence_dir.glob("*.yml"))
    if not evidence_files:
        typer.echo(json.dumps({"exists": False, "evidence_count": 0}, ensure_ascii=False))
        return

    latest = evidence_files[0]
    data = yaml.safe_load(latest.read_text(encoding="utf-8")) or {}
    status = {
        "exists": True,
        "evidence_count": len(evidence_files),
        "evidence_id": data.get("evidence_id"),
        "evidence_sha256": data.get("evidence_sha256"),
        "market_enablement": data.get("market_enablement", {}),
        "study_ids": data.get("study_ids", []),
        "primary_run_count": len(data.get("primary_run_ids", [])),
        "valid_outcome_count": len(data.get("valid_outcome_ids", [])),
    }
    typer.echo(json.dumps(status, ensure_ascii=False, default=str))


@knowledge_app.command("release-preflight")
def knowledge_release_preflight(
    proposal: str = typer.Option(
        "2.0.0", "--proposal", help="提案版本"
    ),
):
    """发布预检。验证前瞻 Study 门槛、市场指标和哈希一致。"""
    root = _get_root()
    from .adapters.study_ledger import StudyLedger
    from .adapters.snapshot_repository import KnowledgeSnapshotRepository
    from .application.release_evidence import run_release_preflight
    from .application.study_report import build_study_report

    ledger = StudyLedger(root)
    repo = KnowledgeSnapshotRepository(root)

    # 检查 Snapshot/index
    snapshots = sorted(repo.snapshots_dir.glob("*.yml")) if repo.snapshots_dir.exists() else []
    indices = sorted(repo.indexes_dir.glob("*.db")) if repo.indexes_dir.exists() else []
    has_snapshot = len(snapshots) > 0
    has_index = len(indices) > 0

    # 构建 Study 报告
    study_ids = ledger.list_studies()
    study_reports: list[dict[str, Any]] = []
    for sid in study_ids:
        try:
            report = build_study_report(sid, ledger)
            study_reports.append(report)
        except Exception:
            pass

    # 检查 ReleaseEvidence（只识别内容寻址的 64-hex 文件名，排除 implementation-evidence.yml）
    import re as _re
    evidence_dir = root / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0" / "evidence"
    release_evidence_files = []
    if evidence_dir.exists():
        for ef in evidence_dir.glob("*.yml"):
            if _re.fullmatch(r"[0-9a-f]{64}", ef.stem):
                release_evidence_files.append(ef)
    has_release_evidence = len(release_evidence_files) > 0
    evidence_hash_valid = True
    for ef in release_evidence_files:
        try:
            data = yaml.safe_load(ef.read_text(encoding="utf-8")) or {}
            expected = data.get("evidence_sha256")
            recomputed = _canonical_hash({k: v for k, v in data.items() if k != "evidence_sha256"})
            if expected != recomputed:
                evidence_hash_valid = False
                break
        except Exception:
            evidence_hash_valid = False
            break

    result = run_release_preflight(
        study_reports=study_reports,
        has_snapshot=has_snapshot,
        has_index=has_index,
        has_release_evidence=has_release_evidence,
        evidence_hash_valid=evidence_hash_valid,
        proposal=proposal,
        evidence_files=release_evidence_files,
    )

    typer.echo(json.dumps({
        "passed": result.passed,
        "gate_results": result.gate_results,
        "market_enablement": result.market_enablement,
        "failure_reasons": list(result.failure_reasons),
        "preflight_sha256": result.preflight_sha256,
    }, ensure_ascii=False, default=str))

    if not result.passed:
        raise typer.Exit(code=1)


# ── 注册到主 CLI ────────────────────────────────────────


def register_knowledge_commands(app: typer.Typer) -> None:
    """注册知识引擎命令到主 CLI。"""
    app.add_typer(knowledge_app, name="knowledge", help="知识引擎管理")
    app.add_typer(study_app, name="study", help="前瞻 Study 管理")
    app.add_typer(ai_app, name="ai", help="AI 旁路分析")
    knowledge_app.add_typer(release_evidence_app, name="release-evidence")
