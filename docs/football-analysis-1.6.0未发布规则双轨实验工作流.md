# football-analysis 1.6.0 未发布规则双轨实验工作流

## 1. 定位与当前状态

本文说明未发布规则如何在不污染正式预测链的前提下参与每场比赛分析。日常基础命令见根目录 `README.md`，正式分析架构见《项目改造与AI分析接入方案》。

截至 2026-08-04：

- 正式活动规则为 `football-analysis@1.5.0`，负责正式结论、锁定、结算和复盘。
- 活动实验为 `football-analysis@1.6.0 revision 2`。
- 活动 proposal SHA-256 为 `59e237f51b399b8aba0fb4557f556b16a4ee235d089ef36138aa86654ec0fae2`。
- Calibration Contract 5 配置 SHA-256 为 `2ed22a04f4663b70db9802291d50530e9bbc43e1d16e68e97996f83cba507101`。
- revision 1 和 revision 2 均为不可变历史快照；当前指针以 `knowledge/rule-experiments/football-analysis/active.yml` 为准。
- 实验报告目前为 0 场已评估、0 场已评分，原因是尚无新比赛完成双轨流程，不是校验失败。

实验激活不等于发布。它不会创建正式 `APPROVAL.yml`，不会修改 `knowledge/rulesets/football-analysis/active.yml`，也不会取得正式锁定或结算权限。

## 2. 双轨边界

| 项目 | 正式轨 | 实验轨 |
|---|---|---|
| 规则来源 | 已发布 `1.5.0` | 已激活的 `1.6.0` 不可变快照 |
| 校准契约 | Contract 4 | Contract 5 |
| 分析回执 | AnalysisReceipt V6 | ExperimentAnalysisReceipt V1/V2 |
| 输出 | AnalysisOutlook V4 | ExperimentOutlook V1 |
| 赛前冻结 | LockCandidateReceipt V1/V2 | ExperimentPredictionReceipt V1 |
| 赛后结果 | 正式 settlement 与 review | ExperimentOutcome V1 |
| 可否锁定 | 可以 | 不可以 |
| 可否正式结算 | 可以 | 不可以 |
| 可否进入正式命中率 | 可以，按现有门禁 | 不可以 |

两轨共享同一比赛身份、`as_of`、开赛时间、原始盘口快照和正式 Draft Input。实验回执 V1 绑定正式 AnalysisReceipt 哈希和兼容盘口快照哈希；存在规范化观测时使用 V2，并额外冻结观测集合与 `MarketFeatureSnapshotV2` 哈希，因此不能在赛后换数据、换截止时间或换正式基础结论。

实验规则不能覆盖以下治理不变量：

- 比赛身份和开赛时间；
- 数据来源、截止时间和防泄漏；
- 数据质量与盘口格式门禁；
- 胜平负、让球和总进球市场隔离；
- 正式赛前锁定、结算和复盘；
- proposal 与 experiment 禁止驱动正式生命周期。

## 3. 实验快照治理

### 3.1 激活

激活前先校验提案：

```powershell
.\scripts\odds-journal.ps1 rules proposal-validate 1.6.0
.\scripts\odds-journal.ps1 rules experiment activate 1.6.0 `
  --approved-by lcz --confirm-experiment
.\scripts\odds-journal.ps1 rules experiment status
```

命令验证 Manifest schema 6、Contract 5 配置、source intake、`precedence.yml`、`source-map.yml` 及其哈希。成功后将提案复制到：

```text
knowledge/rule-experiments/football-analysis/1.6.0/<proposal_sha256>/
```

并写入：

- `EXPERIMENT-ACTIVATION.yml`：批准人、时间、revision 和冻结哈希；
- `knowledge/rule-experiments/football-analysis/active.yml`：当前实验指针；
- `knowledge/evidence/rule-experiment-events.jsonl`：追加式治理和运行事件。

同一 proposal hash 重复激活是幂等的。提案内容变化后再次激活会创建新 revision；旧目录不得编辑或删除。

### 3.2 停用

```powershell
.\scripts\odds-journal.ps1 rules experiment deactivate `
  --approved-by lcz --reason "停止当前实验"
```

