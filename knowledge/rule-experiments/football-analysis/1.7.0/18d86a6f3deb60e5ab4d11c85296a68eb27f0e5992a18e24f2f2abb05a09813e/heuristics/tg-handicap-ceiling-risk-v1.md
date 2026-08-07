---
schema_version: 4
document_id: tg-handicap-ceiling-risk-v1
document_type: heuristic
title: 让球退盘与总进球上限风险规则
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
markets: [handicap, total_goals]
phases: [prematch]
tags: [双轨实验, 让球上限, 风险池]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第一级-亚盘上限}]
index: true
---
# 让球退盘与总进球上限风险规则
## 目的和适用范围
热门方让球退浅且水位承压时生成上限风险，不自动否定大球。
## 术语
上限风险属于 outcome_risk_pool。
## 必需输入
同机构亚洲让球 opening/late line 与热门方水位。
## 数据质量要求
盘口符号须从主队视角标准化。
## 逐步执行过程
检测退盘与水位承压事实，再由 AI 判断是否影响总进球上限。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 退浅达阈值且水位不降 | triggered/risk |
| 盘口走深 | not_triggered |
## 双向假设
可能是热门方上限受限，也可能是资金再平衡。
## 区分触发条件
欧赔与总进球同向才增强采用理由。
## 跨市场冲突优先级
让球风险不能直接改写胜平负或正式结论。
## 失效和 Pass 条件
盘口方向不清或跨机构比较时失效。
## 支持案例
当前无合格案例。
## 反例
退盘后欧赔继续强力支持热门方为反证候选。
## Source Atom 与声明引用
来源为 evidence gap intake。
## 证据快照
零样本。
## 版本变更说明
将强结论降级为可处置风险候选。
