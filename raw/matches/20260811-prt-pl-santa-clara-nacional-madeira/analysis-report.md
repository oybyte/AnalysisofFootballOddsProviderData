# 圣克拉拉 VS 葡萄牙国民 盘面完整推演（数据截止：2026-08-10 17:01）

比赛时间：2026-08-11 03:15

场地：未记录

比赛类型：葡超

### 一、澳盘时序梳理与盘路定性

**澳门盘路（08-06 初盘 → 08-10 即盘）：**

| 时间 | 主队水位 | 盘口 | 客队水位 | 变化 |
|------|---------|------|---------|------|
| 08-06 21:26（初盘） | 0.84 | 0.5 | 0.94 | — |
| 08-10 15:43（即盘） | 0.80 | 0.5 | 0.98 | 主水↓0.04，客水↑0.04 |

澳门盘路定性：盘口维持 0.5 不变，但主队水位从 0.84 降至 0.80，客队水位从 0.94 升至 0.98。水位变化方向与盘口方向一致，属于**正向降水**，表明机构对主队信心增强。但澳门缺少中盘节点，三节点时序不完整。

**跨机构盘口比较：**

| 机构 | 初盘 | → | 即盘 | 变化幅度 |
|------|------|---|------|----------|
| bet365 | 0.83/0.25/1.03 | → | 1.05/0.75/0.80 | **↑2档（0.25→0.75）** |
| 威廉希尔 | 0.80/0.25/0.97 | → | 0.85/0.5/0.85 | ↑1档（0.25→0.5） |
| 澳门 | 0.84/0.5/0.94 | → | 0.80/0.5/0.98 | 不变，降水 |
| Interwetten | 1.10/0.5/0.70 | → | 0.85/0.5/0.95 | 不变，主水大幅回落 |

- **bet365 升盘幅度最大**：从 0.25 升至 0.75，连升两档，且主队水位从 0.83 升至 1.05（高水阻盘）。这是典型的升盘阻上信号——机构通过深盘+高水组合压制主队热度。
- **威廉希尔跟升**：从 0.25 升至 0.5，水位回到 0.85 中低水区间。
- **澳门和 Interwetten 未升盘**：维持 0.5 盘口，但主水均下降。澳门 0.80 → 低水区域，对主队有利。
- **机构分歧**：bet365 已到 0.75 深盘，威廉希尔 0.5，澳门 0.5，这是典型的"分层升盘"——大机构（bet365）领升，其他机构跟进。此形态符合 `operator-market-divergence` 启发式规则中对"逐步收敛型升盘"的识别。

**盘路定性：偏主队方向。** 多机构一致升盘/降水，bet365 领升两档，澳门低水维持。初盘 0.25 区间（bet365/威廉希尔）已被突破，市场共识向主队方向偏移。

---

### 二、胜平负欧赔走势

| 机构 | 初盘主胜 | 初盘平局 | 初盘客胜 | 即盘主胜 | 即盘平局 | 即盘客胜 |
|------|---------|---------|---------|---------|---------|---------|
| 澳门 | 2.10 | 3.24 | 3.71 | 1.80 | 3.24 | 3.90 |
| 威廉希尔 | 2.10 | 3.10 | 3.50 | 1.83 | 3.25 | 4.40 |
| 立博 | 2.10 | 3.25 | 3.50 | 1.85 | 3.40 | 4.40 |
| Interwetten | 2.10 | 3.30 | 3.55 | 1.85 | 3.35 | 4.50 |
| Betfair | 1.96 | 3.30 | 4.40 | 1.89 | 3.55 | 5.10 |
| bet365 | — | — | — | 1.80 | 3.30 | 4.75 |

**核心变化：**
- **主胜赔率全面下降**：五家机构初盘集中在 2.10，即盘降至 1.80-1.89 区间，降幅 0.21-0.25，属于中幅降赔。
- **客胜赔率全面上升**：从 3.50-3.71 升至 3.90-5.10，其中 Betfair 客胜从 4.40 升至 5.10（+0.70），幅度最大。
- **平局赔率变化分化**：澳门平局不变（3.24），其余机构微升 0.05-0.25（3.10→3.25, 3.25→3.40, 3.30→3.35）。Betfair 平局升幅最大（3.30→3.55）。

