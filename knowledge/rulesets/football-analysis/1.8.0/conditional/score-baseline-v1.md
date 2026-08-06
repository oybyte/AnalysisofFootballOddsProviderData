---
schema_version: 4
document_id: score-baseline-v1
document_type: heuristic
title: 比分候选基线实验
rule_version: 1.8.0
reliability: experimental
status: active
effective_at: '2026-08-06T09:24:16+08:00'
evidence_level: low
evidence_snapshot:
  as_of: '2026-08-06T09:24:16+08:00'
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
- handicap
- total_goals
phases:
- prematch
- live
- postmatch
tags:
- 比分
- 候选覆盖
- experimental
source_refs:
- kind: local
  locator: docs/规则提案映射-1.3.0.md
  anchor: 段落 18
index: true
---
# 比分候选基线实验

## 目的和适用范围

为比分候选提供覆盖基线，不把比分模板当作方向结论。

## 术语

比分候选是最终两个可审计剧本，不是精确概率承诺。

## 必需输入

胜平负、让球、总进球区间、赔率和阵容事实。

## 数据质量要求

候选必须与总进球区间和让球结果可结算地一致。

## 逐步执行过程

先生成市场独立候选，再用本规则检查低赔和浅盘覆盖，最终从候选池采纳恰好两个。

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
| 主胜赔率 <= 1.60 | 将 1-0/2-0 纳入候选池 | 不强制选入最终两个 |
| 平半及以下且低赔 < 2.00 | 保留一球分差小球剧本 | 需符合总进球区间 |

## 双向假设

低赔小胜基线与极端赛果/对攻剧本均需保留。

## 区分触发条件

总进球档位、让球深度、双方进球事实和临场反转。

## 跨市场冲突优先级

主市场和总进球区间高于比分模板。

## 失效和 Pass 条件

主市场为 pass 或总进球区间缺失时不得生成比分。

## 支持案例

暂无合格独立案例。

## 反例

低赔条件下大比分或客胜时记录为反例。

## Source Atom 与声明引用

候选来源见 `docs/规则提案映射-1.3.0.md`。

## 证据快照

当前合格独立案例为 0，保持 experimental。

## 版本变更说明

1.4.0 明确本规则只能生成比分候选，不能改变市场排序。
