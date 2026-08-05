# 费内巴切 VS 格拉茨风暴 盘面完整推演（数据截止：2026-08-05 17:51）

比赛时间：2026-08-06 02:00

场地：未记录

比赛类型：欧冠资格赛

### 一、澳盘时序梳理与盘路定性

- 截止 `2026-08-05 17:51 +08:00`，澳门唯一可追溯的精确节点为 `2026-08-03 22:32`：主让 `1.5`、主水 `1.00`、客水 `0.78`。澳门初/即盘从 `0.98/1.5/0.80` 至 `1.00/1.5/0.78`，端点相同档位，但不能证明期间没有变化。
- 让球端点分歧：36 由主让 `1.5` 收至 `1.25`；威廉希尔维持 `1.25` 而主水 `0.92 -> 0.79`；Interwetten 则由 `1.0` 加深至 `1.5`。主队仍是深让方，但不具备可证明的单一时序。
- 因此主队让球仅列第一，不解释为资金流或机构控赔，并保留“赢球不覆盖深盘”的反证。

### 二、胜平负欧赔走势

- 澳门欧赔不变为 `1.28 / 4.80 / 7.10`；威廉希尔、立博和 Interwetten 均压低主胜，并抬高平局、客胜。36 当前主胜为 `1.33`。
- 多家机构的端点共同维持主队显著热门定位，胜平负的首选为主胜；反面是澳门未动且 36 缺少初盘，不能把这些端点描述成已验证的完整行情。

### 三、凯利指数交叉验证

- 六家平均从 `0.96 / 0.83 / 0.89` 收敛为 `0.93 / 0.93 / 0.93`；威廉希尔、立博和 Interwetten 的主胜凯利均下行，和欧赔的主胜低位相容。
- 凯利与欧赔来自同批机构和同一截图，是辅助维度；它不独立证明赛果，也不用于归因机构意图。

### 四、大小球辅助参考

- 澳门 `2.75 -> 3`；威廉希尔与 Interwetten `2.5 -> 3.5`；36 在 `3` 球档位的大球水位 `1.03 -> 0.85`。这些端点支持中高总进球基准。
- 立博仍在 `2.5`，不同机构跨档位的水位不能直接比较；总进球仅以 `3-4` 为核心区间，同时保留低于三球的风险。

### 五、综合权重推演

- 胜平负优先级：主胜 > 平局 > 客胜。
- 亚洲让球优先级：主队让球 > 客队受让。当前参考线为主让 `1.5`，但 36 收至 `1.25` 与澳门时序不足使覆盖结论降级。
- 固定让球胜平负优先级：让胜 > 让平 > 让负。固定让球 `-1` 是从亚洲盘口换算的分析口径，不是独立固定让球市场报价。
- 总进球：`3-4`。比分权重：`3-0`、`3-1`。
- 校准规则处置：`trend-purity-v1`、`provider-consensus-divergence-v1`、`late-market-anomaly-v1` 已采纳为控制约束，未替换基础排序或候选池。

### 六、后市观测清单

- 正向强化信号：主让 `1.5` 或更深在多家机构保持，且主胜继续下调，可强化主队两球以上取胜的假设，仍需重新启动分析后才可更新正式结论。
- 风险预警信号：主要机构同步收浅到主让 `1.25` 或以下，并同步抬高主胜，主队赢球不覆盖的风险上升。
- 失效条件：补入澳门同机构、同档位、同赔率格式的三个精确节点后，现有 `degraded` 结论必须通过 `analysis restart` 重新生成。

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 2
ruleset_id: football-analysis
ruleset_version: 1.5.0
data_cutoff_at: '2026-08-05T17:51:00+08:00'
applied_rule_ids:
- football-analysis-framework
- market-settlement-rules
- data-provenance-time-boundary
- prematch-stage-positioning
- theoretical-vs-actual-market
- market-timeline-cross-validation
- dual-hypothesis-evidence
- layered-decision-confidence-pass
- goals-score-separation
- prematch-checklist-v1
- data-quality-conflict-and-pass
- scenario-identification-and-case-retrieval
- live-update-and-postmatch-separation
- draw-kelly-parity-v1
- korea-goal-drop-v1
- low-stability-league-weight-calibration
- handicap-total-goals-divergence
- water-threshold-operator-style
- handicap-inducement-resistance
- asian-european-divergence
- cross-related-same-pattern
- market-heat-chip-distribution
- hidden-draw-away-cut-v1
- operator-market-divergence
- late-market-reversal
- total-goals-cross-market-v1
- quarter-low-water-inducement-v1
- score-baseline-v1
- korea-deep-line-loss-tolerance-v1
- deep-line-stable-cover-v1
source_refs:
- fact:market-archive-20260805T175100
- fact:macau-single-exact-node
- fact:asian-handicap-endpoints
- fact:european-odds-endpoints
- fact:kelly-endpoints
- fact:total-goals-endpoints
scenario_instance_ids: []
case_ids:
- legacy-seoul-ulsan
- legacy-gimcheon-daejeon
- 20260730-bra-serie-a-fluminense-bahia
- 20260730-bra-serie-a-vitoria-palmeiras
- 20260730-bra-serie-a-mirassol-remo
- legacy-hjk-tps
- legacy-hacken-aik
- legacy-rosenborg-fredrikstad
- legacy-incheon-bucheon
- 20260730-bra-serie-a-internacional-flamengo
ruleset_origin: published
deterministic_rule_ids:
- trend-purity-v1
- provider-consensus-divergence-v1
- late-market-anomaly-v1
disposition_rule_ids:
- trend-purity-v1
- provider-consensus-divergence-v1
- late-market-anomaly-v1
control_rule_ids:
- trend-purity-v1
- provider-consensus-divergence-v1
- late-market-anomaly-v1
profile_chain: [global]
evaluation_bundle_sha256: 7e6946fd1ecb6fa5a548b48080f9fa4a103497d569d86f63b8f48a4ebbef9df0
```
<!-- analysis-trace:end -->
