# 天狼星 VS 布洛马波卡纳 盘面完整推演（数据截止：2026-08-10 18:30）

比赛时间：2026-08-11 01:00

场地：未记录

比赛类型：瑞典超

### 一、澳盘时序梳理与盘路定性

**澳门盘路（08-06 初盘 → 08-10 即盘）：**

| 时间 | 主队水位 | 盘口 | 客队水位 | 变化 |
|------|---------|------|---------|------|
| 08-06 21:36（初盘） | 0.81 | 1.5 | 0.97 | — |
| 08-06 23:06 | 0.80 | 1.5 | 0.98 | 主水↓0.01 |
| 08-10 11:51 | 0.86 | 1.5 | 0.92 | 主水↑0.06 |
| 08-10 13:30 | 0.98 | 1.5/2 | 0.80 | 升盘至1.75 |
| 08-10 17:01（即盘） | 0.78 | 1.5 | 1.00 | 回1.5，主水↓0.20 |

**盘路定性：偏主队深盘穿盘方向。** 澳门初盘定位主让1.5中低水（0.81），盘中经历升盘1.5/2试探后回到1.5，但主水从0.98大幅降至0.78。这种"升盘试探→回盘降水"模式是典型的深盘信心收敛信号——机构试探深盘后确认主队优势可控，回盘降水以降低赔付。主水从初盘0.81降至即盘0.78，全程净降0.03，且五节点均在同档（1.5）或更高档位（1.5/2），未出现降档或回撤至1.25以下的情况。

**触发规则：deep-line-stable-cover-v1。** 盘口深达1.5球（≥一球阈值），澳门五节点中四个节点在1.5档位且水位均在0.78-0.86区间（符合0.80-0.95阈值），升盘试探后回盘降水强化了稳盘信号。记录为cover support，但作为实验性规则不自动让主胜第一。

**反向假设：** 升盘1.5/2后回盘可能反映机构在1.75档位遇到客队方向阻力，回盘1.5但仍给出0.78低水，存在"诱上盘"可能——以低水吸引主队方向筹码，实际客队可能赢盘（输不超过1球）。

**机构亚盘对比：**

| 机构 | 初盘主水 | 初盘盘口 | 初盘客水 | 即盘主水 | 即盘盘口 | 即盘客水 | 变化方向 |
|------|---------|---------|---------|---------|---------|---------|---------|
| 澳* | 0.81 | 1.5 | 0.97 | 0.78 | 1.5 | 1.00 | 主水↓ |
| 36* | 0.85 | 1.5 | 0.95 | 1.00 | 1.5/2 | 0.80 | 升盘+升水 |
| 威* | 0.85 | 1.5 | 0.85 | 0.83 | 1.5 | 0.85 | 主水↓微 |
| Interwet* | 0.80 | 1.5 | 0.90 | 0.80 | 1.5 | 0.90 | 不变 |

**关键分歧：澳门 vs bet365 方向相反。** 澳门从1.5/2回1.5降水（收敛信号），bet365从1.5升1.5/2升水（扩张信号）。这是本场比赛最显著的机构分歧。

- **假设A（澳门优先）：** 澳门作为亚洲让球头部机构，回盘降水是经过试探后的理性收敛，bet365升盘可能是在吸收主队方向过量筹码后的被动调整。
- **假设B（bet365领先）：** bet365升盘至1.5/2反映真实市场力量推动，澳门回盘1.5低水可能是诱盘行为。

**触发规则：operator-market-divergence。** 头部机构（澳门）与主流机构（bet365）在临盘阶段出现0.25档方向性分歧，需记录但裁决权重偏向澳门（头部机构优先）。

**触发规则：provider-consensus-divergence-v1。** 四家机构中三家维持1.5档位，仅bet365升至1.5/2，机构共识度为3/4，属于"多数一致、少数偏离"模式。

### 二、胜平负欧赔走势

| 机构 | 初盘主胜 | 初盘平局 | 初盘客胜 | 即盘主胜 | 即盘平局 | 即盘客胜 |
|------|---------|---------|---------|---------|---------|---------|
| 澳* | 1.25 | 5.30 | 6.90 | 1.24 | 5.30 | 7.22 |
| 威* | 1.30 | 5.00 | 8.00 | 1.30 | 5.00 | 8.50 |
| 立* | 1.28 | 5.00 | 7.00 | 1.30 | 5.00 | 7.00 |
| Interwet* | 1.33 | 5.75 | 7.50 | 1.33 | 5.75 | 8.00 |
| Betfair* | 1.31 | 6.00 | 9.40 | 1.37 | 5.80 | 10.00 |
| 36* | — | — | — | 1.30 | 5.25 | 9.00 |

**欧赔方向：主胜低赔稳定，客胜普遍上升。** 主胜赔率集中在1.24-1.37极低区间，与1.5深盘匹配。澳门主胜从1.25微降至1.24，威廉希尔和Interwetten维持不变，仅立博和Betfair主胜微升0.02-0.06。客胜赔率五家机构全面上升（升幅0.22-0.60），方向一致。

