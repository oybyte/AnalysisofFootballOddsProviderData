---
schema_version: 4
document_id: advisory-total-water-boundaries-pack-v1
document_type: heuristic
title: 总进球绝对水位与边界提示包
rule_version: 1.6.0
reliability: experimental
status: active
effective_at: null
evidence_level: low
evidence_snapshot: {as_of: '2026-08-05T00:00:00+08:00', eligible_independent_cases: 0, support: 0, counterexample: 0, ambiguous: 0, ledger_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855}
source_atom_ids: []
evidence_provenance: gap
scenario_type_ids: []
promotion_reviewed_by: null
markets: [total_goals, one_x_two]
phases: [prematch]
tags: [实验提示, 总进球, 绝对水位, 夹击]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-05_全赛事总进球绝对水位夹击边界平局联动与环境修正规则.md, anchor: 全文}]
index: true
---
# 总进球绝对水位与边界提示包

## 目的和适用范围
在 2.5 球盘口上提示绝对水位分级、2.5/3.0 边界和平局联动；不生成进球区间、比分或方向。
## 术语
阈值采用仓库现有水位口径；非 2.5 盘口不换算，2.5 与 3.0 仅用于并列展示而不跨档相减。
## 必需输入
同机构、同格式的 2.5 球水位；夹击另需 3.0 球水位；环境条款另需天气和半中立事实。
## 数据质量要求
缺报价、存在冲突或非标准盘口必须 `insufficient_data`；天气和场地没有可追溯事实时不得触发。
## 逐步执行过程
读取初始 2.5 球大球水位，按阈值给出等级；分别检查 3.0 边界与正式平局主选择，并保留人工处置。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 2.5 球水位达到明确阈值 | warning |
| 非 2.5 或边界输入不全 | insufficient_data |
| 平局为正式第一顺位 | info 复核 |
## 双向假设
绝对水位可能代表报价风险，也可能是市场平衡；平局与进球的解释均需人工选择。
## 区分触发条件
只比较同机构、同档位、同赔率格式的节点；夹击两档只并列展示。
## 跨市场冲突优先级
提示不改变正式胜平负，也不写入总进球池、比分候选或置信度。
## 失效和 Pass 条件
非 2.5 阈值自动换算、跨档水位差、赛后数据或未解决冲突全部失效。
## 支持案例
当前无合格独立案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源为未可信化 intake，尚无 source atom 或 claim；`evidence_provenance: gap`。
## 证据快照
零样本，不可晋级为 supported。
## 版本变更说明
revision 3 新增仅提示的绝对水位与边界检查。
