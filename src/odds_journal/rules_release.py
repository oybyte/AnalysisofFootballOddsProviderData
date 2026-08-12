from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .analysis_context import ANALYSIS_END, ANALYSIS_START, analysis_is_placeholder, parse_receipt
from .extraction import EXTRACTION_RELATIVE, load_text_inventory, validate_extraction_state
from .indexing import build_index
from .ledger import atomic_write_text, read_ledger
from .markdown import MatchDocument, FRONT_MATTER_RE
from .models import MatchStatus
from .paths import match_files
from .proposals import document_contract
from .rules import RuleMetadata, RulesetManifest, load_ruleset, sha256_binary_file, sha256_file


REQUIRED_BODY_HEADINGS = [
    "## 目的和适用范围",
    "## 术语",
    "## 必需输入",
    "## 数据质量要求",
    "## 逐步执行过程",
    "## 判断矩阵",
    "## 双向假设",
    "## 区分触发条件",
    "## 跨市场冲突优先级",
    "## 失效和 Pass 条件",
    "## 支持案例",
    "## 反例",
    "## Source Atom 与声明引用",
    "## 证据快照",
    "## 版本变更说明",
]


def _proposal_dir(root: Path, version: str) -> Path:
    return root / "knowledge/rule-proposals/football-analysis" / version


def _load_front(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER_RE.match(text)
    if not match:
        raise ValueError(f"规则提案缺少 Front Matter：{path}")
    return yaml.safe_load(match.group(1)) or {}, text[match.end() :]


def _report_hash(root: Path) -> str:
    return hashlib.sha256((root / "reports/历史资料提取覆盖报告.json").read_bytes()).hexdigest()


def _evidence_hash(root: Path) -> str:
    return hashlib.sha256((root / "knowledge/evidence/rule-evidence.jsonl").read_bytes()).hexdigest()


def _proposal_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("**/*.md"))


def _proposal_machine_files(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.glob("**/*.y*ml")
        if path.is_file() and path != directory / "manifest.yml"
    )


