---
schema_version: 4
document_id: advisory-deep-line-goal-trap-pack-v1
document_type: heuristic
title: 深盘大球风险提示包
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
markets: [handicap, total_goals, one_x_two]
phases: [prematch]
tags: [实验提示, 深盘, 大球, 头部机构]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-05_深盘大球诱盘平局双校验与单机构降盘边界规则.md, anchor: 全文}]
index: true
---
# 深盘大球风险提示包

## 目的和适用范围
保存深盘大球、平局双校验与单头部机构降盘边界的风险提醒，不解释资金意图且不影响任何预测输出。
## 术语
深盘、头部机构和资金反向都是待核验输入；“诱盘”仅是待人工评估的假设标签。
## 必需输入
同机构同档位赛前让球和总进球序列、头部机构交叉市场序列，以及可追溯资金或平局权重事实。
## 数据质量要求
资金、机构共识或同档精确时序缺失时必须 `insufficient_data`；不得以单一静态盘口替代。
## 逐步执行过程
分开检查深盘、平局和头部机构条件；缺少任何前置事实时保留缺失原因，绝不补推。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 完整风险条件与来源齐备 | warning |
| 同档或资金数据不足 | insufficient_data |
| 条件未达阈值 | not_triggered |
## 双向假设
深盘可能反映真实差距，也可能吸收热门风险；必须由独立事实和人工处置区分。
## 区分触发条件
让球、总进球和欧赔只能在各自市场内作比较，并明确来源血缘。
## 跨市场冲突优先级
不压制既有 12 条实验规则，不改写正式排序、总进球、比分、锁定或结算。
## 失效和 Pass 条件
资金因果未验证、跨机构拼接、跨档水位差或赛后材料均为失效条件。
## 支持案例
当前无合格独立案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源为未可信化 intake，尚无 source atom 或 claim；`evidence_provenance: gap`。
## 证据快照
零样本，不可晋级为 supported。
## 版本变更说明
revision 3 新增深盘风险提示包，固定 `official_effect: none`。
