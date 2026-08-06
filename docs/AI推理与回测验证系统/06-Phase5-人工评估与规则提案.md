# Phase 5：人工评估与规则提案

## 赛后 Outcome 和人工处置

只对已封存且开赛前合格的 AI Outlook 生成 `AIExperimentOutcomeV1`。结算由代码从冻结预测、冻结盘口和已确认赛果派生：

```yaml
outcome_id: string
outlook_id: string
evaluation_algorithm_version: string
result_event_id: string
result_source_sha256: string
actual_result: {score, one_x_two, total_goals}
market_outcomes:
  one_x_two: correct | incorrect | not_evaluated
  asian_handicap: {frozen_line, settlement}
  fixed_handicap_1x2: {frozen_home_line, outcome}
  total_goals: correct | incorrect | not_evaluated
  score: correct | incorrect | not_evaluated
```

人工错误分类只能通过追加式 `AIExperimentDispositionEventV1` 记录 `outcome_id`、处置人、时间、错误类别、说明和反证引用。它不得改写 Outcome 或结算结果。

## 研究报告

`ai experiment report` 只以已预注册 Study 为范围，默认过滤：

```text
run_role=primary
stale=false
study_eligible=true
sample_relation=out_of_sample
```

报告按市场、联赛、模块 capability profile 分别展示：可判定场次、pass 率、评估数、结算分布、支持、反例和不适用记录。diagnostic、pilot、`in_sample`、`unknown` 仅作独立可运行性或研究摘要，不进入这个命中率分母。

## 到规则提案的边界

AI 结果永远不能直接产生活动规则、修改规则 evidence snapshot 或发布正式版本。如果人工从研究中发现值得验证的模式，仍必须经过既有流程：

```text
rules intake ingest -> inspect -> scaffold -> proposal-validate
  -> lcz experiment activation -> shadow evidence -> release approval
```

规则提案需要可追溯的原始声明、原子处置、独立数据血缘、反证条件和新 revision 测试。AI 仅能作为人工输入来源，不能替代此管道。
