# 塞伊奈约基 VS 赫尔辛基 盘面完整推演（数据截止：2026-08-03 21:14）

比赛时间：2026-08-04 00:00

场地：未记录

比赛类型：芬超联赛

### 一、澳盘时序梳理与盘路定性

- 数据截止：2026-08-03 21:14 (+08:00)，开赛前 2 小时 46 分；本轮只使用截止时间之前的材料。
- 澳门让球的可比时序为：2026-07-28 20:36 主让平半 0.98/0.80；2026-08-01 07:59 主让平半 1.03/0.75；2026-08-03 10:00 升至主让半球 0.82/0.96；10:01 为 0.83/0.95；20:51 为 0.85/0.93。盘口完成平半到半球的升档，升档后主水没有回到高位。
- 同期快照中 Bet365、威廉均由平半升至半球；Interwetten 原本就是半球，后段主水由 0.65 回到 0.75，说明机构间水位强度并不完全一致。
- 亚盘表象偏向塞伊奈约基让球，但这只说明让球结算门槛被抬高，不能单独等同于主队胜负概率已经领先。

### 二、胜平负欧赔走势

- 澳门 2.80/3.65/2.03 变为 3.00/3.65/1.93；威廉 2.88/3.50/2.15 变为 3.10/3.70/2.00；立博 2.90/3.50/2.05 变为 3.10/3.50/1.95；Interwetten 2.90/3.50/2.20 变为 3.25/3.60/2.00；Betfair 3.10/3.55/2.12 变为 3.50/4.20/2.08。
- 五家均出现主胜抬升、客胜收窄；平赔总体稳定或小幅抬升。该方向在机构层面一致，属于赫尔辛基胜负方向的相对支持。
- 澳门客胜收窄约 4.9%，未达到 `hidden-draw-away-cut-v1` 的 10% 阈值，不能据此上调平局为正式第一顺位。

### 三、凯利指数交叉验证

- 澳门凯利由主/平/客 0.79/0.89/0.96 变为 0.85/0.89/0.91；六家平均由 0.82/0.87/1.00 变为 0.91/0.91/0.94。主胜凯利上行、客胜凯利下行，与欧赔主胜漂高、客胜收窄同向。
- 立博、威廉和 Interwetten 的客胜凯利也由约 0.97-1.04 收敛到 0.92-0.94，方向上强化客胜风险；但欧赔与凯利来自同一批用户截图，按同源数据处理，不能当成两份独立维度重复计权。
- 凯利绝对值晚盘仍有收敛现象，但三项最大差值并未形成可独立改写主线的证据；平局实验规则没有满足完整适用条件。

### 四、大小球辅助参考

- 澳门总进球维持 3 球，大球水 0.76 到 0.78，小球水 0.96 到 0.94，变化很小。
- Bet365/英国系由 3/3.5 降到 3，且大球水由 1.00 降至 0.83；Interwetten、威廉在 3.5 档维持高大球水、低小球水，机构间对进球上限存在分歧。
- 大球单向降幅未达到 0.20 的正式实验阈值，大小球只能作为中低进球观察，不能反向解决胜负冲突，也不能用于证明主队穿盘。

### 五、综合权重推演

- 胜平负优先级：正式处置为 `pass`。若仅记录盘面倾向，欧赔/凯利偏赫尔辛基方向，亚盘让球偏塞伊奈约基，无法形成统一胜负排序。
- 亚洲让球优先级：盘口层面塞伊奈约基让半球占优，但升档与欧赔客胜收窄发生背离，不能生成正式让球第一顺位。
- 固定让球胜平负优先级：不从胜负赔率直接推导固定让球穿盘；保留与亚洲让球同源的冲突，不重复累计。
- 总进球：仅保留 2-3 球的观察区间倾向，因主市场 `pass` 不生成正式总进球预测。
- 比分权重：主市场未通过门禁，不生成正式比分候选；低比分与一球差剧本仅作为后续观察，不进入候选回执。
- 校准规则处置：芬超不属于 1.3.0 的挪超、美职联或韩国 profile；全部实验规则记录为未触发/不适用，不改变基础排序。亚盘与欧赔背离仅登记为风险假设，不判定诱盘事实。

