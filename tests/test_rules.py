from __future__ import annotations

from pathlib import Path

from odds_journal.rules import canonical_text, load_ruleset, sha256_text, validate_rules


def test_ruleset_has_required_and_experimental_boundaries(project_root: Path) -> None:
    ruleset = load_ruleset(project_root)
    assert len(ruleset.required) == 10
    assert len(ruleset.conditional) == 4
    assert all(item.metadata.reliability == "experimental" for item in ruleset.conditional)
    settlement = ruleset.documents["market-settlement-rules"].body
    assert "赢/走/输" in settlement
    assert "赢/输一半/输" in settlement
    assert ruleset.documents["market-settlement-rules"].metadata.reliability == "supported"


def test_canonical_hash_is_independent_of_line_endings() -> None:
    assert canonical_text("a\r\nb\r\n") == "a\nb\n"
    assert sha256_text("a\r\nb\r\n") == sha256_text("a\nb\n")


def test_rule_validation_detects_duplicate_document_id(project_root: Path) -> None:
    original = next((project_root / "knowledge" / "rulesets").glob("**/methods/*.md"))
    duplicate = project_root / "knowledge" / "duplicated.md"
    duplicate.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
    errors = validate_rules(project_root)
    assert any("document_id" in error and "重复" in error for error in errors[duplicate])
