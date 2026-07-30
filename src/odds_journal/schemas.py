from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .analysis_context import AnalysisReceipt
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


SCHEMA_MODELS: dict[str, type[BaseModel] | Any] = {
    "match.schema.json": MatchMetadata,
    "analysis-outlook.schema.json": AnalysisOutlook,
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
