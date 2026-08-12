"""Knowledge Engine 收口方案测试。

覆盖：
- Study 台账：事件幂等、哈希错误、JSONL 损坏、状态重建
- Study 生命周期：register/run/expose/evaluate/report
- AI 旁路：失败枚举、台账记录
- ReleaseEvidence：构建、预检门禁、市场矩阵
- Contract 9：V4/V7 模型、市场语义、proposal 隔离
- RenderedOfficialBaseline：时间排序、赛果/赛后观测拒绝
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml

from odds_journal.knowledge_engine.domain.studies import (
    KnowledgeProspectiveStudyV1,
    KnowledgeStudyRunV1,
    KnowledgeStudyLedgerEventV1,
    StudyEventType,
    StudyState,
    RenderedOfficialBaselineV1,
    OfficialBaselineSnapshotV1,
)
from odds_journal.knowledge_engine.domain.features import (
    FeatureSnapshotV2,
    PolicyKernelBaselineV1,
)
from odds_journal.knowledge_engine.domain.decisions import (
    KnowledgeDraftCandidateV1,
    DecisionAuthorityContractV1,
)
from odds_journal.knowledge_engine.domain.contract_v9 import (
    AnalysisDraftInputV4,
    EvaluationBundleV4,
    AnalysisOutlookV7,
    DraftBuildReceiptV2,
)
from odds_journal.knowledge_engine.domain.release_evidence import (
    KnowledgeReleaseEvidenceV1,
    ReleasePreflightResult,
    RELEASE_GATE_THRESHOLDS,
)
from odds_journal.knowledge_engine.adapters.study_ledger import (
    StudyLedger,
    LedgerCorruptionError,
    IdempotencyConflictError,
)
from odds_journal.knowledge_engine.adapters.repository_artifacts import (
    RepositoryArtifactStore,
)
from odds_journal.knowledge_engine.adapters.draft_workflow_registry import (
    DraftWorkflowRegistry,
)
from odds_journal.knowledge_engine.adapters.deterministic_reasoner import (
    DeterministicKnowledgeReasoner,
)
from odds_journal.knowledge_engine.application.run_study import (
    register_study,
    run_study,
    expose_study,
    record_outcome,
    record_failure,
)
from odds_journal.knowledge_engine.application.run_ai_advisory import (
    run_ai_advisory,
    compare_candidates,
    AI_FAILURE_TYPES,
    _map_failure_type,
)
from odds_journal.knowledge_engine.application.study_report import (
    build_study_report,
)
from odds_journal.knowledge_engine.application.release_evidence import (
    build_release_evidence,
    run_release_preflight,
)


TZ = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(TZ).replace(microsecond=0)


def _sha256(data: object) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _future() -> datetime:
    return _now() + timedelta(days=1)


# ── Study 台账测试 ────────────────────────────────────────


class TestStudyLedger:
    """Study 台账幂等、哈希校验和损坏检测。"""

    def test_append_and_rebuild(self, tmp_path: Path):
        """追加事件并从台账重建状态。"""
        ledger = StudyLedger(tmp_path)
        now = _now()

        event = ledger.append(
            event_type=StudyEventType.STUDY_REGISTERED,
            event_id="study-registered:test-study",
            aggregate_id="study:test-study",
            idempotency_key="study-registered:test-study",
            recorded_at=now,
            payload={"study_id": "test-study", "study_name": "Test"},
        )

        assert event.event_type == StudyEventType.STUDY_REGISTERED
        state = ledger.rebuild_study_state("test-study")
        assert state["exists"] is True
        assert state["state"] == StudyState.REGISTERED.value

    def test_idempotent_append_returns_same_event(self, tmp_path: Path):
        """相同 idempotency_key + 相同 payload 返回既有 event。"""
        ledger = StudyLedger(tmp_path)
        now = _now()
        payload = {"study_id": "test-study", "study_name": "Test"}

        event1 = ledger.append(
            StudyEventType.STUDY_REGISTERED,
            "study-registered:test-study",
            "study:test-study",
            "study-registered:test-study",
            now,
            payload,
        )
        event2 = ledger.append(
            StudyEventType.STUDY_REGISTERED,
            "study-registered:test-study",
            "study:test-study",
            "study-registered:test-study",
            now,
            payload,
        )
        assert event1.event_id == event2.event_id
        assert event1.event_sha256 == event2.event_sha256

    def test_idempotency_conflict_rejects_different_payload(self, tmp_path: Path):
        """相同 key、不同内容拒绝。"""
        ledger = StudyLedger(tmp_path)
        now = _now()

        ledger.append(
            StudyEventType.STUDY_REGISTERED,
            "study-registered:test-study",
            "study:test-study",
            "study-registered:test-study",
            now,
            {"study_id": "test-study", "study_name": "Test"},
        )
        with pytest.raises(IdempotencyConflictError):
            ledger.append(
                StudyEventType.STUDY_REGISTERED,
                "study-registered:test-study",
                "study:test-study",
                "study-registered:test-study",
                now,
                {"study_id": "test-study", "study_name": "Different"},
            )

    def test_jsonl_corruption_fail_closed(self, tmp_path: Path):
        """JSONL 损坏时 fail closed。"""
        ledger = StudyLedger(tmp_path)
        now = _now()

        ledger.append(
            StudyEventType.STUDY_REGISTERED,
            "study-registered:test-study",
            "study:test-study",
            "study-registered:test-study",
            now,
            {"study_id": "test-study"},
        )

        # 破坏 JSONL 文件
        path = ledger._ledger_path(StudyEventType.STUDY_REGISTERED)
        path.write_text("not valid json\n", encoding="utf-8")

        with pytest.raises(LedgerCorruptionError):
            ledger.rebuild_study_state("test-study")

    def test_hash_error_fail_closed(self, tmp_path: Path):
        """哈希错误时 fail closed。"""
        ledger = StudyLedger(tmp_path)
        now = _now()

        event = ledger.append(
            StudyEventType.STUDY_REGISTERED,
            "study-registered:test-study",
            "study:test-study",
            "study-registered:test-study",
            now,
            {"study_id": "test-study"},
        )

        # 破坏哈希
        path = ledger._ledger_path(StudyEventType.STUDY_REGISTERED)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["event_sha256"] = "0" * 64
        path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")

        with pytest.raises(LedgerCorruptionError):
            ledger.rebuild_study_state("test-study")

    def test_supersedes_chain_validation(self, tmp_path: Path):
        """supersedes 链断裂时报错。"""
        ledger = StudyLedger(tmp_path)
        now = _now()

        with pytest.raises(LedgerCorruptionError):
            ledger.append(
                StudyEventType.OUTCOME_RECORDED,
                "outcome:test",
                "study:test:match:m1",
                "outcome:test",
                now,
                {"study_id": "test", "match_id": "m1"},
                supersedes_event_id="nonexistent-event",
            )


# ── Study 生命周期测试 ────────────────────────────────────


class TestStudyLifecycle:
    """Study 注册、运行、暴露、评估和报告。"""

    def _make_study(self, store: RepositoryArtifactStore, ledger: StudyLedger) -> KnowledgeProspectiveStudyV1:
        return register_study(
            study_id="test-study",
            study_name="Test Study",
            target_markets=("one_x_two",),
            target_cohort_size=20,
            registered_by="lcz",
            store=store,
            studies_dir=Path("knowledge/knowledge-studies"),
            clock=_FixedClock(),
            ledger=ledger,
        )

    def test_register_and_run(self, tmp_path: Path):
        """注册 Study 并运行 Primary。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        study = self._make_study(store, ledger)

        kickoff = _future()
        now = _now()
        feature = _make_feature(tmp_path, now, kickoff)
        baseline = _make_baseline(tmp_path, now)
        official = _make_official_baseline(now, kickoff)
        candidate = _make_candidate(feature, baseline)
        snapshot = _make_snapshot_manifest()

        run = run_study(
            study=study,
            match_id="test-match",
            kickoff_at=kickoff,
            features=feature,
            baseline=baseline,
            official_baseline=official,
            candidate=candidate,
            store=store,
            runs_dir=tmp_path / "studies",
            snapshot=snapshot,
            clock=_FixedClock(),
            ledger=ledger,
        )

        assert run.run_type == "primary"
        assert run.run_status == "completed"
        assert ledger.has_primary_claim("test-study", "test-match", snapshot.snapshot_sha256)

    def test_duplicate_primary_rejected(self, tmp_path: Path):
        """重复 Primary Claim 被拒绝。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        study = self._make_study(store, ledger)

        kickoff = _future()
        now = _now()
        feature = _make_feature(tmp_path, now, kickoff)
        baseline = _make_baseline(tmp_path, now)
        official = _make_official_baseline(now, kickoff)
        candidate = _make_candidate(feature, baseline)
        snapshot = _make_snapshot_manifest()

        run_study(
            study=study, match_id="m1", kickoff_at=kickoff, features=feature,
            baseline=baseline, official_baseline=official, candidate=candidate,
            store=store, runs_dir=tmp_path / "studies", snapshot=snapshot,
            clock=_FixedClock(), ledger=ledger,
        )

        with pytest.raises(ValueError, match="Primary Claim"):
            run_study(
                study=study, match_id="m1", kickoff_at=kickoff, features=feature,
                baseline=baseline, official_baseline=official, candidate=candidate,
                store=store, runs_dir=tmp_path / "studies", snapshot=snapshot,
                clock=_FixedClock(), ledger=ledger,
            )

    def test_primary_after_kickoff_rejected(self, tmp_path: Path):
        """开赛后 Primary run 被拒绝。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        study = self._make_study(store, ledger)

        kickoff = _now() - timedelta(hours=1)  # 已开赛
        as_of = kickoff - timedelta(hours=1)  # feature as_of 必须在 kickoff 之前
        feature = _make_feature(tmp_path, as_of, kickoff)
        baseline = _make_baseline(tmp_path, as_of)
        official = _make_official_baseline(as_of, kickoff)
        candidate = _make_candidate(feature, baseline)
        snapshot = _make_snapshot_manifest()

        with pytest.raises(ValueError, match="开赛前"):
            run_study(
                study=study, match_id="m1", kickoff_at=kickoff, features=feature,
                baseline=baseline, official_baseline=official, candidate=candidate,
                store=store, runs_dir=tmp_path / "studies", snapshot=snapshot,
                clock=_FixedClock(), ledger=ledger,
            )

    def test_expose_requires_lcz(self, tmp_path: Path):
        """暴露必须由 lcz 批准。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        study = self._make_study(store, ledger)

        kickoff = _future()
        now = _now()
        feature = _make_feature(tmp_path, now, kickoff)
        baseline = _make_baseline(tmp_path, now)
        official = _make_official_baseline(now, kickoff)
        candidate = _make_candidate(feature, baseline)
        snapshot = _make_snapshot_manifest()

        run = run_study(
            study=study, match_id="m1", kickoff_at=kickoff, features=feature,
            baseline=baseline, official_baseline=official, candidate=candidate,
            store=store, runs_dir=tmp_path / "studies", snapshot=snapshot,
            clock=_FixedClock(), ledger=ledger,
        )

        with pytest.raises(ValueError, match="lcz"):
            expose_study(
                study=study, run=run, candidate=candidate,
                exposed_by="not-lcz", reason="test",
                store=store, clock=_FixedClock(), ledger=ledger,
            )

    def test_outcome_supersession(self, tmp_path: Path):
        """Outcome 只能 supersede，不得原地修改。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        study = self._make_study(store, ledger)

        kickoff = _now() + timedelta(hours=1)
        as_of = _now()
        feature = _make_feature(tmp_path, as_of, kickoff)
        baseline = _make_baseline(tmp_path, as_of)
        official = _make_official_baseline(as_of, kickoff)
        candidate = _make_candidate(feature, baseline)
        snapshot = _make_snapshot_manifest()

        run = run_study(
            study=study, match_id="m1", kickoff_at=kickoff, features=feature,
            baseline=baseline, official_baseline=official, candidate=candidate,
            store=store, runs_dir=tmp_path / "studies", snapshot=snapshot,
            clock=_FixedClock(), ledger=ledger,
        )

        # 记录初始 outcome
        outcome1 = record_outcome(
            study=study, run=run, final_score="1-0",
            result_one_x_two="home", result_handicap=None, total_goals=1,
            market_outcomes={"one_x_two": {"status": "assessed", "correct": True}},
            store=store, clock=_FixedClock(), ledger=ledger,
        )

        # supersede 旧 outcome
        outcome2 = record_outcome(
            study=study, run=run, final_score="1-1",
            result_one_x_two="draw", result_handicap=None, total_goals=2,
            market_outcomes={"one_x_two": {"status": "assessed", "correct": False}},
            store=store, clock=_FixedClock(), ledger=ledger,
            supersedes_event_id=outcome1.outcome_id,
        )

        outcomes = ledger.get_outcomes("test-study")
        assert len(outcomes) == 2
        valid = ledger.get_valid_outcomes("test-study")
        assert len(valid) == 1
        assert valid[0]["final_score"] == "1-1"

    def test_counterfactual_not_primary(self, tmp_path: Path):
        """counterfactual Run 不能标记为 primary。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        study = self._make_study(store, ledger)

        kickoff = _future()
        as_of = _now()
        feature = _make_feature(tmp_path, as_of, kickoff)
        baseline = _make_baseline(tmp_path, as_of)
        snapshot = _make_snapshot_manifest()

        run = run_study(
            study=study, match_id="m1", kickoff_at=kickoff, features=feature,
            baseline=baseline, official_baseline=None, candidate=None,
            store=store, runs_dir=tmp_path / "studies", snapshot=snapshot,
            clock=_FixedClock(), ledger=ledger, run_type="counterfactual",
        )

        assert run.run_type == "counterfactual"
        assert not run.primary_run

    def test_study_report_rebuild(self, tmp_path: Path):
        """从台账重建 Study 报告。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        study = self._make_study(store, ledger)

        kickoff = _future()
        as_of = _now()
        feature = _make_feature(tmp_path, as_of, kickoff)
        baseline = _make_baseline(tmp_path, as_of)
        official = _make_official_baseline(as_of, kickoff)
        candidate = _make_candidate(feature, baseline)
        snapshot = _make_snapshot_manifest()

        run = run_study(
            study=study, match_id="m1", kickoff_at=kickoff, features=feature,
            baseline=baseline, official_baseline=official, candidate=candidate,
            store=store, runs_dir=tmp_path / "studies", snapshot=snapshot,
            clock=_FixedClock(), ledger=ledger,
        )

        record_outcome(
            study=study, run=run, final_score="1-0",
            result_one_x_two="home", result_handicap=None, total_goals=1,
            market_outcomes={"one_x_two": {"status": "assessed", "correct": True}},
            store=store, clock=_FixedClock(), ledger=ledger,
        )

        report = build_study_report("test-study", ledger)
        assert report["study_id"] == "test-study"
        assert len(report["primary_runs"]) == 1
        assert len(report["outcomes"]) == 1
        assert report["coverage"]["total_outcomes"] == 1


