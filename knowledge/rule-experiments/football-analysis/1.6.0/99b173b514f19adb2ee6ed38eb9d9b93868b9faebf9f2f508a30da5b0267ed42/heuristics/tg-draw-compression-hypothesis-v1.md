---
schema_version: 4
document_id: tg-draw-compression-hypothesis-v1
document_type: heuristic
title: 平局凯利双假设实验规则
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
markets: [one_x_two, total_goals]
phases: [prematch]
tags: [双轨实验, 凯利, 双向假设]
source_refs: [{kind: local, locator: knowledge/rule-proposals/intake/2026-08-04_总进球分析分级判定清单固化版.md, anchor: 第二级-平局压缩分胜负}]
index: true
---
# 平局凯利双假设实验规则
## 目的和适用范围
平凯利稳定且最低时，同时保留“防范平局”与“平局被压缩”两个互斥解释。
## 术语
代码只识别事实，不预设低凯利的方向语义。
## 必需输入
同机构凯利三项 opening/mid/late 时序及相关欧赔血缘。
## 数据质量要求
平凯利稳定阈值为唯一机器配置；同源欧赔凯利不得重复计数。
## 逐步执行过程
提取最低项、稳定度与主客收敛事实，强制 AI 采用一个解释或全部排除。
## 判断矩阵
| 条件 | 处置 |
|---|---|
| 平凯利最低且波动达稳定阈值 | triggered/hybrid |
| AI 未处置 | 校验失败 |
## 双向假设
假设 A：低凯利代表机构防范平局。假设 B：最新规则认为平局被压缩、胜负极化。
## 区分触发条件
亚洲让球深浅、欧赔方向和跨机构一致性用于判别。
## 跨市场冲突优先级
该规则无 supersedes，不覆盖既有平局凯利规则。
## 失效和 Pass 条件
凯利来源或时序不足时 insufficient_data。
## 支持案例
当前无合格案例。
## 反例
两个解释均无跨市场支持时应全部排除。
## Source Atom 与声明引用
来源为 evidence gap intake。
## 证据快照
零样本。
## 版本变更说明
将冲突解释固化为双假设 AI 处置。
