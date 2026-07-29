from __future__ import annotations

import json
from pathlib import Path

from .aliases import AliasStore
from .markdown import MatchDocument
from .paths import match_files
from .validation import validate_document


class ExportError(ValueError):
    pass


def document_payload(document: MatchDocument, root: Path) -> dict:
    return {
        "schema_version": 1,
        "source_path": document.path.relative_to(root).as_posix(),
        "metadata": document.metadata.model_dump(mode="json"),
        "sections": document.sections,
    }


def export_matches(root: Path, *, skip_invalid: bool = False) -> tuple[int, list[str]]:
    output_dir = root / "data" / "matches"
    output_dir.mkdir(parents=True, exist_ok=True)
    aliases = AliasStore(root)
    exported = 0
    diagnostics: list[str] = []
    for path in match_files(root):
        try:
            document = MatchDocument.load(path)
            errors = validate_document(document, aliases)
            if errors:
                raise ExportError("；".join(errors))
            target = output_dir / f"{document.metadata.match_id}.json"
            target.write_text(
                json.dumps(document_payload(document, root), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            exported += 1
        except Exception as exc:
            message = f"{path}: {exc}"
            diagnostics.append(message)
            if not skip_invalid:
                raise ExportError(message) from exc
    return exported, diagnostics

