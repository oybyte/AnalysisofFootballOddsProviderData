---
title: AI 实验预测报告 - 江原FC vs 大阪钢巴
date: 2026-08-11 15:05:13 +0800
config: openai-gpt56-terra-v1
model: gpt-5.6-terra
provider: openai-compatible
match_id: 20260811-club-friendly-gangwon-fc-team-u-aa44e965b0
---

# AI 实验预测报告：江原FC vs 大阪钢巴

## 比赛信息

| 项目 | 内容 |
|------|------|
| 比赛 | 江原FC vs 大阪钢巴 |
| 联赛 | 俱乐部友谊赛 |
| 开赛时间 | 2026-08-11 18:30:00+08:00 |
| AI 配置 | openai-gpt56-terra-v1 |
| 模型 | gpt-5.6-terra |
| 生成时间 | 2026-08-11 15:05:13 +0800 |

## Token 消耗

| 阶段 | 输入 Tokens | 输出 Tokens |
|------|------------|------------|
| 赛前事实摘要 | 11534 | 821 |
| 规则评估矩阵 | 5153 | 3523 |
| 历史案例对比 | 11319 | 3399 |
| AI 预测结果 | 9011 | 110 |
| 风险评估 | 8745 | 2426 |
| **总计** | **45762** | **10279** |

## 赛前事实摘要

```json
{
  "facts_summary": {
    "asian_handicap_narrative": "澳门亚盘仅提供开盘与临盘两个有效节点，缺少中盘数据。开盘：盘口为平手（0），上盘水位0.95、下盘水位0.83；中盘：未提供；临盘：盘口仍为平手（0），上盘水位升至0.98，较开盘上升0.03；下盘水位降至0.80，较开盘下降0.03。盘口档位全程维持平手（0），没有发生跳档。",
    "european_odds_narrative": "威廉希尔：未提供opening、mid、late三节点主胜/平局/客胜具体赔率，无法判断变化方向及幅度。立博：未提供opening、mid、late三节点主胜/平局/客胜具体赔率，无法判断变化方向及幅度。澳彩（澳门）：开盘主胜2.55、平局3.18、客胜2.40；中盘未提供；临盘主胜2.55、平局3.18、客胜2.40，三项相对开盘均变化0.00，赔率保持不变。由于威廉希尔和立博的具体赔率缺失，无法按0.05阈值核验三家机构之间是否存在分歧。",
    "kelly_index_narrative": "威廉希尔、立博、澳彩三家机构的凯利指数opening、mid、late具体数值均未在所提供结构化数据中给出；现有记录仅说明凯利数据来源覆盖多家机构，但没有可引用的凯利指数数值。因此无法逐机构描述三节点变化，无法验证凯利指数与赔率的联动关系，也无法判断任何凯利值是否处于0.85-0.95的合理区间。",
    "total_goals_narrative": "澳门大小球仅提供开盘与临盘两个有效节点，缺少中盘数据。开盘：盘口为2/2.5球，大球水位0.83、小球水位0.89；中盘：未提供；临盘：盘口仍为2/2.5球，大球水位0.83、小球水位0.89。盘口档位未变化；大球水位变化0.00，小球水位变化0.00，均无升降。",
    "anomalies": [
      "三节点数据不完整：澳门亚盘和大小球均仅有开盘、临盘，缺少中盘节点；凯利指数三节点具体数值缺失。",
      "未发现水位突变超过0.10：澳门亚盘上盘水位0.95→0.98，上升0.03；下盘水位0.83→0.80，下降0.03；大小球大球和小球水位均为0.83/0.89→0.83/0.89，变化均为0.00。",
      "未发现盘口跳档：澳门亚盘始终为平手（0）；大小球始终为2/2.5球。",
      "机构间分歧无法核验：威廉希尔、立博具体欧赔及凯利数值缺失，无法与澳彩的主胜2.55、平局3.18、客胜2.40按超过0.05的阈值进行比较。"
    ]
  }
}
```

## 规则评估矩阵

