---
schema_version: 3
document_id: total-goals-cross-market-v1
document_type: heuristic
title: 总进球跨市场实验
rule_version: 1.3.0
reliability: experimental
status: active
effective_at: null
evidence_level: low
evidence_snapshot: {as_of: '2026-08-02T00:00:00+08:00', eligible_independent_cases: 0, support: 0, counterexample: 0, ambiguous: 0, ledger_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}
source_atom_ids: []
scenario_type_ids: []
promotion_reviewed_by: null
markets: [total_goals, handicap, one_x_two]
phases: [prematch, live, postmatch]
tags: [大小球, 跨市场, experimental]
source_refs: [{kind: local, locator: docs/规则提案映射-1.3.0.md, anchor: 段落 6、17}]
index: true
---
# 总进球跨市场实验

## 目的和适用范围

用总进球水位、档位和让球深浅共同调整进球区间，不替代独立大小球分析。

## 术语

大球水位和档位必须是归一化香港盘值。

## 必需输入

总进球、亚洲让球和胜平负 opening/mid/late 节点。

## 数据质量要求

单一机构或单一水位变化不能独立改变区间；盘口格式未知时不触发。

## 逐步执行过程

检查大球绝对水位、单向变化、让球深浅和低赔方，再保存区间调整理由。

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
| 大球水位 <= 0.60 且单向变化 >= 0.20 | 进球区间上调候选 | 需跨市场复核 |
| 浅盘与低赔不支持大球 | 保留 1-2 球区间 | 不得盲目上调 |

## 双向假设

市场共同收敛与让球/总进球维度背离均需保留。

## 区分触发条件

总进球跨档、让球回撤、阵容事实和临场反转。

## 跨市场冲突优先级

总进球市场只能调整总进球和比分，不能单独改变胜平负。

## 失效和 Pass 条件

缺少总进球数据或存在盘口口径冲突时不触发。

## 支持案例

暂无合格独立案例。

## 反例

大球信号后低比分或闷平时记录为反例。

## Source Atom 与声明引用

候选来源见 `docs/规则提案映射-1.3.0.md`。

## 证据快照

当前合格独立案例为 0，保持 experimental。

## 版本变更说明

新增总进球跨市场阈值实验。