停用只更新实验指针并追加事件，不删除快照，也不影响正式 `1.5.0`。没有活动实验时，新比赛只运行正式轨。

### 3.3 规则覆盖

实验规则通过 `supersedes_rule_ids`、`override_mode` 和 `override_scope` 声明覆盖：

- `replace`：新规则在快照内始终压制目标分析规则。
- `when_triggered`：新规则完整触发时才压制目标分析规则。
- `none`：不覆盖，冲突假设并存并交给 AI 处置。

覆盖图不能成环。被压制规则仍写入 `suppressed`、`original_status`、`suppressed_by_rule_id` 和原因，不能静默消失。当前 `tg-line-drop-over-price-divergence-v1` 仅在触发时压制旧的总进球降盘解释；平局凯利最低的两种解释继续并存。

## 4. 规则与 Profile

Contract 5 当前包含 12 条总进球相关实验规则：

机器直接判断：

- `tg-same-line-water-defense-v1`
- `tg-line-drop-over-price-divergence-v1`
- `tg-late-shock-guard-v1`
- `tg-two-dimension-confirmation-v1`

机器提取事实、AI确认语义：

- `tg-dual-line-bracket-v1`
- `tg-handicap-ceiling-risk-v1`
- `tg-head-provider-divergence-nordic-v1`
- `tg-floor-anchor-upper-tail-v1`
- `tg-draw-compression-hypothesis-v1`
- `tg-one-sided-overrun-risk-v1`
- `tg-away-collapse-prior-v1`
- `tg-extreme-under-context-v1`

Profile 只按注册的赛事代码匹配：

- `global`：全部赛事。
- `low-goal`：韩国 K1/K2 与已注册芬超代码。
- `nordic-low-heat`：挪超、瑞典超与已注册芬超代码。
- `korea-low-goal`：韩国 K1/K2，链为 `global -> low-goal -> korea-low-goal`。

荷乙、澳甲等未注册赛事不能按显示名称模糊套用 Profile。资金数据缺失时固定记录 `fund_flow_status: unknown` 和 `causal_attribution: unverified`，不得把盘口变化自动解释为散户冲击或机构主动控赔。

## 5. 每场比赛操作

### 5.1 冻结上下文

```powershell
.\scripts\odds-journal.ps1 agent start MATCH_PATH --as-of "赛前截止时间"
```

命令先生成正式 AnalysisReceipt V6；若存在活动实验，再生成：

```text
raw/matches/<match_id>/experiment-analysis-receipt.yml
```

实验回执冻结正式回执、盘口快照、实验 revision、proposal/config/precedence 哈希、Profile 链和适用规则。比赛已经冻结其他实验快照时，命令拒绝中途切换。

### 5.2 完成正式轨

先登记场景或明确无场景理由，检索案例，然后按 Contract 4 生成正式 Outlook：

```powershell
.\scripts\odds-journal.ps1 agent evaluate-draft MATCH_PATH `
  --draft-file ANALYSIS_DRAFT_INPUT.yml `
  --dispositions-file OFFICIAL_DISPOSITIONS.yml
```

实验轨依赖正式 Draft Input 和 Outlook，但不能反向修改它们。

### 5.3 完成实验轨

```powershell
.\scripts\odds-journal.ps1 agent evaluate-experiment MATCH_PATH `
  --dispositions-file EXPERIMENT_DISPOSITIONS.yml
```

第一次不传 dispositions 文件时可先生成机器 Bundle，检查每条规则的 `triggered`、`not_triggered`、`not_applicable`、`suppressed` 或 `insufficient_data` 状态。只需处置全部 `triggered` 规则，且每条只能为 `adopted` 或 `excluded`。

每条处置必须包含双向假设、支持证据、反证、失效条件和 actor。采纳总进球规则时还必须给出主区间、区间内众数、可选尾部/排除区间及恰好两个不同的 `H-A` 比分。多个已采纳规则必须收敛到相同候选结构，否则拒绝生成 Outlook。

产物位于：

```text
raw/matches/<match_id>/experiment-rule-evaluation-<sha256>.yml
raw/matches/<match_id>/experimental-analysis-outlook.yml
raw/matches/<match_id>/experimental-analysis-report.md
```

### 5.4 正式校验与赛前冻结

```powershell
.\scripts\odds-journal.ps1 agent validate-draft MATCH_PATH
.\scripts\odds-journal.ps1 agent render-draft MATCH_PATH
.\scripts\odds-journal.ps1 agent prepare-lock MATCH_PATH `
  --market MARKET --selection SELECTION --confidence VALUE
```

