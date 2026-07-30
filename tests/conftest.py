from __future__ import annotations

from pathlib import Path
import shutil

import pytest


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    repository = Path(__file__).resolve().parents[1]
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "match.md").write_text(
        (repository / "templates" / "match.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "data").mkdir()
    for name in ("team_aliases.yml", "competition_aliases.yml"):
        (tmp_path / "data" / name).write_text(
            (repository / "data" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    shutil.copytree(repository / "knowledge" / "rulesets", tmp_path / "knowledge" / "rulesets")
    validation_frameworks = repository / "knowledge" / "validation" / "frameworks"
    if validation_frameworks.exists():
        shutil.copytree(
            validation_frameworks,
            tmp_path / "knowledge" / "validation" / "frameworks",
        )
    source = tmp_path / "knowledge" / "sources" / "doubao-2026-07-28"
    source.mkdir(parents=True)
    shutil.copy2(
        repository / "knowledge" / "sources" / "doubao-2026-07-28" / "原始学习合集.md",
        source / "原始学习合集.md",
    )
    (tmp_path / "docs").mkdir()
    shutil.copy2(
        repository / "docs" / "项目改造与AI分析接入方案.md",
        tmp_path / "docs" / "项目改造与AI分析接入方案.md",
    )
    (tmp_path / "ai").mkdir()
    for name in ("analysis_prompt.md", "review_prompt.md"):
        shutil.copy2(repository / "ai" / name, tmp_path / "ai" / name)
    return tmp_path
