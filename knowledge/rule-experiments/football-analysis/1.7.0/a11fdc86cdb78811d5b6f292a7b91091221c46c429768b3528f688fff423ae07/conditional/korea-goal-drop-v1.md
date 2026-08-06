---
schema_version: 4
document_id: korea-goal-drop-v1
document_type: heuristic
title: 韩国联赛大球下滑实验
rule_version: 1.7.0
reliability: experimental
status: active
effective_at: null
evidence_level: low
evidence_snapshot:
  as_of: '2026-08-04T16:00:00+08:00'
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
- total_goals
phases:
- prematch
- live
- postmatch
tags:
- 韩国
- 大小球
- experimental
source_refs:
- kind: local
  locator: docs/规则提案映射-1.3.0.md
  anchor: 段落 19
index: true
---
# 韩国联赛大球下滑实验

## 目的和适用范围

仅对韩国 K1/K2 profile 记录头部机构大球水位显著下滑的实验信号。

## 术语

韩国 profile 由 competition code 白名单确定，不由球队名称猜测。

## 必需输入

韩国赛事代码、澳门香港盘 opening/mid/late 节点和大球水位。

## 数据质量要求

三个节点必须同机构同市场，水位格式必须为香港盘。

## 逐步执行过程

计算 opening 到 late 的单向下滑；达到配置阈值时只生成总进球/比分候选。

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
| 大球水位单向下滑 >= 0.20 | 进球区间上调候选 | 不改变胜平负 |

## 双向假设

真实进球预期上升与单机构报价调整均需保留。

## 区分触发条件

多机构同步、总进球跨档、让球盘是否支持。

## 跨市场冲突优先级

基础总进球分析和事实高于本规则。

## 失效和 Pass 条件

非韩国 profile、节点不足或格式错误时 `not_applicable` 或 `insufficient_data`。

## 支持案例

暂无合格独立案例。

## 反例

水位下滑但低比分时记录为反例。

## Source Atom 与声明引用

候选来源见 `docs/规则提案映射-1.3.0.md`。

## 证据快照

当前合格独立案例为 0，保持 experimental。

## 版本变更说明

1.4.0 明确该规则不得写入胜平负或固定让球排序。
