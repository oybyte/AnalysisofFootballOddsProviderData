# Phase 5：人工评估与规则提案

## 第二阶段的核心任务

Phase 5 是连接"AI 实验"和"规则演进"的桥梁。当第一阶段（30 场）发现 AI 在某些场景下系统性优于规则时，进入第二阶段：

### 典型流程

```text
第一阶段结束（30 场对比）
    ↓
发现：AI 在"盘口急变 + 时间紧迫"场景下准确率 78%，规则只有 55%
    ↓
Phase 5：人工分析 AI 成功案例
    ├─ 查看 AIExperimentOutcome（哪些预测对了）
    ├─ 查看 AIExperimentOutlook（AI 的推理依据）
    └─ 提炼模式：发现 AI 综合了"凯利指数分散 + 欧赔方差 + 机构分歧"
    ↓
将模式写成文本规则
    ├─ knowledge/rule-proposals/intake/RULE_042.md
    └─ "盘口急变（>0.25 盘 in 2h）+ 多指标分歧 → 谨慎对待初盘方向"
    ↓
规则 Intake 流水线（已有）
    ├─ rules intake ingest
    ├─ rules intake scaffold --proposal 1.9.0
    └─ rules experiment activate 1.9.0 --approved-by lcz
    ↓
第二阶段（31-60 场）：三轨对比
    ├─ 旧规则 1.8.0
    ├─ 新规则 1.9.0（从 AI 提炼）
    └─ AI 实验轨
    ↓
60 场后评估：新规则是否真的更好？
```

### 关键决策点

| 场景 | 决策 |
|------|------|
| AI 准确率 > 规则 + 10% | 提炼新规则，进入第二阶段验证 |
| AI 准确率 > 规则 + 5% | 继续积累到 60 场 |
| AI 准确率 ≈ 规则 | 保持规则，AI 仅作研究 |
| AI 准确率 < 规则 | 该市场放弃 AI |

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

### 第二阶段的验证标准

从 AI 提炼的新规则（如 1.9.0）必须通过三轨对比验证：

| 轨道 | 准确率 | 样本数 | 结论 |
|------|--------|--------|------|
| 旧规则 1.8.0 | 68% | 30 | 基线 |
| 新规则 1.9.0 | 73% | 30 | +5%，显著改进 |
| AI 实验轨 | 70% | 30 | 证明模式有效，但新规则更稳定 |

**只有新规则在 30+ 场独立样本上显著优于旧规则时，才考虑正式发布。** AI 的作用是"发现模式"，不是"替代规则"。
