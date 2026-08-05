---
schema_version: 4
document_id: draw-kelly-parity-v1
document_type: heuristic
title: 凯利收敛与平局风险实验
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
- one_x_two
phases:
- prematch
- live
- postmatch
tags:
- 凯利
- 平局
- experimental
source_refs:
- kind: local
  locator: docs/规则提案映射-1.3.0.md
  anchor: 段落 2、5、11、13
index: true
---
# 凯利收敛与平局风险实验

## 目的和适用范围

在三项凯利收敛且热门承压时记录平局风险，只用于实验性排序校准。

## 术语

- 凯利差值是三项归一化凯利的最大值减最小值。
- 平权候选不等于平局第一顺位。

## 必需输入

- 澳门欧赔和凯利 opening/mid/late 三节点。
- 热门身份未切换。
- 基础胜平负排序。

## 数据质量要求

所有节点必须带 provider、时间、原始字符串、格式和归一化值；同源欧赔与凯利只计一个独立来源。

## 逐步执行过程

1. 计算三项凯利最大差值。
2. 按配置中的严格比较符判断实验层级。
3. 保存支持、反证和未触发原因。
4. 不改变基础第一顺位。

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
| 差值 <= 0.02 | 记录平权候选 | 不直接改锚 |
| 差值 <= 0.03 且热门承压 | 平局风险上调一级 | 需独立反证 |
| 差值 <= 0.05 且低稳定性 profile | 进入实验校准 | 不得泛化 |

## 双向假设

假设 A 为真实概率收敛；假设 B 为同源市场噪声。两者均需证据与反证。

## 区分触发条件

三节点稳定、热门身份稳定、欧赔和亚盘是否同步。

## 跨市场冲突优先级

基础排序高于本实验，事实和理论定位高于凯利解释。

## 失效和 Pass 条件

节点缺失、身份切换、格式错误或时间超界时记录 `insufficient_data`。

## 支持案例

暂无合格独立案例。

## 反例

凯利收敛但主线命中且平局未命中时保留为反例。

## Source Atom 与声明引用

候选来源见 `docs/规则提案映射-1.3.0.md`。

## 证据快照

当前合格独立案例为 0，保持 experimental。

## 版本变更说明

新增凯利收敛和平局风险实验规则。
