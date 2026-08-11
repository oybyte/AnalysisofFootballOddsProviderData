"""复盘 → 证据 → 实验轨 自动化流水线。

阶段1: auto_extract_evidence_from_review — 从复盘内容中自动提取规则反例/支持案例
阶段2: check_evidence_thresholds — 监控证据累积，检查晋级阈值
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .evidence import EvidencePayload, append_evidence
from .ledger import read_ledger
from .markdown import MatchDocument, FRONT_MATTER_RE
from .models import MatchStatus
from .paths import match_files

REVIEW_CONTENT_START = "<!-- review-content:start -->"
REVIEW_CONTENT_END = "<!-- review-content:end -->"

# 匹配 "规则反例" 或 "六、规则反例" 章节标题
RULE_COUNTEREXAMPLES_HEADING = re.compile(
    r"#{1,4}\s*(?:六|七|八|九|十)?[、.]?\s*规则反例"
)
# 匹配 "规则支持案例" 或 "支持案例" 章节标题
RULE_SUPPORT_HEADING = re.compile(
    r"#{1,4}\s*(?:六|七|八|九|十)?[、.]?\s*(?:规则)?支持案例"
)
# 匹配 "可复用教训" 章节标题
LESSONS_HEADING = re.compile(
    r"#{1,4}\s*(?:六|七|八|九|十)?[、.]?\s*可复用教训"
)
# 匹配列表项中的规则 ID：**xxx（rule-id）** 或 **rule-id**
RULE_ID_IN_LIST = re.compile(
    r"\*\*[^*]*?（(rule-v\d+|advisory-v\d+|[a-z][a-z0-9-]*v\d+)）\*\*"
)
# 匹配下一章节标题（用于截断当前章节）
NEXT_HEADING = re.compile(r"^#{1,4}\s+")


def _extract_rule_refs(text: str, heading_pattern: re.Pattern) -> list[tuple[str, str]]:
    """从章节文本中提取 (rule_id, description) 列表。"""
    results: list[tuple[str, str]] = []
    # 找到章节起始位置
    match = heading_pattern.search(text)
    if not match:
        return results
    start = match.end()
    # 找到下一个章节标题作为结束位置
    remaining = text[start:]
    next_match = NEXT_HEADING.search(remaining)
    if next_match:
        section = remaining[: next_match.start()]
    else:
        section = remaining
    # 在章节中提取所有 rule_id
    for m in RULE_ID_IN_LIST.finditer(section):
        rule_id = m.group(1)
        # 尝试提取该列表项的完整描述
        list_start = m.start()
        # 向前找到当前列表项的开始
        line_start = section.rfind("\n", 0, list_start)
        if line_start == -1:
            line_start = 0
        else:
            line_start += 1
        # 向后找到下一个列表项或章节结束
        next_item = re.search(r"\n\d+\.\s+", section[m.end():])
        if next_item:
            line_end = m.end() + next_item.start()
        else:
            line_end = len(section)
        description = section[line_start:line_end].strip()
        # 清理列表标记
        description = re.sub(r"^\d+\.\s+", "", description).strip()
        results.append((rule_id, description))
    return results


def _review_content(review: str) -> str:
    """提取 review-content 标记之间的内容。"""
    start_idx = review.find(REVIEW_CONTENT_START)
    if start_idx == -1:
        return ""
    start_idx += len(REVIEW_CONTENT_START)
    end_idx = review.find(REVIEW_CONTENT_END, start_idx)
    if end_idx == -1:
        return ""
    return review[start_idx:end_idx].strip()


def _fixture_cluster_id(document: MatchDocument) -> str:
    """基于比赛属性生成 fixture cluster ID。"""
    meta = document.metadata
    parts = [
        str(meta.competition_code or "unknown"),
        str(meta.season or "unknown"),
        str(meta.home_team_id or "unknown"),
        str(meta.away_team_id or "unknown"),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _market_from_review_context(description: str) -> Literal["one_x_two", "handicap", "total_goals", "pass"]:
    """从反例描述中推断市场类型。"""
    desc_lower = description.lower()
    if any(kw in desc_lower for kw in ["handicap", "盘口", "让球", "穿盘", "亚盘", "亚*", "盘", "升盘", "降盘", "回盘"]):
        return "handicap"
    if any(kw in desc_lower for kw in ["one_x_two", "胜平负", "欧赔", "主胜", "客胜", "平局", "平赔"]):
        return "one_x_two"
    if any(kw in desc_lower for kw in ["total_goals", "总进球", "大小球", "进球"]):
        return "total_goals"
    return "pass"


def _target_baseline_from_description(description: str) -> tuple[str, str]:
    """从反例描述中提取 target_definition 和 baseline_definition。"""
    # 移除 rule_id 部分
    cleaned = RULE_ID_IN_LIST.sub("", description).strip()
    # 查找 "≠" / "不应" / "实际" 等关键词来分离 target 和 baseline
    if "≠" in cleaned:
        parts = cleaned.split("≠", 1)
        target = parts[0].strip().rstrip("：:。，,")
        baseline = parts[1].strip().rstrip("：:。，,")
        return target[:200], baseline[:200]
    if "不" in cleaned and "应" in cleaned:
        idx = cleaned.find("不应")
        if idx > 0:
            target = cleaned[:idx].strip().rstrip("：:。，,")
            baseline = cleaned[idx:].strip().rstrip("：:。，,")
            if len(target) > 10 and len(baseline) > 5:
                return target[:200], baseline[:200]
    # 默认：取前 200 字符作为 target，后 200 字符作为 baseline
    mid = len(cleaned) // 2
    return cleaned[:mid].strip()[:200], cleaned[mid:].strip()[:200]


def _existing_evidence_ids(root: Path) -> set[str]:
    """获取已存在的 evidence_id 集合，用于去重（从活跃记录的 payload 中提取）。"""
    path = root / "knowledge/evidence/rule-evidence.jsonl"
    if not path.exists():
        return set()
    events = read_ledger(path)
    superseded = {event.supersedes_event_id for event in events if event.supersedes_event_id}
    active = [event for event in events if event.event_id not in superseded]
    ids: set[str] = set()
    for event in active:
        try:
            payload = EvidencePayload.model_validate(event.payload)
            ids.add(payload.evidence_id)
        except Exception:
            pass
    return ids


def auto_extract_evidence_from_review(
    root: Path, path: Path, *, recorded_at: datetime | None = None
) -> list[EvidencePayload]:
    """从复盘内容中自动提取规则反例和规则支持案例，生成证据记录。

    仅处理 MatchStatus.REVIEWED 的比赛文件。
    生成的证据标记 extraction_source: "auto-extracted"。
    """
    document = MatchDocument.load(path)
    if MatchStatus(document.metadata.status) != MatchStatus.REVIEWED:
        return []
    review = document.sections.get("postmatch-review", "")
    if not review:
        return []
    content = _review_content(review)
    if not content:
        return []
    if recorded_at is None:
        recorded_at = datetime.now().astimezone()
    if recorded_at.tzinfo is None:
        raise ValueError("证据记录时间必须包含时区")

    existing_ids = _existing_evidence_ids(root)
    match_id = document.metadata.match_id
    cluster_id = _fixture_cluster_id(document)
    # 从分析追踪中获取锁定规则集版本
    try:
        from .analysis_context import parse_receipt
        receipt = parse_receipt(document.sections.get("prematch-reasoning", ""))
        observed_version = receipt.ruleset_version if receipt else "1.8.0"
    except Exception:
        observed_version = "1.8.0"

    # 从 locked ruleset 获取规则内容哈希
    try:
        from .rules import load_ruleset
        ruleset = load_ruleset(root, f"football-analysis@{observed_version}")
    except Exception:
        ruleset = None

    def _get_rule_hashes(rule_id: str) -> tuple[str | None, str | None]:
        """获取规则的 content_sha256 和 proposal_sha256。"""
        if ruleset and rule_id in ruleset.documents:
            return ruleset.documents[rule_id].content_sha256, None
        # 校准规则：检查是否在 calibration_events 中
        if document.metadata.analysis_outlook:
            for event in document.metadata.analysis_outlook.calibration_events or []:
                if event.rule_id == rule_id:
                    # 校准规则使用 contract_version 生成 proposal_sha256
                    proposal = hashlib.sha256(
                        f"calibration:{rule_id}:contract-{event.contract_version}".encode()
                    ).hexdigest()
                    return None, proposal
        return None, None

    payloads: list[EvidencePayload] = []

    # 提取规则反例
    counterexamples = _extract_rule_refs(content, RULE_COUNTEREXAMPLES_HEADING)
    for rule_id, description in counterexamples:
        evidence_id = f"{match_id}-{rule_id}-counter"
        if evidence_id in existing_ids:
            continue
        rule_content, proposal = _get_rule_hashes(rule_id)
        market = _market_from_review_context(description)
        target, baseline = _target_baseline_from_description(description)
        payloads.append(
            EvidencePayload(
                evidence_id=evidence_id,
                rule_id=rule_id,
                observed_ruleset_version=observed_version if rule_content else None,
                rule_content_sha256=rule_content,
                proposal_sha256=proposal,
                case_type="match",
                case_id=match_id,
                case_cluster_id=cluster_id,
                market=market,
                relation="counterexample",
                eligibility="eligible",
                target_definition=target or "规则反例目标",
                baseline_definition=baseline or "规则反例基线",
                summary=description[:500],
                reviewed_by="system",
                extraction_source="auto-extracted",
            )
        )

    # 提取规则支持案例
    supports = _extract_rule_refs(content, RULE_SUPPORT_HEADING)
    for rule_id, description in supports:
        evidence_id = f"{match_id}-{rule_id}-support"
        if evidence_id in existing_ids:
            continue
        rule_content, proposal = _get_rule_hashes(rule_id)
        market = _market_from_review_context(description)
        target, baseline = _target_baseline_from_description(description)
        payloads.append(
            EvidencePayload(
                evidence_id=evidence_id,
                rule_id=rule_id,
                observed_ruleset_version=observed_version if rule_content else None,
                rule_content_sha256=rule_content,
                proposal_sha256=proposal,
                case_type="match",
                case_id=match_id,
                case_cluster_id=cluster_id,
                market=market,
                relation="support",
                eligibility="eligible",
                target_definition=target or "规则支持目标",
                baseline_definition=baseline or "规则支持基线",
                summary=description[:500],
                reviewed_by="system",
                extraction_source="auto-extracted",
            )
        )

    # 追加到台账
    for payload in payloads:
        append_evidence(root, payload, recorded_at=recorded_at)

    return payloads


# ── 阶段2: 证据累积监控 ──

class EvidenceThreshold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    total_eligible: int
    supports: int
    counterexamples: int
    auto_extracted_pending: int
    threshold_met: bool
    blocking_reason: str | None = None


def _load_active_evidence(root: Path) -> list[EvidencePayload]:
    """加载所有活跃（未被 supersede）的证据记录。"""
    path = root / "knowledge/evidence/rule-evidence.jsonl"
    if not path.exists():
        return []
    events = read_ledger(path)
    superseded = {event.supersedes_event_id for event in events if event.supersedes_event_id}
    active = [event for event in events if event.event_id not in superseded]
    return [EvidencePayload.model_validate(event.payload) for event in active]


def check_evidence_thresholds(
    root: Path,
    *,
    min_eligible: int = 3,
    min_counterexamples: int = 1,
) -> dict[str, EvidenceThreshold]:
    """检查各规则的证据累积状态。

    返回以 rule_id 为键的阈值状态字典。
    """
    all_evidence = _load_active_evidence(root)
    grouped: dict[str, list[EvidencePayload]] = defaultdict(list)
    for item in all_evidence:
        grouped[item.rule_id].append(item)

    thresholds: dict[str, EvidenceThreshold] = {}
    for rule_id, items in sorted(grouped.items()):
        eligible = [item for item in items if item.eligibility == "eligible"]
        auto_pending = sum(
            1 for item in eligible
            if item.extraction_source == "auto-extracted" and item.reviewed_by == "system"
        )
        relation_counts = Counter(item.relation for item in eligible)
        total = len(eligible)
        supports = relation_counts.get("support", 0)
        counterexamples = relation_counts.get("counterexample", 0)

        blocking_reasons: list[str] = []
        threshold_met = True

        if total < min_eligible:
            threshold_met = False
            blocking_reasons.append(f"eligible 证据不足（{total}/{min_eligible}）")
        if counterexamples < min_counterexamples:
            threshold_met = False
            blocking_reasons.append(f"counterexample 不足（{counterexamples}/{min_counterexamples}）")
        if auto_pending > 0:
            threshold_met = False
            blocking_reasons.append(f"有 {auto_pending} 条自动提取证据待 lcz 审核")

        blocking_reason = "；".join(blocking_reasons) if blocking_reasons else None

        thresholds[rule_id] = EvidenceThreshold(
            rule_id=rule_id,
            total_eligible=total,
            supports=supports,
            counterexamples=counterexamples,
            auto_extracted_pending=auto_pending,
            threshold_met=threshold_met,
            blocking_reason=blocking_reason,
        )

    return thresholds


def pipeline_status(root: Path) -> dict[str, Any]:
    """返回完整流水线状态摘要。"""
    thresholds = check_evidence_thresholds(root)
    ready = {
        rule_id: status
        for rule_id, status in thresholds.items()
        if status.threshold_met
    }
    pending = {
        rule_id: status
        for rule_id, status in thresholds.items()
        if not status.threshold_met and status.total_eligible > 0
    }
    return {
        "total_rules_with_evidence": len(thresholds),
        "ready_for_promotion": len(ready),
        "ready_rules": list(ready.keys()),
        "accumulating_rules": {
            rule_id: {
                "total_eligible": status.total_eligible,
                "blocking_reason": status.blocking_reason,
            }
            for rule_id, status in pending.items()
        },
        "all_thresholds": [
            status.model_dump(mode="json") for status in thresholds.values()
        ],
    }