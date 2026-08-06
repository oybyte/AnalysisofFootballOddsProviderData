# Phase 1：确定性离线回放实施计划

## 目标与审查结论

在冻结的 Dataset Manifest 上回放规则，而非重新读取活动规则或赛果。审查后补充：预测和标签必须由不同命令、不同文件阶段生成；主统计单位是比赛而不是同场三个时间点；30 场仅是探索门槛，不足以单独声明统计显著性。

## 实施步骤

1. 在 `backtest.py` 增加 `DeterministicReplayPredictionV1`、Prediction Manifest、Label Manifest、`DeterministicReplayOutcomeV1` 和 Outcome Manifest；每一层冻结前一层哈希、算法版本和时间窗口。
2. 复用 `rules.py`、`analysis_context.py`、`rule_engine` 和 `observations.market_feature_snapshot()`，以 Dataset Manifest 的 ruleset/config/observation IDs 重建输入。禁止读取当前 `active.yml`、当前 Match 分析正文或任何赛后章节。
3. 每个 fixture/市场/锚点生成一条预测记录，含规则事件、输入 feature 哈希、明确 `assessed | pass` 状态和冻结盘口线。任何引用缺失、哈希漂移或合同不支持时记录失败，不补用当前数据。
4. `backtest replay` 只能写 predictions 与 Prediction Manifest；进程不加载结果台账、结果 Markdown、Label/Outcome 路径。Prediction Manifest 一经封存不可覆盖，重跑需新 `backtest_id`。
5. `backtest labels build` 在预测封存后读取确认的 `MatchResultObservation`，生成包含 `result_event_id`、来源哈希、比分和 `label_available_at` 的 Label Manifest。赛果冲突、tracking 或未确认结果只产生不可评价标签。
6. `backtest evaluate` 仅接受已封存 prediction/label manifests，复用 `settlement.py` 结算亚洲盘、固定让球、总进球区间和比分；`pass` 统一派生 `not_evaluated`。比较器不得修改任一输入 manifest。
7. 实现报告：late 为每场主指标；opening/mid 仅描述性展示。按市场、回放模式、sample relation、联赛和 capability 分层，输出 Coverage、Pass、方向命中、前二命中、亚盘结算分布、区间/比分命中及比赛 cluster bootstrap 区间。
8. 将 backtest 产物纳入 Analytics 独立表与指纹，不接入 `reporting.build_statistics()` 的正式分母。新增 `backtest replay/labels build/evaluate/report` CLI，所有路径由 manifest 反查项目根目录并禁止覆盖正式目录。

## 测试与验收

- 同一 Manifest 两次回放的 Prediction Manifest 哈希一致；规则或配置版本不一致、观测来源哈希变化、尝试读取 active rules 均失败。
- 通过进程级夹具证明 replay 阶段无法访问赛果、Label 和 Outcome；Label 必须晚于 Prediction Manifest。
- 覆盖全赢、半赢、走盘、半输、全输、四分之一盘、总进球 pass、比分 pass 和结果冲突。
- 覆盖同场 opening/mid/late 不被累计为三条独立样本，cluster bootstrap 以 fixture 为簇。
- 少于 30 个独立样本只输出计数与探索区间；报告不得输出“显著优于/无效”结论。

## 固定边界

- `historical_reproduction` 和 `counterfactual_current_rules` 的报告、分母和结论始终分开。
- 回放结果只为研究基线服务，不补写历史正式 Outlook、锁定、结算或复盘。
