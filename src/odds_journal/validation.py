from __future__ import annotations

from pathlib import Path

from .aliases import AliasStore
from .markdown import MatchDocument, has_substantive_content
from .models import MatchStatus
from .paths import match_files


def validate_document(document: MatchDocument, aliases: AliasStore) -> list[str]:
    errors: list[str] = []
    metadata = document.metadata
    status = MatchStatus(metadata.status)

    if not aliases.has_team(metadata.home_team_id):
        errors.append(f"未知主队 ID：{metadata.home_team_id}")
    if not aliases.has_team(metadata.away_team_id):
        errors.append(f"未知客队 ID：{metadata.away_team_id}")
    if not aliases.has_competition(metadata.competition_code):
        errors.append(f"未知联赛代码：{metadata.competition_code}")

    errors.extend(f"图片不存在：{target}" for target in document.broken_images())

    lock_exists = bool(metadata.prematch_lock_sha256)
    if status in {MatchStatus.LOCKED, MatchStatus.FINISHED, MatchStatus.REVIEWED} or lock_exists:
        for name in ("prematch-facts", "prematch-reasoning", "prematch-locked"):
            if "TODO:replace-before-lock" in document.sections[name]:
                errors.append(f"锁定章节仍包含待填写标记：{name}")
            if not has_substantive_content(document.sections[name]):
                errors.append(f"锁定章节缺少有效内容：{name}")
        current_hash = document.prematch_hash()
        if metadata.prematch_lock_sha256 != current_hash:
            errors.append("赛前锁定内容已变化，哈希校验失败")

    if status == MatchStatus.FINISHED and not has_substantive_content(document.sections["result"]):
        errors.append("finished 比赛缺少赛果正文")
    if status == MatchStatus.REVIEWED:
        if not has_substantive_content(document.sections["result"]):
            errors.append("reviewed 比赛缺少赛果正文")
        if "TODO:replace-before-review" in document.sections["postmatch-review"]:
            errors.append("复盘章节仍包含待填写标记")
        if not has_substantive_content(document.sections["postmatch-review"], minimum=20):
            errors.append("reviewed 比赛缺少有效复盘正文")
    return errors


def validate_all(root: Path) -> dict[Path, list[str]]:
    aliases = AliasStore(root)
    results: dict[Path, list[str]] = {}
    seen_ids: dict[str, Path] = {}
    for path in match_files(root):
        try:
            document = MatchDocument.load(path)
            errors = validate_document(document, aliases)
            previous = seen_ids.get(document.metadata.match_id)
            if previous:
                errors.append(f"match_id 与 {previous} 重复")
            else:
                seen_ids[document.metadata.match_id] = path
        except Exception as exc:
            errors = [str(exc)]
        results[path] = errors

    all_ids = set(seen_ids)
    for path in match_files(root):
        try:
            document = MatchDocument.load(path)
        except Exception:
            continue
        previous_id = document.metadata.supersedes_match_id
        if previous_id and previous_id not in all_ids:
            results[path].append(f"supersedes_match_id 不存在：{previous_id}")

    alias_errors = aliases.validate_uniqueness()
    if alias_errors:
        results[root / "data"] = alias_errors
    return results
