---
schema_version: 4
document_id: tg-extreme-under-context-v1
document_type: heuristic
title: 极端小球场景实验规则
rule_version: 1.7.0
reliability: experimental
status: active
effective_at: null
evidence_level: low
evidence_snapshot: {as_of: '2026-08-04T16:00:00+08:00', eligible_independent_cases: 0, support: 0, counterexample: 0, ambiguous: 0, ledger_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}
source_atom_ids: []
evidence_provenance: gap
scenario_type_ids: []
promotion_reviewed_by: null
markets: [total_goals]
phases: [prematch]
tags: [双轨实验, 极端小球, 赛事场景]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第三级-极端小球}]
index: true
---
# 极端小球场景实验规则
## 目的和适用范围
2.5 小球低水稳定并具备防守型与保守赛事场景时生成 0-1 球候选。
## 术语
杯赛首回合和保级战必须来自精确赛事事实，不按名称猜测。
## 必需输入
2.5 小球三节点、球队攻防数据和赛事阶段。
## 数据质量要求
三项必须同时可核验；联赛标签不能替代球队数据。
## 逐步执行过程
机器检查盘口阈值，AI确认球队与赛事语义，再处置区间。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 三项均满足 | triggered/hybrid |
| 盘口满足但场景缺失 | insufficient_data |
## 双向假设
保守场景可能压低节奏，也可能因早球打开空间。
## 区分触发条件
阵容、战意来源和跨机构小球一致性用于区分。
## 跨市场冲突优先级
只生成实验总进球与比分候选。
## 失效和 Pass 条件
基本面时点不明或盘口不稳定时失效。
## 支持案例
当前无合格案例。
## 反例
双方定位球或反击效率高为反证。
## Source Atom 与声明引用
来源为 evidence gap intake。
## 证据快照
零样本。
## 版本变更说明
将对称补充规则纳入混合判定。