```json
{
  "rule_interpretations": [
    {
      "rule_id": "lsl-asian-rise-water-rise",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则检测让球盘口升档且对应上盘水位同步上升的组合，通常用于识别固定让球胜平负市场中平局风险。该场仅有澳门开盘和临盘两节点，盘口始终为平手（0），并未出现升盘；上盘水位虽由0.95升至0.98（+0.03），但缺少“盘口升档”这一前提，且规则被标记为不适用，故未触发。",
      "signal_direction": "draw",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "lsl-deep-line-falling-water",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则检测主队获得深让球盘支持后，主队一侧水位下调的信号，通常表示市场继续强化主队穿盘预期。实际亚盘为平手（0），不存在深盘；主队上盘水位反而从0.95升至0.98（+0.03），并非下降。规则状态为不适用，因此不构成主队让球信号。",
      "signal_direction": "home",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "lsl-deep-line-drop-risk",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则检测深让球盘口走弱或降档时的风险，通常提示强势方可能难以打穿，并提高让球平局的关注度。本场盘口开盘和临盘均为平手（0），实际盘口变化为0，没有深盘也没有降盘，故不具备规则适用条件。",
      "signal_direction": "draw",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "lsl-favorite-kelly-draw-resonance",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则检测热门一方的赔率走势与凯利指数共同指向平局防范的情况。需要可核验的热门方判断、赔率变化和凯利数值；本场威廉希尔、立博及澳门的凯利开中临具体数值均缺失，且规则被判定为不适用，无法形成凯利与平局的联动验证。",
      "signal_direction": "draw",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "lsl-single-side-draw-protection",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则寻找单侧市场保护平局的赔率或水位结构，即某一结果并未获得相应强化、但平局被刻意防范。该场缺少完整三节点欧赔及凯利数据，澳门欧赔主胜2.55、平局3.18、客胜2.40从开盘到临盘均变化0.00，且规则被标为不适用，未见可确认的单侧平局保护形态。",
      "signal_direction": "draw",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "lsl-underdog-kelly-defense",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则检测被低估一方的凯利指数出现防守性配置，通常可指向该方不败或取胜。本场虽从澳门欧赔2.55/3.18/2.40可见客胜为最低赔率，但没有任何可引用的客队凯利指数开中临数据，无法验证凯利防守；规则亦被标记为不适用。",
      "signal_direction": "away",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "lsl-kelly-narrow-range",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则检测主、平、客凯利指数处于狭窄区间，通常意味着三项赔付风险接近、平局权重可能被抬升。实际凯利值及其范围均缺失，无法比较实际离散度与规则要求的窄区间阈值；规则被标记为不适用，故不触发。",
      "signal_direction": "draw",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "lsl-extreme-over-calibration",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则检测大小球市场出现极端大球水位或异常调整，并将其校准为大球判断。实际澳门大小球盘口始终为2/2.5球，大球水位始终0.83、小球水位始终0.89，水位变化均为0.00；同时规则状态为不适用，未出现需要校准的极端大球信号。",
      "signal_direction": "over",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "draw-kelly-parity-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该规则检测平局凯利与主、客两项凯利是否接近，以判断市场是否对平局作出均衡防范。规则本身适用，但主胜、平局、客胜的凯利指数实际值全部缺失，因而无法计算实际凯利差，也无法与规则的平价阈值比较，所以因数据不足未触发。",
      "signal_direction": "draw",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "deep-line-stable-cover-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该规则检测深让球盘在多阶段保持稳定、且强势方水位表现支持其穿盘的情形。实际可见盘口为平手（0），并无深让基础；更关键的是仅有开盘和临盘、缺少中盘，无法完成规则所需的多阶段稳定性检验，因此标记为数据不足，未形成主队让球支持。",
      "signal_direction": "home",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "quarter-low-water-inducement-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该规则识别平/半等四分之一盘口配合低水时，是否存在诱导市场追捧一方、但实际结果风险偏向另一侧的结构。本场盘口实际为平手（0），不是四分之一盘口；且缺少中盘节点，无法验证盘口—水位的完整演变，故虽规则可适用，仍因数据不足未触发。",
      "signal_direction": "home",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "hidden-draw-away-cut-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该规则检测客胜赔率下调与平局防范之间的隐性组合，用于判断客胜受压后平局是否仍具风险。澳门欧赔主胜2.55、平局3.18、客胜2.40从开盘到临盘均为0.00变化，威廉希尔和立博的具体赔率又缺失；因此无法核验客胜降幅及其是否达到规则阈值，也无法确认平局联动，故数据不足。",
      "signal_direction": "draw",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "total-goals-cross-market-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该规则通过大小球、让球及欧赔等不同市场的联动，寻找支持大球的跨市场证据。实际大小球盘口固定在2/2.5球，大球水位0.83→0.83、变化0.00；亚盘也仅有两个节点，欧赔和凯利信息不完整。由于缺少至少可交叉验证的独立维度，无法满足规则要求，未形成大球信号。",
      "signal_direction": "over",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "score-baseline-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该规则将完整的赛果、让球、大小球及凯利信息整合为比分/胜负基线，并在此规则设定中偏向主队。当前虽基线市场评分实际显示客胜87.5、主胜-87.5，客队排名第一且领先主队175.0分，但规则所需的比分层输入与完整凯利、三阶段数据缺失，无法完成该规则自身的阈值核验，因此未触发，不能将其预设目标视为有效主队信号。",
      "signal_direction": "home",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "korea-goal-drop-v1",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则是韩国相关赛事画像下，对大小球盘口或大球水位下调进行解读并指向大球的专项规则。本场归入全局画像（competition_profile为global），且赛事为俱乐部友谊赛；实际大小球盘口2/2.5球不变、大球水位0.83不变，变化0.00。规则不适用，未触发。",
      "signal_direction": "over",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "korea-deep-line-loss-tolerance-v1",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该规则是韩国相关赛事的专项风险规则，检测深盘下市场对强队小负或输盘的容忍结构，通常提示客队方向的结果风险。本场使用全局而非韩国专项画像，且亚盘始终为平手（0），实际不存在深让球盘，因此规则不适用、未触发。",
      "signal_direction": "away",
      "resonance_with": [],
      "conflict_with": []
    },
    {
      "rule_id": "trend-purity-v1",
      "triggered": false,
      "disposition": "excluded",
      "reasoning": "该控制规则检测盘口趋势在多个节点中是否足够一致；纯度达到阈值时才允许把趋势视为可靠。实际趋势纯度为0.00，规则要求不低于0.67，差0.67，未达标；同时只有开盘和临盘，缺失中盘也削弱趋势判断。因此未触发，其含义是不能因单一、轻微的水位变化建立明确方向。",
      "signal_direction": "pass",
      "resonance_with": [
        "provider-consensus-divergence-v1"
      ],
      "conflict_with": []
    },
    {
      "rule_id": "provider-consensus-divergence-v1",
      "triggered": true,
      "disposition": "excluded",
      "reasoning": "该控制规则检测市场提供商数量或共识结构达到需人工警戒的程度，目标并非选择主、客或大小，而是提示“暂停/谨慎处理”。实际provider_count为6，达到规则阈值2（6≥2），因此触发；不过其证据仅落在澳门开盘、临盘两个快照，且反证明确写为“需要AI处置并保留反证”。在威廉希尔、立博具体欧赔及凯利数据缺失、无法验证真实机构间分歧的条件下，该控制警报不应推翻已评估的客队让球基线，故作为排除的风险提示保留，而非采纳为最终pass结论。",
      "signal_direction": "pass",
      "resonance_with": [
        "trend-purity-v1",
        "cross-dimension-netting-v1",
        "late-market-anomaly-v1",
        "single-kelly-value-guard-v1"
      ],
      "conflict_with": [
        "score-baseline-v1"
      ]
    },
    {
      "rule_id": "cross-dimension-netting-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该控制规则要求至少两个独立市场维度形成可相互抵消或校验的信号，以决定是否需要暂停。实际独立维度数为0，规则阈值为至少2，即0<2，未满足；欧赔、凯利及完整时序数据不足导致无法建立独立维度，故未触发。",
      "signal_direction": "pass",
      "resonance_with": [
        "provider-consensus-divergence-v1"
      ],
      "conflict_with": []
    },
    {
      "rule_id": "late-market-anomaly-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该控制规则检测临盘是否出现异常跳盘、突变水位或异常赔率。实际亚盘上盘水位0.95→0.98（+0.03）、下盘0.83→0.80（-0.03），大小球两侧均变化0.00，且没有盘口跳档；这些已知变化没有超过异常说明中0.10的突变标准。但由于缺少中盘及其他机构临盘细节，无法完成完整异常检验，规则以数据不足而非明确否定处理。",
      "signal_direction": "pass",
      "resonance_with": [
        "provider-consensus-divergence-v1"
      ],
      "conflict_with": []
    },
    {
      "rule_id": "single-kelly-value-guard-v1",
      "triggered": false,
      "disposition": "insufficient_data",
      "reasoning": "该控制规则防止仅凭单一凯利值作出胜负判断，需用完整凯利数值及其与赔率的关系验证。实际主、平、客凯利开中临具体数值均缺失，无法判断是否存在单一异常值，更无法与规则阈值比较，因此未触发。",
      "signal_direction": "pass",
      "resonance_with": [
        "provider-consensus-divergence-v1"
      ],
      "conflict_with": []
    }
  ],
  "resonance_summary": "有效方向性规则没有任何一条被触发，因此不存在由规则触发形成的主队、客队、平局或大小球共振。基线市场本身则高度一致地偏向大阪钢巴：1X2评分客胜87.5、平局-40.0、主胜-87.5，客胜第一且相对

... (输出过长，已截断，完整内容见原始响应)
```

