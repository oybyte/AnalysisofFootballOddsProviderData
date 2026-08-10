# 规则 Intake 与实验流水线

`football-analysis@1.8.0` 是唯一的正式分析、锁定、结算、复盘和统计规则集。`1.7.0 revision 2` 是已激活但未发布的 Contract 6 实验快照：它把新增文本规则保存为可审计的原子声明，再生成隔离的预测、提示与研究产物；候选、激活和发布是三个独立动作。revision 3 是待激活候选，使用合并清单把重复原文收敛为独立提示或赛后研究项，绝不修改 revision 2。

## 操作顺序

```powershell
.\scripts\odds-journal.ps1 rules intake ingest --file knowledge/rule-proposals/intake/RULE.md
.\scripts\odds-journal.ps1 rules intake inspect --intake INTAKE_ID
.\scripts\odds-journal.ps1 rules intake disposition --atom ATOM_ID --as advisory_candidate --reason "人工处置原因"
.\scripts\odds-journal.ps1 rules intake scaffold --intake INTAKE_ID --proposal 1.7.0
.\scripts\odds-journal.ps1 rules intake consolidate --proposal 1.7.0 --file knowledge/rule-proposals/football-analysis/1.7.0/rule-consolidations.yml
.\scripts\odds-journal.ps1 rules proposal-validate 1.7.0
```

`ingest` 只追加原文路径和内容哈希；同一哈希重试返回 `duplicate`。`inspect` 使用确定性的段落与行范围拆分，不把自然语言直接转换为可执行预测。资金归因、固定概率、赛后反推和跨市场越权内容会被标记为 `research_only` 或 `invalid`。只有 `advisory_candidate` 可由 `scaffold` 写入 `rule-build.yml` 与 `rule-specs/`。

`disposition` 是追加式人工决定，可记录已有规则、缺失输入与冲突 ID。`consolidate` 只接受 proposal 内唯一的 `rule-consolidations.yml`：每个合并项绑定全部 source atom、完整 RuleSpec、替换的旧 RuleSpec 和内容哈希。它会从全部已纳入 Intake 的最新处置重建 `rule-build.yml`，将 `retired`、`deferred`、`duplicate` 和未合并的 `research_only` 原子排除出单原子规格。旧 snapshot、旧 Build 和其回执永不重算。

编译清单冻结 intake、atom、处置、合并清单和 RuleSpec 哈希。修改原文、阈值、求值器或处置都需要形成新的 proposal revision 和新的实验快照，不能修改既有快照。

## 实验隔离

提示规则只输出事实、缺失输入和人工确认项，不能写入正式或实验预测的排序、候选池、比分、置信度、锁定、结算或正式统计。预测实验规则仍须赛前冻结并逐条人工处置。`research_only` 使用 `postmatch_only`，赛前固定为 `not_applicable`；它只能研究价格模式与赛果的相关性，不能把热门、筹码、机构意图或资金流向由盘口反推为事实。

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
