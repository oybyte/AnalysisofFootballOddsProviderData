---
schema_version: 4
document_id: tg-away-collapse-prior-v1
document_type: heuristic
title: 客场崩盘属性先验实验规则
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
tags: [双轨实验, 基本面先验, 时点数据]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第三级-客场崩盘}]
index: true
---
# 客场崩盘属性先验实验规则
## 目的和适用范围
带时间来源的客场防守排名与主场进攻排名只作为极端大球先验修正。
## 术语
“客场虫”不是机器事实，必须拆为可核验排名和历史大败记录。
## 必需输入
赛前可见的联赛排名、样本窗口、主客场拆分与来源。
## 数据质量要求
不得从赛果或盘口反推球队属性。
## 逐步执行过程
机器检查标签化事实是否存在，AI审查样本与时效后采用或排除。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 排名和历史记录完整 | triggered/hybrid |
| 缺时间来源 | insufficient_data |
## 双向假设
客队可能早丢后崩盘，也可能因样本回归而保持韧性。
## 区分触发条件
阵容、近期对手质量和盘口共振用于区分。
## 跨市场冲突优先级
不得单独生成方向或百分比确定值。
## 失效和 Pass 条件
排名口径、赛季或时间点不明时失效。
## 支持案例
当前无合格案例。
## 反例
客队近期对强队防守稳定为反证。
## Source Atom 与声明引用
来源为 evidence gap intake。
## 证据快照
零样本。
## 版本变更说明
移除自动 5%-10% 权重，改为 AI 先验候选。
