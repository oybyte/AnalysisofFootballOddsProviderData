from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from .aliases import AliasStore
from .markdown import MatchDocument
from .models import EvaluationValue, MatchStatus, PrimaryMarket, RecordIntegrity
from .paths import match_files
from .validation import validate_document


def build_match_index(root: Path) -> Path:
    report_path = root / "reports" / "比赛索引.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    grouped: dict[tuple[int, int], list[MatchDocument]] = defaultdict(list)
    for path in match_files(root):
        document = MatchDocument.load(path)
        local = document.metadata.kickoff_at
        grouped[(local.year, local.month)].append(document)
    lines = ["# 比赛索引", ""]
    if not grouped:
        lines.append("当前还没有比赛记录。")
    for (year, month), documents in sorted(grouped.items(), reverse=True):
        lines.extend([f"## {year}-{month:02d}", "", "| 比赛 | 联赛 | 状态 | 主市场 |", "|---|---|---|---|"])
        for document in sorted(documents, key=lambda item: item.metadata.kickoff_at):
            link = Path("..") / document.path.relative_to(root)
            label = f"{document.metadata.home_team} vs {document.metadata.away_team}"
            lines.append(
                f"| [{label}]({link.as_posix()}) | {document.metadata.competition} | "
                f"{document.metadata.status} | {document.metadata.primary_market or '-'} |"
            )
        lines.append("")
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return report_path


def _rate_text(counter: Counter) -> str:
    denominator = counter["correct"] + counter["wrong"] + counter["partial"]
    if denominator < 10:
        return f"样本不足（n={denominator}）"
    return f"{counter['correct'] / denominator:.1%}（严格正确 {counter['correct']}/{denominator}）"


def _inclusive_rate_text(counter: Counter) -> str:
    denominator = counter["correct"] + counter["wrong"] + counter["partial"]
    if denominator < 10:
        return f"样本不足（n={denominator}）"
    return f"{(counter['correct'] + counter['partial']) / denominator:.1%}（含部分命中）"


