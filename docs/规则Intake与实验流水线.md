# 规则 Intake 与实验流水线

`football-analysis@1.8.0` 是唯一的正式分析、锁定、结算、复盘和统计规则集。`1.7.0 revision 2` 是已激活但未发布的 Contract 6 实验快照：它把新增文本规则保存为可审计的原子声明，再生成隔离的预测、提示与研究产物；候选、激活和发布是三个独立动作。本 revision 于 2026-08-07 新增四份 Intake 的 51 条 `manual_review` 提示规格，均不具备预测输出或正式影响面。

## 操作顺序

```powershell
.\scripts\odds-journal.ps1 rules intake ingest --file knowledge/rule-proposals/intake/RULE.md
.\scripts\odds-journal.ps1 rules intake inspect --intake INTAKE_ID
.\scripts\odds-journal.ps1 rules intake scaffold --intake INTAKE_ID --proposal 1.7.0
.\scripts\odds-journal.ps1 rules proposal-validate 1.7.0
```

`ingest` 只追加原文路径和内容哈希；同一哈希重试返回 `duplicate`。`inspect` 使用确定性的段落与行范围拆分，不把自然语言直接转换为可执行预测。资金归因、固定概率、赛后反推和跨市场越权内容会被标记为 `research_only` 或 `invalid`。只有 `advisory_candidate` 可由 `scaffold` 写入 `rule-build.yml` 与 `rule-specs/`。

编译清单冻结 intake、atom、处置和 RuleSpec 哈希。修改原文、阈值、求值器或处置都需要形成新的 proposal revision 和新的实验快照，不能修改既有快照。

## 实验隔离

提示规则只输出事实、缺失输入和人工确认项，不能写入正式或实验预测的排序、候选池、比分、置信度、锁定、结算或正式统计。预测实验规则仍须赛前冻结并逐条人工处置。`research_only` 仅记录研究事件。

生成候选不会激活实验。只有 lcz 明确批准后才能执行：

```powershell
.\scripts\odds-journal.ps1 rules experiment activate 1.7.0 --approved-by lcz --confirm-experiment
```

该命令创建内容寻址快照，但不会发布规则或修改 `knowledge/rulesets/football-analysis/active.yml`。正式发布必须另建正式提案并由 lcz 单独执行 `rules release`。

## 人工状态迁移

```powershell
.\scripts\odds-journal.ps1 rules intake defer --rule RULE_ID --reason "缺少可追溯输入"
.\scripts\odds-journal.ps1 rules intake retire --rule RULE_ID --reason "与治理门禁冲突"
.\scripts\odds-journal.ps1 rules intake promote --rule RULE_ID --to prediction_experiment --reason "准备新 revision"
```

`promote` 不会自动改变规则或激活实验。预测实验必须在新的 revision 中明确输出影响面、反证条件、赛前冻结策略和回归夹具，否则命令会拒绝晋级。