# ── AI 旁路测试 ───────────────────────────────────────────


class TestAIAdvisory:
    """AI 旁路失败枚举和台账记录。"""

    def test_failure_type_mapping(self):
        """失败原因映射到固定枚举。"""
        assert _map_failure_type("network unreachable", "failed") == "network_denied"
        assert _map_failure_type("request timeout", "failed") == "timeout"
        assert _map_failure_type("budget exceeded", "failed") == "budget_exceeded"
        assert _map_failure_type("schema validation error", "failed") == "schema_error"
        assert _map_failure_type("hash mismatch", "failed") == "input_hash_mismatch"
        assert _map_failure_type("provider error", "failed") == "provider_error"
        assert _map_failure_type("", "unavailable") == "unavailable"

    def test_all_failure_types_defined(self):
        """固定失败枚举完整。"""
        assert set(AI_FAILURE_TYPES) == {
            "unavailable", "network_denied", "timeout",
            "budget_exceeded", "schema_error", "input_hash_mismatch", "provider_error",
        }

    def test_unavailable_records_failure(self, tmp_path: Path):
        """AI unavailable 记录失败事件。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        now = _now()
        kickoff = _future()
        feature = _make_feature(tmp_path, now, kickoff)
        baseline = _make_baseline(tmp_path, now)
        retrieval = _make_retrieval()

        receipt = run_ai_advisory(
            match_id="m1", study_id="test", run_id="test:m1:abc",
            features=feature, retrieval=retrieval, baseline=baseline,
            ai_reasoner=_UnavailableAIReasoner(), store=store,
            ledger=ledger, clock=_FixedClock(),
        )

        assert receipt.advisory_status == "unavailable"
        state = ledger.rebuild_study_state("test")
        failures = state.get("failures", [])
        assert len(failures) == 1
        assert failures[0]["failure_type"] == "unavailable"

    def test_ai_failure_does_not_fake_success(self, tmp_path: Path):
        """AI failure 不让 Study Run 伪装为成功。"""
        store = RepositoryArtifactStore(tmp_path)
        ledger = StudyLedger(tmp_path)
        now = _now()
        kickoff = _future()
        feature = _make_feature(tmp_path, now, kickoff)
        baseline = _make_baseline(tmp_path, now)
        retrieval = _make_retrieval()

        receipt = run_ai_advisory(
            match_id="m1", study_id="test", run_id="test:m1:abc",
            features=feature, retrieval=retrieval, baseline=baseline,
            ai_reasoner=_FailingAIReasoner(), store=store,
            ledger=ledger, clock=_FixedClock(),
        )

        assert receipt.advisory_status == "failed"
        assert receipt.ai_candidate_sha256 is None
        state = ledger.rebuild_study_state("test")
        assert len(state.get("failures", [])) == 1

    def test_compare_candidates_no_ai(self, tmp_path: Path):
        """无 AI 候选时比较仍返回结果。"""
        feature = _make_feature(tmp_path, _now(), _future())
        baseline = _make_baseline(tmp_path, _now())
        det = _make_candidate(feature, baseline)

        comparison = compare_candidates(
            match_id="m1", study_id="test", run_id="test:m1:abc",
            deterministic=det, ai_candidate=None,
        )

        assert comparison.ai_candidate_sha256 == "0" * 64
        assert comparison.agreement == {}


# ── Contract 9 模型测试 ───────────────────────────────────


class TestContractV9Models:
    """Contract 9 V4/V7 模型验证。"""

    def test_draft_input_v4_valid(self):
        """AnalysisDraftInputV4 有效构造。"""
        draft = AnalysisDraftInputV4(
            match_id="m1",
            as_of=_now(),
            compiler_version="knowledge-engine-v1",
            analysis_receipt_sha256="0" * 64,
            official_baseline_sha256="0" * 64,
            feature_sha256="0" * 64,
            policy_baseline_sha256="0" * 64,
            snapshot_sha256="0" * 64,
            index_manifest_sha256="0" * 64,
            retrieval_receipt_sha256="0" * 64,
            evaluation_bundle_sha256="0" * 64,
            candidate_sha256="0" * 64,
            market_enablement={
                "one_x_two": "baseline_only",
                "asian_handicap": "baseline_only",
                "fixed_handicap_1x2": "disabled",
                "total_goals": "baseline_only",
                "score": "disabled",
            },
            calibration_config_sha256="0" * 64,
            draft_input_sha256="0" * 64,
        )
        assert draft.schema_version == 4

    def test_draft_input_v4_rejects_enabled_score(self):
        """score 必须为 disabled。"""
        with pytest.raises(ValueError, match="score"):
            AnalysisDraftInputV4(
                match_id="m1",
                as_of=_now(),
                compiler_version="v1",
                analysis_receipt_sha256="0" * 64,
                official_baseline_sha256="0" * 64,
                feature_sha256="0" * 64,
                policy_baseline_sha256="0" * 64,
                snapshot_sha256="0" * 64,
                index_manifest_sha256="0" * 64,
                retrieval_receipt_sha256="0" * 64,
                evaluation_bundle_sha256="0" * 64,
                candidate_sha256="0" * 64,
                market_enablement={
                    "one_x_two": "baseline_only",
                    "asian_handicap": "baseline_only",
                    "fixed_handicap_1x2": "disabled",
                    "total_goals": "baseline_only",
                    "score": "enabled",
                },
                calibration_config_sha256="0" * 64,
                draft_input_sha256="0" * 64,
            )

    def test_outlook_v7_pass_market_no_candidate(self):
        """pass 市场不得有候选。"""
        with pytest.raises(ValueError, match="pass.*候选"):
            AnalysisOutlookV7(
                match_id="m1",
                as_of=_now(),
                kickoff_at=_future(),
                analysis_receipt_sha256="0" * 64,
                draft_input_sha256="0" * 64,
                evaluation_bundle_sha256="0" * 64,
                market_status={
                    "one_x_two": "pass",
                    "asian_handicap": "pass",
                    "fixed_handicap_1x2": "pass",
                    "total_goals": "pass",
                    "score": "pass",
                },
                market_knowledge={},
                candidates={"one_x_two": {"ranking": ["home"]}},
                outlook_sha256="0" * 64,
            )

    def test_outlook_v7_knowledge_pass_requires_status_pass(self):
        """knowledge_mode=pass 必须对应 status=pass。"""
        with pytest.raises(ValueError, match="knowledge_mode=pass"):
            AnalysisOutlookV7(
                match_id="m1",
                as_of=_now(),
                kickoff_at=_future(),
                analysis_receipt_sha256="0" * 64,
                draft_input_sha256="0" * 64,
                evaluation_bundle_sha256="0" * 64,
                market_status={
                    "one_x_two": "assessed",
                    "asian_handicap": "pass",
                    "fixed_handicap_1x2": "pass",
                    "total_goals": "pass",
                    "score": "pass",
                },
                market_knowledge={
                    "one_x_two": {"knowledge_mode": "pass"},
                },
                candidates={},
                outlook_sha256="0" * 64,
            )

    def test_outlook_v7_baseline_pass_not_reopened(self):
        """baseline pass 不能被知识重开。"""
        with pytest.raises(ValueError, match="baseline pass.*重开"):
            AnalysisOutlookV7(
                match_id="m1",
                as_of=_now(),
                kickoff_at=_future(),
                analysis_receipt_sha256="0" * 64,
                draft_input_sha256="0" * 64,
                evaluation_bundle_sha256="0" * 64,
                market_status={
                    "one_x_two": "pass",
                    "asian_handicap": "pass",
                    "fixed_handicap_1x2": "pass",
                    "total_goals": "pass",
                    "score": "pass",
                },
                market_knowledge={
                    "one_x_two": {"knowledge_mode": "enabled"},
                },
                candidates={},
                outlook_sha256="0" * 64,
            )

    def test_outlook_v7_reorder_requires_degraded(self):
        """首选变化必须 degraded。"""
        with pytest.raises(ValueError, match="首选变化.*degraded"):
            AnalysisOutlookV7(
                match_id="m1",
                as_of=_now(),
                kickoff_at=_future(),
                analysis_receipt_sha256="0" * 64,
                draft_input_sha256="0" * 64,
                evaluation_bundle_sha256="0" * 64,
                market_status={
                    "one_x_two": "assessed",
                    "asian_handicap": "pass",
                    "fixed_handicap_1x2": "pass",
                    "total_goals": "pass",
                    "score": "pass",
                },
                market_knowledge={
                    "one_x_two": {"knowledge_change": "reorder"},
                },
                candidates={},
                outlook_sha256="0" * 64,
            )

    def test_outlook_v7_all_pass_valid(self):
        """全部 pass 有效。"""
        outlook = AnalysisOutlookV7(
            match_id="m1",
            as_of=_now(),
            kickoff_at=_future(),
            analysis_receipt_sha256="0" * 64,
            draft_input_sha256="0" * 64,
            evaluation_bundle_sha256="0" * 64,
            market_status={
                "one_x_two": "pass",
                "asian_handicap": "pass",
                "fixed_handicap_1x2": "pass",
                "total_goals": "pass",
                "score": "pass",
            },
            market_knowledge={
                m: {"knowledge_mode": "pass"} for m in
                ("one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score")
            },
            candidates={},
            outlook_sha256="0" * 64,
        )
        assert outlook.schema_version == 7

    def test_draft_build_receipt_v2_market_matrix(self):
        """DraftBuildReceiptV2 市场矩阵验证。"""
        with pytest.raises(ValueError, match="fixed_handicap_1x2"):
            DraftBuildReceiptV2(
                match_id="m1",
                built_at=_now(),
                as_of=_now(),
                ruleset_id="football-analysis",
                ruleset_version="2.0.0",
                ruleset_sha256="0" * 64,
                snapshot_sha256="0" * 64,
                index_manifest_sha256="0" * 64,
                candidate_sha256="0" * 64,
                draft_input_sha256="0" * 64,
                evaluation_bundle_sha256="0" * 64,
                market_enablement={
                    "fixed_handicap_1x2": "enabled",
                    "score": "disabled",
                },
                receipt_sha256="0" * 64,
            )


# ── Contract 9 工作流隔离测试 ─────────────────────────────


class TestContractV9Workflow:
    """Contract 9 proposal 隔离和索引校验。"""

    def test_build_v4_rejects_without_index(self, tmp_path: Path):
        """Contract 9 索引未就绪时 fail closed。"""
        registry = DraftWorkflowRegistry(tmp_path)
        with pytest.raises(RuntimeError, match="索引未就绪"):
            registry.route_build(9, "match.md", snapshot_sha256="abc")

    def test_build_v4_rejects_proposal_isolation(self, tmp_path: Path):
        """2.0.0 未发布时禁止正式 Draft。"""
        registry = DraftWorkflowRegistry(tmp_path)
        # 创建假的 snapshot 和 index
        snapshot_sha = "a" * 64
        snapshot_dir = tmp_path / "raw" / "knowledge-engine" / "snapshots"
        index_dir = tmp_path / "raw" / "knowledge-engine" / "index"
        snapshot_dir.mkdir(parents=True)
        index_dir.mkdir(parents=True)

        snapshot_path = snapshot_dir / f"{snapshot_sha}.yml"
        db_path = index_dir / f"{snapshot_sha}.db"
        manifest_path = index_dir / f"{snapshot_sha}.manifest.yml"

        snapshot_path.write_text("test", encoding="utf-8")
        db_path.write_bytes(b"test db")
        manifest_path.write_text(
            yaml.safe_dump({
                "snapshot_sha256": snapshot_sha,
                "sqlite_file_sha256": hashlib.sha256(b"test db").hexdigest(),
            }),
            encoding="utf-8",
        )

        # 2.0.0 未发布，非 proposal 模式
        with pytest.raises(RuntimeError, match="2.0.0 未发布"):
            registry.route_build(9, "match.md", snapshot_sha256=snapshot_sha)

    def test_build_v4_proposal_mode_allowed(self, tmp_path: Path):
        """proposal 模式允许 Contract 9 构建。"""
        registry = DraftWorkflowRegistry(tmp_path)
        snapshot_sha = "a" * 64
        snapshot_dir = tmp_path / "raw" / "knowledge-engine" / "snapshots"
        index_dir = tmp_path / "raw" / "knowledge-engine" / "index"
        snapshot_dir.mkdir(parents=True)
        index_dir.mkdir(parents=True)

        (snapshot_dir / f"{snapshot_sha}.yml").write_text("test", encoding="utf-8")
        db_bytes = b"test db"
        (index_dir / f"{snapshot_sha}.db").write_bytes(db_bytes)
        (index_dir / f"{snapshot_sha}.manifest.yml").write_text(
            yaml.safe_dump({
                "snapshot_sha256": snapshot_sha,
                "sqlite_file_sha256": hashlib.sha256(db_bytes).hexdigest(),
            }),
            encoding="utf-8",
        )

        result = registry.route_build(9, "match.md", snapshot_sha256=snapshot_sha, proposal=True)
        assert result["status"] == "knowledge_v4_built"
        assert result["proposal"] is True

    def test_accept_v4_requires_lcz_confirmation(self, tmp_path: Path):
        """accept 必须由 lcz 确认。"""
        registry = DraftWorkflowRegistry(tmp_path)
        candidate = {
            "feature_sha256": "0" * 64,
            "retrieval_sha256": "0" * 64,
            "evaluation_bundle_sha256": "0" * 64,
            "snapshot_sha256": "0" * 64,
            "candidate_sha256": "0" * 64,
        }
        with pytest.raises(ValueError, match="lcz"):
            registry.route_accept(9, "match.md", candidate, approved_by="not-lcz", confirm_draft=False)

    def test_validate_v7_pass_market_rejects_candidate(self, tmp_path: Path):
        """validate 拒绝 pass 市场的候选。"""
        registry = DraftWorkflowRegistry(tmp_path)
        with pytest.raises(ValueError, match="pass.*候选"):
            registry.route_validate(
                9, "match.md",
                outlook={
                    "market_status": {"one_x_two": "pass"},
                    "candidates": {"one_x_two": {"ranking": ["home"]}},
                    "market_knowledge": {},
                },
            )

    def test_validate_v7_baseline_pass_not_reopened(self, tmp_path: Path):
        """validate 拒绝知识重开 baseline pass。"""
        registry = DraftWorkflowRegistry(tmp_path)
        with pytest.raises(ValueError, match="baseline pass.*重开"):
            registry.route_validate(
                9, "match.md",
                outlook={
                    "market_status": {"one_x_two": "pass"},
                    "candidates": {},
                    "market_knowledge": {"one_x_two": {"knowledge_mode": "enabled"}},
                },
            )


# ── RenderedOfficialBaseline 测试 ─────────────────────────


class TestRenderedOfficialBaseline:
    """RenderedOfficialBaselineV1 模型验证。"""

    def test_valid_baseline(self):
        """有效基线构造。"""
        now = _now()
        baseline = RenderedOfficialBaselineV1(
            match_id="m1",
            as_of=now - timedelta(hours=2),
            kickoff_at=now + timedelta(hours=1),
            analysis_receipt_sha256="0" * 64,
            validated_at=now - timedelta(hours=1),
            rendered_at=now - timedelta(minutes=30),
            ruleset_id="football-analysis",
            ruleset_version="1.8.0",
            baseline_sha256="0" * 64,
        )
        assert baseline.ruleset_version == "1.8.0"

    def test_rejects_result(self):
        """存在赛果时拒绝冻结。"""
        now = _now()
        with pytest.raises(ValueError, match="赛果"):
            RenderedOfficialBaselineV1(
                match_id="m1",
                as_of=now - timedelta(hours=2),
                kickoff_at=now + timedelta(hours=1),
                analysis_receipt_sha256="0" * 64,
                validated_at=now - timedelta(hours=1),
                rendered_at=now - timedelta(minutes=30),
                ruleset_id="football-analysis",
                ruleset_version="1.8.0",
                has_result=True,
                baseline_sha256="0" * 64,
            )

    def test_rejects_post_kickoff_observation(self):
        """存在赛后观测时拒绝冻结。"""
        now = _now()
        with pytest.raises(ValueError, match="赛后观测"):
            RenderedOfficialBaselineV1(
                match_id="m1",
                as_of=now - timedelta(hours=2),
                kickoff_at=now + timedelta(hours=1),
                analysis_receipt_sha256="0" * 64,
                validated_at=now - timedelta(hours=1),
                rendered_at=now - timedelta(minutes=30),
                ruleset_id="football-analysis",
                ruleset_version="1.8.0",
                has_post_kickoff_observation=True,
                baseline_sha256="0" * 64,
            )

    def test_rejects_rendered_after_kickoff(self):
        """rendered_at 必须在 kickoff_at 之前。"""
        now = _now()
        with pytest.raises(ValueError, match="rendered_at.*kickoff_at"):
            RenderedOfficialBaselineV1(
                match_id="m1",
                as_of=now - timedelta(hours=3),
                kickoff_at=now - timedelta(hours=1),
                analysis_receipt_sha256="0" * 64,
                validated_at=now - timedelta(hours=2),
                rendered_at=now - timedelta(minutes=30),
                ruleset_id="football-analysis",
                ruleset_version="1.8.0",
                baseline_sha256="0" * 64,
            )


# ── ReleaseEvidence 测试 ──────────────────────────────────


class TestReleaseEvidence:
    """发布证据和预检门禁。"""

    def test_build_evidence_baseline_only(self, tmp_path: Path):
        """样本不足时市场维持 baseline_only。"""
        study_reports = [{
            "primary_runs": [{"run_id": "r1", "match_id": "m1"}],
            "outcomes": [{"outcome_id": "o1", "match_id": "m1", "market_outcomes": {}}],
            "failures": [],
        }]

        evidence, filename = build_release_evidence(
            proposal_sha256="0" * 64,
            manifest_sha256="0" * 64,
            calibration_config_sha256="0" * 64,
            snapshot_sha256="0" * 64,
            logical_index_sha256="0" * 64,
            study_reports=study_reports,
            study_ids=("test-study",),
        )

        assert evidence.market_enablement["one_x_two"] == "baseline_only"
        assert evidence.market_enablement["fixed_handicap_1x2"] == "disabled"
        assert evidence.market_enablement["score"] == "disabled"

    def test_preflight_rejects_insufficient_outcomes(self):
        """Outcome 不足时预检失败。"""
        result = run_release_preflight(
            study_reports=[],
            has_snapshot=True,
            has_index=True,
            has_release_evidence=True,
            evidence_hash_valid=True,
        )
        assert not result.passed
        assert any("Outcome 不足" in r for r in result.failure_reasons)

    def test_preflight_rejects_missing_snapshot(self):
        """缺少 Snapshot 时预检失败。"""
        result = run_release_preflight(
            study_reports=[],
            has_snapshot=False,
            has_index=True,
            has_release_evidence=True,
            evidence_hash_valid=True,
        )
        assert not result.passed
        assert any("Snapshot" in r for r in result.failure_reasons)

    def test_preflight_rejects_evidence_hash_mismatch(self):
        """ReleaseEvidence 哈希不一致时预检失败。"""
        result = run_release_preflight(
            study_reports=[],
            has_snapshot=True,
            has_index=True,
            has_release_evidence=True,
            evidence_hash_valid=False,
        )
        assert not result.passed
        assert any("哈希不一致" in r for r in result.failure_reasons)

    def test_release_evidence_market_matrix_fixed(self):
        """ReleaseEvidence 市场矩阵固定约束。"""
        with pytest.raises(ValueError, match="fixed_handicap_1x2"):
            KnowledgeReleaseEvidenceV1(
                evidence_id="test",
                proposal_sha256="0" * 64,
                manifest_sha256="0" * 64,
                calibration_config_sha256="0" * 64,
                snapshot_sha256="0" * 64,
                logical_index_sha256="0" * 64,
                market_enablement={
                    "one_x_two": "enabled",
                    "asian_handicap": "baseline_only",
                    "fixed_handicap_1x2": "enabled",  # 错误
                    "total_goals": "baseline_only",
                    "score": "disabled",
                },
                gate_results={},
                study_report_sha256="0" * 64,
                evidence_sha256="0" * 64,
            )

    def test_release_evidence_score_always_disabled(self):
        """score 永远 disabled。"""
        with pytest.raises(ValueError, match="score"):
            KnowledgeReleaseEvidenceV1(
                evidence_id="test",
                proposal_sha256="0" * 64,
                manifest_sha256="0" * 64,
                calibration_config_sha256="0" * 64,
                snapshot_sha256="0" * 64,
                logical_index_sha256="0" * 64,
                market_enablement={
                    "one_x_two": "baseline_only",
                    "asian_handicap": "baseline_only",
                    "fixed_handicap_1x2": "disabled",
                    "total_goals": "baseline_only",
                    "score": "enabled",  # 错误
                },
                gate_results={},
                study_report_sha256="0" * 64,
                evidence_sha256="0" * 64,
            )


# ── 确定性推理器测试 ──────────────────────────────────────


class TestDeterministicReasoner:
    """确定性推理器裁决权限。"""

    def test_baseline_pass_never_reopen(self):
        """baseline pass 不可重新打开。"""
        reasoner = DeterministicKnowledgeReasoner()
        feature = _make_feature(Path("."), _now(), _future())
        baseline = PolicyKernelBaselineV1(
            match_id="m1",
            as_of=_now(),
            baseline_pass=True,
            policy_kernel_sha256="0" * 64,
        )
        retrieval = _make_retrieval()

        bundle = reasoner.analyze(feature, retrieval, baseline)
        for market in ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"):
            assert bundle.market_decisions[market]["status"] == "pass"

    def test_time_boundary_invalid_all_pass(self):
        """时间边界无效时全部 pass。"""
        reasoner = DeterministicKnowledgeReasoner()
        feature = _make_feature(Path("."), _now(), _future())
        baseline = PolicyKernelBaselineV1(
            match_id="m1",
            as_of=_now(),
            cutoff_valid=False,
            policy_kernel_sha256="0" * 64,
        )
        retrieval = _make_retrieval()

        bundle = reasoner.analyze(feature, retrieval, baseline)
        for market in ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"):
            assert bundle.market_decisions[market]["status"] == "pass"

    def test_missing_baseline_ranking_passes(self):
        """缺少冻结正式基线排序时 pass。"""
        reasoner = DeterministicKnowledgeReasoner()
        feature = _make_feature(Path("."), _now(), _future())
        baseline = PolicyKernelBaselineV1(
            match_id="m1",
            as_of=_now(),
            policy_kernel_sha256="0" * 64,
        )
        retrieval = _make_retrieval()

        bundle = reasoner.analyze(feature, retrieval, baseline)
        for market in ("one_x_two", "asian_handicap", "total_goals", "score", "fixed_handicap_1x2"):
            assert bundle.market_decisions[market]["status"] == "pass"


# ── 辅助类 ────────────────────────────────────────────────


class _FixedClock:
    """固定时钟，返回预设时间。"""
    def __init__(self, time: datetime | None = None) -> None:
        self._time = time or _now()

    def now(self) -> datetime:
        return self._time


class _UnavailableAIReasoner:
    """AI 不可用的测试替身。"""
    def is_available(self) -> bool:
        return False

    def generate_advisory(self, *args, **kwargs):
        return {"status": "unavailable", "reason": "not available"}


class _FailingAIReasoner:
    """AI 失败的测试替身。"""
    def is_available(self) -> bool:
        return True

    def generate_advisory(self, *args, **kwargs):
        return {"status": "failed", "reason": "provider error"}


def _make_feature(root: Path, as_of: datetime, kickoff: datetime) -> FeatureSnapshotV2:
    raw = {
        "schema_version": 2,
        "match_id": "test-match",
        "as_of": as_of.isoformat(),
        "kickoff_at": kickoff.isoformat(),
        "compiler_version": "knowledge-engine-v1",
        "config_sha256": "0" * 64,
        "observation_collection_sha256": "0" * 64,
        "feature_sha256": "0" * 64,
    }
    raw["feature_sha256"] = _sha256({k: v for k, v in raw.items() if k != "feature_sha256"})
    return FeatureSnapshotV2.model_validate(raw)


def _make_baseline(root: Path, as_of: datetime) -> PolicyKernelBaselineV1:
    raw = {
        "schema_version": 1,
        "match_id": "test-match",
        "as_of": as_of.isoformat(),
        "policy_kernel_sha256": "0" * 64,
    }
    raw["policy_kernel_sha256"] = _sha256({k: v for k, v in raw.items() if k != "policy_kernel_sha256"})
    return PolicyKernelBaselineV1.model_validate(raw)


def _make_official_baseline(as_of: datetime, kickoff: datetime) -> OfficialBaselineSnapshotV1:
    raw = {
        "schema_version": 1,
        "match_id": "test-match",
        "as_of": as_of.isoformat(),
        "kickoff_at": kickoff.isoformat(),
        "analysis_receipt_sha256": "0" * 64,
        "snapshot_sha256": "0" * 64,
    }
    raw["snapshot_sha256"] = _sha256({k: v for k, v in raw.items() if k != "snapshot_sha256"})
    return OfficialBaselineSnapshotV1.model_validate(raw)


def _make_candidate(feature: FeatureSnapshotV2, baseline: PolicyKernelBaselineV1) -> KnowledgeDraftCandidateV1:
    raw = {
        "schema_version": 1,
        "match_id": "test-match",
        "as_of": feature.as_of.isoformat(),
        "feature_sha256": feature.feature_sha256,
        "retrieval_sha256": "0" * 64,
        "baseline_sha256": baseline.policy_kernel_sha256,
        "evaluation_bundle_sha256": "0" * 64,
        "contract_version": 9,
        "market_candidates": {},
        "candidate_sha256": "0" * 64,
    }
    raw["candidate_sha256"] = _sha256({k: v for k, v in raw.items() if k != "candidate_sha256"})
    return KnowledgeDraftCandidateV1.model_validate(raw)


def _make_snapshot_manifest():
    from odds_journal.knowledge_engine.domain.snapshot import KnowledgeSnapshotManifestV1
    raw = {
        "schema_version": 1,
        "snapshot_id": "test-snapshot",
        "proposal_version": "2.0.0",
        "snapshot_sha256": "0" * 64,
        "source_inventory_count": 1,
        "source_disposition_coverage": 1.0,
        "migration_manifest_sha256": "0" * 64,
        "cards_collection_sha256": "0" * 64,
        "card_count": 0,
        "card_ids": [],
        "card_content_sha256s": {},
    }
    raw["snapshot_sha256"] = _sha256({k: v for k, v in raw.items() if k != "snapshot_sha256"})
    return KnowledgeSnapshotManifestV1.model_validate(raw)


def _make_retrieval():
    from odds_journal.knowledge_engine.domain.retrieval import KnowledgeRetrievalReceiptV1
    raw = {
        "schema_version": 1,
        "retrieval_id": "test-retrieval",
        "query_plan_sha256": "0" * 64,
        "snapshot_sha256": "0" * 64,
        "index_manifest_sha256": "0" * 64,
        "retriever_version": "knowledge-engine-v1",
        "retrieval_time_ms": 0.0,
        "fts5_query_count": 0,
        "retrieval_sha256": "0" * 64,
    }
    raw["retrieval_sha256"] = _sha256({k: v for k, v in raw.items() if k != "retrieval_sha256"})
    return KnowledgeRetrievalReceiptV1.model_validate(raw)
