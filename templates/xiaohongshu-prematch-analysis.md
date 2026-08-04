# {{home_team}} vs {{away_team}}｜{{headline_question}}

{{home_team}} vs {{away_team}}  
数据截止时间：{{data_cutoff}}（赛前约 {{minutes_to_kickoff}} 分钟）  
比赛时间：{{kickoff_at}} | 天气：{{weather}} | 场地：{{venue}} | 联赛：{{competition}}

盘口反映赛前市场定价，不代表确定赛果。本文兼顾赛前分析与盘口教学，仅供足球数据学习交流。

## 1、让球盘：{{handicap_headline}}

让球盘可以理解为市场设置的一条实力差距线。

{{handicap_plain_language}}

```text
阶段 | 盘口 | 主队水位 | 客队水位 | 走势
{{handicap_rows}}
```

{{handicap_settlement_plain_language}}

**机构角度**

{{handicap_institutional_psychology}}

**用户角度**

{{handicap_user_psychology}}

## 2、胜平负赔率：{{one_x_two_headline}}

```text
机构 | 主胜（初 / 即） | 平局（初 / 即） | 客胜（初 / 即） | 赔率走势
{{one_x_two_rows}}
```

{{one_x_two_change_summary}}

**机构角度**

{{one_x_two_institutional_psychology}}

**用户角度**

{{one_x_two_user_psychology}}

## 3、凯利指数：{{kelly_headline}}

凯利指数用于比较三种赛果之间的赔付风险分布；重点是三项差距和变化，不是孤立解读单一数值。

```text
机构 | 主胜（初 / 即） | 平局（初 / 即） | 客胜（初 / 即） | 凯利走势
{{kelly_rows}}
```

```text
即时平均凯利：
主胜：{{home_kelly_now}}
平局：{{draw_kelly_now}}
客胜：{{away_kelly_now}}
三项差值：{{kelly_max_gap}}
```

**机构角度**

{{kelly_institutional_psychology}}

**用户角度**

{{kelly_user_psychology}}

## 4、总进球：{{total_goals_headline}}

{{total_goals_plain_language}}

```text
机构 | 盘口 | 大球水位（初 / 即） | 小球水位（初 / 即） | 走势
{{total_goals_rows}}
```

**机构角度**

{{total_goals_institutional_psychology}}

**用户角度**

{{total_goals_user_psychology}}

```text
核心进球区间：{{core_goals_range}}
次选进球区间：{{secondary_goals_range}}
```

## 5、综合判断：{{synthesis_headline}}

```text
让球盘：{{handicap_conclusion}}
胜平负：{{one_x_two_conclusion}}
凯利：{{kelly_conclusion}}
总进球：{{total_goals_conclusion}}
```

**机构角度**

{{synthesis_institutional_psychology}}

**用户角度**

{{synthesis_user_psychology}}

## 6、比分场景

```text
核心比分：{{core_scores}}
次选比分：{{secondary_scores}}
```

{{score_reasoning}}

## 7、临场重点观察

### {{positive_signal_title}}

```text
{{positive_signals}}
```

{{positive_signal_interpretation}}

### {{risk_signal_title}}

```text
{{risk_signals}}
```

{{risk_signal_interpretation}}

## 8、极简结论

```text
胜平负：{{brief_one_x_two}}
让球盘：{{brief_handicap}}
总进球：{{brief_total_goals}}
核心比分：{{brief_scores}}
```

{{final_sentence}}

{{hashtags}}

<!--
写作约束：
- 完整保留用户提供的原始数据、机构名称、初盘/即时值、盘口和截止时间；不得以概括性文字替代数据。
- 让球结算仅使用与实际盘口、盘向一致的简洁结论；四分之一盘必须明确全赢、赢半、走盘、输半或全输。
- “机构角度”写机构可能的风险控制或引导倾向，必须使用“可能”“更像”“暂时不能排除”等限定语，不能把机构意图写成已证实事实。
- “用户角度”写普通读者面对低水、降赔、升盘等信号时常见的心理预期，以及该预期与实际结算门槛之间的差别。
- 观点必须紧跟对应数据，不重复同一结论；避免“机构视角/用户视角/稳健建议”式空泛模板话术。
- 发布前检查标题、正文、表格、结论和标签，避免使用平台限制用语及含义相近、无法证实的宣传表述。
- 外部发布稿不是正式 Match 分析、锁定回执或规则文档，不得替代仓库的赛前工作流。
-->