**欧赔定性：**
- 主胜降赔 + 客胜升赔 + 平局微升 → 典型的主胜方向收敛。
- 澳门平赔 3.24 不变，与其他机构 3.25-3.55 形成对比——澳门对平局的保留态度值得关注。但整体平赔仍处于 3.24-3.55 区间，属于正常偏高范围，平局保护力度一般。
- 欧赔与亚盘方向一致（主胜降赔 + 亚盘升盘），无亚欧背离信号。

---

### 三、凯利指数交叉验证

| 机构 | 主胜凯利 | 平局凯利 | 客胜凯利 |
|------|---------|---------|---------|
| 澳门 | 0.92 | 0.91 | 0.81 |
| bet365 | 0.92 | 0.92 | 0.99 |
| 威廉希尔 | 0.94 | 0.91 | 0.91 |
| 立博 | 0.95 | 0.95 | 0.91 |
| Interwetten | 0.95 | 0.94 | 0.93 |
| Betfair | 0.97 | 0.99 | 1.06 |
| **6家平均** | **0.94** | **0.94** | **0.93** |

**凯利交叉验证：**
- 主胜凯利 0.92-0.97，均值 0.94，处于正常偏低区间，无明显异常。
- 平局凯利 0.91-0.99，均值 0.94。澳门平局凯利 0.91 为最低，与平赔 3.24 不变形成呼应——澳门在平局方向有轻微保留。
- 客胜凯利 0.81-1.06，离散度最大。澳门客胜凯利 0.81 最低，Betfair 客胜凯利 1.06 最高。Betfair 客胜凯利 > 1.0，表明该机构对客胜的赔付风险较高。
- **平局凯利与主胜凯利均值持平（0.94 vs 0.94）**，不存在明显的平局凯利偏低信号。触发 `draw-kelly-parity-v1` 校准规则的前置条件（平局凯利 ≤ 主胜凯利 - 0.03）不满足，平局方向不适用该规则调整。

**凯利定性：支持主胜方向，平局和客胜无明显凯利异常。**

---

### 四、大小球辅助参考

| 机构 | 即盘大球水位 | 盘口 | 即盘小球水位 | 变化 |
|------|------------|------|------------|------|
| 澳门 | 0.88 | 2.25 | 0.84 | 无变化 |
| bet365 | 0.98 | 2.25 | 0.88 | 无变化 |
| 立博 | 1.20 | 2.5 | 0.60 | 大球水位↑0.05 |
| 威廉希尔 | 1.15 | 2.5 | 0.65 | 大球水位↓0.05 |
| Interwetten | 1.15 | 2.5 | 0.67 | 大球水位不变 |

**大小球分析：**
- 澳门和 bet365 维持 2.25 盘口不变，大小球水位持平或接近（澳门 0.88/0.84，bet365 0.98/0.88）。
- 立博、威廉希尔、Interwetten 维持 2.5 盘口。
- 盘口分歧：澳门/bet365 在 2.25，其他机构在 2.5。2.25 是更保守的盘口设置。
- 大球水位整体偏高（0.88-1.20），小球水位偏低（0.60-0.88），市场偏向小球方向。
- 触发 `total-goals-cross-market-v1` 校准规则：亚盘升盘方向（主胜）与大小球 2.25 保守盘口形成对照——主胜方向不必然伴随大球。

**大小球定性：偏小球方向（≤2球），与主队让球升盘形成交叉背离，需要降低总进球预期。**

---

### 五、综合权重推演

**胜平负优先级：**
- 主胜 > 平局 > 客胜
- 主胜：欧赔全面降赔（2.10→1.80），亚盘多机构升盘，凯利支持，必发交易量主胜占 52% → **首选**
- 平局：澳门平赔不变+平局凯利 0.91 最低，存在轻微保留，但整体平赔偏高（3.24-3.55）→ 次选
- 客胜：欧赔全面升赔，凯利离散度高，Betfair 凯利 1.06 异常 → 末选

**亚洲让球优先级：**
- 主队 -0.5（澳门即盘） > 主队 -0.75（bet365 即盘）
- 澳门 0.5 盘口低水 0.80 是核心参考，bet365 0.75 深盘高水 1.05 是阻盘信号
- 首选：主队 -0.5 @ 0.80（澳门水位）

**固定让球胜平负优先级：**
- 主队 -1 胜平负：基于主队 -0.5 盘口，-1 让球后的胜平负需要主队净胜 2 球
- 结合大小球 2.25 盘口偏小球方向，主队大胜概率不高
- 主队 -1 平局（主队赢 1 球）> 主队 -1 胜（主队赢 ≥2 球）

