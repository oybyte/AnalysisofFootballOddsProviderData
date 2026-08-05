"""Repository-owned smoke checks for the eleven Codex Desktop scenarios.

The synchronizer records this module's immutable subprocess output.  Broader
behavioural coverage still runs in the normal full pytest preflight.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = yaml.safe_load((ROOT / "integrations/certification/scenarios.yml").read_text(encoding="utf-8"))
SKILL = (ROOT / "integrations/skills/football-odds-journal/SKILL.md").read_text(encoding="utf-8")
GOVERNANCE = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
CLI = (ROOT / "src/odds_journal/cli.py").read_text(encoding="utf-8")


def _scenario(scenario_id: str) -> None:
    assert scenario_id in SCENARIOS["required_scenario_ids"]


def test_extraction_only() -> None:
    _scenario("extraction-only")
    assert "journal new" in SKILL and "do not add predictions" in GOVERNANCE


def test_governed_analysis() -> None:
    _scenario("governed-analysis")
    assert "agent start MATCH_PATH" in SKILL and "agent validate-draft" in SKILL


def test_degraded_or_pass() -> None:
    _scenario("degraded-or-pass")
    assert "degraded" in GOVERNANCE and "0.69" in GOVERNANCE


def test_failed_gate() -> None:
    _scenario("failed-gate")
    assert "Stop on failure" in SKILL


def test_postmatch_review() -> None:
    _scenario("postmatch-review")
    assert "journal finish" in SKILL and "prepare-review" in GOVERNANCE


def test_long_text_storage() -> None:
    _scenario("long-text-storage")
    assert "journal append" in SKILL and "用户材料归档" in GOVERNANCE


def test_historical_result_completion() -> None:
    _scenario("historical-result-completion")
    assert "finish-historical" in GOVERNANCE and "historical_finished" in GOVERNANCE


def test_low_stability_calibration() -> None:
    _scenario("low-stability-calibration")
    assert "single rule cannot change the baseline first choice" in GOVERNANCE


def test_normalized_market_bundle() -> None:
    _scenario("normalized-market-bundle")
    assert "journal finish --bundle" in (ROOT / "AI_START_HERE.md").read_text(encoding="utf-8")


def test_incremental_market_monitoring() -> None:
    _scenario("incremental-market-monitoring")
    assert "journal market-archive compare" in SKILL


def test_prematch_lock_readiness() -> None:
    _scenario("prematch-lock-readiness")
    assert "agent readiness" in (ROOT / "AI_START_HERE.md").read_text(encoding="utf-8")
    assert "prepare-lock" in CLI
