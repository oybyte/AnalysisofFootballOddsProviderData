# 圣克拉拉 VS 葡萄牙国民 盘面完整推演（数据截止：2026-08-10 17:56）

比赛时间：2026-08-11 03:15

场地：未记录

比赛类型：葡超

### 一、澳盘时序梳理与盘路定性

**澳门盘路（08-06 初盘 → 08-10 即盘）：**

| 时间 | 主队水位 | 盘口 | 客队水位 | 变化 |
|------|---------|------|---------|------|
| 08-06 21:26（初盘） | 0.84 | 0.5 | 0.94 | — |
| 08-10 15:43（即盘） | 0.80 | 0.5 | 0.98 | 主水↓0.04，客水↑0.04 |

**盘路定性：偏主队方向。** 澳门维持主让0.5不变，主水从0.84降至0.80，客水从0.94升至0.98。盘口稳定+水位单向收敛，属典型的主队信心增强信号。

**多机构交叉验证：**

| 机构 | 初盘口 | 即盘口 | 方向 |
|------|--------|--------|------|
| bet365 | 0.25 | 0.75 | 主队升盘 |
| 威廉希尔 | 0.25 | 0.5 | 主队升盘 |
| Interwetten | 0.5 | 0.5 | 主水1.10→0.85 |

bet365和威廉希尔均从主让0.25升至0.5/0.75，Interwetten主水大幅下降。四家机构方向一致，机构共识度高。

### 二、胜平负欧赔走势

| 机构 | 初盘主胜 | 即盘主胜 | 变化 | 初盘客胜 | 即盘客胜 | 变化 |
|------|---------|---------|------|---------|---------|------|
| 澳门 | 2.10 | 1.80 | ↓0.30 | 3.71 | 3.90 | ↑0.19 |
| 威廉希尔 | 2.10 | 1.83 | ↓0.27 | 3.50 | 4.40 | ↑0.90 |
| 立博 | 2.10 | 1.85 | ↓0.25 | 3.50 | 4.40 | ↑0.90 |
| Interwetten | 2.10 | 1.85 | ↓0.25 | 3.55 | 4.50 | ↑0.95 |
| Betfair | 1.96 | 1.89 | ↓0.07 | 4.40 | 5.10 | ↑0.70 |

**欧赔定性：典型的主胜方向收敛。** 五家机构主胜赔率全面下降（降幅0.07-0.30），客胜赔率同步上升（升幅0.19-0.95）。平赔变化幅度较小（+0.01至+0.25），说明市场对平局的判断相对稳定。

### 三、凯利指数交叉验证

**即盘凯利（6家机构）：**

| 项目 | 主胜 | 平局 | 客胜 |
|------|------|------|------|
| 最大值 | 0.97 | 0.99 | 1.06 |
| 最小值 | 0.92 | 0.91 | 0.81 |
| 6家平均 | 0.94 | 0.94 | 0.93 |

**凯利定性：支持主胜方向。** 主胜凯利均值0.94处于合理区间，客胜凯利均值0.93但Betfair高达1.06，存在高凯利赔付风险。澳门凯利0.92/0.91/0.81显示主胜和平局接近，客胜最低。

### 四、大小球辅助参考

| 机构 | 初盘 | 即盘 | 大球水位 | 小球水位 |
|------|------|------|---------|---------|
| 澳门 | 2.25 | 2.25 | 0.88 | 0.84 |
| bet365 | 2.25 | 2.25 | 0.98 | 0.88 |
| 立博 | 2.5 | 2.5 | 1.20 | 0.60 |

**大小球定性：偏小球。** 三机构盘口均未变化，澳门和bet365仅2.25的浅盘搭配低水小球，立博2.5盘口小球水位极低（0.60），市场整体倾向小球方向。

### 五、综合权重推演

**胜平负优先级：** 主胜 > 平局 > 客胜
**亚洲让球优先级：** 主队 -0.5（澳门即盘）
**固定让球胜平负优先级：** 主队 -1（由亚盘0.5推导）
**总进球：** 偏小球（1-2球）
**比分权重：** 1-0 > 2-0 > 1-1

**校准规则处置：**
- 趋势纯度（trend-purity-v1）：触发，主水从0.84→0.80全程无回撤
- 机构共识（provider-consensus-divergence-v1）：触发，四家机构方向一致

### 六、后市观测清单

**正向强化信号：**
- 临场澳门主水继续下降至0.75以下
- bet365维持0.75深盘且主水不升破1.05
- 欧赔主胜进一步降至1.75以下

**风险预警信号：**
- 临场澳门主水回升至0.85以上
- bet365从0.75回调至0.5
- 欧赔平赔大幅下降

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 2
ruleset_id: football-analysis
ruleset_version: 1.8.0
data_cutoff_at: '2026-08-10T17:56:49+08:00'
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
- handicap-total-goals-divergence
- handicap-inducement-resistance
- asian-european-divergence
- market-heat-chip-distribution
- draw-kelly-parity-v1
- total-goals-cross-market-v1
- water-threshold-operator-style
- cross-related-same-pattern
- operator-market-divergence
- late-market-reversal
- quarter-low-water-inducement-v1
- hidden-draw-away-cut-v1
- score-baseline-v1
- deep-line-stable-cover-v1
excluded_rules:
- rule_id: korea-deep-line-loss-tolerance-v1
  reason: 非韩K联赛，不适用
- rule_id: korea-goal-drop-v1
  reason: 非韩K联赛，不适用
- rule_id: low-stability-league-weight-calibration
  reason: 低稳定性联赛权重校准规则，葡超使用 global profile，不适用
source_refs:
- user-screenshot:macau-detail-20260810
- user-screenshot:asian-handicap-table-20260810
- user-screenshot:european-odds-table-20260810
- user-screenshot:total-goals-table-20260810
- user-screenshot:kelly-index-table-20260810
- user-screenshot:betfair-exchange-20260810
scenario_instance_ids: []
case_ids:
- legacy-gimcheon-daejeon
- legacy-seoul-ulsan
- legacy-pohang-jeonbuk
- legacy-incheon-bucheon
- legacy-hjk-tps
- legacy-hacken-aik
- legacy-rosenborg-fredrikstad
- legacy-malmo-elfsborg
- legacy-flamengo-sao-paulo
- legacy-gremio-fluminense
ruleset_origin: published
deterministic_rule_ids:
- trend-purity-v1
- provider-consensus-divergence-v1
- cross-dimension-netting-v1
disposition_rule_ids:
- deep-line-stable-cover-v1
- total-goals-cross-market-v1
- score-baseline-v1
control_rule_ids:
- draw-kelly-parity-v1
- hidden-draw-away-cut-v1
- quarter-low-water-inducement-v1
- late-market-anomaly-v1
- single-kelly-value-guard-v1
profile_chain:
- global
evaluation_bundle_sha256: db7ba5aaec7a9247fe07eaf45f554543a2bf62daa2563b05fd7127a57ff67fa6
```
<!-- analysis-trace:end -->


## 机器市场状态

- 无判断：total_goals：insufficient_independent_exact_series；score：total_goals_score_separation