### 六、后市观测清单

- 正向强化信号：澳门半球继续站稳且主水保持低位，同时澳门客胜停止继续下压并出现跨机构同步，才可重新评估塞伊奈约基让球方向。
- 风险预警信号：澳门退回平半、主水重新升高，或客胜赔率继续同步收窄；任一出现都继续偏向赫尔辛基不败风险。大小球若重新升档并伴随大球水持续下行，才扩大进球区间。

本轮正式结论为 `pass`，不创建锁定候选；以上条件只用于说明何种新证据可以解除当前冲突。

<!-- analysis-trace:start -->
### 分析追踪

```yaml
schema_version: 1
ruleset_id: football-analysis
ruleset_version: 1.3.0
data_cutoff_at: '2026-08-03T21:14:00+08:00'
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
- rule_id: draw-kelly-parity-v1
  reason: 芬超不属于低稳定性校准 profile，且本场没有满足该实验完整三节点门禁。
- rule_id: handicap-total-goals-divergence
  reason: 仅作大小球与让球的背离观察，未形成方向性校准。
- rule_id: handicap-inducement-resistance
  reason: 升盘与欧赔背离存在双向解释，不能把阻诱标签当成事实。
- rule_id: korea-goal-drop-v1
  reason: 非韩国 K1/K2 赛事，不适用。
- rule_id: low-stability-league-weight-calibration
  reason: 芬超不在挪超或美职联 profile，不适用。
- rule_id: hidden-draw-away-cut-v1
  reason: 澳门客胜收窄约 4.9%，未达到 10% 阈值。
- rule_id: water-threshold-operator-style
  reason: 水位变化不能独立解决亚盘与欧赔的核心冲突。
- rule_id: asian-european-divergence
  reason: 已登记为未解释背离风险，未把经验规则升级为方向结论。
- rule_id: total-goals-cross-market-v1
  reason: 大球水单向变化未达到 0.20 阈值，且芬超不进入专项 profile。
- rule_id: cross-related-same-pattern
  reason: 未找到可验证的同型盘独立案例，不能替代本场证据。
- rule_id: market-heat-chip-distribution
  reason: 没有独立资金流事实，盘口不能反推热度。
- rule_id: operator-market-divergence
  reason: 机构间存在差异，但不构成单独方向证据。
- rule_id: score-baseline-v1
  reason: 主市场 pass，不生成比分候选。
- rule_id: late-market-reversal
  reason: 没有可验证的临场反转链，只有升档后的稳定节点。
- rule_id: quarter-low-water-inducement-v1
  reason: 半球低水与欧赔背离虽存在，但实验规则只登记风险，不足以改写主线。
- rule_id: korea-deep-line-loss-tolerance-v1
  reason: 非韩国 K1/K2 赛事，不适用。
- rule_id: deep-line-stable-cover-v1
  reason: 本场为半球而非一球以上深盘，且没有该规则所需的同档三节点条件。
source_refs:
- matches/2026/08/2026-08-04_芬超联赛_塞伊奈约基_vs_赫尔辛基.md#market_snapshots
- raw/matches/20260804-competition-u-388f03e8f4-team-u-369c6e16ff-hjk-helsinki/journal/2026/08/20260803T211400_journal-20260803211400-5fb3121f2c/source.md
- raw/journal-inbox/2026/08/20260803T155500_journal-20260803155500-5c995dab1d/source.md
scenario_instance_ids: []
case_ids:
- legacy-hjk-tps
- legacy-rosenborg-fredrikstad
- legacy-hacken-aik
- legacy-malmo-elfsborg
- legacy-flamengo-sao-paulo
- legacy-gremio-fluminense
- legacy-gais-halmstad
- 20260730-bra-serie-a-fluminense-bahia
- 20260730-bra-serie-a-vitoria-palmeiras
- 20260730-bra-serie-a-mirassol-remo
```
<!-- analysis-trace:end -->
