from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .analysis_context import ANALYSIS_END, ANALYSIS_START, analysis_is_placeholder
from .ledger import atomic_write_text
from .markdown import MatchDocument
from .models import MatchStatus
from .rules import sha256_text


LOCKED_CONCLUSION_PLACEHOLDER = """## 三、赛前最终结论

<!-- TODO:replace-before-lock -->

- 主线方向：
- 次选方向：
- 放弃分析条件：
- 总进球区间：
- 比分区间：
- 置信度依据：
- 最大风险：
- 保留的反例：
"""


def restart_analysis(path: Path, *, reason: str, restarted_at: datetime) -> Path:
    document = MatchDocument.load(path)
    status = MatchStatus(document.metadata.status)
    kickoff_passed = (
        document.metadata.kickoff_at is not None
        and restarted_at >= document.metadata.kickoff_at
    )
    if status == MatchStatus.LOCKED:
        if kickoff_passed:
            raise ValueError("比赛已开赛，无法重启分析")
        was_locked = True
    elif status in {MatchStatus.DRAFT, MatchStatus.TRACKING}:
        was_locked = False
    else:
        raise ValueError("只有 draft/tracking 或未开赛的 locked 比赛可以重启分析")
    if not reason.strip():
        raise ValueError("重启分析必须填写原因")
    reasoning = document.sections["prematch-reasoning"]
    if analysis_is_placeholder(reasoning) and "rules-retrieval:start" not in reasoning:
        raise ValueError("当前没有需要归档和重启的分析上下文")
    root = path.resolve().parent
    for candidate in (root, *root.parents):
        if (candidate / "pyproject.toml").exists():
            root = candidate
            break
    else:
        raise ValueError("无法定位项目根目录")
    locked_conclusion = document.sections["prematch-locked"]
    digest = sha256_text(reasoning + "\n" + locked_conclusion)
    reason_digest = sha256_text(reason.strip())[:8]
    archive = (
        root
        / "raw/matches"
        / document.metadata.match_id
        / "analysis-drafts"
        / f"{restarted_at:%Y%m%dT%H%M%S}-{digest[:12]}-{reason_digest}.md"
    )
    archived = (
        "---\n"
        f"match_id: {document.metadata.match_id}\n"
        f"restarted_at: {restarted_at.isoformat()}\n"
        f"reason: {reason.strip()}\n"
        f"draft_sha256: {digest}\n"
        "---\n"
        "# 已归档赛前推演\n\n"
        + reasoning.rstrip()
        + "\n\n# 已归档赛前最终结论\n\n"
        + locked_conclusion.rstrip()
        + "\n"
    )
    current = path.read_bytes()
    if archive.exists():
        raise ValueError(f"分析草稿归档已存在，拒绝覆盖：{archive}")
    atomic_write_text(archive, archived)
    if path.read_bytes() != current:
        archive.unlink(missing_ok=True)
        raise ValueError("归档期间比赛文件已变化，未执行重启")
    reset = (
        "## 二、赛前推演\n\n"
        f"{ANALYSIS_START}\n"
        "<!-- TODO:replace-before-lock -->\n\n"
        "在完成规则、场景和案例检索后填写缺失信息、理论盘口、双向假设、证据、反证和规则引用。\n"
        f"{ANALYSIS_END}\n"
    )
    document.replace_section("prematch-reasoning", reset)
    document.replace_section("prematch-locked", LOCKED_CONCLUSION_PLACEHOLDER)
    if was_locked:
        document.metadata.status = MatchStatus.TRACKING
        document.metadata.primary_selection = None
        document.metadata.secondary_selection = None
        document.metadata.primary_market = None
        document.metadata.confidence = None
        document.metadata.locked_at = None
        document.metadata.prematch_lock_sha256 = None
        document.metadata.analysis_outlook = None
    document.save()
    return archive
