# 江原FC VS 大阪钢巴 盘面完整推演（数据截止：2026-08-11 13:52）

比赛时间：2026-08-11 18:30

场地：未记录

比赛类型：俱乐部友谊赛

<!-- journal-entry:86e187a658a4d2e9: -->

### 一、澳盘时序梳理与盘路定性

**澳门盘路：** 平手盘开盘（0.95/0/0.83），临盘维持平手盘（0.98/0/0.80）。主队水位从0.95上行至0.98，客队水位从0.83下行至0.80。盘口未变但水位向客队倾斜，市场对主队信心不足。

**机构对比：**
- bet365：平手盘初盘0.85/0/0.95 → 即盘1.00/0/0.80，主队水位大幅上行0.15，客队水位大幅下行0.15
- 威廉：初盘让半球（-0.5）→ 即盘退至平/半（-0.25），主队水位从0.44升至0.69，属于典型的退盘看衰
- Interwetten：初盘让半球（-0.5）→ 即盘维持-0.5，但主队水位从0.50降至0.45，与威廉方向相反

**盘路定性：** 威廉从让半球退盘至平/半是核心信号，表明市场对江原FC的实际定位低于理论预期。bet365和澳门在平手盘上均向客队倾斜，整体盘路偏客队。Interwetten维持-0.5让球但主队低水，构成机构分歧。

### 二、胜平负欧赔走势

| 机构 | 初盘主胜 | 初盘平局 | 初盘客胜 | 即盘主胜 | 即盘平局 | 即盘客胜 | 变化方向 |
|------|---------|---------|---------|---------|---------|---------|---------|
| 澳门 | 2.55 | 3.18 | 2.40 | 2.55 | 3.18 | 2.40 | 不变 |
| 威廉 | 2.70 | 3.00 | 2.50 | 2.70 | 3.10 | 2.45 | 平升客降 |
| 立博 | 2.45 | 3.00 | 2.62 | 2.62 | 3.00 | 2.45 | 主升客降 |
| Interwetten | 2.55 | 3.05 | 2.70 | 2.75 | 3.05 | 2.45 | 主升客降 |
| Betfair | 2.74 | 2.82 | 2.56 | 2.86 | 3.30 | 2.66 | 主升平升客升 |
| bet365 | — | — | — | 2.63 | 3.10 | 2.40 | 仅即盘 |

**欧赔分析：**
1. 澳门是唯一保持不变的主机构，2.55/3.18/2.40的赔率组合显示客胜为最低赔
2. Betfair平赔从2.82大幅升至3.30，升幅达0.48，清晰排除平局
3. 立博和Interwetten主胜赔均上升，客胜赔下降，与威廉方向一致
4. 整体欧赔趋势：主胜赔↑、平赔↑、客胜赔↓ → 市场看衰主队、看衰平局、看好客队
5. 当前即盘最低赔：bet365客胜2.40、澳门客胜2.40，统一指向客队

### 三、凯利指数交叉验证

| 机构 | 即盘主胜凯利 | 即盘平局凯利 | 即盘客胜凯利 |
|------|------------|------------|------------|
| 最大值 | 0.98 | 0.95 | 0.98 |
| 最小值 | 0.87 | 0.87 | 0.89 |
| 6家平均 | 0.92 | 0.90 | 0.92 |
| 澳门 | 0.87 | 0.92 | 0.89 |
| Betfair | 0.98 | 0.95 | 0.98 |

**凯利分析：**
1. Betfair主胜和客胜凯利均为0.98，接近1.0的风险阈值，但平局凯利0.95也在高位
2. 澳门主胜凯利0.87最低，客胜凯利0.89次低，两端凯利可控
3. 6家平均凯利：主胜0.92、平局0.90、客胜0.92，三者差异不大，未形成明确的凯利偏好
4. 凯利指数未提供明确的单边信号，整体处于中性偏高水平

**规则处置：** draw-kelly-parity-v1 — 澳门平局凯利0.92 > 主胜凯利0.87，符合"平局凯利高于主胜凯利"的平局风险信号。但Betfair平赔3.30大幅上升对此构成反证。

### 四、大小球辅助参考

