# 奥胡斯 VS 萨巴赫 盘面完整推演（数据截止：2026-08-05 17:48）

比赛时间：2026-08-06 00:30

场地：未记录

比赛类型：欧冠资格赛

### 一、澳盘时序梳理与盘路定性

- 截止 `2026-08-05 17:48 +08:00`，澳门仅有一条可追溯的精确让球节点：主让 `0.75`，主水 `0.77`、客水 `1.01`。截图中的澳门初盘与即盘数值相同，但其实际报价时间未分开给出，不能据此认定全程稳定。
- 其他机构的端点显示主让收缩：36 从主让 `1.0` 到 `0.75`，威廉希尔从 `1.25` 到 `0.75`，Interwetten 从 `1.5` 到 `0.5`。它们支持“主队优势被压缩”的端点假设，却不构成可验证的连续退盘路径。
- 因此亚洲盘只保留客队受让与主队小胜/不穿盘风险，不能把它解释成资金流、诱盘或机构主动控赔。

### 二、胜平负欧赔走势

- 威廉希尔主胜 `1.40 -> 1.65`、客胜 `6.50 -> 4.50`；立博和 Interwetten 也同步抬高主胜、降低客胜至 `4.60`。这些端点与让球收缩在“削弱主队绝对优势”上相互印证。
- 反面是：多数当前主胜仍是三项最低赔率，主队并未失去胜平负首选资格。故胜平负不做客胜单向结论，而将平局和主队一球胜置于主要低比分簇。
- 必发截图仅被归档为交易事实，不用于推导资金因果或机构意图。

### 三、凯利指数交叉验证

- 终盘汇总中客胜凯利最小值为 `0.82`，低于主胜 `0.93` 与平局 `0.87`；多家机构主胜凯利较初盘上行，客胜端出现收敛。这与欧赔端点的风险重估一致。
- 凯利与欧赔来自同批机构和同一截图，属于相关证据，合成时按既定矩阵对凯利半权处理；不把同一信息重复计权。
- 该维度不能单独判断赛果，也不能证明市场真实赔付压力。

### 四、大小球辅助参考

- 澳门和 36 维持 `2.75`，立博、威廉希尔、Interwetten 为 `2.5`。在 `2.5` 档位，后三家终盘小球水位低于初盘，支持总进球向中低区间收敛的轻度假设。
- 但 `2.5` 与 `2.75` 并存，各家初末价格也不完全同向；跨档水位不可相减。因此总进球只给 `1-2` 的保守核心区间，并保留 3 球风险。

### 五、综合权重推演

- 胜平负优先级：平局 > 主胜 > 客胜。平局领先反映让球收缩、欧赔及凯利端点共同保留的风险，而非否定主队主场胜率。
- 亚洲让球优先级：客队受让 > 主队让球。当前参考线为主让 `0.75`；主队若取胜，仍需重点区分一球胜与净胜两球以上。
- 固定让球胜平负优先级：让负 > 让平 > 让胜。固定让球 `-1` 仅由当前亚洲线换算为分析口径，并非独立官方固定让球市场报价。
- 总进球：`1-2`；这是由 `2.5/2.75` 多层盘口及低比分端点假设形成的保守区间，不是对精确总数的承诺。
- 比分权重：`1-1`、`1-0`。两个比分均服务于“主队仍可小胜、但平局风险上升”的同一低比分簇。
- 校准规则处置：`trend-purity-v1` 与 `provider-consensus-divergence-v1` 已触发并采纳为降级控制，未提升或替换任何候选；其余规则没有满足本场可验证输入或不适用条件。

### 六、后市观测清单

- 正向强化信号：若临场主让恢复到 `1.0` 或更深，且威廉希尔、立博、Interwetten 同步压低主胜，主队优势恢复的假设获得支持，需重新启动分析。
- 风险预警信号：若主让继续向 `0.5` 收缩，同时欧赔继续抬高主胜并压低客胜，当前的客队受让与平局风险会强化；仍须以新截图的精确时间节点为准。
- 失效条件：补入至少三个同机构、同档位、同赔率格式的精确澳门赛前节点后，现有降级结论不得沿用，必须执行 `analysis restart` 并重新生成回执。

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 2
ruleset_id: football-analysis
ruleset_version: 1.5.0
data_cutoff_at: '2026-08-05T17:48:00+08:00'
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
- fact:market-archive-20260805T174800
- fact:macau-single-exact-node
- fact:asian-handicap-endpoints
- fact:european-odds-endpoints
- fact:kelly-endpoints
- fact:total-goals-endpoints
scenario_instance_ids: []
case_ids:
- legacy-seoul-ulsan
- legacy-gimcheon-daejeon
- legacy-hacken-aik
- legacy-rosenborg-fredrikstad
- legacy-hjk-tps
- legacy-flamengo-sao-paulo
- legacy-gremio-fluminense
- legacy-incheon-bucheon
- legacy-anyang-gangwon
- legacy-gais-halmstad
ruleset_origin: published
deterministic_rule_ids:
- trend-purity-v1
- provider-consensus-divergence-v1
disposition_rule_ids:
- trend-purity-v1
- provider-consensus-divergence-v1
control_rule_ids:
- trend-purity-v1
- provider-consensus-divergence-v1
profile_chain:
- global
evaluation_bundle_sha256: ba747c34e7af03bab2835e3fa1df05801971566c301ad869d2fd04d8f2591bc8
```
<!-- analysis-trace:end -->
