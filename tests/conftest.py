from __future__ import annotations

from pathlib import Path

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
    return tmp_path

