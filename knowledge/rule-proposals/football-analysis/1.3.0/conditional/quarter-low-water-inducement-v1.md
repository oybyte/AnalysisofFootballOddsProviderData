---
schema_version: 3
document_id: quarter-low-water-inducement-v1
document_type: heuristic
title: 半球平半低水诱盘实验
rule_version: 1.3.0
reliability: experimental
status: active
effective_at: null
evidence_level: low
evidence_snapshot: {as_of: '2026-08-02T00:00:00+08:00', eligible_independent_cases: 0, support: 0, counterexample: 0, ambiguous: 0, ledger_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}
source_atom_ids: []
scenario_type_ids: []
promotion_reviewed_by: null
markets: [handicap, one_x_two]
phases: [prematch, live, postmatch]
tags: [低水, 诱盘, experimental]
source_refs: [{kind: local, locator: docs/规则提案映射-1.3.0.md, anchor: 段落 15}]
index: true
---
# 半球平半低水诱盘实验

## 目的和适用范围

记录浅盘低水与欧亚背离的诱盘风险，不直接改变主线。

## 术语

低水阈值必须从机器配置读取，不能使用未登记的口语阈值。

## 必需输入

澳门香港盘、欧赔、凯利和三个可比节点。

## 数据质量要求

同机构同盘口比较；欧赔与凯利同源时标记相关。

## 逐步执行过程

核对盘口深度、低水阈值、欧赔方向和凯利收敛，再登记 risk。

## 判断矩阵

| 条件 | 动作 | 边界 |
|---|---|---|
| 半球低水且欧赔背离 | 诱盘风险 | 不直接改第一顺位 |
| 平半低水且凯利无优势 | 下盘风险提示 | 保留双向假设 |

## 双向假设

可能是低水阻上，也可能是热门吸收；两者均需反证。

## 区分触发条件

后续档位是否站稳、凯利是否同步、跨机构是否确认。

## 跨市场冲突优先级

事实、理论定位和基础排序高于实验风险。

## 失效和 Pass 条件

低水阈值未登记、节点不足或格式未知时不触发。

## 支持案例

暂无合格独立案例。

## 反例

低水背离后主线命中时记录为反例。

## Source Atom 与声明引用

候选来源见 `docs/规则提案映射-1.3.0.md`。

## 证据快照

当前合格独立案例为 0，保持 experimental。

## 版本变更说明

新增浅盘低水诱盘风险实验。