| 机构 | 初盘大球 | 初盘盘口 | 初盘小球 | 即盘大球 | 即盘盘口 | 即盘小球 |
|------|---------|---------|---------|---------|---------|---------|
| 澳门 | 0.83 | 2/2.5 | 0.89 | 0.83 | 2/2.5 | 0.89 |
| bet365 | 0.95 | 2/2.5 | 0.85 | 0.85 | 2/2.5 | 0.95 |
| 立博 | 1.05 | 2.5 | 0.70 | 1.00 | 2.5 | 0.70 |
| 威廉 | 1.10 | 2.5 | 0.67 | 1.05 | 2.5 | 0.70 |
| Interwetten | 1.05 | 2.5 | 0.65 | 0.95 | 2.5 | 0.70 |

**大小球分析：**
1. 澳门和bet365维持2/2.5盘口不变，但bet365大球水位从0.95降至0.85（大球热度下降）
2. 立博、威廉、Interwetten维持2.5盘口，大球水位均小幅下降
3. 整体大球水位趋势向下，但盘口未变，信号偏弱
4. 规则处置：total-goals-cross-market-v1 — 澳门2/2.5盘口与立博等2.5盘口存在0.25球的跨市场差异，但方向一致，不存在明确背离
5. 大小球方向不明确，建议pass

### 五、综合权重推演

**胜平负优先级：** 客胜 > 主胜 > 平局

**证据：**
1. 威廉退盘（-0.5→-0.25）：市场对主队定位低于预期，客队方向获支持
2. 欧赔统一趋势：5家机构主胜赔上升，客胜赔下降
3. Betfair平赔2.82→3.30大幅上升，清晰排除平局
4. bet365和澳门客胜赔均为2.40（最低），指向客队
5. 必发交易：客胜交易量最大(1,119元)，冷热指数+13偏热，市场资金偏向客队

**反证：**
1. Interwetten维持-0.5让球，主队低水(0.45)，与威廉退盘方向相反
2. 澳门主胜赔2.55仅在开盘阶段，未经受中盘验证
3. 必发交易总量仅2,669元，样本偏小，信号可靠性不足
4. 俱乐部友谊赛参考价值有限，缺乏两队近期交锋数据

**亚洲让球优先级：** 客队+0（大阪钢巴赢盘） > 主队+0（江原FC赢盘）

**固定让球胜平负优先级：** 不适用（平手盘无法映射固定让球胜平负）

**证据：**
1. 澳门平手盘主队水位从0.95→0.98，客队0.83→0.80，水位向客队倾斜
2. bet365平手盘主队水位从0.85→1.00，大幅上行，客队受热
3. 威廉退盘信号明确，平手盘下客队方向更安全

**反证：**
1. Interwetten维持-0.5让球与整体盘路不一致
2. 平手盘退盘风险：威廉退至-0.25意味着主队仍有微弱让球优势

**总进球：** pass（大小球方向不明确，盘口信号弱）

**比分权重：** 0:1 > 1:1（比分范围仅供参考，俱乐部友谊赛可预测性低）

**校准规则处置：**
1. draw-kelly-parity-v1：触发平局凯利偏高风险，但Betfair平赔3.30大幅上升构成反证 → 降低平局权重
2. low-stability-league-weight-calibration：俱乐部友谊赛属于低稳定性联赛，整体置信度下调
3. provider-consensus-divergence-v1：Interwetten与威廉方向分歧，触发机构分歧风险
4. quarter-low-water-inducement-v1：威廉退至-0.25后主队水位0.69，属于中低水但非诱盘区间
5. single-kelly-value-guard-v1：Betfair凯利0.98接近阈值，但未超1.0

### 六、后市观测清单

**正向强化信号：**
1. 澳门/365平手盘客队水位继续下行（当前0.80，若下行至0.75以下）
2. 更多机构客胜赔继续下跌
3. 威廉退盘至平手盘（-0.25→0）

**风险预警信号：**
1. Interwetten维持-0.5让球，若临场升盘至-0.75则反向信号增强
2. 澳门平手盘主队水位若回落至0.90以下，需重新评估
3. 必发主胜交易量若突然增加，可能为临场信息
4. 俱乐部友谊赛存在首发阵容不确定性风险

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 2
ruleset_id: football-analysis
ruleset_version: 1.8.0
data_cutoff_at: '2026-08-11T13:52:47+09:00'
applied_rule_ids:
- low-stability-league-weight-calibration
excluded_rules:
- rule_id: football-analysis-framework
  reason: 基础框架文档，非可触发规则
- rule_id: market-settlement-rules
  reason: 市场结算规则，非可触发规则
- rule_id: data-provenance-time-boundary
  reason: 数据来源规则，非可触发规则
