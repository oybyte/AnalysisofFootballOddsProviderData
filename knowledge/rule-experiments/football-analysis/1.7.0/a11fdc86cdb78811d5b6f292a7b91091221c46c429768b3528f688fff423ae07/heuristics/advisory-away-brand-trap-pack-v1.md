---
schema_version: 4
document_id: advisory-away-brand-trap-pack-v1
document_type: heuristic
title: 客场强队名气诱盘提示包
rule_version: 1.7.0
reliability: experimental
status: active
effective_at: null
evidence_level: low
evidence_snapshot: {as_of: '2026-08-05T00:00:00+08:00', eligible_independent_cases: 0, support: 0, counterexample: 0, ambiguous: 0, ledger_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}
source_atom_ids: []
evidence_provenance: gap
scenario_type_ids: []
promotion_reviewed_by: null
markets: [handicap, one_x_two]
phases: [prematch]
tags: [实验提示, 客场强队, 名气风险]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-05_客场强队名气型诱盘五步前置排查与风险分级规则.md, anchor: 全文}]
index: true
---
# 客场强队名气诱盘提示包

## 目的和适用范围
为五步客场强队名气风险排查保留独立人工提示，不得因球队名称、名气或赔率自动生成方向。
## 术语
名气、交锋和交易热度都是外部事实，不得从盘口数值、赛果或队名反推。
## 必需输入
赛事阶段、可追溯球队实力与交锋事实、交易或热度数据，以及同市场赛前盘口。
## 数据质量要求
任何一个关键外部事实缺失均为 `insufficient_data`；未结构化的描述不当作可验证输入。
## 逐步执行过程
逐项显示五步风险覆盖状态；满足事实门槛后仅生成 warning，由人工确认或驳回。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 五步事实完整且风险项达到阈值 | warning |
| 外部事实缺失 | insufficient_data |
| 风险项不足 | not_triggered |
## 双向假设
客场强队可能被名气高估，也可能有真实实力支撑；提示不预设任何一个解释。
## 区分触发条件
需要独立来源的球队与交易事实，不能由同一盘口来源循环证明。
## 跨市场冲突优先级
不改变让球、胜平负、总进球、比分、排序或正式锁定。
## 失效和 Pass 条件
只有名气标签、缺赛前事实或赛后补录时，必须停止提示结论。
## 支持案例
当前无合格独立案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源为未可信化 intake，尚无 source atom 或 claim；`evidence_provenance: gap`。
## 证据快照
零样本，不可晋级为 supported。
## 版本变更说明
revision 3 新增风险覆盖提示，不加入实验预测候选池。
