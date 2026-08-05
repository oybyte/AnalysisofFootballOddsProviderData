---
schema_version: 4
document_id: tg-head-provider-divergence-nordic-v1
document_type: heuristic
title: 北欧头部机构分歧实验规则
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
tags: [双轨实验, 北欧, 多机构]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第二级-头部机构优先}]
index: true
---
# 北欧头部机构分歧实验规则
## 目的和适用范围
只在注册的北欧 competition code 中识别普通机构多数方向与威廉希尔或立博反向。
## 术语
头部身份由 Contract 5 精确 provider ID 注册，不按名称模糊匹配。
## 必需输入
至少三家普通机构与一个头部机构的同市场可比节点。
## 数据质量要求
每家机构独立形成时序，禁止跨机构拼接。
## 逐步执行过程
计算各机构方向矩阵，提取分歧事实，由 AI 决定采用或排除。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 普通机构达到数量且头部反向 | triggered/hybrid |
| 非北欧 profile | not_applicable |
## 双向假设
头部反向可能表达赔付态度，也可能是报价时间差。
## 区分触发条件
幅度、同步窗口和后续延续用于区分。
## 跨市场冲突优先级
不得默认头部机构永远正确。
## 失效和 Pass 条件
provider 未注册或时间窗口不可比时 insufficient_data。
## 支持案例
当前无合格案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源为 evidence gap intake。
## 证据快照
零样本。
## 版本变更说明
新增北欧精确 profile 和 AI 处置。
