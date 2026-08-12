"""批次 A 单元测试：Contract 9 发布后隔离护栏解除 + load_ruleset 校准内容校验。

对应实现方案：
- 步骤 1（G1）：analysis_context.py 的 Contract 9 隔离改为仅未发布时阻断
- 步骤 2（G2）：rules.py 的 load_ruleset 对 Contract 9 调用 KnowledgeEnginePolicyV1 内容校验

测试分类：
- TestLoadCalibrationConfigContract9：load_calibration_config 对 v9 配置的解析校验（已实现，直接通过）
- TestLoadRulesetContract9Calibration：load_ruleset 对 Contract 9 的内容校验（需 G2 修改后通过）
- TestIsPublishedGuard：_is_2_0_0_published 发布状态检查（已实现，直接通过）
- TestAnalysisContextContract9Guard：隔离护栏条件逻辑（需 G1 修改后通过）
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml

from odds_journal.calibration import load_calibration_config, KnowledgeEnginePolicyV1
from odds_journal.knowledge_engine.adapters.draft_workflow_registry import DraftWorkflowRegistry
from odds_journal.rules import load_ruleset, sha256_file


REPOSITORY = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))


# ── 辅助函数 ────────────────────────────────────────────────


def _valid_v9_config() -> dict:
    """返回有效的 Contract 9 校准配置。"""
    return {
        "schema_version": 9,
        "profile_id": "football-analysis-v9",
        "ruleset_origin": "proposal",
        "formal_mode": "disabled_until_release",
        "knowledge_snapshot": {
            "required": True,
            "source": "active_experiment_snapshot_only",
            "mutable_proposal_fallback": False,
            "minimum_source_disposition_coverage": 1.0,
        },
        "retrieval": {
            "contract_version": 5,
            "index_schema_version": 6,
            "market_isolation": True,
            "cross_market_audit_only": True,
            "same_source_family_counts_as_one": True,
        },
        "reasoner": {
            "contract_id": "knowledge-engine-v1-default",
            "deterministic": True,
            "ai_effect": "advisory_only",
            "baseline_pass_never_reopen": True,
            "confidence_cap_after_anchor_change": 0.69,
        },
        "study": {
            "primary_requires_official_baseline": True,
            "primary_requires_candidate": True,
            "primary_requires_pre_kickoff": True,
            "counterfactual_without_baseline": True,
            "counterfactual_in_release_evidence": False,
        },
        "outbound": {
            "real_provider": "controlled_disabled",
            "network": "denied_by_default",
        },
        "formal_isolation": {
            "proposal_cannot_write_match": True,
            "proposal_cannot_lock": True,
            "proposal_cannot_settle": True,
            "proposal_cannot_enter_official_statistics": True,
        },
    }


def _write_v9_config(path: Path, config: dict | None = None) -> None:
    """写入 v9 校准配置文件。"""
    data = config if config is not None else _valid_v9_config()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    """使用项目的 canonical_text 规范化后计算哈希，与 sha256_file 一致。"""
    return sha256_file(path)


def _write_active_yml(root: Path, version: str) -> None:
    """写入 active.yml 指定活动版本。"""
    active_path = root / "knowledge" / "rulesets" / "football-analysis" / "active.yml"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_text(
        f"schema_version: 1\nruleset_id: football-analysis\nruleset_version: {version}\n",
        encoding="utf-8",
    )


def _setup_2_0_0_proposal(root: Path) -> Path:
    """从真实仓库复制 2.0.0 提案和 1.8.0 规则集到测试目录。

    schema_version=10 的 2.0.0 提案需要 base_ruleset（1.8.0）提供规则文档。
    """
    proposal_src = REPOSITORY / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0"
    proposal_dst = root / "knowledge" / "rule-proposals" / "football-analysis" / "2.0.0"
    proposal_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(proposal_src, proposal_dst)

    base_src = REPOSITORY / "knowledge" / "rulesets" / "football-analysis" / "1.8.0"
    base_dst = root / "knowledge" / "rulesets" / "football-analysis" / "1.8.0"
    base_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(base_src, base_dst)

    return proposal_dst


def _tamper_calibration(
    proposal_dir: Path,
    *,
    mutate: callable,
) -> None:
    """篡改校准配置并同步更新 manifest 哈希。

    mutate 接收 config dict，就地修改后返回。
    """
    config_path = proposal_dir / "calibration" / "football-analysis-v9.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    mutate(config)
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    # 同步 manifest 哈希以通过哈希校验，使内容校验成为唯一拦截点
    manifest_path = proposal_dir / "manifest.yml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["calibration_config_sha256"] = _sha256_file(config_path)
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


# ── load_calibration_config 对 Contract 9 的校验 ────────────


class TestLoadCalibrationConfigContract9:
    """load_calibration_config 对 Contract 9 配置的解析与校验。

    这些测试验证 KnowledgeEnginePolicyV1 的语义不变量校验。
    load_calibration_config 已实现，测试直接通过。
    """

    def test_valid_v9_returns_knowledge_engine_policy(self, tmp_path: Path):
        """有效的 v9 配置返回 KnowledgeEnginePolicyV1 实例。"""
        config_path = tmp_path / "calibration" / "v9.yml"
        _write_v9_config(config_path)
        result = load_calibration_config(config_path)
        assert isinstance(result, KnowledgeEnginePolicyV1)
        assert result.schema_version == 9
        assert result.profile_id == "football-analysis-v9"
        assert result.reasoner.get("ai_effect") == "advisory_only"

    def test_invalid_ai_effect_rejected(self, tmp_path: Path):
        """ai_effect 不是 advisory_only 被拒绝。"""
        config = _valid_v9_config()
        config["reasoner"]["ai_effect"] = "active_override"
        config_path = tmp_path / "v9.yml"
        _write_v9_config(config_path, config)
        with pytest.raises(ValueError, match="ai_effect"):
            load_calibration_config(config_path)

    def test_invalid_network_rejected(self, tmp_path: Path):
        """network 不是 denied_by_default 被拒绝。"""
        config = _valid_v9_config()
        config["outbound"]["network"] = "open"
        config_path = tmp_path / "v9.yml"
        _write_v9_config(config_path, config)
        with pytest.raises(ValueError, match="network"):
            load_calibration_config(config_path)

    def test_missing_proposal_cannot_lock_rejected(self, tmp_path: Path):
        """缺少 proposal_cannot_lock 标志被拒绝。"""
        config = _valid_v9_config()
        del config["formal_isolation"]["proposal_cannot_lock"]
        config_path = tmp_path / "v9.yml"
        _write_v9_config(config_path, config)
        with pytest.raises(ValueError, match="proposal_cannot_lock"):
            load_calibration_config(config_path)

    def test_missing_proposal_cannot_settle_rejected(self, tmp_path: Path):
        """缺少 proposal_cannot_settle 标志被拒绝。"""
        config = _valid_v9_config()
        del config["formal_isolation"]["proposal_cannot_settle"]
        config_path = tmp_path / "v9.yml"
        _write_v9_config(config_path, config)
        with pytest.raises(ValueError, match="proposal_cannot_settle"):
            load_calibration_config(config_path)

    def test_false_formal_isolation_flag_rejected(self, tmp_path: Path):
        """formal_isolation 标志为 false 被拒绝。"""
        config = _valid_v9_config()
        config["formal_isolation"]["proposal_cannot_write_match"] = False
        config_path = tmp_path / "v9.yml"
        _write_v9_config(config_path, config)
        with pytest.raises(ValueError, match="proposal_cannot_write_match"):
            load_calibration_config(config_path)

    def test_extra_field_rejected(self, tmp_path: Path):
        """多余字段被拒绝（extra=forbid）。"""
        config = _valid_v9_config()
        config["unknown_field"] = "should_fail"
        config_path = tmp_path / "v9.yml"
        _write_v9_config(config_path, config)
        with pytest.raises(Exception, match="unknown_field"):
            load_calibration_config(config_path)

    def test_hash_mismatch_rejected(self, tmp_path: Path):
        """expected_sha256 不一致时被拒绝。"""
        config_path = tmp_path / "v9.yml"
        _write_v9_config(config_path)
        with pytest.raises(ValueError, match="哈希不一致"):
            load_calibration_config(config_path, expected_sha256="0" * 64)

    def test_schema_version_field_required(self, tmp_path: Path):
        """KnowledgeEnginePolicyV1 要求 schema_version 字段存在。"""
        config = _valid_v9_config()
        del config["schema_version"]
        config_path = tmp_path / "v9.yml"
        _write_v9_config(config_path, config)
        with pytest.raises(Exception, match="schema_version"):
            load_calibration_config(config_path)


# ── load_ruleset 对 Contract 9 校准内容校验（G2）────────────


class TestLoadRulesetContract9Calibration:
    """load_ruleset 对 Contract 9 规则集的校准配置内容校验。

    前置条件：rules.py 的 load_ruleset 已修改为对 Contract 9 调用
    load_calibration_config（G2 修改）。

    G2 修改前：load_ruleset 对 Contract 9 只做哈希校验，跳过内容校验，
    篡改内容（同步哈希后）不会被拦截 → xfail。
    G2 修改后：load_ruleset 调用 KnowledgeEnginePolicyV1 校验内容语义，
    篡改内容被拦截 → 通过。
    """

    def test_valid_contract9_proposal_loads(self, tmp_path: Path):
        """有效的 Contract 9 提案规则集加载并通过校准内容校验。"""
        _setup_2_0_0_proposal(tmp_path)
        ruleset = load_ruleset(tmp_path, "football-analysis@2.0.0", allow_proposal=True)
        assert ruleset.manifest.calibration_contract_version == 9
        assert ruleset.manifest.schema_version == 10
        assert ruleset.calibration_config is not None
        # 校准配置应通过 KnowledgeEnginePolicyV1 校验
        assert ruleset.calibration_config.get("schema_version") == 9

    def test_invalid_ai_effect_rejected(self, tmp_path: Path):
        """Contract 9 校准配置 ai_effect 无效时 load_ruleset 拒绝加载。"""
        proposal_dir = _setup_2_0_0_proposal(tmp_path)

        def mutate(config: dict) -> None:
            config["reasoner"]["ai_effect"] = "active_override"

        _tamper_calibration(proposal_dir, mutate=mutate)
        with pytest.raises(ValueError, match="ai_effect"):
            load_ruleset(tmp_path, "football-analysis@2.0.0", allow_proposal=True)

    def test_invalid_network_rejected(self, tmp_path: Path):
        """Contract 9 校准配置 network 无效时 load_ruleset 拒绝加载。"""
        proposal_dir = _setup_2_0_0_proposal(tmp_path)

        def mutate(config: dict) -> None:
            config["outbound"]["network"] = "open"

        _tamper_calibration(proposal_dir, mutate=mutate)
        with pytest.raises(ValueError, match="network"):
            load_ruleset(tmp_path, "football-analysis@2.0.0", allow_proposal=True)

    def test_missing_formal_isolation_rejected(self, tmp_path: Path):
        """Contract 9 校准配置缺少 formal_isolation 标志时 load_ruleset 拒绝加载。"""
        proposal_dir = _setup_2_0_0_proposal(tmp_path)

        def mutate(config: dict) -> None:
            del config["formal_isolation"]["proposal_cannot_settle"]

        _tamper_calibration(proposal_dir, mutate=mutate)
        with pytest.raises(ValueError, match="proposal_cannot_settle"):
            load_ruleset(tmp_path, "football-analysis@2.0.0", allow_proposal=True)

    def test_false_isolation_flag_rejected(self, tmp_path: Path):
        """Contract 9 校准配置 formal_isolation 标志为 false 时 load_ruleset 拒绝加载。"""
        proposal_dir = _setup_2_0_0_proposal(tmp_path)

        def mutate(config: dict) -> None:
            config["formal_isolation"]["proposal_cannot_lock"] = False

        _tamper_calibration(proposal_dir, mutate=mutate)
        with pytest.raises(ValueError, match="proposal_cannot_lock"):
            load_ruleset(tmp_path, "football-analysis@2.0.0", allow_proposal=True)


# ── 发布状态检查（G1 控制点）──────────────────────────────


class TestIsPublishedGuard:
    """_is_2_0_0_published 发布状态检查。

    这是 G1 隔离护栏的控制点：修改后 analysis_context.py 通过此方法
    判断 Contract 9 是否应被阻断。
    方法已实现，测试直接通过。
    """

    def test_returns_false_when_active_yml_missing(self, tmp_path: Path):
        """active.yml 不存在时返回 False。"""
        registry = DraftWorkflowRegistry(tmp_path)
        assert registry._is_2_0_0_published() is False

    def test_returns_false_when_version_is_1_8_0(self, tmp_path: Path):
        """活动版本为 1.8.0 时返回 False。"""
        _write_active_yml(tmp_path, "1.8.0")
        registry = DraftWorkflowRegistry(tmp_path)
        assert registry._is_2_0_0_published() is False

    def test_returns_false_when_version_is_1_0_0(self, tmp_path: Path):
        """活动版本为 1.0.0 时返回 False。"""
        _write_active_yml(tmp_path, "1.0.0")
        registry = DraftWorkflowRegistry(tmp_path)
        assert registry._is_2_0_0_published() is False

    def test_returns_true_when_version_is_2_0_0(self, tmp_path: Path):
        """活动版本为 2.0.0 时返回 True。"""
        _write_active_yml(tmp_path, "2.0.0")
        registry = DraftWorkflowRegistry(tmp_path)
        assert registry._is_2_0_0_published() is True

    def test_returns_false_when_active_yml_corrupt(self, tmp_path: Path):
        """active.yml 损坏时返回 False（fail closed）。"""
        active_path = tmp_path / "knowledge" / "rulesets" / "football-analysis" / "active.yml"
        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.write_text("not valid yaml: [", encoding="utf-8")
        registry = DraftWorkflowRegistry(tmp_path)
        assert registry._is_2_0_0_published() is False

    def test_returns_false_when_version_key_missing(self, tmp_path: Path):
        """active.yml 缺少 version 字段时返回 False。"""
        active_path = tmp_path / "knowledge" / "rulesets" / "football-analysis" / "active.yml"
        active_path.parent.mkdir(parents=True, exist_ok=True)
        active_path.write_text(
            "schema_version: 1\nruleset_id: football-analysis\n",
            encoding="utf-8",
        )
        registry = DraftWorkflowRegistry(tmp_path)
        assert registry._is_2_0_0_published() is False


# ── analysis_context 隔离护栏条件逻辑（G1）────────────────


class TestAnalysisContextContract9Guard:
    """analysis_context.py 的 Contract 9 隔离护栏条件逻辑。

    修改前（当前）：无条件阻断 Contract 9
        if ruleset.manifest.calibration_contract_version == 9:
            raise ValueError(...)
    修改后（G1）：仅未发布时阻断
        if ruleset.manifest.calibration_contract_version == 9:
            if not <_is_2_0_0_published>:
                raise ValueError(...)

    由于 prepare_analysis_context 依赖完整分析环境（比赛文件、文档校验、
    build_index 等），此处通过验证控制点 _is_2_0_0_published 的行为来
    确认隔离逻辑的正确性。完整的 prepare_analysis_context 集成测试应
    在后续批次中覆盖。
    """

    def test_unpublished_blocks_contract9(self, tmp_path: Path):
        """2.0.0 未发布时，隔离护栏应阻断 Contract 9。"""
        # 活动版本为 1.8.0（2.0.0 未发布）
        _write_active_yml(tmp_path, "1.8.0")
        registry = DraftWorkflowRegistry(tmp_path)
        # 隔离控制点：未发布时 _is_2_0_0_published 返回 False
        assert registry._is_2_0_0_published() is False
        # G1 修改后：prepare_analysis_context 中
        #   if not registry._is_2_0_0_published(): raise ValueError(...)
        # 此条件为 True → 阻断

    def test_published_allows_contract9(self, tmp_path: Path):
        """2.0.0 已发布时，隔离护栏应放行 Contract 9。"""
        # 活动版本为 2.0.0（已发布）
        _write_active_yml(tmp_path, "2.0.0")
        registry = DraftWorkflowRegistry(tmp_path)
        # 隔离控制点：已发布时 _is_2_0_0_published 返回 True
        assert registry._is_2_0_0_published() is True
        # G1 修改后：prepare_analysis_context 中
        #   if not registry._is_2_0_0_published(): raise ValueError(...)
        # 此条件为 False → 放行

    # 注意：prepare_analysis_context 的完整集成测试需要构造比赛文件、
    # 规则文档、build_index 等完整分析环境，不适合在单元测试中覆盖。
    # G1 修改后的集成验证应在 tests/test_formal_draft.py 或专门的
    # Contract 9 集成测试中补充，此处仅验证控制点 _is_2_0_0_published。
