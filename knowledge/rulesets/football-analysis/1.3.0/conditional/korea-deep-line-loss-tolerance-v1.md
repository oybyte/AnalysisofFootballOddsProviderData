---
schema_version: 3
document_id: korea-deep-line-loss-tolerance-v1
document_type: heuristic
title: 韩国深盘输球容错实验
rule_version: 1.3.0
reliability: experimental
status: active
effective_at: '2026-08-03T00:20:21+08:00'
evidence_level: low
evidence_snapshot:
  as_of: '2026-08-03T00:20:21+08:00'
  eligible_independent_cases: 0
  support: 0
  counterexample: 0
  ambiguous: 0
  ledger_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
source_atom_ids: []
scenario_type_ids: []
promotion_reviewed_by: null
markets:
- one_x_two
- handicap
phases:
- prematch
- live
- postmatch
tags:
- 韩国
- 深盘
- 输球容错
- experimental
source_refs:
- kind: local
  locator: docs/规则提案映射-1.3.0.md
  anchor: 段落 19
index: true
---
# 韩国深盘输球容错实验

## 目的和适用范围

仅对韩国 K1/K2 profile 扩展深盘示弱时的直接输球风险剧本。

## 术语

深盘为一球及以上；示弱必须由水位和凯利反向共同定义。

## 必需输入

韩国赛事代码、澳门香港盘和凯利 opening/mid/late 节点。

## 数据质量要求

盘口、凯利、时间和机构必须可核验；不使用盘口推断未记录的伤停或资金。

## 逐步执行过程

确认深度、高水和凯利反向后，将直接输球加入风险候选，不覆盖基础主线。

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
| 韩国 profile 且一球以上深盘示弱 | 增加直接输球候选 | 不自动改让胜第一 |

## 双向假设

深盘示弱可能是真实实力反转，也可能是风险管理噪声。

## 区分触发条件

后续降档、欧赔/凯利同步、阵容事实和临场延续。

## 跨市场冲突优先级

基础事实、理论盘和基础排序高于本实验。

## 失效和 Pass 条件

非韩国 profile、节点不足、盘口格式错误或凯利不完整时不触发。

## 支持案例

暂无合格独立案例。

## 反例

示弱后主队大胜时记录为反例。

## Source Atom 与声明引用

候选来源见 `docs/规则提案映射-1.3.0.md`。

## 证据快照

当前合格独立案例为 0，保持 experimental。

## 版本变更说明

新增韩国深盘直接输球风险实验。