## 历史案例对比

```json
{
  "case_comparisons": [
    {
      "case_id": "20260811-prt-pl-santa-clara-nacional-madeira",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛盘口特征：澳门亚盘平手（0）全程不变，江原FC一侧水位0.95升至0.98，大阪钢巴一侧水位0.83降至0.80；大小球维持2/2.5球，大球0.83、小球0.89均无变化；澳门1X2固定为2.55/3.18/2.40，客胜为最低赔率。",
        "案例盘口特征：所提供案例索引未包含asian_line、water_range、trend的实际字段值，无法逐项验证其让球档位、水位区间及走势是否与当前平手盘、客队低水下调结构一致。"
      ],
      "differences": [
        "当前比赛为俱乐部友谊赛，案例为葡超圣克拉拉对葡萄牙国民，联赛属性、比赛动机和轮换逻辑不同。",
        "当前比赛涉及韩日俱乐部交锋，案例为葡萄牙国内联赛；球队实力参照系、主场因素及赛季阶段均不可直接横比。",
        "当前比赛缺少完整中盘、威廉希尔/立博赔率和凯利数据；案例虽标记为赛前验证完整，但未提供可供比对的具体盘口明细。"
      ],
      "historical_result": "未提供result_score或最终比分，无法引用该案例赛果。",
      "caveat": "案例在数据完整性标签上可用，且同为赛前市场案例，理论上可用于寻找平手盘和低水方向的历史样本；但实际盘口、水位和走势字段缺失，无法确认相似度，不能将其赛果套用于当前客队低水结构。"
    },
    {
      "case_id": "20260811-swe-allsvenskan-team-u-437644d1fb-team-u-1f654e188d",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛为平手盘，客队大阪钢巴处于0.80低水且临盘再降0.03，盘口未跳档；总进球盘固定2/2.5球。",
        "案例为瑞典超天狼星对布洛马波卡纳，已标记赛前验证完整、统计可用；但未提供案例实际asian_line、water_range与trend，不能确认是否同属平手盘或客队低水下调。"
      ],
      "differences": [
        "案例为瑞典超正式联赛，当前为俱乐部友谊赛，正式积分压力与热身赛阵容不确定性明显不同。",
        "北欧联赛环境与韩日球队对阵的旅行、气候、轮换和战术节奏不同。",
        "当前欧赔只有澳门固定报价，凯利缺失；案例的具体欧赔与凯利信息亦未随输入提供。"
      ],
      "historical_result": "未提供result_score或最终比分，无法引用该案例赛果。",
      "caveat": "该案例的赛前验证完整性使其具备潜在数据库参考价值，但缺少核心盘口字段，无法证实其与当前平手、客队低水格局相似；仅能作为待补充数据后的候选案例。"
    },
    {
      "case_id": "20260811-swe-allsvenskan-team-u-c729cf1248-team-u-062bc98d3a",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛盘口档位为平手（0），全程稳定；客队水位0.83降至0.80，主队水位0.95升至0.98，市场基线偏向大阪钢巴。",
        "案例为瑞典超瓦斯特拉斯对尤尔加登，标记为赛前验证完整、统计可用；输入未展示该案例的让球档位、水位范围和盘口走势，无法形成具体对照。"
      ],
      "differences": [
        "当前为俱乐部友谊赛，案例为瑞典超联赛，赛事目标与临场轮换强度不同。",
        "当前主队江原FC与案例球队不存在可直接映射的实力层级或伤停信息。",
        "当前大小球为2/2.5且静止，案例大小球结构未提供，无法判断节奏预期是否相近。"
      ],
      "historical_result": "未提供result_score或最终比分，无法引用该案例赛果。",
      "caveat": "此案例可在补齐具体盘口记录后用于检验“平手盘下客方低水”的历史表现；在现有信息下，相似度无法量化，不能以案例赛果替代当前判断。"
    },
    {
      "case_id": "legacy-seoul-ulsan",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛：澳门让球平手不变，客队低水由0.83降至0.80，欧赔客胜2.40低于主胜2.55，形成轻度客队市场倾向。",
        "案例为韩K联FC首尔对蔚山HD，属于韩国足球语境，与当前江原FC的联赛背景存在一定地域和球队环境关联；但案例的实际asian_line、water_range、trend未提供，不能确认盘口结构相似。"
      ],
      "differences": [
        "案例为韩K联正式联赛，当前为江原FC对大阪钢巴的俱乐部友谊赛；正式联赛积分目标与友谊赛练兵目标不可等同。",
        "当前有日本球队大阪钢巴参与，跨联赛对阵削弱了韩国国内联赛案例的直接可比性。",
        "案例虽完整且统计可用，但输入没有给出其具体基本面、盘口细节和赛果。"
      ],
      "historical_result": "未提供result_score或最终比分，无法引用该案例赛果。",
      "caveat": "该案例对江原FC所处韩国足球生态、主客场和联赛风格的背景参考价值相对较高；但友谊赛的阵容实验和战意波动远高于联赛，且缺少案例盘口原始值，不能直接迁移结果。"
    },
    {
      "case_id": "legacy-gimcheon-daejeon",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛：平手盘稳定、客队处于低水并小幅下调、大小球2/2.5球无波动。",
        "案例为韩K联金泉尚武对大田市民，具备韩国联赛环境上的潜在关联，且赛前验证完整、统计可用；但未给出案例盘口档位、水位区间及趋势。"
      ],
      "differences": [
        "当前为韩日俱乐部友谊赛，案例为韩国国内正式联赛。",
        "金泉尚武的球队人员构成和赛季管理模式具有特殊性，不能与江原FC的友谊赛排兵直接类比。",
        "当前缺少凯利与多机构欧赔轨迹，案例相应的可比数值没有展示。"
      ],
      "historical_result": "未提供result_score或最终比分，无法引用该案例赛果。",
      "caveat": "韩国联赛案例可辅助理解江原FC相关的市场定价环境，但无法证明与当前比赛的盘口结构一致；尤其在平手盘下，友谊赛的低水变化仅0.03，信号强度不足以由单个历史案例放大解读。"
    },
    {
      "case_id": "legacy-incheon-bucheon",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛：让球盘固定平手，主队水位偏高并上升至0.98，客队低水降至0.80，市场基线偏向客队。",
        "案例为仁川联对富川FC，属于韩国球队赛事，且被标记为完整、可用于统计；但案例的具体让球、水位及走势未在输入中提供。"
      ],
      "differences": [
        "案例为韩国国内球队比赛，当前是江原FC对大阪钢巴的国际俱乐部友谊赛。",
        "仁川联与富川FC的赛事级别、交锋背景可能不同于当前对阵，不能仅以韩国球队标签建立等价关系。",
        "当前大小球2/2.5球静止，案例总进球市场资料缺失。"
      ],
      "historical_result": "未提供result_score或最终比分，无法引用该案例赛果。",
      "caveat": "该案例的价值仅在于可作为韩国足球市场样本池的一部分；由于缺少可核验的盘口特征和最终赛果，无法认定为高相似案例，更不能支持直接追随客队方向。"
    },
    {
      "case_id": "legacy-pohang-jeonbuk",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛：平手盘未变，客队水位小降，且澳门1X2客胜为最低项；没有盘口跳档或水位突变。",
        "案例为韩K联浦项制铁对全北现代，在韩国顶级联赛背景上与江原FC具一定关联；但案例记录为partial、mixed，未提供可验证的盘口特征。"
      ],
      "differences": [
        "当前为俱乐部友谊赛，案例为韩K联正式比赛。",
        "案例数据完整度为partial、时间线为mixed且statistics_eligible为false，数据质量弱于当前已知澳门双节点信息。",
        "案例具体赛果、阵容、伤停、盘口轨迹均未提供。"
      ],
      "historical_result": "未提供result_score或最终比分，且该案例不具统计资格。",
      "caveat": "韩国顶级联赛背景提供有限的环境参考，但该案例本身存在时间线混杂和信息不完整问题，不应作为当前比赛方向判断或概率估计的依据。"
    },
    {
      "case_id": "legacy-anyang-gangwon",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛主队正是江原FC；当前盘口为平手，江原FC水位由0.95升至0.98，大阪钢巴水位由0.83降至0.80。",
        "案例为FC安养对江原FC，直接涉及江原FC，因此在球队风格、阵容框架和市场定价习惯方面具有潜在参考价值；但未提供案例的asian_line、water_range、trend实际数值。"
      ],
      "differences": [
        "案例为韩K联正式赛事，当前为对大阪钢巴的俱乐部友谊赛；江原FC的战意、出场时间分配和换人策略均可能改变。",
        "案例中江原FC为客队，当前江原FC为主队，主客定位发生转换。",
        "该案例为partial、mixed且statistics_eligible为false，不能用于稳健统计比较。"
      ],
      "historical_result": "未提供result_score或最终比分，且该案例不具统计资格。",
      "caveat": "这是所有案例中球队维度最相关的样本，能帮助回看江原FC在既往市场中的定价特征；但主客身份、赛事性质均不同，加之原始记录不完整，不能把历史结果直接映射为当前江原FC或大阪钢巴的结论。"
    },
    {
      "case_id": "legacy-gwangju-jeju",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛：平手盘不变、客队低水下调0.03、大小球2/2.5无变化，整体只有轻微客队定价倾向。",
        "案例为韩K联FC光州对济州SK，处于韩国足球市场范畴；但未披露该案例实际盘口档位、水位范围、走势和赛果，无法验证结构相似度。"
      ],
      "differences": [
        "当前为俱乐部友谊赛，案例为韩K联正式联赛。",
        "案例并不涉及江原FC或大阪钢巴，球队层面的直接关联有限。",
        "案例为partial、mixed且不具统计资格，不能作为有效历史频率样本。"
      ],
      "historical_result": "未提供result_score或最终比分，且该案例不具统计资格。",
      "caveat": "该案例最多反映韩国联赛市场的一般背景，不能证明当前平手盘客队低水会复制相同赛果；数据质量和赛事属性差异均限制其参考价值。"
    },
    {
      "case_id": "legacy-rosenborg-fredrikstad",
      "similarity_score": 0.0,
      "comparable_points": [
        "当前比赛：让球为平手、客队低水0.80、大小球2/2.5，临盘没有档位变化。",
        "案例为挪超罗森博格对腓特烈斯塔，同属俱乐部赛事；然而案例的实际asian_line、water_range、trend均未提供，无法确认是否与当前盘口档位和水位方向一致。"
      ],
      "differences": [
        "案例为挪超正式联赛，当前为韩日俱乐部友谊赛，联赛节奏、场地气候、战意与阵容管理不同。",
        "案例不涉及当前两队，球队实力与市场关注度不能横向替代。",
        "案例记录为partial、mixed且statistics_eligible为false，最终赛果也未给出。"
      ],
      "historical_result": "未提供result_score或最终比分，且该案例不具统计资格。",
      "caveat": "该案例仅可作为不同联赛中俱乐部市场形态的外围参照；由于赛事、球队和数据质量均存在显著差异，参考权重应很低。"
    }
  ],
  "overall_case_assessment": "当前比赛的可确认市场特征为：澳门亚盘平手（0）不变，江原FC水位0.95升至0.98，大阪钢巴水位0.83降至0.80；澳门欧赔固定为主胜2.55、平局3.18、客胜2.40，客胜处于最低赔率；大小球固定2/2.5球且水位无变化。该结构只呈现轻微且未被多机构验证的客队倾向，并未出现跳盘、极端水位或大小球联动。所列案例缺少开发要求中的asian_line、water_range、trend、result_score实际值，无法完成可靠的逐项相似度匹配，故相似度统一记为0.0表示“不可量化”而非“确认不相似”。其中涉及江原FC的legacy-anyang-gangwon具最高潜在球队关联，韩国联赛案例具有限环境参考，但友谊赛与正式联赛的战意和轮换差异显著；同时多个legacy案例为partial、mixed或不具统计资格。总体应以当前盘口的有限信息为主，历史案例只能待补齐原始盘口和赛果后再作验证，不能直接套用。"
}
```

