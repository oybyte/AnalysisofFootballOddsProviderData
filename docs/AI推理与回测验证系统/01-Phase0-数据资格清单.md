# Phase 0：数据资格清单

## 目标

产生 `BacktestDatasetManifestV1`，在任何回放前确定每场比赛、每个时间点、每个市场可使用的赛前观测。它是权威资格清单，不允许用比赛级布尔值代替。

## 两个资格读取入口

| 入口 | 用途 | 门禁 |
|---|---|---|
| `prediction_eligible_market_observations()` | 真实赛前正式分析和 `historical_reproduction` | 材料必须在 cutoff 前进入仓库 |
| `retrospective_validation_market_observations()` | `counterfactual_current_rules` 离线回放 | 赛前报价证据必须已完成历史认证 |

二者不可相互替代。`received_at > cutoff` 的赛后补录观测永远不能用于正式预测或历史复现；它只能在认证后用于反事实回放。

## 资格规则

- 报价节点必须满足 `observed_at <= cutoff < kickoff_at` 且 `time_precision == exact`。
- 观测必须可用、无未解决冲突，并保留来源哈希与冲突处置事件。
- LegacyCase 只有 `approved + prematch_verified + statistics_eligible` 时才能用于严格验证。
- Match 与 LegacyCase 通过 fixture fingerprint / case cluster 去重，禁止同一赛事重复计数。
- `tracking`、赛果冲突或未确认比赛不产生评价标签。

## Manifest 结构

`BacktestDatasetManifestV1` 冻结规则版本、配置哈希、feature-set、回放模式和每场资格。每场包含 `fixture_fingerprint`、关联 case、`sample_relation`、资格状态与排除原因。

每个 `opening | mid | late` 时间点下，每个 `asian_handicap`、`european_odds`、`kelly_index`、`total_goals` 分别记录：

```yaml
status: eligible | partial | ineligible
observation_ids: []
source_sha256s: []
conflict_resolution_event_ids: []
feature_snapshot_sha256: string | null
reasons: []
```

只读摘要可以展示比赛级资格、主 late 节点和排除原因，但它是 Manifest 的派生报告，不能作为评估器输入。

## 固定时间点

- `opening`：满足该市场最低输入契约的最早精确赛前时间。
- `late`：固定为 `kickoff_at - 5 minutes`，仅读取该时刻前的合格节点。
- `mid`：`opening` 与 `late` 的时间中点前最近的合格状态。

不存在合格输入时必须标记 `partial/ineligible` 或后续 `pass`，不得移动 cutoff 挑选更有利的报价。

## 命令与退出门槛

```powershell
odds-journal backtest inventory `
  --mode historical_reproduction|counterfactual_current_rules `
  --ruleset football-analysis@VERSION `
  --backtest-id BT_ID

odds-journal backtest inventory --mode historical_reproduction --ruleset football-analysis@1.8.0 --backtest-id BT_ID
```

只有 Manifest 的规则、观测、来源、冲突和去重验证通过后，才能进入 Phase 1。

## 与演进路线的关系

Phase 0 是全部后续阶段的基础。它产生的 `BacktestDatasetManifest` 同时服务于：

1. **冻结 Outlook 回放**（Phase 1）：验证历史赛前结论的冻结输入、重建结果与结算可复验；不重新执行当前 `1.8.0` 规则，也不单独证明其真实准确率
2. **AI 实验对比**（Phase 2-4）：与规则在相同数据集上对比
3. **新规则验证**（第二阶段）：验证从 AI 提炼、并由 lcz 新建实验 proposal revision 的规则是否真的更好；不得预占或复用正式 proposal 的版本号

**第一阶段典型场景**：
```powershell
# 1. 为具备完整冻结输入的历史结论建立可复验基线
odds-journal backtest inventory --mode historical_reproduction --ruleset football-analysis@1.8.0

# 2. 同一数据集上运行 AI 实验
odds-journal ai experiment study register --file STUDY.yml
odds-journal ai experiment run MATCH_PATH --role primary --study STUDY_ID

# 3. 30 场后对比
odds-journal backtest report --backtest-id BT_ID
odds-journal ai experiment report --study STUDY_ID
```

严格的数据资格清单只是后续研究的必要前提。只有真实 provider 获批、同一预注册 cohort 的冻结 Outlook 与 AI Outcome 均可评价后，才可讨论类似"冻结 Outlook 72%"与"AI 65%"的比较结果；两者均不得外推为当前规则的绝对准确率。
