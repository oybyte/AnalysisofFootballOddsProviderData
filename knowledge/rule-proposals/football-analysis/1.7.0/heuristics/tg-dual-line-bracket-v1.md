---
schema_version: 4
document_id: tg-dual-line-bracket-v1
document_type: heuristic
title: 双层盘口夹击区间实验规则
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
tags: [双轨实验, 多层盘口, AI处置]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第一级-双层夹击}]
index: true
---
# 双层盘口夹击区间实验规则
## 目的和适用范围
同机构同时间窗口的 2.5 与 3.5 盘口形成上下界时生成整数众数候选。
## 术语
多层盘口必须来自同机构且时间窗口可比。
## 必需输入
低档大球水位、高档小球趋势和节点时间。
## 数据质量要求
禁止跨机构拼接；高档小球必须有可计算趋势。
## 逐步执行过程
机器提取阈值事实，AI确认是否构成夹击并处置区间。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 低档超低水且高档小球降水 | triggered/hybrid |
| 缺任一层 | insufficient_data |
## 双向假设
假设 A 为中间整数聚集；假设 B 为两端独立定价。
## 区分触发条件
多机构重复结构支持 A，孤立单机构支持 B。
## 跨市场冲突优先级
只写总进球池和比分池。
## 失效和 Pass 条件
盘口时间窗口不重叠或格式不同即失效。
## 支持案例
当前无合格案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源为 evidence gap intake。
## 证据快照
零样本。
## 版本变更说明
新增机器事实加 AI 语义确认。
