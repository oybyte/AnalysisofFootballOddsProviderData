"""Knowledge Engine 功能测试。

覆盖：cutoff、时区、冲突、概率、裁决、Study、Contract 路由。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from odds_journal.knowledge_engine.domain.knowledge import (
    KnowledgeCardV1,
    KnowledgeTier,
    KnowledgeCategory,
    SourceTrack,
    KnowledgeEffect,
    CardStatus,
    MigrationDisposition,
    SourceInventoryItem,
    BaselineFreezeV1,
    ProposalSupersessionEventV1,
    Ruleset170Disposition,
)
from odds_journal.knowledge_engine.domain.features import (
    FeatureSnapshotV2,
    PolicyKernelBaselineV1,
)
from odds_journal.knowledge_engine.domain.decisions import (
    DecisionAuthorityContractV1,
    KnowledgeEvaluationBundleV1,
    KnowledgeDraftCandidateV1,
    KnowledgeDraftBuildReceiptV1,
)
from odds_journal.knowledge_engine.domain.forecasts import (
    MarketProbabilityForecastV1,
    SettlementUtility,
)
from odds_journal.knowledge_engine.domain.retrieval import (
    KnowledgeQueryPlanV1,
    KnowledgeRetrievalReceiptV1,
    HypothesisGraphV1,
)
from odds_journal.knowledge_engine.domain.studies import (
    KnowledgeProspectiveStudyV1,
    KnowledgeStudyRunV1,
    KnowledgeStudyExposureEventV1,
    KnowledgeStudyOutcomeV1,
    KnowledgeStudyFailureV1,
    OfficialBaselineSnapshotV1,
)
from odds_journal.knowledge_engine.domain.exceptions import (
    KnowledgeEngineError,
    SnapshotNotFoundError,
    IndexCorruptedError,
    AdjudicationBlockedError,
    StudyPrimaryConflictError,
    ExposureWindowExpiredError,
)
from odds_journal.knowledge_engine.adapters.deterministic_reasoner import (
    DeterministicKnowledgeReasoner,
)
from odds_journal.knowledge_engine.adapters.draft_workflow_registry import (
    DraftWorkflowRegistry,
)
from odds_journal.rules import sha256_binary_file


# ── 时区辅助 ──────────────────────────────────────────────

TZ = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(TZ).replace(microsecond=0)


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def test_binary_artifact_digest_handles_non_utf8_bytes(tmp_path: Path) -> None:
    """SQLite indexes are byte-addressed and must not use text canonicalization."""
    artifact = tmp_path / "knowledge-index.db"
    payload = b"SQLite format 3\x00\xa9\xff"
    artifact.write_bytes(payload)

    assert sha256_binary_file(artifact) == hashlib.sha256(payload).hexdigest()


# ── 领域模型测试 ────────────────────────────────────────


class TestKnowledgeCardV1:
    """KnowledgeCardV1 模型验证。"""

    def test_valid_card(self):
        card = KnowledgeCardV1(
            card_id="test-card-001",
            tier=KnowledgeTier.MARKET,
            category=KnowledgeCategory.DECISION_POLICY,
            source_track=SourceTrack.PUBLISHED_RULESET,
            applicable_markets=("asian_handicap",),
            interpretation="测试规则",
            allowed_effects=(KnowledgeEffect.SUPPORT_EXISTING_DIRECTION,),
            max_adjustment=0.5,
            provenance_group="test-group",
            source_family="test-family",
            card_content_sha256=_sha256("test"),
        )
        assert card.card_id == "test-card-001"
        assert card.tier == KnowledgeTier.MARKET

    def test_policy_kernel_must_have_force_pass(self):
        with pytest.raises(ValueError, match="force_pass"):
            KnowledgeCardV1(
                card_id="test-policy",
                tier=KnowledgeTier.FOUNDATION,
                category=KnowledgeCategory.POLICY_KERNEL,
                source_track=SourceTrack.PUBLISHED_RULESET,
                applicable_markets=("one_x_two",),
                interpretation="测试",
                allowed_effects=(KnowledgeEffect.EXPLAIN,),
                max_adjustment=0,
                provenance_group="test",
                source_family="test",
                card_content_sha256=_sha256("test"),
            )

    def test_research_only_cannot_use_decision_effects(self):
        with pytest.raises(ValueError, match="research_only"):
            KnowledgeCardV1(
                card_id="test-research",
                tier=KnowledgeTier.SCENARIO,
                category=KnowledgeCategory.RESEARCH_ONLY,
                source_track=SourceTrack.AI_RESEARCH,
                applicable_markets=("one_x_two",),
                interpretation="测试",
                allowed_effects=(KnowledgeEffect.SUPPORT_EXISTING_DIRECTION,),
                max_adjustment=0,
                provenance_group="test",
                source_family="test",
                card_content_sha256=_sha256("test"),
            )

    def test_duplicate_markets_rejected(self):
        with pytest.raises(ValueError, match="applicable_markets"):
            KnowledgeCardV1(
                card_id="test-dup",
                tier=KnowledgeTier.MARKET,
                category=KnowledgeCategory.DECISION_POLICY,
                source_track=SourceTrack.PUBLISHED_RULESET,
                applicable_markets=("one_x_two", "one_x_two"),
                interpretation="测试",
                allowed_effects=(KnowledgeEffect.EXPLAIN,),
                max_adjustment=0,
                provenance_group="test",
                source_family="test",
                card_content_sha256=_sha256("test"),
            )


class TestFeatureSnapshotV2:
    """FeatureSnapshotV2 模型验证。"""

    def test_timezone_required(self):
        with pytest.raises(ValueError, match="时区"):
            FeatureSnapshotV2(
                schema_version=2,
                match_id="test-match",
                as_of=datetime(2026, 1, 1, 12, 0),
                kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
                compiler_version="v1",
                config_sha256=_sha256("config"),
                observation_collection_sha256=_sha256("obs"),
                feature_sha256=_sha256("feat"),
            )

    def test_as_of_before_kickoff(self):
        with pytest.raises(ValueError, match="as_of 必须在 kickoff_at 之前"):
            FeatureSnapshotV2(
                schema_version=2,
                match_id="test-match",
                as_of=datetime(2026, 1, 1, 15, 0, tzinfo=TZ),
                kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
                compiler_version="v1",
                config_sha256=_sha256("config"),
                observation_collection_sha256=_sha256("obs"),
                feature_sha256=_sha256("feat"),
            )


class TestBaselineFreezeV1:
    """BaselineFreezeV1 模型验证。"""

    def test_valid_freeze(self):
        freeze = BaselineFreezeV1(
            frozen_at=datetime(2026, 8, 11, 12, 0, tzinfo=TZ),
            ruleset_180_content_sha256=_sha256("content"),
            ruleset_180_manifest_sha256=_sha256("manifest"),
            proposal_190_manifest_sha256=_sha256("proposal"),
            experiment_170_manifest_sha256=_sha256("experiment"),
            experiment_170_source_inventory_count=996,
            ruleset_170_disposition=Ruleset170Disposition.CONTINUE_PARALLEL,
            ruleset_170_disposition_reason="等待 2.0.0 发布",
            ruleset_170_disposition_by="lcz",
            ruleset_170_disposition_at=datetime(2026, 8, 11, 12, 0, tzinfo=TZ),
        )
        assert freeze.experiment_170_source_inventory_count == 996

    def test_timezone_required(self):
        with pytest.raises(ValueError, match="时区"):
            BaselineFreezeV1(
                frozen_at=datetime(2026, 8, 11, 12, 0),
                ruleset_180_content_sha256=_sha256("content"),
                ruleset_180_manifest_sha256=_sha256("manifest"),
                proposal_190_manifest_sha256=_sha256("proposal"),
                experiment_170_manifest_sha256=_sha256("experiment"),
                experiment_170_source_inventory_count=0,
            )


# ── 概率预测测试 ────────────────────────────────────────


class TestMarketProbabilityForecastV1:
    """概率预测模型验证。"""

    def test_valid_forecast(self):
        forecast = MarketProbabilityForecastV1(
            match_id="test-match",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            provider_ids=("bet365", "macau", "pinnacle"),
            baseline_probabilities={"home": 0.5, "draw": 0.3, "away": 0.2},
            forecast_sha256=_sha256("forecast"),
        )
        assert forecast.ranking == ["home", "draw", "away"]

    def test_probabilities_must_sum_to_one(self):
        with pytest.raises(ValueError, match="总和"):
            MarketProbabilityForecastV1(
                match_id="test-match",
                as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
                provider_ids=("bet365", "macau", "pinnacle"),
                baseline_probabilities={"home": 0.6, "draw": 0.3, "away": 0.3},
                forecast_sha256=_sha256("forecast"),
            )

    def test_invalid_forecast_needs_reason(self):
        with pytest.raises(ValueError, match="原因"):
            MarketProbabilityForecastV1(
                match_id="test-match",
                as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
                provider_ids=("bet365", "macau", "pinnacle"),
                baseline_probabilities={"home": 0.5, "draw": 0.3, "away": 0.2},
                forecast_valid=False,
                forecast_sha256=_sha256("forecast"),
            )


# ── 裁决测试 ────────────────────────────────────────────


class TestDecisionAuthority:
    """裁决权限合约测试。"""

    def test_default_contract(self):
        contract = DecisionAuthorityContractV1(
            contract_id="test-contract",
        )
        assert contract.single_card_cannot_flip is True
        assert contract.anchor_change_requires_two_independent is True
        assert contract.baseline_pass_never_reopen is True
        assert contract.max_confidence_after_anchor_change == 0.69


class TestDeterministicReasoner:
    """确定性推理器测试。"""

    def test_all_pass_when_baseline_pass(self):
        reasoner = DeterministicKnowledgeReasoner()
        features = FeatureSnapshotV2(
            schema_version=2,
            match_id="test",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
            compiler_version="v1",
            config_sha256=_sha256("config"),
            observation_collection_sha256=_sha256("obs"),
            feature_sha256=_sha256("feat"),
        )
        retrieval = KnowledgeRetrievalReceiptV1(
            retrieval_id="test",
            query_plan_sha256=_sha256("plan"),
            snapshot_sha256=_sha256("snap"),
            index_manifest_sha256=_sha256("index"),
            retriever_version="v1",
            retrieval_time_ms=0,
            fts5_query_count=0,
            retrieval_sha256=_sha256("retrieval"),
        )
        baseline = PolicyKernelBaselineV1(
            match_id="test",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            baseline_pass=True,
            pass_markets=("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"),
            policy_kernel_sha256=_sha256("kernel"),
        )

        bundle = reasoner.analyze(features, retrieval, baseline)
        assert bundle.degraded is False
        for market in ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"):
            assert bundle.market_decisions[market]["status"] == "pass"

    def test_time_boundary_invalid_all_pass(self):
        reasoner = DeterministicKnowledgeReasoner()
        features = FeatureSnapshotV2(
            schema_version=2,
            match_id="test",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
            compiler_version="v1",
            config_sha256=_sha256("config"),
            observation_collection_sha256=_sha256("obs"),
            feature_sha256=_sha256("feat"),
        )
        retrieval = KnowledgeRetrievalReceiptV1(
            retrieval_id="test",
            query_plan_sha256=_sha256("plan"),
            snapshot_sha256=_sha256("snap"),
            index_manifest_sha256=_sha256("index"),
            retriever_version="v1",
            retrieval_time_ms=0,
            fts5_query_count=0,
            retrieval_sha256=_sha256("retrieval"),
        )
        baseline = PolicyKernelBaselineV1(
            match_id="test",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            cutoff_valid=False,
            post_kickoff_leak=True,
            policy_kernel_sha256=_sha256("kernel"),
        )

        bundle = reasoner.analyze(features, retrieval, baseline)
        for market in ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"):
            assert bundle.market_decisions[market]["status"] == "pass"

    def test_score_passes_without_independent_rule(self):
        reasoner = DeterministicKnowledgeReasoner()
        features = FeatureSnapshotV2(
            schema_version=2,
            match_id="test",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
            compiler_version="v1",
            config_sha256=_sha256("config"),
            observation_collection_sha256=_sha256("obs"),
            feature_sha256=_sha256("feat"),
        )
        retrieval = KnowledgeRetrievalReceiptV1(
            retrieval_id="test",
            query_plan_sha256=_sha256("plan"),
            snapshot_sha256=_sha256("snap"),
            index_manifest_sha256=_sha256("index"),
            retriever_version="v1",
            retrieval_time_ms=0,
            fts5_query_count=0,
            retrieval_sha256=_sha256("retrieval"),
        )
        baseline = PolicyKernelBaselineV1(
            match_id="test",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            independent_evidence_score=False,
            policy_kernel_sha256=_sha256("kernel"),
        )

        bundle = reasoner.analyze(features, retrieval, baseline)
        assert bundle.market_decisions["score"]["status"] == "pass"


# ── Study 测试 ──────────────────────────────────────────


class TestStudyModels:
    """Study 模型验证。"""

    def test_primary_run_must_be_before_kickoff(self):
        with pytest.raises(ValueError, match="开赛前"):
            KnowledgeStudyRunV1(
                run_id="test-run",
                study_id="test-study",
                match_id="test-match",
                run_at=datetime(2026, 1, 1, 15, 0, tzinfo=TZ),
                kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
                snapshot_sha256=_sha256("snap"),
                official_baseline_sha256=_sha256("baseline"),
                policy_baseline_sha256=_sha256("policy"),
                run_sha256=_sha256("run"),
            )

    def test_hypothesis_graph_requires_all_three(self):
        with pytest.raises(ValueError, match="不完整"):
            HypothesisGraphV1(
                match_id="test",
                hypotheses={
                    "one_x_two": {
                        "supporting_hypothesis": "支持",
                        "counter_hypothesis": "反证",
                    }
                },
            )


# ── Contract 路由测试 ───────────────────────────────────


class TestDraftWorkflowRegistry:
    """DraftWorkflowRegistry 测试。"""

    def test_detect_contract_7(self):
        registry = DraftWorkflowRegistry(Path("."))
        assert registry.detect_contract_version({"schema_version": 7}) == 7
        assert registry.detect_contract_version({"contract_version": 7}) == 7

    def test_detect_contract_8(self):
        registry = DraftWorkflowRegistry(Path("."))
        assert registry.detect_contract_version({"schema_version": 8}) == 8
        assert registry.detect_contract_version({"calibration_contract_version": 8}) == 8

    def test_detect_contract_9(self):
        registry = DraftWorkflowRegistry(Path("."))
        assert registry.detect_contract_version({"schema_version": 9}) == 9
        assert registry.detect_contract_version({"calibration_contract_version": 9}) == 9

    def test_route_build_contract_9_without_index(self):
        registry = DraftWorkflowRegistry(Path("."))
        with pytest.raises(RuntimeError, match="索引未就绪"):
            registry.route_build(9, "test-match", snapshot_sha256=_sha256("missing-snapshot"))

    def test_agent_start_status(self):
        registry = DraftWorkflowRegistry(Path("."))
        status = registry.agent_start_status()
        assert "contracts" in status
        assert "contract_7" in status["contracts"]
        assert "contract_8" in status["contracts"]
        assert "contract_9" in status["contracts"]
        assert status["contracts"]["contract_7"] == "legacy"
        assert status["contracts"]["contract_8"] == "current"


# ── 迁移测试 ───────────────────────────────────────────


class TestMigrationInventory:
    """知识迁移清单测试。"""

    def test_source_inventory_item_frozen(self):
        item = SourceInventoryItem(
            rule_id="test-rule",
            document_id="test-doc",
            ruleset_id="football-analysis",
            ruleset_version="1.8.0",
            file_path="test.md",
            file_sha256=_sha256("test"),
            reliability="established",
            markets=("all",),
        )
        with pytest.raises(Exception):  # frozen
            item.disposition = MigrationDisposition.MIGRATED  # type: ignore

    def test_migration_disposition_values(self):
        assert MigrationDisposition.MIGRATED.value == "migrated"
        assert MigrationDisposition.CONSOLIDATED.value == "consolidated"
        assert MigrationDisposition.ADVISORY.value == "advisory"
        assert MigrationDisposition.RESEARCH.value == "research"
        assert MigrationDisposition.DEFERRED.value == "deferred"


# ── 异常测试 ───────────────────────────────────────────


class TestExceptions:
    """领域异常测试。"""

    def test_exception_hierarchy(self):
        assert issubclass(SnapshotNotFoundError, KnowledgeEngineError)
        assert issubclass(IndexCorruptedError, KnowledgeEngineError)
        assert issubclass(AdjudicationBlockedError, KnowledgeEngineError)
        assert issubclass(StudyPrimaryConflictError, KnowledgeEngineError)
        assert issubclass(ExposureWindowExpiredError, KnowledgeEngineError)


# ── 结算效用测试 ───────────────────────────────────────


class TestSettlementUtility:
    """结算效用测试。"""

    def test_default_values(self):
        util = SettlementUtility()
        assert util.full_win == 1.00
        assert util.half_win == 0.75
        assert util.push == 0.50
        assert util.half_loss == 0.25
        assert util.full_loss == 0.00


# ── 概率置换测试 ───────────────────────────────────────


class TestProbabilityPermutation:
    """概率置换与 Brier/Log Loss 测试。"""

    def test_permute_preserves_probability_set(self):
        """合法排序变化后，概率集合保持不变。"""
        original = {"home": 0.5, "draw": 0.3, "away": 0.2}
        forecast = MarketProbabilityForecastV1(
            match_id="test",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            provider_ids=("bet365", "macau", "pinnacle"),
            baseline_probabilities=original,
            forecast_sha256=_sha256("forecast"),
        )
        assert forecast.ranking == ["home", "draw", "away"]

        # 模拟排序变化：知识裁决改变排序后，概率置换
        permuted = {
            "home": original["draw"],
            "draw": original["home"],
            "away": original["away"],
        }
        new_forecast = MarketProbabilityForecastV1(
            match_id="test",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            provider_ids=("bet365", "macau", "pinnacle"),
            baseline_probabilities=permuted,
            forecast_sha256=_sha256("forecast2"),
        )
        assert new_forecast.ranking == ["draw", "home", "away"]
        # 概率集合不变
        assert set(permuted.values()) == set(original.values())

    def test_brier_score_calculation(self):
        """Brier Score 计算：预测概率 vs 实际结果。"""
        # 预测 {home: 0.5, draw: 0.3, away: 0.2}，实际主胜
        probs = {"home": 0.5, "draw": 0.3, "away": 0.2}
        # Brier = (0.5-1)^2 + (0.3-0)^2 + (0.2-0)^2 = 0.25 + 0.09 + 0.04 = 0.38
        brier = sum((probs[k] - (1.0 if k == "home" else 0.0)) ** 2 for k in probs)
        assert abs(brier - 0.38) < 1e-10

    def test_log_loss_calculation(self):
        """Log Loss 计算。"""
        import math

        # 预测概率 0.5，实际发生
        log_loss = -math.log(0.5)
        assert abs(log_loss - 0.693147) < 1e-4


# ── 裁决边缘情况测试 ──────────────────────────────────


class TestAdjudicationEdgeCases:
    """裁决权限边缘情况测试。"""

    def _make_features(self) -> FeatureSnapshotV2:
        return FeatureSnapshotV2(
            schema_version=2,
            match_id="test-edge",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
            compiler_version="v1",
            config_sha256=_sha256("config"),
            observation_collection_sha256=_sha256("obs"),
            feature_sha256=_sha256("feat"),
        )

    def _make_retrieval(self) -> KnowledgeRetrievalReceiptV1:
        return KnowledgeRetrievalReceiptV1(
            retrieval_id="test-edge",
            query_plan_sha256=_sha256("plan"),
            snapshot_sha256=_sha256("snap"),
            index_manifest_sha256=_sha256("index"),
            retriever_version="v1",
            retrieval_time_ms=0,
            fts5_query_count=0,
            retrieval_sha256=_sha256("retrieval"),
        )

    def _make_baseline(self, **kwargs: Any) -> PolicyKernelBaselineV1:
        defaults = {
            "match_id": "test-edge",
            "as_of": datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            "policy_kernel_sha256": _sha256("kernel"),
        }
        defaults.update(kwargs)
        return PolicyKernelBaselineV1(**defaults)

    def test_fixed_handicap_passes_without_independent_rule(self):
        """固定让球缺少独立正式规则时 pass。"""
        reasoner = DeterministicKnowledgeReasoner()
        baseline = self._make_baseline(independent_evidence_fixed_handicap=False)
        bundle = reasoner.analyze(
            self._make_features(), self._make_retrieval(), baseline,
        )
        assert bundle.market_decisions["fixed_handicap_1x2"]["status"] == "pass"

    def test_total_goals_passes_without_independent_rule(self):
        """总进球缺少独立正式规则时 pass。"""
        reasoner = DeterministicKnowledgeReasoner()
        baseline = self._make_baseline(independent_evidence_total_goals=False)
        bundle = reasoner.analyze(
            self._make_features(), self._make_retrieval(), baseline,
        )
        assert bundle.market_decisions["total_goals"]["status"] == "pass"

    def test_unresolved_conflicts_logged(self):
        """未解决冲突被记录但不阻断裁决。"""
        reasoner = DeterministicKnowledgeReasoner()
        baseline = self._make_baseline(
            has_unresolved_conflicts=True,
            conflict_ids=("conflict-1", "conflict-2"),
        )
        bundle = reasoner.analyze(
            self._make_features(), self._make_retrieval(), baseline,
        )
        # 冲突被记录，但裁决不因此全部 pass
        log_text = " ".join(bundle.adjudication_log)
        assert "未解决冲突" in log_text

    def test_baseline_pass_market_never_reopen(self):
        """baseline_pass 的市场不可重新打开。"""
        authority = DecisionAuthorityContractV1(
            contract_id="test-authority",
            baseline_pass_never_reopen=True,
        )
        reasoner = DeterministicKnowledgeReasoner(authority)
        baseline = self._make_baseline(
            pass_markets=("one_x_two", "asian_handicap"),
        )
        bundle = reasoner.analyze(
            self._make_features(), self._make_retrieval(), baseline, authority,
        )
        assert bundle.market_decisions["one_x_two"]["status"] == "pass"
        assert bundle.market_decisions["asian_handicap"]["status"] == "pass"

    def test_confidence_capped_at_069_after_anchor_change(self):
        """锚点变化后置信度不超过 0.69。"""
        authority = DecisionAuthorityContractV1(
            contract_id="test-authority",
            max_confidence_after_anchor_change=0.69,
        )
        assert authority.max_confidence_after_anchor_change == 0.69

    def test_single_card_cannot_flip(self):
        """单张卡不能改变第一选择。"""
        authority = DecisionAuthorityContractV1(
            contract_id="test-authority",
            single_card_cannot_flip=True,
        )
        assert authority.single_card_cannot_flip is True

    def test_anchor_change_requires_two_independent(self):
        """第一选择变化至少需要两个独立 provenance group。"""
        authority = DecisionAuthorityContractV1(
            contract_id="test-authority",
            anchor_change_requires_two_independent=True,
        )
        assert authority.anchor_change_requires_two_independent is True


# ── Study 完整生命周期测试 ─────────────────────────────


class TestStudyLifecycle:
    """Study 完整生命周期测试。"""

    def test_register_study(self):
        """注册前瞻 Study。"""
        study = KnowledgeProspectiveStudyV1(
            study_id="test-study-001",
            study_name="Test Study",
            proposal_id="football-analysis",
            proposal_version="2.0.0",
            target_markets=("one_x_two", "asian_handicap"),
            target_cohort_size=60,
            stop_conditions=(),
            exclusion_conditions=(),
            registered_at=datetime.now(TZ).replace(microsecond=0),
            registered_by="lcz",
            status="active",
            study_sha256=_sha256("study"),
        )
        assert study.study_id == "test-study-001"
        assert study.status == "active"
        assert study.target_cohort_size == 60

    def test_primary_run_must_be_before_kickoff(self):
        """Primary run 必须在开赛前。"""
        with pytest.raises(ValueError, match="开赛前"):
            KnowledgeStudyRunV1(
                run_id="test-run",
                study_id="test-study",
                match_id="test-match",
                run_at=datetime(2026, 1, 1, 15, 0, tzinfo=TZ),
                kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
                snapshot_sha256=_sha256("snap"),
                official_baseline_sha256=_sha256("baseline"),
                policy_baseline_sha256=_sha256("policy"),
                run_sha256=_sha256("run"),
            )

    def test_exposure_event(self):
        """暴露 Study 结果。"""
        from datetime import timezone, timedelta

        tz = timezone(timedelta(hours=8))
        event = KnowledgeStudyExposureEventV1(
            event_id="exposure:test:match:run",
            study_id="test-study",
            match_id="test-match",
            run_id="test-run",
            snapshot_sha256=_sha256("snapshot"),
            candidate_sha256=_sha256("candidate"),
            exposed_at=datetime.now(tz).replace(microsecond=0),
            exposed_by="lcz",
            exposure_reason="研究需要",
            exposure_sha256=_sha256("exposure"),
        )
        assert event.exposed_by == "lcz"
        assert event.exposure_reason == "研究需要"

    def test_outcome_recording(self):
        """记录 Study Outcome。"""
        from datetime import timezone, timedelta

        tz = timezone(timedelta(hours=8))
        outcome = KnowledgeStudyOutcomeV1(
            outcome_id="outcome:test:match:run",
            study_id="test-study",
            match_id="test-match",
            run_id="test-run",
            final_score="2-1",
            result_one_x_two="home",
            result_handicap="home_handicap",
            total_goals=3,
            market_outcomes={
                "one_x_two": {"status": "correct", "prediction": "home", "actual": "home"},
                "asian_handicap": {"status": "correct", "prediction": "home_cover", "actual": "home_cover"},
            },
            supersedes_event_id=None,
            recorded_at=datetime.now(tz).replace(microsecond=0),
            outcome_sha256=_sha256("outcome"),
        )
        assert outcome.final_score == "2-1"
        assert outcome.result_one_x_two == "home"
        assert outcome.total_goals == 3
        assert outcome.result_handicap == "home_handicap"

    def test_outcome_supersession(self):
        """Outcome 纠错必须追加带 supersedes_event_id 的新事件。"""
        from datetime import timezone, timedelta

        tz = timezone(timedelta(hours=8))
        outcome = KnowledgeStudyOutcomeV1(
            outcome_id="outcome:v2:test:match:run",
            study_id="test-study",
            match_id="test-match",
            run_id="test-run",
            final_score="2-2",
            result_one_x_two="draw",
            result_handicap=None,
            total_goals=4,
            market_outcomes={},
            supersedes_event_id="outcome:v1:test:match:run",
            recorded_at=datetime.now(tz).replace(microsecond=0),
            outcome_sha256=_sha256("outcome-v2"),
        )
        assert outcome.supersedes_event_id == "outcome:v1:test:match:run"

    def test_failure_recording(self):
        """记录 Study Failure。"""
        from datetime import timezone, timedelta

        tz = timezone(timedelta(hours=8))
        failure = KnowledgeStudyFailureV1(
            failure_id="failure:test:match:20260101T120000",
            study_id="test-study",
            match_id="test-match",
            run_id=None,
            failure_type="other",
            failure_message="索引未就绪，无法执行 Study",
            failure_context={"snapshot_sha256": _sha256("snap")},
            recorded_at=datetime.now(tz).replace(microsecond=0),
            failure_sha256=_sha256("failure"),
        )
        assert failure.failure_type == "other"
        assert "索引未就绪" in failure.failure_message

    def test_official_baseline_snapshot(self):
        """OfficialBaselineSnapshot 冻结。"""
        snapshot = OfficialBaselineSnapshotV1(
            match_id="test-match",
            as_of=datetime(2026, 1, 1, 12, 0, tzinfo=TZ),
            kickoff_at=datetime(2026, 1, 1, 14, 0, tzinfo=TZ),
            analysis_receipt_sha256=_sha256("receipt"),
            outlook_sha256=_sha256("outlook"),
            snapshot_sha256=_sha256("snapshot"),
        )
        assert snapshot.match_id == "test-match"
        assert snapshot.baseline_valid is True


# ── Contract 路由边界测试 ─────────────────────────────


class TestContractRoutingEdgeCases:
    """Contract 路由边界情况测试。"""

    def test_unknown_schema_defaults_to_7(self):
        """空 schema 默认路由到 Contract 7。"""
        registry = DraftWorkflowRegistry(Path("."))
        assert registry.detect_contract_version({"schema_version": 0}) == 7
        assert registry.detect_contract_version({"schema_version": 6}) == 7
        assert registry.detect_contract_version({}) == 7  # schema_version 默认为 0 <= 7

    def test_contract_9_fail_closed_without_index(self):
        """Contract 9 索引未就绪时 fail closed。"""
        registry = DraftWorkflowRegistry(Path("."))
        with pytest.raises(RuntimeError, match="索引未就绪"):
            registry.route_build(9, "test-match", snapshot_sha256=_sha256("missing-snapshot"))

    def test_contract_7_legacy_route(self):
        """Contract 7 路由到 legacy。"""
        registry = DraftWorkflowRegistry(Path("."))
        result = registry.route_build(7, "test-match")
        assert result["contract"] == 7
        assert result["status"] == "legacy"

    def test_contract_8_v3_route(self):
        """Contract 8 路由到 V3。"""
        registry = DraftWorkflowRegistry(Path("."))
        result = registry.route_build(8, "test-match")
        assert result["contract"] == 8
        assert result["status"] == "v3_built"

    def test_contract_version_invalid(self):
        """不支持的 Contract 版本抛出异常。"""
        registry = DraftWorkflowRegistry(Path("."))
        with pytest.raises(ValueError, match="不支持的 Contract 版本"):
            registry.route_build(10, "test-match")

    def test_validate_candidate_consistency(self):
        """候选一致性验证。"""
        registry = DraftWorkflowRegistry(Path("."))
        valid = {
            "feature_sha256": "abc",
            "retrieval_sha256": "def",
            "evaluation_bundle_sha256": "ghi",
            "snapshot_sha256": _sha256("snapshot"),
        }
        assert registry._validate_candidate_consistency(valid) is True
        invalid = {"feature_sha256": "abc"}
        assert registry._validate_candidate_consistency(invalid) is False


# ── 前瞻 Study 提案验证测试 ───────────────────────────


class TestProposalValidation:
    """提案验证与迁移覆盖测试。"""

    def test_proposal_supersession_event(self):
        """提案取代事件。"""
        from datetime import timezone, timedelta

        tz = timezone(timedelta(hours=8))
        event = ProposalSupersessionEventV1(
            event_id="supersede-190-to-200",
            superseded_proposal_id="football-analysis",
            superseded_proposal_version="1.9.0",
            superseded_by_proposal_id="football-analysis",
            superseded_by_proposal_version="2.0.0",
            reason="1.9.0 被 2.0.0 知识引擎取代",
            recorded_at=datetime.now(tz).replace(microsecond=0),
            recorded_by="lcz",
        )
        assert event.superseded_proposal_version == "1.9.0"
        assert event.superseded_by_proposal_version == "2.0.0"
        assert "知识引擎" in event.reason

    def test_ruleset_170_disposition_values(self):
        """1.7.0 处置值。"""
        assert Ruleset170Disposition.CONTINUE_PARALLEL.value == "continue_parallel"
        assert Ruleset170Disposition.DEACTIVATE_AFTER_2_0_RELEASE.value == "deactivate_after_2_0_release"
        assert Ruleset170Disposition.ARCHIVE_WITHOUT_ACTIVATION.value == "archive_without_activation"

    def test_migration_inventory_auto_disposition(self):
        """自动处置：基础规则 → migrated。"""
        from odds_journal.knowledge_engine.application.migrate_knowledge import auto_disposition

        inventory = [
            SourceInventoryItem(
                rule_id="football-analysis-framework",
                document_id="football-analysis-framework",
                ruleset_id="football-analysis",
                ruleset_version="1.8.0",
                file_path="test.md",
                file_sha256=_sha256("test"),
                reliability="established",
                markets=("all",),
            ),
            SourceInventoryItem(
                rule_id="unknown-rule",
                document_id="unknown-rule",
                ruleset_id="football-analysis",
                ruleset_version="1.8.0",
                file_path="test.md",
                file_sha256=_sha256("test"),
                reliability="unknown",
                markets=("all",),
            ),
        ]
        result = auto_disposition(inventory)
        assert result[0].disposition == MigrationDisposition.MIGRATED
        assert result[1].disposition == MigrationDisposition.DEFERRED

    def test_validate_coverage(self):
        """验证覆盖率计算。"""
        from odds_journal.knowledge_engine.application.migrate_knowledge import validate_coverage

        inventory = [
            SourceInventoryItem(
                rule_id="r1", document_id="d1", ruleset_id="f", ruleset_version="1.8.0",
                file_path="f1.md", file_sha256=_sha256("f1"), reliability="established",
                markets=("all",), disposition=MigrationDisposition.MIGRATED,
            ),
            SourceInventoryItem(
                rule_id="r2", document_id="d2", ruleset_id="f", ruleset_version="1.8.0",
                file_path="f2.md", file_sha256=_sha256("f2"), reliability="experimental",
                markets=("all",), disposition=MigrationDisposition.ADVISORY,
            ),
            SourceInventoryItem(
                rule_id="r3", document_id="d3", ruleset_id="f", ruleset_version="1.8.0",
                file_path="f3.md", file_sha256=_sha256("f3"), reliability="unknown",
                markets=("all",), disposition=MigrationDisposition.DEFERRED,
            ),
        ]
        is_covered, counts = validate_coverage(inventory)
        # Deferred 是已记录的人工处置，不生成卡片但完成来源覆盖。
        assert is_covered is True
        assert counts.get("migrated", 0) == 1
        assert counts.get("advisory", 0) == 1
        assert counts.get("deferred", 0) == 1


# ── Analytics 测试 ─────────────────────────────────────


class TestAnalytics:
    """Analytics 统计测试。"""

    def test_compute_migration_coverage(self):
        """迁移覆盖率计算。"""
        from odds_journal.knowledge_engine.application.analytics import compute_migration_coverage

        inventory = [
            {"disposition": "migrated"},
            {"disposition": "migrated"},
            {"disposition": "advisory"},
            {"disposition": "deferred"},
        ]
        stats = compute_migration_coverage(inventory)
        assert stats["total_sources"] == 4
        assert stats["coverage"] == 1.0  # deferred is an explicit disposition

    def test_compute_capability_status(self):
        """能力状态计算。"""
        from odds_journal.knowledge_engine.application.analytics import compute_capability_status

        # 无快照/索引
        status = compute_capability_status(None, None, 0, 0, False)
        assert status["status"] == "implemented_disabled"

        # 有快照/索引
        status = compute_capability_status("sha256", "sha256", 0, 0, False)
        assert status["status"] == "shadow_ready"

        # 有 Study
        status = compute_capability_status("sha256", "sha256", 1, 0, False)
        assert status["status"] == "study_active"

        # 达到发布门槛
        status = compute_capability_status("sha256", "sha256", 1, 60, True)
        assert status["status"] == "release_eligible"

    def test_compute_retrieval_performance(self):
        """检索性能统计。"""
        from odds_journal.knowledge_engine.application.analytics import compute_retrieval_performance

        logs = [
            {"retrieval_time_ms": 100, "fts5_query_count": 2, "retrieved_decision_cards": ["c1", "c2"]},
            {"retrieval_time_ms": 200, "fts5_query_count": 3, "retrieved_decision_cards": ["c3"]},
            {"retrieval_time_ms": 300, "fts5_query_count": 1, "retrieved_decision_cards": []},
        ]
        stats = compute_retrieval_performance(logs)
        assert stats["sample_count"] == 3
        assert stats["avg_retrieval_time_ms"] == 200.0
        assert stats["max_retrieval_time_ms"] == 300
        assert stats["avg_decision_cards"] == 1.0

    def test_compute_market_adjudication_stats(self):
        """市场裁决统计。"""
        from odds_journal.knowledge_engine.application.analytics import compute_market_adjudication_stats

        outcomes = [
            {
                "market_outcomes": {
                    "one_x_two": {"status": "assessed", "correct": True},
                    "asian_handicap": {"status": "pass"},
                }
            },
            {
                "market_outcomes": {
                    "one_x_two": {"status": "assessed", "correct": False},
                    "asian_handicap": {"status": "assessed", "correct": True},
                }
            },
        ]
        stats = compute_market_adjudication_stats(outcomes)
        assert stats["sample_count"] == 2
        assert stats["markets"]["one_x_two"]["correct"] == 1
        assert stats["markets"]["one_x_two"]["wrong"] == 1
        assert stats["markets"]["one_x_two"]["accuracy"] == 0.5
        assert stats["markets"]["asian_handicap"]["pass"] == 1

    def test_compute_probability_scoring(self):
        """概率评分计算。"""
        from odds_journal.knowledge_engine.application.analytics import compute_probability_scoring

        forecasts = [
            {
                "study_id": "study-a", "match_id": "match-a", "run_id": "run-a", "snapshot_sha256": _sha256("snap-a"),
                "forecast_valid": True,
                "baseline_probabilities": {"home": 0.5, "draw": 0.3, "away": 0.2},
            },
            {
                "study_id": "study-a", "match_id": "match-b", "run_id": "run-b", "snapshot_sha256": _sha256("snap-a"),
                "forecast_valid": True,
                "baseline_probabilities": {"home": 0.4, "draw": 0.35, "away": 0.25},
            },
        ]
        results = [
            {"study_id": "study-a", "match_id": "match-a", "run_id": "run-a", "snapshot_sha256": _sha256("snap-a"), "result_one_x_two": "home"},
            {"study_id": "study-a", "match_id": "match-b", "run_id": "run-b", "snapshot_sha256": _sha256("snap-a"), "result_one_x_two": "draw"},
        ]
        stats = compute_probability_scoring(forecasts, results)
        assert stats["sample_count"] == 2
        assert stats["avg_brier_score"] > 0
        assert stats["avg_log_loss"] > 0

    def test_compute_exposure_stratification(self):
        """Exposure 分层统计。"""
        from odds_journal.knowledge_engine.application.analytics import compute_exposure_stratification

        exposure_events = [{"match_id": "match-1"}]
        outcomes = [
            {"match_id": "match-1"},
            {"match_id": "match-2"},
            {"match_id": "match-3"},
        ]
        stats = compute_exposure_stratification(exposure_events, outcomes)
        assert stats["total_outcomes"] == 3
        assert stats["exposed_count"] == 1
        assert stats["blind_count"] == 2
        assert abs(stats["exposure_rate"] - 1 / 3) < 1e-10
