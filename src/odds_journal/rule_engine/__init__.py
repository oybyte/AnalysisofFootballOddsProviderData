"""Contract 4 deterministic rule evaluation.

The module is intentionally isolated from the legacy calibration implementation.
It evaluates traceable market features only; it never invents a baseline direction.
"""

from .evaluation import (
    AnalysisDraftInput,
    EvaluationBundle,
    ReasoningDisposition,
    build_outlook,
    evaluate_draft,
)

__all__ = [
    "AnalysisDraftInput",
    "EvaluationBundle",
    "ReasoningDisposition",
    "build_outlook",
    "evaluate_draft",
]
