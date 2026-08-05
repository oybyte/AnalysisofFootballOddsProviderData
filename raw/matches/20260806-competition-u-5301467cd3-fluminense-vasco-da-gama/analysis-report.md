# 弗鲁米嫩塞 VS 瓦斯科达伽马 盘面完整推演（数据截止：2026-08-05 16:36）

比赛时间：2026-08-06 08:30

场地：未记录

比赛类型：巴西杯

### 一、澳盘时序梳理与盘路定性

数据截止至 2026-08-05 16:36。澳门可确认的两个节点由主让半球 `1.02 / 0.76` 退至主让平半 `0.84 / 0.94`。36 与威廉希尔的初末端点同样由半球退至平半；Interwetten 守住半球，但其下盘处于低水。让步的共识是主队优势收缩，不能把 Interwetten 的独立报价当作主队强化。

反证是澳门缺少中盘节点，无法确认过程是否单向；因此本场不是完整趋势场景，只能按降级盘口端点评估。

### 二、胜平负欧赔走势

澳彩主胜由 2.02 升至 2.14，威廉希尔由 1.91 升至 2.20，立博、Interwetten 和 Betfair 亦提高主胜价格。客胜价格多数收窄或相对主胜更受支撑，胜平负排序为客胜、平局、主胜。平局价格方向不一致，故平局仅作第二候选，不单独放大。

### 三、凯利指数交叉验证

澳门即盘客胜凯利为 0.81，且六家均值客胜从 0.98 降至 0.91，和让球、欧赔的客队方向一致。Betfair 客胜凯利上行至 1.00，说明该维度不能独立确认，只提供弱交叉支持。

### 四、大小球辅助参考

澳门总进球由 2.25 降至 2.0；36、立博、威廉希尔和 Interwetten 在同档 2.5 均压低小球水位。总进球基准区间为 1 至 2 球。澳门跨档后大球水位同步下调，跨档水位不可相减，因此不将其描述为大球或小球的连续单边资金趋势。

### 五、综合权重推演

- 胜平负优先级：客胜、平局、主胜。
- 亚洲让球优先级：瓦斯科达伽马受让平半、弗鲁米嫩塞让平半。
- 固定让球胜平负优先级：主让一球让平、让负。
- 总进球：1 至 2 球。
- 比分权重：0-1、1-1。
- 校准规则处置：`trend-purity-v1` 与 `provider-consensus-divergence-v1` 虽触发控制信号，但分别缺少三节点和统一观察时间，均已排除，未改变基础排序。

本次为 `degraded`：没有可追溯阵容、伤停和赛程材料，澳门仅有两个精确节点；评分中的缺失维度不重分配，置信度不得高于 0.69。

### 六、后市观测清单

- 正向强化信号：临场仍维持主让平半或进一步缩浅，且多家主胜欧赔继续上调；2.5 档小球保持低水。
- 风险预警信号：澳门及多家主流机构恢复主让半球，同时主胜欧赔同步下调；或总进球恢复 2.25/2.5 且同档出现连续大球降水。出现任一情况应重新启动分析，而不是修改本次回执。

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 2
ruleset_id: football-analysis
ruleset_version: 1.5.0
ruleset_origin: published
data_cutoff_at: '2026-08-05T16:36:00+08:00'
applied_rule_ids:
  - football-analysis-framework
  - market-settlement-rules
  - data-provenance-time-boundary
  - market-timeline-cross-validation
  - dual-hypothesis-evidence
  - layered-decision-confidence-pass
  - goals-score-separation
  - data-quality-conflict-and-pass
  - scenario-identification-and-case-retrieval
excluded_rules:
  - {rule_id: prematch-stage-positioning, reason: 未提供可追溯基本面。}
  - {rule_id: theoretical-vs-actual-market, reason: 仅按盘口端点评估。}
  - {rule_id: prematch-checklist-v1, reason: 本次未进入锁定流程。}
  - {rule_id: live-update-and-postmatch-separation, reason: 本次没有临场或赛后材料。}
  - {rule_id: korea-goal-drop-v1, reason: 巴西杯不适用韩国联赛规则。}
  - {rule_id: handicap-total-goals-divergence, reason: 缺少可验证的完整同窗趋势。}
  - {rule_id: handicap-inducement-resistance, reason: 机构意图无法由端点数据确认。}
  - {rule_id: water-threshold-operator-style, reason: 缺少三节点同档水位序列。}
  - {rule_id: low-stability-league-weight-calibration, reason: 巴西杯不属于配置的低稳定联赛。}
  - {rule_id: asian-european-divergence, reason: 两市场均指向主队优势收缩。}
  - {rule_id: market-heat-chip-distribution, reason: 交易量无法证明资金因果。}
  - {rule_id: draw-kelly-parity-v1, reason: 凯利离散度未达阈值。}
  - {rule_id: cross-related-same-pattern, reason: 缺少独立同型场景证据。}
  - {rule_id: operator-market-divergence, reason: 初末端点的观察时间不统一。}
  - {rule_id: late-market-reversal, reason: 澳门没有中盘节点验证回撤。}
  - {rule_id: total-goals-cross-market-v1, reason: 触发阈值未满足。}
  - {rule_id: quarter-low-water-inducement-v1, reason: 触发阈值未满足。}
  - {rule_id: score-baseline-v1, reason: 触发阈值未满足。}
  - {rule_id: korea-deep-line-loss-tolerance-v1, reason: 巴西杯不适用韩国联赛规则。}
  - {rule_id: hidden-draw-away-cut-v1, reason: 可比较输入不足。}
  - {rule_id: deep-line-stable-cover-v1, reason: 深盘三节点输入不足。}
source_refs:
  - raw:matches/20260806-competition-u-5301467cd3-fluminense-vasco-da-gama/journal/2026/08/20260805T163600_journal-20260805163600-380b990850/source.md
scenario_instance_ids: []
case_ids:
  - 20260730-bra-serie-a-fluminense-bahia
  - legacy-gremio-fluminense
  - legacy-seoul-ulsan
  - legacy-gimcheon-daejeon
  - legacy-rosenborg-fredrikstad
  - legacy-hacken-aik
  - legacy-20260803-internacional-team-u-731c351377
  - 20260730-bra-serie-a-vitoria-palmeiras
  - 20260730-bra-serie-a-mirassol-remo
  - legacy-incheon-bucheon
deterministic_rule_ids:
  - draw-kelly-parity-v1
  - deep-line-stable-cover-v1
  - quarter-low-water-inducement-v1
  - hidden-draw-away-cut-v1
  - total-goals-cross-market-v1
  - score-baseline-v1
  - trend-purity-v1
  - provider-consensus-divergence-v1
  - cross-dimension-netting-v1
  - late-market-anomaly-v1
  - single-kelly-value-guard-v1
disposition_rule_ids: [trend-purity-v1, provider-consensus-divergence-v1]
control_rule_ids: [trend-purity-v1, provider-consensus-divergence-v1]
profile_chain: [global]
evaluation_bundle_sha256: f806bad29ecc92ea66b30184bc70007420b5ed6c66bbfdfdedc5e7cee6192ecc
```
<!-- analysis-trace:end -->
