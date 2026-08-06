# Phase 0：数据资格清单实施计划

## 目标与审查结论

实现 `BacktestDatasetManifestV1` 作为回放唯一权威输入。审查后固定三项约束：直接读取追加式市场观测台账而非 `MarketSnapshot` 兼容投影；按市场和锚点记录资格；同一 fixture/case cluster 在一个 Manifest 中只能占用一次。

## 实施步骤

1. 新建 `backtest.py`，定义 `BacktestMode`、`BacktestMarketEligibilityV1`、`BacktestFixtureEligibilityV1` 和 `BacktestDatasetManifestV1`，并注册 Schema。Manifest 冻结 `ruleset_id/version/content_sha256`、规则配置哈希、回放模式、生成算法版本、时间锚点、每个市场的观测/来源/冲突处置 ID 和自身哈希。
2. 在 `observations.py` 的 `_active_observations()`、`prediction_eligible_market_observations()`、`market_feature_snapshot()` 之上实现两个明确入口：
   - `historical_reproduction` 仅取 `prediction_eligible=true`、`received_at <= cutoff`、`observed_at <= cutoff < kickoff_at`、`exact`、可用且已解决冲突的观测。
   - `counterfactual_current_rules` 仅取赛前报价、已历史认证且 `retrospective_validation_eligible=true` 的观测；所有后补文本仍不得进入前者。
3. 对每场的四个市场独立计算 `opening/mid/late`。`opening` 是满足该市场最低规则输入的最早精确状态；`late` 的固定 as-of 为 `kickoff_at - 5min`，选择该时刻前最新合格状态；`mid` 为 opening/late 的中点前最新状态。没有状态时写 `partial/ineligible`，不移动锚点、不借用其他市场。
4. 为每个锚点保留可重放的完整观测集合和 `feature_snapshot_sha256`，而不是只保留终点报价。规则最低输入由冻结 ruleset/contract 解析；缺失的市场只影响该市场资格，不能伪造比赛级 `eligible`。
5. 用 `cases.fixture_fingerprint_v2()` 和 case cluster 做去重。优先保留同一 fixture 的已确认 Match；若其与合格 LegacyCase 指向同一 cluster，LegacyCase 标为 `duplicate_fixture`。无可验证 fingerprint 或 cluster 的记录标为 `unknown_relation`，不得进入严格分母。
6. `historical_reproduction` 还校验规则发布快照、配置和 CaseReceipt revision 在 cutoff 前可得；`counterfactual_current_rules` 冻结当前规则/配置哈希并显式标记 `in_sample/out_of_sample/unknown`。任何运行不得读取 `active.yml` 决定历史版本。
7. 将 Manifest、只读摘要和构建日志写入 `raw/backtests/<backtest_id>/`；以 `manifest_id + payload_sha256` 幂等。新增 `backtest inventory` 与 `backtest inventory --summary`，只读摘要不得被后续回放器接受为输入。

## 测试与验收

- 覆盖 cutoff 后 received、非精确时间、未显示、未解决冲突、已认证赛前补录、跨档/跨市场及缺失节点。
- 验证 opening/mid/late 对固定时点稳定，重复运行产生相同 Manifest；新增更晚观测不改变已封存 Manifest。
- 验证 Match/LegacyCase/cluster 三类重复均只保留一个严格样本，未知关系不会进入严格统计。
- 覆盖历史 ruleset 不可得、来源哈希变更和 feature 哈希不一致的 fail closed。
- 完成 `schemas check`、`analytics build/validate`、`validate --all` 和新增 backtest 单测；正式 Match、规则实验与统计哈希不变。

## 固定边界

- Manifest 仅为 Phase 1、AI 研究和后续规则验证提供输入，不创建预测、标签或研究结论。
- `partial` 是数据覆盖状态，不能被自动解释为 `pass`、正确或错误。
