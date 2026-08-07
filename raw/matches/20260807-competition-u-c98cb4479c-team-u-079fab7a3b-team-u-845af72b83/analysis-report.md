# 横滨水手 VS 鹿岛鹿角 盘面完整推演（数据截止：2026-08-07 16:20）

比赛时间：2026-08-07 18:25

场地：未记录

比赛类型：J联赛

### 一、澳盘时序梳理与盘路定性

- 本次回执的截止时间为 `2026-08-07T16:20:12+08:00`，开赛前约两小时五分钟；只使用此前入账的市场观测。
- 澳门让球四个精确节点均为横滨水手主让半球，主水从 `0.86` 逐步降至 `0.72`，客水从 `0.98` 升至 `1.12`。这是一条同档位、同机构、同格式的主队水位下行事实。
- 但 Bet365 从主让半球改为主让平半，主水由 `0.85` 升至 `0.98`；威廉希尔始终为主让平半且客队低水；Interwetten 则维持主让半球不变。机构间没有同档、同方向的完整一致性。
- 水位变化只记录价格事实，不能据此推断资金、热度或机构意图。

### 二、胜平负欧赔走势

- 即盘中，鹿岛鹿角仍是多数公司最低赔率的一方：澳门 `2.12`、威廉希尔 `2.05`、立博 `2.00`、Interwetten `2.15`、Betfair `2.20`，Bet365 为 `2.10`。
- 同时，澳门主胜从 `3.42` 降至 `3.05`，威廉从 `3.70` 降至 `3.50`，立博从 `3.70` 降至 `3.40`，Betfair 从 `3.95` 降至 `3.80`；这说明主胜端点被压低，但未改变多数欧赔对客队的最低价定位。
- 因此，澳门让球的主让半球与欧赔的客队低价未形成可解释的一致关系。缺少阵容、赛程或理论定位等结构化事实，不能从二者任选其一作为正式胜负方向。

### 三、凯利指数交叉验证

- 六家平均凯利由 `0.97 / 0.93 / 0.89` 变为 `0.92 / 0.91 / 0.95`，即盘三项最大差仅 `0.04`，处于平权提示区间。
- 澳门即盘为 `0.80 / 0.91 / 0.95`，而 Bet365 即盘为 `0.98 / 0.89 / 0.95`；个别低值不能消除亚盘与欧赔的核心分歧。
- 凯利与欧赔来自同一批截图，不能作为独立信号重复加权；只保留为“需人工复核排序”的提示，不产生第一、第二优先级。

### 四、大小球辅助参考

- 澳门和 Bet365 都在 `2/2.5` 档显示小球端点下行，立博、威廉和 Interwetten 的 `2.5` 档也维持或强化低小球水；这是端点价格的共同现象。
- 然而，每家机构只提供初盘/即盘快照，未形成三个同机构、同盘口档位、同赔率格式的精确节点；不同档位之间也不得相减或互相确认。
- 按 Contract 7，总进球为 `pass`，不输出区间；比分随之 `pass`，不输出两个比分候选。

### 五、综合权重推演

- 正式结论：整场 `pass`。并非“无数据”，而是澳门亚盘主队倾向与欧赔客队低价在同一截止时间内未被结构化基本面解释，基础门禁为 `unexplained_divergence`。
- 胜平负优先级：`pass`，不生成排序或锁定选择。
- 亚洲让球优先级：`pass`，不将澳门单一时序覆盖机构间盘口差异。
- 固定让球胜平负优先级：`pass`，不从胜负赔率推导让球穿盘。
- 总进球：`pass`，不生成区间。
- 比分权重：`pass`，不生成两个比分候选。
- 校准规则处置：`trend-purity-v1` 和 `provider-consensus-divergence-v1` 已记录为价格趋势/分歧控制信号；它们均不能绕过基础门禁。其余已加载条件规则逐项排除，理由见 analysis-trace。
- 已触发的 `trend-purity-v1` 和 `provider-consensus-divergence-v1` 仅记录水位趋势及机构分歧，不能覆盖基础门禁。历史检索结果以非同联赛、时间质量不一的案例为主，仅作候选对照，未参与本场判断。

### 六、后市观测清单

- 正向强化信号：澳门、Bet365、威廉至少三家在同一盘口档位形成可比较的同向变化，并与欧赔的胜负定位同步；届时才可重新启动分析。
- 风险预警信号：开赛前仍不能补入阵容、伤停、赛程或理论定位等可追溯结构化事实，或亚盘与欧赔的方向继续背离；则本次 `pass` 必须维持。
- 总进球方向需至少两家独立机构各有三个同档精确节点，且无合格反向序列，才允许解除 `pass`；否则继续不输出区间或比分。