**总进球：**
- 触发 `total-goals-cross-market-v1`：亚盘升盘 + 大小球 2.25 保守盘口 → 交叉背离
- 澳门 2.25 盘口小球水位 0.84 偏低，机构倾向小球
- 总进球区间：**1-2 球**（偏小球方向）

**比分权重：**
- 触发 `score-baseline-v1` 规则
- 1-0（主胜小胜）：大小球偏小 + 主队让 0.5 盘口，一球小胜概率最高
- 2-0（主胜两球）：若主队攻击力充足，有两球可能，但大小球 2.25 盘口不支持
- 比分参考：**1-0 > 2-0 > 1-1**

**校准规则处置：**
- `draw-kelly-parity-v1`：不触发（平局凯利 0.94 不低于主胜凯利 0.94 - 0.03）
- `deep-line-stable-cover-v1`：bet365 升盘 0.25→0.75 属于深盘覆盖信号，正向增强主胜
- `quarter-low-water-inducement-v1`：澳门 0.5 盘口 0.80 低水，不属于 0.25 盘口低水诱盘，不触发
- `hidden-draw-away-cut-v1`：澳门平赔 3.24 不变 + 客胜升赔，属于平局隐藏信号，需要关注但不改变主胜首选
- `total-goals-cross-market-v1`：触发，亚盘升盘 vs 大小球 2.25 保守盘口 → 交叉背离，降低总进球预期
- `score-baseline-v1`：触发，结合让球盘口和大小球盘口，比分区间 1-0 至 2-0
- `trend-purity-v1`：多机构一致升盘/降水，趋势纯度较高
- `provider-consensus-divergence-v1`：bet365 0.75 vs 澳门 0.5，存在分歧，但方向一致（均看好主队），分歧程度可控
- `cross-dimension-netting-v1`：欧赔降赔 + 亚盘升盘 + 凯利支持 → 三维度一致，主胜方向信号强度高
- `late-market-anomaly-v1`：bet365 升盘两档属于显著变化，但无回撤或反转，不触发异常
- `single-kelly-value-guard-v1`：Betfair 客胜凯利 1.06 > 1.0，触发客胜方向单点凯利警戒，进一步降低客胜概率

---

### 六、后市观测清单

**正向强化信号：**
- 澳门中盘节点出现（若 08-10 晚间/08-11 凌晨有更新），确认是否继续降水或升盘
- 其他机构进一步跟随 bet365 升至 0.75 盘口
- 澳门主胜欧赔进一步降至 1.75 以下
- 必发交易量主胜占比继续扩大（> 55%）

**风险预警信号：**
- 澳门平赔 3.24 维持不变是隐藏的平局风险（`hidden-draw-away-cut-v1` 关注）
- bet365 若从 0.75 回调至 0.5，属于深盘回撤，需警惕主队过热
- 大小球 2.25 盘口若进一步降至 2.0，主队大胜概率进一步降低
- 临场水位若出现澳门主水从 0.80 升至 0.85+，属于反向信号

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 2
ruleset_id: football-analysis
ruleset_version: 1.8.0
data_cutoff_at: '2026-08-10T17:01:11+08:00'
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
  reason: '低稳定性联赛权重校准规则，葡超使用 global profile，不适用'
source_refs:
- user-screenshot:macau-detail-20260810
- user-screenshot:asian-handicap-table-20260810
- user-screenshot:european-odds-table-20260810
- user-screenshot:total-goals-table-20260810
- user-screenshot:kelly-index-table-20260810
- user-screenshot:betfair-exchange-20260810
scenario_instance_ids: []
case_ids:
- legacy-seoul-ulsan
- legacy-pohang-jeonbuk
- legacy-incheon-bucheon
- legacy-gimcheon-daejeon
- legacy-hjk-tps
- legacy-hacken-aik
- legacy-rosenborg-fredrikstad
- legacy-gwangju-jeju
- legacy-gais-halmstad
- legacy-malmo-elfsborg
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
evaluation_bundle_sha256: ac1fba89ea6c4598138a622db1f29f7c2280ee4980359242dd488ff3d0331380
```
<!-- analysis-trace:end -->


## 机器市场状态

- 无判断：total_goals：insufficient_independent_exact_series；score：total_goals_score_separation