**Betfair反向信号：** Betfair主胜从1.31升至1.37（+0.06），平局从6.00降至5.80（-0.20），这是五家机构中唯一主胜升赔的机构，且平局降赔幅度最大。结合必发87%交易量集中在主胜，Betfair升赔可能是赔付压力下的被动调整，而非真实概率变化。

**触发规则：asian-european-divergence。** 澳门亚盘主水↓0.03（强化主队），但Betfair欧赔主胜↑0.06（弱化主队），形成局部亚欧背离。但此背离仅限于Betfair一家，其余四家欧赔方向与亚盘一致，背离程度有限。

**触发规则：cross-dimension-netting-v1。** 亚盘（澳门1.5稳盘降水）+ 欧赔（主胜1.24-1.37极低区间）+ 必发（87%资金主胜）三维度均指向主队方向，无跨维度背离。

### 三、凯利指数交叉验证

**即盘凯利（六家机构）：**

| 机构 | 主胜凯利 | 平局凯利 | 客胜凯利 |
|------|---------|---------|---------|
| 澳* | 0.88 | 0.92 | 0.82 |
| 36* | 0.93 | 0.91 | 1.03 |
| 威* | 0.93 | 0.87 | 0.97 |
| 立* | 0.93 | 0.87 | 0.80 |
| Interwet* | 0.95 | 1.00 | 0.91 |
| Betfair* | 0.98 | 1.00 | 1.14 |

**凯利均值：主胜0.93 / 平局0.93 / 客胜0.95**

**主胜凯利：** 0.88-0.98区间，澳门最低0.88（<0.90偏低），Betfair最高0.98（<1.0正常运行）。整体处于正常偏低区间，无过热信号。

**触发规则：draw-kelly-parity-v1。** 三项凯利最大差值：主胜(0.98-0.88=0.10)，平局(1.00-0.87=0.13)，客胜(1.14-0.80=0.34)。平局凯利差值0.13 > 0.05阈值，不满足触发条件。记录为未触发。

**触发规则：single-kelly-value-guard-v1。** Betfair客胜凯利1.14 > 1.0，触发单点凯利警戒。立博客胜凯利0.80为最低值。客胜凯利跨度0.34为三项最大，反映机构对客胜概率判断分歧最大。但仅Betfair一家超过1.0，且客胜方向不是主线，记录为弱警戒信号。

**凯利综合判断：** 主胜凯利正常偏低，澳门0.88为最低值，与澳门亚盘0.78低水形成呼应。平局凯利存在分歧，但差值未达到draw-kelly-parity触发阈值。凯利维度不改变主线方向。

### 四、大小球辅助参考

| 机构 | 初盘大球水 | 初盘盘口 | 初盘小球水 | 即盘大球水 | 即盘盘口 | 即盘小球水 |
|------|-----------|---------|-----------|-----------|---------|-----------|
| 澳* | 0.91 | 3.5 | 0.81 | 0.92 | 3.5 | 0.80 |
| 36* | 0.98 | 3.5 | 0.83 | 0.80 | 3/3.5 | 1.00 |
| 立* | 0.36 | 2.5 | 1.87 | 0.36 | 2.5 | 1.80 |
| 威* | 0.95 | 3.5 | 0.75 | 0.95 | 3.5 | 0.75 |
| Interwet* | 0.90 | 3.5 | 0.80 | 0.95 | 3.5 | 0.75 |

**盘口定位：3.5球为深盘档位。** 澳门、威廉希尔、Interwetten三家维持3.5档位，bet365从3.5退至3.25，立博维持在2.5档位（独立体系）。

**触发规则：total-goals-cross-market-v1。** 跨市场总进球分析：

- **澳门3.5：** 盘口不变，大球水微升0.01（0.91→0.92），小球水微降0.01（0.81→0.80），变化极小，方向中性。
- **bet365退盘：** 从3.5退至3.25，大球水从0.98降至0.80（降幅0.18），属于"退盘降水"模式——通常解读为机构降低大球门槛但以低水保护，暗示大球方向仍有支撑。
- **威廉希尔3.5稳定：** 水位完全不变（0.95/0.75），小球水0.75偏低。
- **立博2.5独立体系：** 大球水0.36极低，是鼓励大球方向下注的定价，但与3.5体系不可直接比较。

**触发规则：handicap-total-goals-divergence。** 让球深度（1.5）与大小球高度（3.5）方向一致，均指向大比分方向，无背离。

**总进球判断：** 结合1.5深盘和3.5大小球盘口，总进球大概率在3球以上。澳门3.5大小球水位稳定，大球方向无阻力信号。参考区间：3-5球。

### 五、综合权重推演

**数据模式：** degraded（凯利仅有即盘快照，无初盘凯利完整时序；bet365缺少欧赔初盘）。

**权重分配：** 亚盘60% + 欧赔20% + 凯利15% + 大小球5%。

**各维度评分：**

