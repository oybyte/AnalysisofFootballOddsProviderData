---
schema_version: 4
document_id: advisory-initial-water-guard-pack-v1
document_type: heuristic
title: 初始水位守盘提示包
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
markets: [total_goals]
phases: [prematch, postmatch]
tags: [实验提示, 初始水位, 守盘]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-05_初始水位守盘校验大热方进球传导与复盘偏差规则.md, anchor: 全文}]
index: true
---
# 初始水位守盘提示包

## 目的和适用范围
将初始绝对水位守盘检查、大热主队进球传导和赛后偏差尺度拆为独立提示；不得生成预测、候选池或置信度。
## 术语
“初始”是同机构同档位最早可核验的赛前节点；“守盘”只描述可见报价，不推断资金或控赔原因。
## 必需输入
2.5 球同机构同格式水位；趋势检查另需三个 exact 节点。大热传导需要交易、热度和阵容事实。
## 数据质量要求
跨机构、跨档位或 phase_only 节点不能作趋势触发；资金、热度和阵容缺失必须 `insufficient_data`。
## 逐步执行过程
先检查 2.5 球初始水位，再检查同档三节点；大热传导条款单独等待外部事实，赛后偏差只记录研究结论。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 初始低水且三 exact 节点可比 | warning 或 not_triggered |
| 节点或外部事实缺失 | insufficient_data |
| 赛后偏差 | 仅 advisory outcome |
## 双向假设
低水可能反映持续风险重定价，也可能是一般报价调整；任何资金归因保持 `unverified`。
## 区分触发条件
仅同机构、同档位、同赔率格式的赛前完整序列可用于比较。
## 跨市场冲突优先级
不覆盖任何正式或实验预测规则；只向人工展示警示和反证要求。
## 失效和 Pass 条件
非 2.5 盘口、三节点不足、冲突未解决或赛后才出现的数据均不触发赛前提示。
## 支持案例
当前无合格独立案例。
## 反例
当前无冻结反例。
## Source Atom 与声明引用
来源为未可信化 intake，尚无 source atom 或 claim；`evidence_provenance: gap`。
## 证据快照
零样本，不可晋级为 supported。
## 版本变更说明
revision 3 新增 warning-only 提示包，与 12 条预测实验规则隔离。