def build_statistics(root: Path) -> tuple[Path, Path, dict]:
    aliases = AliasStore(root)
    market_counts: dict[str, Counter] = defaultdict(Counter)
    confidence_counts: dict[str, Counter] = defaultdict(Counter)
    dimension_counts: dict[str, Counter] = defaultdict(Counter)
    competition_counts: dict[str, Counter] = defaultdict(Counter)
    month_counts: dict[str, Counter] = defaultdict(Counter)
    tag_counts: dict[str, Counter] = defaultdict(Counter)
    changed_counts = Counter()
    v2_data_modes = Counter()
    v2_outcomes = Counter()
    reviewed = 0
    passes = 0
    excluded = Counter()

    for path in match_files(root):
        try:
            document = MatchDocument.load(path)
        except Exception:
            excluded["invalid"] += 1
            continue
        metadata = document.metadata
        if MatchStatus(metadata.status) == MatchStatus.VOID:
            excluded["void"] += 1
            continue
        if MatchStatus(metadata.status) != MatchStatus.REVIEWED:
            excluded["not_reviewed"] += 1
            continue
        if RecordIntegrity(metadata.record_integrity) != RecordIntegrity.COMPLETE:
            excluded["incomplete"] += 1
            continue
        if validate_document(document, aliases):
            excluded["invalid"] += 1
            continue
        reviewed += 1
        if metadata.schema_version == 2 and metadata.analysis_outlook:
            v2_data_modes[str(metadata.analysis_outlook.data_mode)] += 1
            if metadata.settlement:
                v2_outcomes[f"asian_{metadata.settlement.asian_result}"] += 1
                v2_outcomes[
                    "total_goals_hit" if metadata.settlement.total_goals_range_hit else "total_goals_miss"
                ] += 1
                v2_outcomes[
                    "score_hit" if metadata.settlement.score_candidate_hit else "score_miss"
                ] += 1
        market = str(metadata.primary_market)
        if PrimaryMarket(metadata.primary_market) == PrimaryMarket.PASS:
            passes += 1
            continue
        primary_eval = str(metadata.evaluation.primary)
        market_counts[market][primary_eval] += 1
        for dimension in ("primary", "handicap", "total_goals_range", "score_range"):
            value = str(getattr(metadata.evaluation, dimension))
            if value not in {"pending", "not_applicable"}:
                dimension_counts[dimension][value] += 1
        competition_counts[metadata.competition_code][primary_eval] += 1
        month_counts[metadata.kickoff_at.strftime("%Y-%m")][primary_eval] += 1
        for tag in metadata.tags:
            tag_counts[tag][primary_eval] += 1
        if metadata.confidence is not None:
            lower = min(int(metadata.confidence * 10) / 10, 0.9)
            bucket = f"{lower:.1f}-{lower + 0.09:.2f}"
            confidence_counts[bucket][primary_eval] += 1
        if metadata.live_update_changed_main is not None:
            changed_counts["changed" if metadata.live_update_changed_main else "unchanged"] += 1
            if primary_eval == EvaluationValue.CORRECT:
                changed_counts["correct"] += 1

    payload = {
        "schema_version": 1,
        "reviewed_matches": reviewed,
        "pass_matches": passes,
        "excluded": dict(excluded),
        "markets": {market: dict(counts) for market, counts in market_counts.items()},
        "confidence_bins": {bucket: dict(counts) for bucket, counts in confidence_counts.items()},
        "evaluation_dimensions": {name: dict(counts) for name, counts in dimension_counts.items()},
        "by_competition": {name: dict(counts) for name, counts in competition_counts.items()},
        "by_month": {name: dict(counts) for name, counts in month_counts.items()},
        "by_tag": {name: dict(counts) for name, counts in tag_counts.items()},
        "pass_coverage": passes / reviewed if reviewed else None,
        "live_updates": dict(changed_counts),
        "v2_data_modes": dict(v2_data_modes),
        "v2_outcomes": dict(v2_outcomes),
    }
    report_dir = root / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "统计报告.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    coverage = f"{passes / reviewed:.1%}" if reviewed else "无样本"
    lines = [
        "# 统计报告", "", f"- 已完成复盘：{reviewed}", f"- 主动 pass：{passes}",
        f"- pass 覆盖率：{coverage}", "", "## 分市场表现", "",
    ]
    if not market_counts:
        lines.append("暂无可统计比赛。")
    for market, counts in sorted(market_counts.items()):
        lines.extend(
            [
                f"### {market}",
                "",
                f"- 严格正确率：{_rate_text(counts)}",
                f"- 包含部分命中率：{_inclusive_rate_text(counts)}",
                f"- 正确：{counts['correct']}；部分正确：{counts['partial']}；错误：{counts['wrong']}",
                "",
            ]
        )
    lines.extend(["## 置信度校准", ""])
    if not confidence_counts:
        lines.append("暂无足够数据。")
    for bucket, counts in sorted(confidence_counts.items()):
        lines.append(f"- {bucket}：{_rate_text(counts)}")
    lines.extend(["", "## 分维度表现", ""])
    if not dimension_counts:
        lines.append("暂无可统计维度。")
    for name, counts in sorted(dimension_counts.items()):
        lines.append(f"- {name}：{_rate_text(counts)}；{_inclusive_rate_text(counts)}")
    lines.extend(["", "## 分组表现", ""])
    for label, groups in (("联赛", competition_counts), ("月份", month_counts), ("标签", tag_counts)):
        if not groups:
            lines.append(f"- {label}：暂无数据")
            continue
        for name, counts in sorted(groups.items()):
            lines.append(f"- {label}/{name}：{_rate_text(counts)}")
    lines.extend(["", "## V2 四层输出", ""])
    if v2_data_modes:
        lines.append(f"- 数据模式：{dict(v2_data_modes)}")
        lines.append(f"- 自动结算：{dict(v2_outcomes)}")
    else:
        lines.append("暂无 V2 reviewed 比赛。")
    lines.extend(["", "## 排除记录", ""])
    if excluded:
        for reason, count in sorted(excluded.items()):
            lines.append(f"- {reason}：{count}")
    else:
        lines.append("无。")
    markdown_path = report_dir / "统计报告.md"
    markdown_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    return markdown_path, json_path, payload
