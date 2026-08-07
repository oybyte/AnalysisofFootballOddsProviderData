---
schema_version: 4
document_id: tg-late-shock-guard-v1
document_type: heuristic
title: 临场水位剧变保护规则
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
tags: [双轨实验, 临场异常, 控制规则]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 临场动态校准}]
index: true
---
# 临场水位剧变保护规则
## 目的和适用范围
标记开赛前 60 分钟的水位剧变，避免将单点异动自动升级为方向。
## 术语
保护规则只产生 control 事件。
## 必需输入
同档相邻临场节点及带时区时间。
## 数据质量要求
时间必须处于赛前窗口，节点必须同源可比。
## 逐步执行过程
计算最后两节点绝对变化，达到阈值时触发异常保护。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 60分钟内变化至少0.10 | triggered/control |
| 窗口外 | not_triggered |
## 双向假设
可能是资金冲击，也可能是新信息重定价，两者均需保留。
## 区分触发条件
多机构同步和可核验新闻可支持重定价，否则保持未验证。
## 跨市场冲突优先级
不得单独改变总进球主区间。
## 失效和 Pass 条件
缺捕获时间、跨档或赛后节点失效。
## 支持案例
当前无合格案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源为未 atom 化用户 intake。
## 证据快照
零样本。
## 版本变更说明
将临场校准改为非方向性保护事件。
