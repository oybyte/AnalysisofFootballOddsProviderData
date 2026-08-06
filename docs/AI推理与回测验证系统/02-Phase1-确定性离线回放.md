# Phase 1：确定性离线回放

## 目标与模式

在不调用 LLM 的前提下回放规则引擎，验证时间门禁、特征重建和代码化结算。这是后续 AI 实验的不可跳过前置。

| 回放模式 | 观测入口 | 规则与案例时间 |
|---|---|---|
| `historical_reproduction` | `prediction_eligible_market_observations()` | 规则、配置、案例 revision 必须在历史 cutoff 前生效 |
| `counterfactual_current_rules` | `retrospective_validation_market_observations()` | 允许后来冻结的规则，但必须标记 `in_sample/out_of_sample/unknown` |

不得在执行时重新解析 `active.yml`；一切读取都以 Dataset Manifest 中冻结的版本、哈希和 ID 集合为准。参与形成、调参或证据快照的 case cluster 必须标为 `in_sample`，不进入独立验证分母。

## 预测与标签隔离

```text
Dataset Manifest -> 特征重建 -> 规则评估 -> Prediction Manifest 封存
                                                           |
                                                           v
                                                Label Manifest 物化
                                                           |
                                                           v
                                              独立比较器 -> Outcome Manifest
```

预测进程不得读取赛果、复盘、Label Manifest 或 Outcome 投影。Prediction Manifest 不可变封存后，`backtest labels build` 才能从赛果台账生成 `BacktestLabelManifestV1`，其中包含 `result_event_id`、`result_source_sha256`、比分和 `label_available_at`。

## 执行和结算

回放器对每场、每个 opening/mid/late 节点：验证冻结 ID 与来源哈希，重建 `MarketFeatureSnapshot`，运行冻结规则，再封存 `DeterministicReplayPrediction`。比较器仅在预测封存后加载标签，并以当时冻结的盘口线进行代码化结算。

亚盘结算必须区分 `full_win`、`half_win`、`push`、`half_loss`、`full_loss`，并覆盖四分之一盘。市场 `pass` 一律派生 `not_evaluated`，不进入命中率分母。

## 统计与报告

- 主指标为每场唯一的 `late` 节点。opening/mid/late 是同场重复观测，仅作描述性对比；如需置信区间，使用按比赛 cluster bootstrap。
- 只计算方向准确率、前二命中率（三选一市场）、亚盘结算分布、总进球区间和比分候选命中率、Coverage/Pass 率。不计算 Brier 或 ECE。
- 少于 30 个合格独立样本时，仅报告计数、Coverage 与探索性区间，不作规则有效/无效结论。
- 报告必须分开 `out_of_sample`、`in_sample` 和 `unknown`。正式研究只读取 `out_of_sample`。

## 命令与退出门槛

```powershell
odds-journal backtest replay `
  --manifest raw/backtests/BT_ID/dataset-manifest.yml `
  --output raw/backtests/BT_ID/

odds-journal backtest labels build `
  --predictions raw/backtests/BT_ID/prediction-manifest.yml `
  --output raw/backtests/BT_ID/label-manifest.yml

odds-journal backtest evaluate `
  --predictions raw/backtests/BT_ID/prediction-manifest.yml `
  --labels raw/backtests/BT_ID/label-manifest.yml

odds-journal backtest report --backtest-id BT_ID `
  --output reports/backtest/BT_ID/replay-report.md
```

只有时间泄漏、标签隔离、亚盘结算和历史兼容回归都通过后，才可进入 Phase 2。
