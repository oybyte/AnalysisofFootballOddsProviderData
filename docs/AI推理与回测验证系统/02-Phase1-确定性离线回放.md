# Phase 1：确定性离线回放

## 为何先做确定性回放

在任何 AI 实验前，必须先用确定性回放回答两个问题：

1. **历史冻结结论是否可复验？**
   - 回放器只接受内容寻址的赛前 Draft、人工处置与 Evaluation Bundle，重建相同 Outlook 后再结算
   - 它不读取当前规则，因此其结果是历史冻结结论的研究基线，不能单独声明现有 `1.8.0` 的真实准确率

2. **回放系统是否有时间泄漏？**
   - 如果回放准确率虚高（如 90%），说明用了未来信息
   - 那么后续的 AI 对比结果也不可信

**第一阶段关键里程碑**（实施 Phase 1 后）：
```markdown
# 确定性回放报告示例（假设具备足量完整冻结输入）
## 冻结 Outlook 研究基线
- 让球盘：72%（30 场）
- 胜平负：68%（30 场）
- 精确比分：15%（30 场）— 规则几乎无效

## 结论
1. 这些数值仅描述该冻结 cohort，不代表当前规则版本的性能
2. 真实 provider 的预注册 AI Study 只能与同一合资格 cohort 比较，且需另行检查样本量与统计不确定性
3. 回放系统无时间泄漏（验证通过）
```

只有建立了可信的冻结结论基线，并完成真实 provider 的预注册研究后，才能判断 AI 是否具有增益。

## 目标与模式

在不调用 LLM 的前提下，回放器验证内容寻址的赛前 Draft、人工处置与 Evaluation Bundle，并从这些冻结输入重建 Outlook 后执行代码化结算。它不读取当前 `active.yml`、赛果或赛后正文；缺少完整冻结输入的历史记录固定为 `pass`。这是后续 AI 实验的不可跳过前置。

| 回放模式 | 观测入口 | 规则与案例时间 |
|---|---|---|
| `historical_reproduction` | `prediction_eligible_market_observations()` | 规则、配置、案例 revision 必须在历史 cutoff 前生效 |
| `counterfactual_current_rules` | `retrospective_validation_market_observations()` | 允许后来冻结的规则，但必须标记 `in_sample/out_of_sample/unknown` |

不得在执行时重新解析 `active.yml`；一切读取都以 Dataset Manifest 中冻结的版本、哈希和 ID 集合为准。参与形成、调参或证据快照的 case cluster 必须标为 `in_sample`，不进入独立验证分母。

## 预测与标签隔离

```text
Dataset Manifest -> 冻结输入验证与 Outlook 重建 -> Prediction Manifest 封存
                                                           |
                                                           v
                                                Label Manifest 物化
                                                           |
                                                           v
                                              独立比较器 -> Outcome Manifest
```

预测进程不得读取赛果、复盘、Label Manifest 或 Outcome 投影。Prediction Manifest 不可变封存后，`backtest labels build` 才能从赛果台账生成 `BacktestLabelManifestV1`，其中包含 `result_event_id`、`result_source_sha256`、比分和 `label_available_at`。

## 执行和结算

回放器对每场、每个 opening/mid/late 节点验证冻结 ID、来源哈希和赛前输入，并仅以已重建的冻结 Outlook 封存 `DeterministicReplayPrediction`。比较器仅在预测封存后加载标签，并以当时冻结的盘口线进行代码化结算。

亚盘结算必须区分 `full_win`、`half_win`、`push`、`half_loss`、`full_loss`，并覆盖四分之一盘。市场 `pass` 一律派生 `not_evaluated`，不进入命中率分母。

## 统计与报告

- 主指标为每场唯一的 `late` 节点。opening/mid/late 是同场重复观测，仅作描述性对比；如需置信区间，使用按比赛 cluster bootstrap。
- 只计算方向准确率、前二命中率（三选一市场）、亚盘结算分布、总进球区间和比分候选命中率、Coverage/Pass 率。不计算 Brier 或 ECE。
- 少于 30 个合格独立样本时，仅报告计数、Coverage 与探索性区间，不作规则有效/无效结论。
- 报告必须分开 `out_of_sample`、`in_sample` 和 `unknown`。正式研究只读取 `out_of_sample`。

## 命令与退出门槛

```powershell
odds-journal backtest replay `
  --manifest raw/backtests/BT_ID/dataset-manifest.yml

odds-journal backtest labels build `
  --predictions raw/backtests/BT_ID/prediction-manifest.yml

odds-journal backtest evaluate `
  --predictions raw/backtests/BT_ID/prediction-manifest.yml `
  --labels raw/backtests/BT_ID/label-manifest.yml

odds-journal backtest report --backtest-id BT_ID
```

只有时间泄漏、标签隔离、亚盘结算和历史兼容回归都通过后，才可进入 Phase 2。

**第一阶段里程碑**：Phase 1 完成后，应产出"规则引擎基线报告"，明确各市场的准确率、pass 率和样本量。这是后续 AI 对比的锚点。