- rule_id: prematch-stage-positioning
  reason: 基本面定位方法，非可触发规则
- rule_id: theoretical-vs-actual-market
  reason: 理论盘口比较方法，非可触发规则
- rule_id: market-timeline-cross-validation
  reason: 盘口时序交叉验证方法，非可触发规则
- rule_id: dual-hypothesis-evidence
  reason: 双向假设反证方法，非可触发规则
- rule_id: layered-decision-confidence-pass
  reason: 分层决策置信度方法，非可触发规则
- rule_id: goals-score-separation
  reason: 总进球比分分层方法，非可触发规则
- rule_id: prematch-checklist-v1
  reason: 赛前锁定检查清单，非可触发规则
- rule_id: data-quality-conflict-and-pass
  reason: 数据质量冲突处理方法，非可触发规则
- rule_id: scenario-identification-and-case-retrieval
  reason: 场景识别与案例检索方法，非可触发规则
- rule_id: live-update-and-postmatch-separation
  reason: 临场更新与赛后复盘隔离方法，非可触发规则
- rule_id: total-goals-cross-market-v1
  reason: 澳门2/2.5与立博2.5跨市场差异方向一致，无背离，数据不足
- rule_id: korea-goal-drop-v1
  reason: 俱乐部友谊赛非K联赛，不适用
- rule_id: handicap-total-goals-divergence
  reason: 让球与总进球无背离关系，不触发
- rule_id: hidden-draw-away-cut-v1
  reason: Betfair平赔3.30已明确排除平局，该规则不适用
- rule_id: asian-european-divergence
  reason: 亚盘与欧赔方向一致指向客队，无背离
- rule_id: cross-related-same-pattern
  reason: 无可识别的交叉关联同型盘
- rule_id: handicap-inducement-resistance
  reason: 平手盘水位变化属于正常市场调整，非阻盘诱盘
- rule_id: water-threshold-operator-style
  reason: 水位区间未触发机构风格信号
- rule_id: late-market-reversal
  reason: 缺少中盘节点，无法判断临场反转
- rule_id: market-heat-chip-distribution
  reason: 必发交易量仅2,669元样本偏小，不触发
- rule_id: draw-kelly-parity-v1
  reason: 澳门平局凯利0.92>主胜凯利0.87，但Betfair平赔3.30大幅上升构成反证，数据不足
- rule_id: operator-market-divergence
  reason: Interwetten与威廉方向分歧已在provider-consensus-divergence中处置
- rule_id: deep-line-stable-cover-v1
  reason: 平手盘不适用深盘规则
- rule_id: quarter-low-water-inducement-v1
  reason: 威廉退至-0.25后主队水位0.69，属于中低水但非诱盘区间，数据不足
- rule_id: korea-deep-line-loss-tolerance-v1
  reason: 平手盘非深盘，不适用
- rule_id: score-baseline-v1
  reason: 缺少中盘节点，数据不足
source_refs:
- 截图 08-10 23:14
- 截图 08-11 12:08
scenario_instance_ids: []
case_ids:
- 20260811-prt-pl-santa-clara-nacional-madeira
- 20260811-swe-allsvenskan-team-u-437644d1fb-team-u-1f654e188d
- 20260811-swe-allsvenskan-team-u-c729cf1248-team-u-062bc98d3a
- legacy-seoul-ulsan
- legacy-gimcheon-daejeon
- legacy-incheon-bucheon
- legacy-pohang-jeonbuk
- legacy-anyang-gangwon
- legacy-gwangju-jeju
- legacy-rosenborg-fredrikstad
ruleset_origin: published
deterministic_rule_ids:
- draw-kelly-parity-v1
- low-stability-league-weight-calibration
disposition_rule_ids:
- provider-consensus-divergence-v1
- quarter-low-water-inducement-v1
- single-kelly-value-guard-v1
control_rule_ids:
- handicap-inducement-resistance
- asian-european-divergence
- operator-market-divergence
- market-heat-chip-distribution
- late-market-reversal
profile_chain:
- global
evaluation_bundle_sha256: c509ec0d63a9cd8e4cd25f7981d46d6b35aef4a410c6ddc9c4e20953ac35fc6c
```
<!-- analysis-trace:end -->


## 机器市场状态

- 无判断：total_goals：大小球方向信号弱，盘口未变仅水位微调；跨市场差异不足以支撑明确判断；score：total_goals_score_separation