## AI 预测结果

```json
{
  "market_statuses": {
    "one_x_two": "pass",
    "asian_handicap": "pass",
    "fixed_handicap_1x2": "pass",
    "total_goals": "pass",
    "score": "pass"
  },
  "predictions": {}
}
```

## 风险评估

```json
{
  "risk_watchlist": {
    "positive_signals": [
      {
        "signal": "大阪钢巴方向获得进一步低水支持，且盘口不退回主队倾斜",
        "data_point": "澳门亚盘维持平手（0），大阪钢巴一侧水位由当前0.80继续降至0.78或以下，同时江原FC一侧升至1.00或以上",
        "reliability_impact": "若同步持续15分钟以上且无盘口反向跳动，可将原本仅属轻度的客队市场倾向提升为中等可信度；但因友谊赛及多机构数据缺失，仍不宜视为高置信结论。"
      },
      {
        "signal": "客胜欧赔得到临场压低确认",
        "data_point": "澳门客胜赔率从2.40下调至2.35或以下，主胜维持2.55或上调至2.60以上，且平局赔率不低于3.18",
        "reliability_impact": "若客胜降幅达到0.05以上并与亚盘客队低水共振，客队方向可靠性可提升约一个等级；若只有单一澳门机构变化，则提升有限。"
      },
      {
        "signal": "平手盘稳定而客队低水延续",
        "data_point": "临场前30分钟内澳门亚盘持续为平手（0），大阪钢巴水位稳定在0.80以下，未回升至0.85或以上",
        "reliability_impact": "可确认客队至少获得不败倾向的市场保护，降低平手盘下客队被临场抛售的风险；对客队方向的可靠性提升约10%-15%。"
      },
      {
        "signal": "多机构欧赔形成一致客倾",
        "data_point": "补齐威廉希尔、立博临场赔率后，至少两家机构客胜赔率低于主胜赔率0.10以上，且相较各自开盘客胜降幅达到0.05以上",
        "reliability_impact": "该信号可弥补当前跨机构验证缺失的问题；若满足，可显著提高客队倾向的可验证性，可靠性提升约20%-25%。"
      },
      {
        "signal": "大小球维持稳定，未出现与客队方向冲突的节奏预期",
        "data_point": "澳门大小球保持2/2.5球，大球0.83、小球0.89均不发生超过0.05的反向水位变动",
        "reliability_impact": "只能说明市场节奏预期稳定，避免总进球盘产生明显反证；对客队方向仅提供轻度辅助，可靠性提升不超过5%。"
      }
    ],
    "risk_signals": [
      {
        "signal": "客队低水优势消失，市场回补江原FC",
        "data_point": "澳门平手盘不变，但大阪钢巴水位由0.80升至0.88或以上，同时江原FC水位由0.98降至0.90或以下",
        "reliability_impact": "客队原有的唯一明确亚盘优势将被明显削弱，客队方向可靠性下降约20%-30%，应停止依据现有盘口追随客队。"
      },
      {
        "signal": "盘口由平手转向江原FC让球",
        "data_point": "澳门亚盘由平手（0）升至江原FC让0.25球，且江原FC水位低于0.95",
        "reliability_impact": "属于方向性反转信号，表明临场资金或信息转向主队；客队倾向可靠性下降约40%以上。"
      },
      {
        "signal": "欧赔客胜被明显抬高",
        "data_point": "澳门客胜赔率由2.40升至2.50或以上，同时主胜由2.55降至2.45或以下",
        "reliability_impact": "若与亚盘客队升水同步出现，说明客队市场定价被实质性削弱；原客队倾向应降至低可信度。"
      },
      {
        "signal": "平局赔率被大幅压低而让球盘不支持客队",
        "data_point": "澳门平局赔率由3.18降至3.05或以下，同时亚盘维持平手但大阪钢巴水位升至0.85或以上",
        "reliability_impact": "显示市场对平局的防范上升，客队单边方向可能失效；客队方向可靠性下降约20%-25%。"
      },
      {
        "signal": "大小球临场大幅下调，放大友谊赛低节奏与平局风险",
        "data_point": "大小球由2/2.5球降至2球，或小球水位从0.89降至0.80以下",
        "reliability_impact": "低比分、平局和偶发赛果权重上升，会削弱依赖实力倾向的客队判断；客队方向可靠性下降约15%-20%。"
      },
      {
        "signal": "出现异常水位突变或跨机构报价分歧",
        "data_point": "任一亚盘一侧水位在15分钟内变动超过0.10，或威廉希尔、立博与澳门的客胜赔率差异超过0.15",
        "reliability_impact": "意味着现有两节点静态结构不再有效，且可能存在未反映的阵容或战意信息；应将预测视为暂时无效并重新评估。"
      }
    ],
    "live_monitoring_items": [
      {
        "item": "澳门亚盘平手盘下大阪钢巴水位走势",
        "threshold": "重点观察0.80、0.85、0.88三个位置；当前基准为0.80",
        "action_if_triggered": "跌破0.78且平手盘不变，可将客队倾向由观察提升为可跟踪；回升至0.85以上则降低信心；升至0.88以上则暂停客队方向判断。"
      },
      {
        "item": "澳门亚盘盘口档位是否变化",
        "threshold": "平手（0）升至江原FC让0.25球，或降至大阪钢巴让0.25球",
        "action_if_triggered": "若升至江原FC让0.25且主队低水，放弃客队倾向；若降至大阪钢巴让0.25且客队水位不高于0.95，可视为客队方向增强，但仍需确认阵容信息。"
      },
      {
        "item": "澳门1X2客胜与主胜赔率相对位置",
        "threshold": "客胜≤2.35为强化；客胜≥2.50且主胜≤2.45为反转风险",
        "action_if_triggered": "客胜压低至2.35或以下时，结合客队低水可提高客队倾向；客胜升至2.50或以上且主胜同步下调时，停止客队方向。"
      },
      {
        "item": "平局赔率是否被临场压低",
        "threshold": "平局由3.18跌至3.05或以下",
        "action_if_triggered": "若平赔下压且客队水位不再低于0.85，应转为防范平局，不再将客队方向作为单一判断依据；若平赔稳定在3.15以上，则维持原有观察。"
      },
      {
        "item": "大小球2/2.5球盘口与小球水位",
        "threshold": "盘口降至2球，或小球水位跌至0.80以下；大球水位升至0.95以上",
        "action_if_triggered": "出现上述低节奏信号时，降低对客队实力兑现的预期并提高平局风险权重；若盘口和0.83/0.89水位保持不变，则不以大小球干扰胜负方向。"
      },
      {
        "item": "威廉希尔与立博临场欧赔补充情况",
        "threshold": "至少补齐两家机构的开盘与临场客胜、主胜、平局数据；客胜降幅是否达到0.05",
        "action_if_triggered": "若两家均显示客胜下调至少0.05且客胜低于主胜，确认多机构客倾；若其中一家或以上明显抬高客胜0.05以上，维持pass并避免扩大判断。"
      },
      {
        "item": "临场异常波动",
        "threshold": "15分钟内亚盘水位单侧变动超过0.10，或盘口发生一次以上跳档",
        "action_if_triggered": "立即暂停使用当前预测框架，优先核查首发、轮换、伤停、比赛场地及开赛时间变更；未完成复核前维持pass。"
      }
    ],
    "failure_conditions": [
      {
        "condition": "澳门亚盘由平手（0）调整为江原FC让0.25球，且江原FC水位低于0.95",
        "verification_method": "核验澳门临场让球盘口档位及主队对应水位；两项同时满足即推翻客队倾向。"
      },
      {
        "condition": "澳门平手盘维持不变，但大阪钢巴水位升至0.90或以上，江原FC水位降至0.88或以下",
        "verification_method": "对比临场澳门亚盘双边水位；满足客队升水和主队降水的双重条件即判定原低水客倾失效。"
      },
      {
        "condition": "澳门欧赔客胜升至2.55或以上，同时主胜降至2.45或以下",
        "verification_method": "核验澳门临场1X2报价；客主赔率相对优势完全翻转即推翻原客队市场倾向。"
      },
      {
        "condition": "至少两家可核验机构显示客胜赔率较开盘上调0.08或以上，且主胜赔率较开盘下调0.08或以上",
        "verification_method": "使用威廉希尔、立博、澳门中至少两家的开盘与临场1X2数据计算变化幅度；达到条件即判定跨机构反向共识成立。"
      },
      {
        "condition": "临场出现亚盘单次水位变动超过0.10或盘口连续两次跳档，且无法由公开首发信息解释",
        "verification_method": "记录临场盘口时间戳、盘口档位和水位变化；确认异常发生并核查官方首发后仍无合理解释，即废弃原预测。"
      },
      {
        "condition": "大小球从2/2.5球降至2球，同时小球水位低于0.82",
        "verification_method": "核验澳门临场大小球盘口和小球水位；双条件满足时，比赛低节奏及平局风险显著抬升，原客队方向不再适用。"
      },
      {
        "condition": "临场首发显示大阪钢巴缺少3名或以上常规主力，且其中包含至少1名核心中前场或中卫主力",
        "verification_method": "比对官方首发与最近正式比赛常规主力名单；该非盘口因素触发后，应结合盘口重新定价并推翻现有市场基线。"
      }
    ]
  }
}
```