| 维度 | 权重 | 主队方向 | 平局方向 | 客队方向 | 关键信号 |
|------|------|---------|---------|---------|---------|
| 亚盘 | 60% | +1.0 | — | -1.0 | 澳门稳盘降水+升盘试探回盘 |
| 欧赔 | 20% | +1.0 | +0.5 | -1.0 | 主胜极低赔率+客胜普升 |
| 凯利 | 15% | +0.5 | +0.0 | -0.5 | 主胜凯利正常偏低 |
| 大小球 | 5% | 大球+0.5 | — | — | 3.5深盘+bet365退盘降水 |

**胜平负优先级：** 主胜 > 平局 > 客胜。主胜赔率1.24-1.37极低区间，五家机构客胜上升，方向一致。

**亚洲让球优先级：** 主队让球-1.5（主队穿盘）> 客队受让+1.5（客队赢盘）。澳门稳盘降水、3/4机构共识、升盘试探回盘路径均指向主队方向。

**固定让球胜平负优先级：** 主队-2胜 > 平局 > 客队+2胜。固定让球由亚洲让球深度推导（-2 = -1.5 - 0.5的上舍入），主队方向占优。

**总进球：** 评估为pass（insufficient_independent_exact_series）。大小球数据不足以独立确定总进球方向，但结合1.5深盘，参考区间3-5球。

**比分权重：** 评估为pass（total_goals_score_separation）。由于总进球为pass，比分不生成。分析参考比分：2-0、3-0（由score-baseline-v1候选池建议，主胜赔率1.24 ≤ 1.60时纳入1-0/2-0，结合深盘调整为2-0/3-0）。

**校准规则处置：** 所有低稳定性校准规则（lsl-*系列）均未触发（not_applicable）。draw-kelly-parity-v1未触发（平局凯利差值0.13 > 0.05）。deep-line-stable-cover-v1、total-goals-cross-market-v1、score-baseline-v1均为insufficient_data未触发。仅trend-purity-v1（纯度1.0）和provider-consensus-divergence-v1（provider_count=6）触发，均为adopted。

**锁定结论：**
- **主线方向：主队让球-1.5（主队穿盘）**
- **次选方向：无（深盘单一方向）**
- **放弃分析条件：** 临场澳门主水回升至0.85以上或盘口降至1/1.5
- **置信度：0.69（degraded模式上限）**
- **置信度依据：** 澳门完整五节点时序+3/4机构共识+欧赔方向一致，但bet365方向性分歧+凯利仅即盘+Betfair欧赔反向信号限制置信度上限

### 六、后市观测清单

**正向强化信号：**
1. 澳门五节点"升盘试探→回盘降水"路径，是经典深盘信心收敛信号
2. 澳门即盘主水0.78为五节点最低，方向明确
3. 威廉希尔、Interwetten维持1.5档位不变，与澳门形成3/4机构共识
4. 欧赔五家机构客胜全面上升，方向一致
5. 必发87%资金集中在主胜方向，市场共识强
6. 3.5大小球深盘与1.5让球深盘方向一致，无背离

**风险预警信号：**
1. bet365与澳门方向性分歧（bet365升盘1.5/2 vs 澳门回盘1.5），若bet365为领先信号，主队可能赢球不穿盘
2. Betfair欧赔主胜升赔+平局降赔，是五家机构中唯一的反向信号
3. Betfair客胜凯利1.14 > 1.0触发单点警戒
4. 立博大小球2.5档位大球水0.36极低，暗示其独立体系中对大球的保守判断
5. 澳门平赔5.30全程不变，存在隐藏平局风险（hidden-draw-away-cut-v1弱信号）

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 2
ruleset_id: football-analysis
ruleset_version: 1.8.0
data_cutoff_at: '2026-08-10T18:30:08+08:00'
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
- handicap-inducement-resistance
- handicap-total-goals-divergence
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
  reason: 低稳定性联赛权重校准规则，使用 global profile，不适用
source_refs:
- user-screenshot:macau-detail-20260810
- user-screenshot:asian-handicap-table-20260810
- user-screenshot:european-odds-table-20260810
- user-screenshot:total-goals-table-20260810
- user-screenshot:kelly-index-table-20260810
- user-screenshot:betfair-exchange-20260810
scenario_instance_ids: []
case_ids:
- legacy-rosenborg-fredrikstad
- legacy-hacken-aik
- legacy-hjk-tps
- legacy-incheon-bucheon
- legacy-seoul-ulsan
- legacy-gimcheon-daejeon
- legacy-gais-halmstad
- legacy-flamengo-sao-paulo
- legacy-gwangju-jeju
- legacy-pohang-jeonbuk
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
evaluation_bundle_sha256: cfbbaab30cc0455e1a2f90ca32ed40a1728db90248fea4ebcf8820586106f128
profile_chain:
- global
```
<!-- analysis-trace:end -->


## 机器市场状态

- 无判断：total_goals：insufficient_independent_exact_series；score：total_goals_score_separation
