---
schema_version: 4
document_id: tg-line-drop-over-price-divergence-v1
document_type: heuristic
title: 降盘与大球价格背离实验规则
rule_version: 1.6.0
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
tags: [双轨实验, 总进球, 显式覆盖]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第一级-降盘诱大}]
index: true
---
# 降盘与大球价格背离实验规则
## 目的和适用范围
盘口至少下调一档而大球价格未同步收紧时生成小球实验候选。
## 术语
`when_triggered` 只在完整触发时压制旧的总进球降盘解释。
## 必需输入
同机构开盘与临盘的总进球 line、大球水位、格式和时间。
## 数据质量要求
不得跨机构拼接盘口与水位，不得推断资金来源。
## 逐步执行过程
计算 line drop 与大球水位变化，使用 Contract 5 严格比较符并写覆盖事件。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 降盘达阈值且大球微跌以内或上升 | triggered/under |
| 只满足一项 | not_triggered |
## 双向假设
假设 A 为低门槛吸收大球；假设 B 为真实进球预期下调。
## 区分触发条件
后续水位与跨机构方向用于 AI 处置，代码不预设因果。
## 跨市场冲突优先级
仅覆盖显式声明的旧分析规则，不覆盖数据门禁、锁定和结算。
## 失效和 Pass 条件
缺少同源开临盘或盘口格式不明时 insufficient_data。
## 支持案例
当前无合格独立案例。
## 反例
降盘后大球同步大幅降水为反向候选。
## Source Atom 与声明引用
来源尚未 atom 化，标记 evidence gap。
## 证据快照
零样本，不具发布资格。
## 版本变更说明
新增内容寻址双轨覆盖语义。
