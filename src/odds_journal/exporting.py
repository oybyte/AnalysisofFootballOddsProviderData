from __future__ import annotations

import json
import shutil
import uuid
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
    aliases = AliasStore(root)
    payloads: dict[str, dict] = {}
    diagnostics: list[str] = []
    for path in match_files(root):
        try:
            document = MatchDocument.load(path)
            errors = validate_document(document, aliases)
            if errors:
                raise ExportError("；".join(errors))
            if document.metadata.match_id in payloads:
                raise ExportError(f"match_id 重复：{document.metadata.match_id}")
            payloads[document.metadata.match_id] = document_payload(document, root)
        except Exception as exc:
            message = f"{path}: {exc}"
            diagnostics.append(message)
            if not skip_invalid:
                raise ExportError(message) from exc
    if diagnostics and skip_invalid:
        return len(payloads), diagnostics

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_dir.parent / f"matches.tmp-{uuid.uuid4().hex}"
    backup = output_dir.parent / f"matches.backup-{uuid.uuid4().hex}"
    temporary.mkdir()
    try:
        for match_id, payload in sorted(payloads.items()):
            (temporary / f"{match_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        for path in temporary.glob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))
        if output_dir.exists():
            output_dir.replace(backup)
        temporary.replace(output_dir)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if output_dir.exists() and backup.exists():
            shutil.rmtree(output_dir)
        if backup.exists():
            backup.replace(output_dir)
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return len(payloads), diagnostics
