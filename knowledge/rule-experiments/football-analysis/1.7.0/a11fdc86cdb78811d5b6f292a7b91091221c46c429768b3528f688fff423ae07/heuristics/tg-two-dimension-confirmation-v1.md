---
schema_version: 4
document_id: tg-two-dimension-confirmation-v1
document_type: heuristic
title: 两个独立维度确认控制规则
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
markets: [total_goals, pass]
phases: [prematch]
tags: [双轨实验, 独立血缘, 控制规则]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 多维度交叉验证体系}]
index: true
---
# 两个独立维度确认控制规则
## 目的和适用范围
只有至少两个独立数据维度同向时才把实验方向标记为共识。
## 术语
独立维度按 provider、market、line 与证据血缘区分。
## 必需输入
前序实验事件的方向、影响面和 independence keys。
## 数据质量要求
同源欧赔和凯利不得重复计数。
## 逐步执行过程
聚合同向触发事件，按独立维度去重后与阈值比较。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 至少两个独立维度同向 | consensus |
| 少于两个 | not_triggered |
## 双向假设
同向可能是真共识，也可能是共同数据源重复，必须审计血缘。
## 区分触发条件
不同市场与不同证据 ID 才可增强独立性。
## 跨市场冲突优先级
控制规则不得创建方向，只确认已有候选。
## 失效和 Pass 条件
血缘缺失时不能计为独立支持。
## 支持案例
当前无合格案例。
## 反例
欧赔与凯利同源重复为明确反例。
## Source Atom 与声明引用
来源为未 atom 化用户 intake。
## 证据快照
零样本。
## 版本变更说明
将“至少两维共振”代码化为去重门禁。