本轮不创建锁定候选，不提供胜负、让球、总进球或比分预测。

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 2
ruleset_id: football-analysis
ruleset_version: 1.8.0
data_cutoff_at: '2026-08-07T16:20:12+08:00'
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
excluded_rules:
- {rule_id: korea-goal-drop-v1, reason: 非韩国赛事且无专项时间序列。}
- {rule_id: draw-kelly-parity-v1, reason: 凯利平权只构成提示，不能消除基础市场背离。}
- {rule_id: low-stability-league-weight-calibration, reason: J联赛不属于该专项 profile。}
- {rule_id: water-threshold-operator-style, reason: 水位绝对值不能解释亚欧定位冲突。}
- {rule_id: handicap-total-goals-divergence, reason: 总进球缺少合格精确序列。}
- {rule_id: hidden-draw-away-cut-v1, reason: 未满足可验证的同源三节点条件。}
- {rule_id: score-baseline-v1, reason: Contract 7 总进球 pass，比分不得生成。}
- {rule_id: total-goals-cross-market-v1, reason: 没有两家独立机构的同档三节点确认。}
- {rule_id: handicap-inducement-resistance, reason: 不把盘口事实归因于诱盘。}
- {rule_id: asian-european-divergence, reason: 已作为基础门禁 pass 原因，不生成方向性结论。}
- {rule_id: cross-related-same-pattern, reason: 检索案例不具备同联赛同质量可统计可比性。}
- {rule_id: market-heat-chip-distribution, reason: 无独立结构化资金或热度事实。}
- {rule_id: quarter-low-water-inducement-v1, reason: 机构间盘口档位不一致且基础门禁为 pass。}
- {rule_id: late-market-reversal, reason: 未见可验证的跨档反转链。}
- {rule_id: operator-market-divergence, reason: 分歧仅支持 pass，不单独导出方向。}
- {rule_id: deep-line-stable-cover-v1, reason: 本场不是一球以上深盘。}
- {rule_id: korea-deep-line-loss-tolerance-v1, reason: 非韩国赛事。}
source_refs:
- matches/2026/08/2026-08-07_J联赛_横滨水手_vs_鹿岛鹿角.md#market_snapshots
- raw/matches/20260807-competition-u-c98cb4479c-team-u-079fab7a3b-team-u-845af72b83/journal/2026/08/20260807T154100_journal-20260807154100-9fe17c06de/source.md
scenario_instance_ids: []
case_ids:
- 20260730-bra-serie-a-mirassol-remo
- 20260730-bra-serie-a-fluminense-bahia
- 20260730-bra-serie-a-vitoria-palmeiras
- 20260730-bra-serie-a-internacional-flamengo
- legacy-hjk-tps
- legacy-gais-halmstad
- legacy-seoul-ulsan
- legacy-hacken-aik
- legacy-incheon-bucheon
- legacy-gimcheon-daejeon
ruleset_origin: published
deterministic_rule_ids:
- draw-kelly-parity-v1
- deep-line-stable-cover-v1
- quarter-low-water-inducement-v1
- hidden-draw-away-cut-v1
- total-goals-cross-market-v1
- score-baseline-v1
disposition_rule_ids: []
control_rule_ids:
- trend-purity-v1
- provider-consensus-divergence-v1
- cross-dimension-netting-v1
- late-market-anomaly-v1
- single-kelly-value-guard-v1
profile_chain: [global]
evaluation_bundle_sha256: 05d603259cf62e2d120df507d60f485b704605abea408669e4ee615fa0789945
```
<!-- analysis-trace:end -->


## 机器市场状态

- 无判断：one_x_two：theoretical_positioning_unavailable_no_structured_team_facts；unexplained_asian_european_favorite_divergence；asian_handicap：theoretical_positioning_unavailable_no_structured_team_facts；unexplained_asian_european_favorite_divergence；fixed_handicap_1x2：theoretical_positioning_unavailable_no_structured_team_facts；unexplained_asian_european_favorite_divergence；total_goals：theoretical_positioning_unavailable_no_structured_team_facts；unexplained_asian_european_favorite_divergence；score：theoretical_positioning_unavailable_no_structured_team_facts；unexplained_asian_european_favorite_divergence
