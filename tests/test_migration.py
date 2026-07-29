from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml


def test_archived_sources_match_manifest() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "knowledge" / "sources" / "doubao-2026-07-28"
    manifest = yaml.safe_load((source / "MANIFEST.yml").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        path = source / record["archived_name"]
        assert path.stat().st_size == record["size"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]


def test_all_archived_image_references_resolve() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "knowledge" / "sources" / "doubao-2026-07-28"
    text = (source / "原始图文学习合集.md").read_text(encoding="utf-8")
    targets = re.findall(r"^!\[图片]\((images/[^)]+)\)", text, re.MULTILINE)
    assert len(targets) == 215
    assert all((source / target).exists() for target in targets)


def test_archived_image_inventory_digest() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "knowledge" / "sources" / "doubao-2026-07-28"
    manifest = yaml.safe_load((source / "MANIFEST.yml").read_text(encoding="utf-8"))
    rows = []
    for path in sorted((source / "images").iterdir(), key=lambda item: item.name):
        rows.append(f"{path.name}|{path.stat().st_size}|{hashlib.sha256(path.read_bytes()).hexdigest()}")
    inventory = ("\n".join(rows) + "\n").encode("utf-8")
    assert hashlib.sha256(inventory).hexdigest() == manifest["images"]["inventory_sha256"]