def _validate_heuristic_promotion(root: Path, metadata: RuleMetadata) -> list[str]:
    if metadata.document_type != "heuristic" or metadata.reliability != "supported":
        return []
    errors: list[str] = []
    snapshot = metadata.evidence_snapshot
    study_id = snapshot.validation_study_id if snapshot else None
    if not study_id:
        return ["supported 经验规则必须引用冻结验证研究"]
    report_path = root / "reports/验证研究报告.json"
    if not report_path.exists():
        return ["supported 经验规则缺少验证研究报告"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    record = (report.get("studies") or {}).get(study_id)
    if not record:
        return [f"验证研究报告不包含：{study_id}"]
    if record.get("rule_id") != metadata.document_id:
        errors.append("验证研究 rule_id 与规则不一致")
    if record.get("promotion_candidate") is not True:
        errors.append("验证研究尚未通过全部晋级门禁")
    if metadata.promotion_reviewed_by != "lcz":
        errors.append("经验规则晋级必须由 lcz 完成人工审核")
    if snapshot:
        expected = {
            "eligible_independent_cases": record.get("eligible_independent_cases"),
            "baseline_rate": record.get("baseline_rate"),
            "point_estimate": record.get("point_estimate"),
            "wilson_95_lower": record.get("wilson_95_lower"),
        }
        actual = snapshot.model_dump(mode="json")
        mismatches = [key for key, value in expected.items() if actual.get(key) != value]
        if mismatches:
            errors.append("经验规则证据快照与验证报告不一致：" + ", ".join(mismatches))
    return errors


def validate_ruleset_proposal(root: Path, version: str) -> dict[Path, list[str]]:
    directory = _proposal_dir(root, version)
    manifest_path = directory / "manifest.yml"
    results: dict[Path, list[str]] = {manifest_path: []}
    if not manifest_path.exists():
        return {manifest_path: ["规则提案 manifest 不存在"]}
    try:
        extraction_errors = validate_extraction_state(root)
        if extraction_errors:
            results[manifest_path].extend(extraction_errors)
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        required_ids, conditional_ids = document_contract(version)
        expected_schema = 10 if version == "2.0.0" else 9 if version == "1.9.0" else 8 if version == "1.8.0" else 7 if version == "1.7.0" else 6 if version == "1.6.0" else 5 if version == "1.5.0" else 4 if version in {"1.2.0", "1.3.0", "1.4.0"} else 3
        if manifest.get("schema_version") != expected_schema:
            results[manifest_path].append(f"{version} 提案必须使用 manifest schema {expected_schema}")
        if manifest.get("ruleset_id") != "football-analysis" or manifest.get("ruleset_version") != version:
            results[manifest_path].append("提案路径与规则集身份不一致")
        if manifest.get("publication_status") != "proposal" or manifest.get("effective_at") is not None:
            results[manifest_path].append("提案阶段 publication_status 必须为 proposal 且 effective_at 必须为空")
        if manifest.get("required_document_ids") != required_ids:
            results[manifest_path].append(f"必需规则列表与 {version} 契约不一致")
        if manifest.get("conditional_document_ids") != conditional_ids:
            results[manifest_path].append(f"条件规则列表与 {version} 契约不一致")
        if expected_schema in {4, 5, 6, 7, 8, 9, 10}:
            config_relative = manifest.get("calibration_config_path")
            config_path = directory / str(config_relative or "")
            if not config_relative or not config_path.is_file():
                results[manifest_path].append("schema 4 提案缺少校准配置")
            else:
                if manifest.get("calibration_config_sha256") != sha256_file(config_path):
                    results[manifest_path].append("提案校准配置哈希不一致")
                try:
                    if version in {"1.6.0", "1.7.0"}:
                        from .experiments import ExperimentCalibrationConfig, ExperimentCalibrationConfigV6

                        model = ExperimentCalibrationConfigV6 if version == "1.7.0" else ExperimentCalibrationConfig
                        model.model_validate(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
                    else:
                        from .calibration import load_calibration_config

                        load_calibration_config(config_path)
                except Exception as exc:
                    results[manifest_path].append(str(exc))
            expected_calibration_contract = 9 if version == "2.0.0" else 8 if version == "1.9.0" else 7 if version == "1.8.0" else 6 if version == "1.7.0" else 5 if version == "1.6.0" else 4 if version == "1.5.0" else 3 if version == "1.4.0" else 2 if version == "1.3.0" else 1
            if manifest.get("calibration_contract_version") != expected_calibration_contract:
                results[manifest_path].append(
                    f"提案必须声明 calibration contract {expected_calibration_contract}"
                )
            expected_receipt = 9 if version == "2.0.0" else 8 if version == "1.9.0" else 7 if version == "1.8.0" else 6 if version in {"1.5.0", "1.6.0", "1.7.0"} else 5 if version == "1.4.0" else 4
            if manifest.get("analysis_receipt_schema_version") != expected_receipt:
                results[manifest_path].append(f"提案必须声明 AnalysisReceipt schema {expected_receipt}")
        if version in {"1.9.0", "2.0.0"}:
            evidence_relative = manifest.get("implementation_evidence_path")
            evidence_path = directory / str(evidence_relative or "")
            if not evidence_relative or not evidence_path.is_file():
                results[manifest_path].append(f"{version} 提案缺少编译器实现与回归证据")
            else:
                if manifest.get("implementation_evidence_sha256") != sha256_file(evidence_path):
                    results[manifest_path].append("1.9.0 实现证据清单哈希不一致")
                try:
                    evidence = yaml.safe_load(evidence_path.read_text(encoding="utf-8")) or {}
                    if evidence.get("schema_version") != 1 or evidence.get("proposal_version") != version:
                        raise ValueError("实现证据身份或 schema 无效")
                    artifacts = evidence.get("artifacts")
                    if not isinstance(artifacts, list):
                        raise ValueError("实现证据 artifacts 必须为列表")
                    paths = {item.get("path") for item in artifacts if isinstance(item, dict)}
                    required_paths = {
                        "src/odds_journal/formal_draft.py",
                        "src/odds_journal/backtest.py",
                        "src/odds_journal/analytics.py",
                        "src/odds_journal/cli.py",
                        "src/odds_journal/observations.py",
                        "src/odds_journal/case_retrieval.py",
                        "src/odds_journal/lock_lifecycle.py",
                        "src/odds_journal/settlement.py",
                        "src/odds_journal/agent_workflow.py",
                        "schemas/formal-analysis-gate.schema.json",
                        "schemas/market-assessment.schema.json",
                        "schemas/prematch-fact-bundle.schema.json",
                        "schemas/analysis-draft-input.schema.json",
                        "schemas/rule-evaluation-bundle.schema.json",
                        "schemas/analysis-outlook.schema.json",
                        "tests/test_formal_draft.py",
                        "raw/backtests/formal-draft-1-9-0-regression/dataset-manifest.yml",
                        "raw/backtests/formal-draft-1-9-0-regression/prediction-manifest.yml",
                        "raw/backtests/formal-draft-1-9-0-regression/label-manifest.yml",
                        "raw/backtests/formal-draft-1-9-0-regression/outcome-manifest.yml",
                        "reports/backtest/formal-draft-1-9-0-regression/replay-report.json",
                    }
                    if version == "2.0.0":
                        required_paths = {
                            "src/odds_journal/knowledge_engine/application/migrate_knowledge.py",
                            "src/odds_journal/knowledge_engine/application/build_snapshot.py",
                            "src/odds_journal/knowledge_engine/application/run_study.py",
                            "src/odds_journal/knowledge_engine/application/analytics.py",
                            "src/odds_journal/knowledge_engine/adapters/rule_spec_reader.py",
                            "src/odds_journal/knowledge_engine/adapters/repository_artifacts.py",
                            "src/odds_journal/knowledge_engine/adapters/snapshot_repository.py",
                            "src/odds_journal/knowledge_engine/adapters/deterministic_reasoner.py",
                            "src/odds_journal/knowledge_engine/adapters/sqlite_index.py",
                            "src/odds_journal/knowledge_engine/cli.py",
                            "src/odds_journal/knowledge_engine/domain/snapshot.py",
                            "src/odds_journal/knowledge_engine/domain/studies.py",
                            "schemas/ruleset.schema.json",
                            "schemas/analysis-receipt.schema.json",
                            "tests/knowledge_engine/test_functional.py",
                        }
                    if not required_paths.issubset(paths):
                        raise ValueError("实现证据未覆盖编译器、回放、Analytics、Schema 和测试")
                    for item in artifacts:
                        relative = Path(str(item.get("path") or ""))
                        if relative.is_absolute() or ".." in relative.parts:
                            raise ValueError("实现证据包含越界路径")
                        artifact = root / relative
                        if not artifact.is_file() or item.get("sha256") != sha256_file(artifact):
                            raise ValueError(f"实现证据文件缺失或哈希过期：{relative.as_posix()}")
                except Exception as exc:
                    results[manifest_path].append(f"{version} 实现证据无效：{exc}")
        if version == "2.0.0":
            try:
                from .knowledge_engine.adapters.ruleset_source import RulesetSourceAdapter
                from .knowledge_engine.adapters.snapshot_repository import KnowledgeSnapshotRepository
                from .knowledge_engine.application.migrate_knowledge import auto_disposition, build_source_inventory, validate_coverage
                from .knowledge_engine.domain.snapshot import KnowledgeIndexManifestV1
                from .rules import load_ruleset

                baseline = load_ruleset(root, "football-analysis@1.8.0")
                if manifest.get("base_ruleset_version") != "1.8.0" or manifest.get("base_ruleset_sha256") != baseline.content_sha256:
                    raise ValueError("2.0.0 必须绑定当前可验证的 1.8.0 已发布基线")
                inventory = auto_disposition(build_source_inventory(RulesetSourceAdapter(root), root))
                covered, counts = validate_coverage(inventory)
                if not covered:
                    raise ValueError(f"活动实验快照来源处置不完整：{counts}")
                repository = KnowledgeSnapshotRepository(root)
                snapshots = sorted(repository.snapshots_dir.glob("*.yml"))
                if not snapshots:
                    raise ValueError("2.0.0 尚无已封存知识 Snapshot；先执行 knowledge snapshot --seal")
                valid_pairs = 0
                for snapshot_path in snapshots:
                    snapshot = repository.load(snapshot_path.stem)
                    repository.load_cards(snapshot)
                    index_path = repository.indexes_dir / f"{snapshot.snapshot_sha256}.db"
                    index_manifest_path = repository.index_manifest_path(snapshot.snapshot_sha256)
                    if not index_path.is_file() or not index_manifest_path.is_file():
                        continue
                    index_manifest = KnowledgeIndexManifestV1.model_validate(yaml.safe_load(index_manifest_path.read_text(encoding="utf-8")) or {})
                    if index_manifest.snapshot_sha256 != snapshot.snapshot_sha256 or sha256_binary_file(index_path) != index_manifest.sqlite_file_sha256:
                        continue
                    valid_pairs += 1
                if not valid_pairs:
                    raise ValueError("2.0.0 尚无与知识 Snapshot 匹配的有效索引")
            except Exception as exc:
                results[manifest_path].append(f"2.0.0 知识迁移资产无效：{exc}")
        if manifest.get("source_coverage_sha256") != _report_hash(root):
            results[manifest_path].append("提案绑定的覆盖报告已过期")
        if manifest.get("evidence_snapshot_sha256") != _evidence_hash(root):
            results[manifest_path].append("提案绑定的证据台账已过期")
        if version == "1.7.0":
            from .rule_intakes import (
                ATOM_LEDGER, RULE_BUILD_NAME, RULE_CONSOLIDATIONS_NAME, RuleAtomV1,
                RuleBuildManifestV1, RuleConsolidationManifestV1, RuleSpecV1,
            )

            build_path = directory / RULE_BUILD_NAME
            try:
                build = RuleBuildManifestV1.model_validate(yaml.safe_load(build_path.read_text(encoding="utf-8")) or {})
                expected_build = dict(build.model_dump(mode="json"))
                expected_build["build_sha256"] = "0" * 64
                if build.compiler_version == "rule-intake-compiler-v1":
                    expected_build.pop("consolidation_manifest_sha256", None)
                    expected_build.pop("consolidation_resolutions", None)
                if build.build_sha256 != hashlib.sha256(json.dumps(expected_build, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest():
                    results[manifest_path].append("规则编译清单内容哈希不一致")
                atoms = {event.payload.get("atom_id"): event.payload for event in read_ledger(root / ATOM_LEDGER)}
                for selected in build.selected_atoms:
                    atom = atoms.get(selected.atom_id)
                    if not atom or atom.get("atom_sha256") != selected.atom_sha256:
                        results[manifest_path].append(f"规则编译清单引用的 atom 无效：{selected.atom_id}")
                contract = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                specs_root = directory / str(contract.get("rule_specs_path") or "")
                for item in build.generated_rule_specs:
                    spec_path = specs_root / f"{item.get('rule_id')}.yml"
                    if not spec_path.is_file() or sha256_file(spec_path) != item.get("rule_spec_sha256"):
                        results[manifest_path].append(f"RuleSpec 不存在或哈希不一致：{item.get('rule_id')}")
                        continue
                    spec = RuleSpecV1.model_validate(yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {})
                    missing = set(spec.source_atoms) - {entry.atom_id for entry in build.selected_atoms}
                    if missing:
                        results[manifest_path].append(f"RuleSpec 未绑定编译 atom：{spec.rule_id}")
                consolidation_path = directory / RULE_CONSOLIDATIONS_NAME
                if build.consolidation_manifest_sha256:
                    if not consolidation_path.is_file():
                        results[manifest_path].append("规则编译清单引用的合并清单不存在")
                    else:
                        consolidation = RuleConsolidationManifestV1.model_validate(
                            yaml.safe_load(consolidation_path.read_text(encoding="utf-8")) or {}
                        )
                        if consolidation.manifest_sha256 != build.consolidation_manifest_sha256:
                            results[manifest_path].append("规则合并清单哈希不一致")
                        selected_ids = {entry.atom_id for entry in build.selected_atoms}
                        generated_ids = {str(item.get("rule_id")) for item in build.generated_rule_specs}
                        for item in consolidation.consolidations:
                            if not set(item.source_atoms).issubset(selected_ids):
                                results[manifest_path].append(f"合并 RuleSpec 未绑定编译 atom：{item.rule_id}")
                            if item.rule_id not in generated_ids:
                                results[manifest_path].append(f"合并 RuleSpec 未进入编译清单：{item.rule_id}")
                            leaked = set(item.superseded_rule_ids) & generated_ids
                            if leaked:
                                results[manifest_path].append("已退役 RuleSpec 仍进入编译清单：" + ", ".join(sorted(leaked)))
                elif consolidation_path.is_file():
                    results[manifest_path].append("规则合并清单未绑定至 rule-build.yml")
            except Exception as exc:
                results[manifest_path].append(f"Contract 6 规则编译清单无效：{exc}")
        known_atoms: set[str] = set()
        known_claims: set[str] = set()
        extraction_root = root / "knowledge" / "extraction"
        for inventory in extraction_root.glob("*/text-inventory.jsonl"):
            for line in inventory.read_text(encoding="utf-8").splitlines():
                if line:
                    try:
                        atom_id = json.loads(line).get("atom_id")
                        if atom_id:
                            known_atoms.add(str(atom_id))
                    except Exception:
                        continue
        for ledger in extraction_root.glob("*/claim-events.jsonl"):
            for event in read_ledger(ledger):
                if event.payload.get("claim_id"):
                    known_claims.add(str(event.payload["claim_id"]))
        documents: dict[str, Path] = {}
        if version == "2.0.0":
            # Schema 10 explicitly reuses a verified published baseline.  Its
            # proposal directory intentionally contains no duplicate Markdown.
            documents = {item: directory / "manifest.yml" for item in [*required_ids, *conditional_ids]}
        for path in ([] if version == "2.0.0" else _proposal_files(directory)):
            errors: list[str] = []
            try:
                raw, body = _load_front(path)
                if raw.get("effective_at") is not None:
                    errors.append("提案规则 effective_at 必须为空")
                candidate = dict(raw)
                candidate["effective_at"] = "2099-01-01T00:00:00+08:00"
                metadata = RuleMetadata.model_validate(candidate)
                if metadata.rule_version != version:
                    errors.append("rule_version 与提案版本不一致")
                if metadata.document_id in documents:
                    errors.append(f"document_id 与 {documents[metadata.document_id]} 重复")
                documents[metadata.document_id] = path
                missing_atoms = sorted(set(metadata.source_atom_ids) - known_atoms)
                if missing_atoms:
                    errors.append(f"引用不存在的 source atom：{missing_atoms[:3]}")
                expected_claims = {f"claim-{atom}" for atom in metadata.source_atom_ids}
                missing_claims = sorted(expected_claims - known_claims)
                if missing_claims:
                    errors.append(f"引用不存在的 claim：{missing_claims[:3]}")
                unlisted_claims = sorted(identity for identity in expected_claims if identity not in body)
                if unlisted_claims:
                    errors.append(f"正文缺少 source atom 对应 claim 引用：{unlisted_claims[:3]}")
                if metadata.evidence_snapshot and metadata.evidence_snapshot.ledger_sha256 != _evidence_hash(root):
                    errors.append("证据快照台账哈希已过期")
                missing_headings = [heading for heading in REQUIRED_BODY_HEADINGS if heading not in body]
                if missing_headings:
                    errors.append("缺少详细规则章节：" + ", ".join(missing_headings))
                errors.extend(_validate_heuristic_promotion(root, metadata))
                if metadata.document_id == "market-settlement-rules":
                    official_hosts = {
                        urlparse(item.locator).hostname
                        for item in metadata.source_refs
                        if item.kind == "external"
                        and urlparse(item.locator).hostname
                        in {"help.bet365.com", "support.betfair.com"}
                    }
                    if official_hosts != {"help.bet365.com", "support.betfair.com"}:
                        errors.append("结算规则缺少两个独立官方运营方来源")
            except Exception as exc:
                errors.append(str(exc))
            results[path] = errors
        expected = set(required_ids) | set(conditional_ids)
        if set(documents) != expected:
            results[manifest_path].append(
                f"提案文档集合不一致；缺少={sorted(expected-set(documents))} 多出={sorted(set(documents)-expected)}"
            )
    except Exception as exc:
        results[manifest_path].append(str(exc))
    return results


def _proposal_sha256(directory: Path) -> str:
    rows = []
    for path in sorted(
        [directory / "manifest.yml", *_proposal_files(directory), *_proposal_machine_files(directory)]
    ):
        rows.append(f"{path.relative_to(directory).as_posix()}|{sha256_file(path)}")
    return hashlib.sha256(("\n".join(rows) + "\n").encode("utf-8")).hexdigest()


def _rewrite_front(path: Path, update: dict[str, Any]) -> None:
    raw, body = _load_front(path)
    raw.update(update)
    header = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=1000).rstrip()
    atomic_write_text(path, f"---\n{header}\n---\n{body}")


def _resume_existing_release(
    root: Path,
    target: Path,
    proposal: Path,
    *,
    approved_by: str,
) -> datetime:
    approval_path = target / "APPROVAL.yml"
    if not approval_path.exists():
        raise ValueError(f"正式版本目录已存在但缺少 APPROVAL.yml：{target}")
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8")) or {}
    expected = {
        "ruleset_id": "football-analysis",
        "ruleset_version": target.name,
        "approved_by": approved_by.strip(),
        "proposal_sha256": _proposal_sha256(proposal),
        "source_coverage_sha256": _report_hash(root),
        "evidence_snapshot_sha256": _evidence_hash(root),
    }
    manifest = yaml.safe_load((proposal / "manifest.yml").read_text(encoding="utf-8")) or {}
    if manifest.get("schema_version") in {4, 5, 6, 7}:
        expected["calibration_config_sha256"] = manifest.get("calibration_config_sha256")
    mismatches = [key for key, value in expected.items() if approval.get(key) != value]
    if mismatches:
        raise ValueError("已生成的未激活版本与当前提案或批准信息不一致：" + ", ".join(mismatches))
    approved_at = datetime.fromisoformat(str(approval.get("approved_at")))
    if approved_at.tzinfo is None or approved_at.utcoffset() is None:
        raise ValueError("APPROVAL.yml 的 approved_at 必须包含时区")
    load_ruleset(root, f"football-analysis@{target.name}")
    return approved_at


def _preflight_matches(root: Path) -> list[Path]:
    migratable: list[Path] = []
    blockers: list[str] = []
    for path in match_files(root):
        document = MatchDocument.load(path)
        if MatchStatus(document.metadata.status) not in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
            continue
        reasoning = document.sections["prematch-reasoning"]
        receipt = parse_receipt(reasoning)
        try:
            placeholder = analysis_is_placeholder(reasoning)
        except Exception:
            placeholder = False
        if receipt and receipt.schema_version == 1 and not placeholder:
            blockers.append(f"{path}: 未锁定且已有实质 v1 分析")
        elif not placeholder:
            blockers.append(f"{path}: 未锁定且分析正文无法安全迁移")
        else:
            migratable.append(path)
    if blockers:
        raise ValueError("；".join(blockers))
    return migratable


def _migrate_placeholder_match(path: Path) -> None:
    document = MatchDocument.load(path)
    reasoning = (
        "## 二、赛前推演\n\n"
        f"{ANALYSIS_START}\n"
        "<!-- TODO:replace-before-lock -->\n\n"
        "在完成规则、场景和案例检索后填写缺失信息、理论盘口、双向假设、证据、反证和规则引用。\n"
        f"{ANALYSIS_END}\n"
    )
    document.replace_section("prematch-reasoning", reasoning)
    review = document.sections["postmatch-review"]
    if "<!-- review-content:start -->" not in review:
        review = (
            "## 六、赛后复盘\n\n"
            "<!-- review-content:start -->\n"
            "<!-- TODO:replace-before-review -->\n\n"
            "在此记录正确判断、错误判断、遗漏信号、错误分类、规则反例和可复用教训。\n"
            "<!-- review-content:end -->\n"
        )
        document.replace_section("postmatch-review", review)
    document.save()


def release_ruleset(
    root: Path,
    version: str,
    *,
    approved_by: str,
    effective_at: datetime,
) -> Path:
    if not approved_by.strip():
        raise ValueError("发布必须记录人工批准人")
    if effective_at.tzinfo is None or effective_at.utcoffset() is None:
        raise ValueError("发布时间必须包含时区")
    results = validate_ruleset_proposal(root, version)
    errors = [f"{path}: {error}" for path, values in results.items() for error in values]
    if errors:
        raise ValueError("；".join(errors))
    # Knowledge Engine release-preflight (for 2.0.0)
    if version == "2.0.0":
        from .knowledge_engine.application.release_evidence import run_release_preflight
        from .knowledge_engine.adapters.study_ledger import StudyLedger
        from .knowledge_engine.application.study_report import build_study_report
        ledger = StudyLedger(root)
        study_ids = ledger.list_studies()
        study_reports = []
        for sid in study_ids:
            try:
                study_reports.append(build_study_report(sid, ledger))
            except Exception:
                pass
        snapshot_dir = root / "raw" / "knowledge-engine" / "snapshots"
        index_dir = root / "raw" / "knowledge-engine" / "index"
        evidence_dir = root / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0" / "evidence"
        evidence_files = list(evidence_dir.glob("*.yml")) if evidence_dir.exists() else []
        preflight = run_release_preflight(
            study_reports=study_reports,
            has_snapshot=snapshot_dir.exists() and bool(list(snapshot_dir.glob("*.yml"))),
            has_index=index_dir.exists() and bool(list(index_dir.glob("*.db"))),
            has_release_evidence=bool(evidence_files),
            evidence_hash_valid=True,
            proposal=version,
            evidence_files=evidence_files,
        )
        if not preflight.passed:
            raise ValueError(f"知识引擎发布预检失败：{'; '.join(preflight.failure_reasons)}")
    migratable = _preflight_matches(root)
    proposal = _proposal_dir(root, version)
    target = root / "knowledge/rulesets/football-analysis" / version
    proposal_hash = _proposal_sha256(proposal)
    evidence_hash = _evidence_hash(root)
    report_hash = _report_hash(root)
    if target.exists():
        effective_at = _resume_existing_release(
            root, target, proposal, approved_by=approved_by
        )
    else:
        temporary = target.parent / f".{version}.release-{uuid.uuid4().hex}"
        shutil.copytree(proposal, temporary)
        try:
            manifest_path = temporary / "manifest.yml"
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            manifest.pop("proposal_prepared_at", None)
            manifest.update(
                {
                    "publication_status": "published",
                    "effective_at": effective_at.isoformat(),
                    "source_coverage_sha256": report_hash,
                    "evidence_snapshot_sha256": evidence_hash,
                }
            )
            RulesetManifest.model_validate(manifest)
            atomic_write_text(manifest_path, yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
            for path in _proposal_files(temporary):
                current_raw, _ = _load_front(path)
                current_metadata = RuleMetadata.model_validate(
                    {**current_raw, "effective_at": effective_at.isoformat()}
                )
                evidence_snapshot = current_raw.get("evidence_snapshot")
                if not (
                    current_metadata.document_type == "heuristic"
                    and current_metadata.reliability == "supported"
                ):
                    evidence_snapshot = {
                        "as_of": effective_at.isoformat(),
                        "eligible_independent_cases": 0,
                        "support": 0,
                        "counterexample": 0,
                        "ambiguous": 0,
                        "ledger_sha256": evidence_hash,
                    }
                _rewrite_front(
                    path,
                    {
                        "effective_at": effective_at.isoformat(),
                        "evidence_snapshot": evidence_snapshot,
                    },
                )
                raw, _ = _load_front(path)
                RuleMetadata.model_validate(raw)
            approval = {
                "schema_version": 1,
                "ruleset_id": "football-analysis",
                "ruleset_version": version,
                "approved_by": approved_by.strip(),
                "approved_at": effective_at.isoformat(),
                "proposal_sha256": proposal_hash,
                "source_coverage_sha256": report_hash,
                "evidence_snapshot_sha256": evidence_hash,
            }
            if manifest.get("schema_version") in {4, 5}:
                approval["calibration_config_sha256"] = manifest.get(
                    "calibration_config_sha256"
                )
            atomic_write_text(
                temporary / "APPROVAL.yml",
                yaml.safe_dump(approval, allow_unicode=True, sort_keys=False),
            )
            temporary.replace(target)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary)
            raise

    backups = {path: path.read_bytes() for path in migratable}
    active_path = root / "knowledge/rulesets/football-analysis/active.yml"
    active_backup = active_path.read_bytes()
    try:
        load_ruleset(root, f"football-analysis@{version}")
        for path in migratable:
            _migrate_placeholder_match(path)
        build_index(root)
        active = {
            "schema_version": 1,
            "ruleset_id": "football-analysis",
            "ruleset_version": version,
        }
        atomic_write_text(active_path, yaml.safe_dump(active, allow_unicode=True, sort_keys=False))
        load_ruleset(root)
    except Exception:
        for path, content in backups.items():
            rollback = path.with_suffix(path.suffix + ".rollback")
            rollback.write_bytes(content)
            rollback.replace(path)
        rollback = active_path.with_suffix(".yml.rollback")
        rollback.write_bytes(active_backup)
        rollback.replace(active_path)
        raise
    return target
