---
schema_version: 1
document_id: ai-review-instruction
document_type: instruction
title: AI 赛后复盘规范
reliability: established
effective_at: 2026-07-29T17:30:51+08:00
trusted_instruction: true
---

# AI 赛后复盘规范

复盘前必须执行 `odds-journal prepare-review MATCH_PATH`，核对赛前锁定内容、锁定时规则集、赛果哈希和场景列表。禁止根据赛果覆盖赛前判断；当前活动规则集只能作为 `postmatch_only` 参考，不能改写旧比赛当时的规则含义。

复盘必须逐个追加 `scenario resolution`，分别评价主线、让球、总进球区间、比分区间和置信度，并将错误归类为数据、概念、逻辑、权重、信息缺失或随机事件。需要同时记录规则的支持、反例、模糊和不适用情况。

只有比赛进入 `reviewed` 后才能执行 `evidence link`。`defer` 项必须进入待处理记录，单场结果不能提升经验规则的可信度，也不能直接修改已发布规则。
