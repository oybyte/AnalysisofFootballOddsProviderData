---
schema_version: 4
document_id: tg-one-sided-overrun-risk-v1
document_type: heuristic
title: 单边碾压式大球风险规则
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
markets: [handicap, one_x_two, total_goals]
phases: [prematch]
tags: [双轨实验, 异常盘, 尾部风险]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第三级-碾压式大球}]
index: true
---
# 单边碾压式大球风险规则
## 目的和适用范围
三项前置同时满足时生成单边大比分尾部候选，不改写正式主线。
## 术语
三项为 2.5 大球低水稳定、热门方深盘阻上、平局凯利冲突事实。
## 必需输入
总进球、亚洲让球与凯利三个市场的赛前可比节点。
## 数据质量要求
至少两个独立血缘维度，且凯利语义必须由 AI 处置。
## 逐步执行过程
机器核验三项事实，AI判断是否为单边结构并填写尾部与比分。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 三项同时满足 | triggered/anomalous |
| 少一项 | not_triggered |
## 双向假设
可能为热门方单边大胜，也可能为受热后的阻上假象。
## 区分触发条件
欧赔热门方支撑与弱队进攻能力用于区分。
## 跨市场冲突优先级
只写实验总进球、比分与风险池。
## 失效和 Pass 条件
任一市场缺时序或血缘重复时不完整。
## 支持案例
当前无合格案例。
## 反例
弱队持续具备进球支持时反对“零封”叙事。
## Source Atom 与声明引用
来源为 evidence gap intake。
## 证据快照
零样本。
## 版本变更说明
将极端场景改为三条件联合候选。
