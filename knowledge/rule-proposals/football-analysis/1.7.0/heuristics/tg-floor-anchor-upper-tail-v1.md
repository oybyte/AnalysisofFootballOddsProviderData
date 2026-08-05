---
schema_version: 4
document_id: tg-floor-anchor-upper-tail-v1
document_type: heuristic
title: 下限锚定与上限松动实验规则
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
tags: [双轨实验, 尾部区间, 多层盘口]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第二级-下限焊死加上限松动}]
index: true
---
# 下限锚定与上限松动实验规则
## 目的和适用范围
识别 2.5 大球低水稳定与 3.5 上限松动的组合，保留高进球尾部风险。
## 术语
尾部风险不等于主区间，也不进入正式预测。
## 必需输入
同机构 2.5 与 3.5 多层盘口时序。
## 数据质量要求
低档稳定需可计算回撤，高档需有头部或跨机构支持。
## 逐步执行过程
机器提取下限与上限信号，AI填写主区间、众数和尾部。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 下限锚定且上限松动 | triggered/hybrid |
| 仅下限 | excluded 或普通大球候选 |
## 双向假设
可能是高尾部真实扩张，也可能是高档流动性噪声。
## 区分触发条件
多机构持续性支持尾部，单点反向支持噪声。
## 跨市场冲突优先级
尾部可与唯一主区间并存，不得形成第二主区间。
## 失效和 Pass 条件
缺多层盘口或时间不可比时 insufficient_data。
## 支持案例
当前无合格案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源为 evidence gap intake。
## 证据快照
零样本。
## 版本变更说明
新增尾部风险结构。
