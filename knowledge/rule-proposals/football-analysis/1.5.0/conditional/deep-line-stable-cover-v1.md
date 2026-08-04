---
schema_version: 4
document_id: deep-line-stable-cover-v1
document_type: heuristic
title: 深盘稳盘穿盘实验
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
- handicap
phases:
- prematch
- live
- postmatch
tags:
- 深盘
- 稳盘
- experimental
source_refs:
- kind: local
  locator: docs/规则提案映射-1.3.0.md
  anchor: 段落 14
index: true
---
# 深盘稳盘穿盘实验

## 目的和适用范围

识别深盘稳定和同档降水的 cover support，只调整实验性让球排序。

## 术语

深盘指一球及以上；稳盘指节点间档位不变且无回调。

## 必需输入

同机构澳门香港盘 opening/mid/late、基础让球排序和水位原值。

## 数据质量要求

必须是同机构、同市场、同盘口、三个可比节点；跨档不得计算同档水位变化。

## 逐步执行过程

记录深度、节点和水位方向；达到配置阈值时输出 `cover support`。

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
| 一球及以上同档三节点，水位均在 0.80-0.95 | 记录稳盘信号 | 不自动让胜第一 |
| 半一同档降至 <= 0.70 且无回调 | 让胜候选上调一级 | 单规则不得越锚 |

## 双向假设

真实实力重估与风险管理/热度吸收必须同时保留。

## 区分触发条件

跨机构同步、后续站稳、欧赔和凯利是否共振。

## 跨市场冲突优先级

基础排序和事实高于稳盘实验信号。

## 失效和 Pass 条件

少于三个节点、发生回调或盘口格式不明时不触发。

## 支持案例

暂无合格独立案例。

## 反例

稳盘但赢球不穿时记录为反例。

## Source Atom 与声明引用

候选来源见 `docs/规则提案映射-1.3.0.md`。

## 证据快照

当前合格独立案例为 0，保持 experimental。

## 版本变更说明

1.4.0 固化深盘合理水位区间与半一单向降水门槛。
