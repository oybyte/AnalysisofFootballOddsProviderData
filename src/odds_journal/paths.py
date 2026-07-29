from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("未找到项目根目录（缺少 pyproject.toml）")


def match_files(root: Path) -> list[Path]:
    matches = root / "matches"
    if not matches.exists():
        return []
    return sorted(matches.glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/*.md"))

