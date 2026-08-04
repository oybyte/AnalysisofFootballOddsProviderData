---
schema_version: 4
document_id: hidden-draw-away-cut-v1
document_type: heuristic
title: 降客隐平实验
rule_version: 1.5.0
reliability: experimental
status: active
effective_at: null
evidence_level: low
evidence_snapshot:
  as_of: '2026-08-03T12:00:00+08:00'
  eligible_independent_cases: 0
  support: 0
  counterexample: 0
  ambiguous: 0
  ledger_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
source_atom_ids: []
evidence_provenance: gap
scenario_type_ids: []
promotion_reviewed_by: null
markets:
- one_x_two
phases:
- prematch
- live
- postmatch
tags:
- 平局
- 隐平
- experimental
source_refs:
- kind: local
  locator: docs/规则提案映射-1.3.0.md
  anchor: 段落 16
index: true
---
# 降客隐平实验

## 目的和适用范围

记录客胜赔率收窄而平局保持稳定时的平局风险。

## 术语

赔率收窄、凯利中位和平赔稳定均按配置比较符计算。

## 必需输入

澳门欧赔、澳门凯利 opening/mid/late 三节点和热门身份。

## 数据质量要求

热门身份不得切换；缺任一数据维度时记录 `insufficient_data`。

## 逐步执行过程

计算客胜变化、客胜凯利区间、平赔相对波动和平局凯利区间；四项均满足后提升平局风险。

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
| 客胜收窄 >= 10% 且凯利 0.90-0.95 | 平局风险上调 | 不直接锁平 |
| 平赔波动 <= 5% 且凯利稳定 | 增加隐平说明 | 需保留反证 |

## 双向假设

客胜吸引搏冷与平局隐性防范均需保留。

## 区分触发条件

平赔后续抬升、凯利离开中位、跨机构是否同步。

## 跨市场冲突优先级

基础胜平负排序高于本实验。

## 失效和 Pass 条件

节点缺失、身份切换、赔率格式错误或变化方向不明确时不触发。

## 支持案例

暂无合格独立案例。

## 反例

条件满足但客胜命中时记录为反例。

## Source Atom 与声明引用

候选来源见 `docs/规则提案映射-1.3.0.md`。

## 证据快照

当前合格独立案例为 0，保持 experimental。

## 版本变更说明

1.4.0 新增平局凯利稳定阈值，仍只生成平局排序候选。
