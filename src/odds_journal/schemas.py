from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .analysis_context import AnalysisReceipt
from .calibration import CalibrationConfig
from .case_retrieval import CaseRetrievalReceipt
from .cases import LegacyCase
from .evidence import EvidencePayload
from .evidence_registry import EvidenceRecord
from .extraction import MediaInventory, TextAtom
from .agent_workflow import AnalysisTrace
from .models import AnalysisOutlook, MatchMetadata
from .rules import RuleMetadata, RulesetManifest
from .scenarios import ResolutionCollection, ScenarioCollection
from .validation_studies import ValidationCasePayload, ValidationStudy
from .historical_certification import HistoricalCertificationManifest
from .desktop_agents import (
    CertificationResult,
    DesktopLocalState,
    DesktopManifest,
    DesktopReleaseState,
)
from .journal import (
    JournalAlignmentV1,
    JournalAttachmentV1,
    JournalEntryRecordV1,
    JournalIngestRequestV1,
    JournalOperationResultV1,
    JournalSegmentV1,
)
from .market_archive import MarketArchiveDraftV1, MarketArchivePreviewV1, MarketArchiveResultV1
from .market_monitoring import MarketArchiveComparisonV1, PrematchRiskWatchlistV1
from .observations import (
    FixtureFactObservationV1,
    MatchDataBundleV1,
    MarketObservationEventV1,
    MatchResultObservationV1,
)
from .lock_lifecycle import LifecycleAction, LockCandidateReceiptV1
from .rule_engine.evaluation import AnalysisDraftInput, EvaluationBundle, ReasoningDisposition
from .experiments import (
    ActiveExperiment,
    ExperimentAdvisoryBundle,
    ExperimentAdvisoryDisposition,
    ExperimentAdvisoryOutcome,
    ExperimentAdvisoryReceipt,
    ExperimentAnalysisReceipt,
    ExperimentCalibrationConfig,
    ExperimentEvaluationBundle,
    ExperimentOutcome,
    ExperimentOutlook,
    ExperimentPredictionReceipt,
    LiveExperimentInput,
    LiveExperimentReceipt,
)


SCHEMA_MODELS: dict[str, type[BaseModel] | Any] = {
    "match.schema.json": MatchMetadata,
    "analysis-outlook.schema.json": AnalysisOutlook,
    "calibration-config.schema.json": CalibrationConfig,
    "analysis-trace.schema.json": AnalysisTrace,
    "legacy-case.schema.json": LegacyCase,
    "evidence-registry.schema.json": EvidenceRecord,
    "rule-evidence.schema.json": EvidencePayload,
    "scenario.schema.json": TypeAdapter(ScenarioCollection | ResolutionCollection),
    "analysis-receipt.schema.json": AnalysisReceipt,
    "case-retrieval-receipt.schema.json": CaseRetrievalReceipt,
    "rule.schema.json": RuleMetadata,
    "ruleset.schema.json": RulesetManifest,
    "text-atom.schema.json": TextAtom,
    "media-inventory.schema.json": MediaInventory,
    "validation-study.schema.json": ValidationStudy,
    "validation-case.schema.json": ValidationCasePayload,
    "historical-certification-manifest.schema.json": HistoricalCertificationManifest,
    "desktop-agent-manifest.schema.json": DesktopManifest,
    "desktop-agent-local.schema.json": DesktopLocalState,
    "desktop-agent-release.schema.json": DesktopReleaseState,
    "desktop-agent-certification.schema.json": CertificationResult,
    "journal-ingest-request.schema.json": JournalIngestRequestV1,
    "journal-segment.schema.json": JournalSegmentV1,
    "journal-attachment.schema.json": JournalAttachmentV1,
    "journal-entry.schema.json": JournalEntryRecordV1,
    "journal-alignment.schema.json": JournalAlignmentV1,
    "journal-operation-result.schema.json": JournalOperationResultV1,
    "market-archive-draft.schema.json": MarketArchiveDraftV1,
    "market-archive-preview.schema.json": MarketArchivePreviewV1,
    "market-archive-result.schema.json": MarketArchiveResultV1,
    "market-archive-comparison.schema.json": MarketArchiveComparisonV1,
    "prematch-risk-watchlist.schema.json": PrematchRiskWatchlistV1,
    "match-data-bundle.schema.json": MatchDataBundleV1,
    "market-observation.schema.json": MarketObservationEventV1,
    "fixture-fact-observation.schema.json": FixtureFactObservationV1,
    "match-result-observation.schema.json": MatchResultObservationV1,
    "lock-candidate-receipt.schema.json": LockCandidateReceiptV1,
    "lifecycle-action.schema.json": LifecycleAction,
    "analysis-draft-input.schema.json": AnalysisDraftInput,
    "rule-evaluation-bundle.schema.json": EvaluationBundle,
    "reasoning-disposition.schema.json": ReasoningDisposition,
    "experiment-active.schema.json": ActiveExperiment,
    "experiment-advisory-bundle.schema.json": ExperimentAdvisoryBundle,
    "experiment-advisory-disposition.schema.json": ExperimentAdvisoryDisposition,
    "experiment-advisory-outcome.schema.json": ExperimentAdvisoryOutcome,
    "experiment-advisory-receipt.schema.json": ExperimentAdvisoryReceipt,
    "experiment-calibration-config.schema.json": ExperimentCalibrationConfig,
    "experiment-analysis-receipt.schema.json": ExperimentAnalysisReceipt,
    "experiment-evaluation-bundle.schema.json": ExperimentEvaluationBundle,
    "experiment-outlook.schema.json": ExperimentOutlook,
    "experiment-prediction-receipt.schema.json": ExperimentPredictionReceipt,
    "experiment-outcome.schema.json": ExperimentOutcome,
    "live-experiment-input.schema.json": LiveExperimentInput,
    "live-experiment-receipt.schema.json": LiveExperimentReceipt,
}


def _schema(name: str, model: type[BaseModel] | TypeAdapter) -> str:
    data = model.json_schema() if isinstance(model, TypeAdapter) else model.model_json_schema()
    data["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    data["$id"] = f"https://odds-journal.local/schemas/{name}"
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def build_schemas(root: Path, *, check: bool = False) -> list[Path]:
    schema_root = root / "schemas"
    changed: list[Path] = []
    for name, model in SCHEMA_MODELS.items():
        path = schema_root / name
        expected = _schema(name, model)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != expected:
            changed.append(path)
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8", newline="\n")
    if check and changed:
        raise ValueError("JSON Schema 与模型不一致：" + ", ".join(path.name for path in changed))
    return changed
