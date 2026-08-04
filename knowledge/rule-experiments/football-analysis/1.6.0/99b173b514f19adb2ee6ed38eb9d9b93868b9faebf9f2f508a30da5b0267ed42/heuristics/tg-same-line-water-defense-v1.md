---
schema_version: 4
document_id: tg-same-line-water-defense-v1
document_type: heuristic
title: 同档水位持续下滑实验规则
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
tags: [双轨实验, 总进球, 同档水位]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第一级-守盘控赔}]
index: true
---
# 同档水位持续下滑实验规则

## 目的和适用范围
识别同机构、同盘口档位、赛前 opening/mid/late 三节点的单向水位下滑，只生成实验总进球候选。
## 术语
同档指 provider、market、line、odds_format 一致；阈值以 Contract 5 为准。
## 必需输入
同机构三个赛前节点、原始水位、采集时间与来源。
## 数据质量要求
节点必须早于开赛；缺资金数据时 `causal_attribution: unverified`。
## 逐步执行过程
按同档分组，计算净变化与回撤，满足阈值后生成方向候选并等待处置。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 三节点且累计下降达阈值 | triggered |
| 节点缺失 | insufficient_data |
| 未达阈值 | not_triggered |
## 双向假设
假设 A 为持续风险重定价；假设 B 为资金再平衡，禁止代码自动宣称控赔。
## 区分触发条件
跨机构同向与无回调支持 A；临场孤立异动支持 B。
## 跨市场冲突优先级
只影响总进球池，不覆盖正式市场或治理门禁。
## 失效和 Pass 条件
跨机构、跨档、跨格式比较或赛后节点均失效。
## 支持案例
当前无合格独立案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源原文尚未完成 atom/claim 迁移，`evidence_provenance: gap`。
## 证据快照
零样本，保持 experimental。
## 版本变更说明
1.6.0 首次进入双轨实验。