`prepare-lock` 只生成正式锁定候选，并在开赛前尝试写入 `experiment-predictions/`：

- 实验 Outlook 完整：冻结 `complete` 实验预测；
- 实验 Outlook 缺失：冻结 `insufficient_data` 和原因；
- 实验引擎异常：追加失败事件，不阻断正式候选。

实验预测绑定正式候选 ID 与哈希，但不能作为正式锁定参数。开赛后禁止补建实验预测。

## 6. 完赛与赛中实验

正式 `finish` 继续派生正式 settlement。只有赛前存在 `complete` 实验预测时，系统才额外生成：

```text
raw/matches/<match_id>/experimental-outcome.yml
```

评价包含主区间、众数、尾部和比分覆盖，以及 `experiment_better`、`official_better` 或 `same` 比较。随机事件初始为 `unreviewed`；结果不能反向改写赛前 Outlook。不存在合格实验预测时不得赛后补造评价。

赛中规则使用独立入口：

```powershell
.\scripts\odds-journal.ps1 agent evaluate-live MATCH_PATH `
  --as-of "赛中时间" --event-file LIVE_EVENT.yml
```

它要求已有正式赛前锁定，事件时间不得早于开赛，并写入 `live-experiments/`。早进球或两球领先的候选只属于 `LiveExperimentReceiptV1`，不修改正式或实验赛前预测，也不改变正式结算。

## 7. Analytics 与人工评估

Analytics schema 3 在既有正式/实验投影外增加规范化事实、盘口观测、来源、冲突、序列、特征和赛果投影：

- `experimental_runs`
- `experimental_rule_events`
- `experimental_predictions`
- `experimental_outcomes`
- `official_experiment_deltas`
- `fixture_fact_observations`
- `market_observations`
- `observation_sources`
- `observation_conflicts`
- `market_series`
- `market_series_nodes`
- `market_series_features`
- `match_result_observations`
- `market_observation_coverage`

构建和查看报告：

```powershell
.\scripts\odds-journal.ps1 analytics build
.\scripts\odds-journal.ps1 analytics validate
.\scripts\odds-journal.ps1 rules experiment report 1.6.0
```

报告按规则、赛事、provider 和 Profile 链统计触发、数据不足、采纳/排除、支持/反例及两轨差异。`automatic_promotion` 固定为 `false`；样本数不会自动发布规则。

lcz 可据报告选择继续当前 revision、修改提案并激活新 revision、停用实验、将规则降级为风险提示，或另行批准正式发布。实验激活批准不能复用为发布批准，已发布版本也不得用实验结果原地修改。

## 8. 验收与排障

```powershell
.\scripts\odds-journal.ps1 agent doctor
.\scripts\odds-journal.ps1 rules proposal-validate 1.6.0
.\scripts\odds-journal.ps1 schemas check
.\scripts\odds-journal.ps1 analytics validate
.\scripts\odds-journal.ps1 validate --all
.\scripts\odds-journal.ps1 agent changes
```

常见阻断：

- “没有实验分析回执”：重新运行 `agent start`；若比赛已冻结其他 revision，不能强制覆盖。
- “正式分析回执已变化”：按正式流程重启分析，不手工修改实验回执。
- “盘口快照已变化”：使用新的赛前截止时间重启，不能沿用旧实验上下文。
- “处置必须覆盖全部触发规则”：补齐所有且仅有 `triggered` 规则的处置。
- “多个已采纳规则必须收敛”：统一候选结构或排除缺乏独立支持的规则。
- 已开赛：停止生成赛前实验预测；需要研究赛中信号时使用 `evaluate-live`。

实验工作流、CLI、schema 和可信指令变更属于 `workflow_breaking`。完成代码和文档校验后运行 `agent changes`；未经 lcz 新的明确批准不得执行 `agent sync`。
