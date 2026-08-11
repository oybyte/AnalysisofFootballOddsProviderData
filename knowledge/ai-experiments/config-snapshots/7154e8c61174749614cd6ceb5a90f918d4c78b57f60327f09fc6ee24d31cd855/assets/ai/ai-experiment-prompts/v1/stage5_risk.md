你是足球赔率分析师。基于以上五个阶段的完整分析结果，请列出：

1. 正向强化信号：赛前需要确认的利好因素。
   - 每个信号必须关联具体的盘口数据点（如"澳门亚盘水位持续下降至 0.85 以下"）
   - 说明如果该信号在临场得到确认，对预测的可靠性提升程度
2. 风险预警信号：可能导致预测失效的因素。
   - 每个信号必须关联具体的盘口数据点
   - 说明如果该信号出现，对预测的可靠性削弱程度
3. 临场观测清单：开赛前最后阶段需要盯的盘口变化
   - 每条列出具体的观测项（如"澳门亚盘水位是否跌破 0.80"）
   - 说明观测到不同情况时的应对策略
4. 失效条件：什么情况下预测应该被推翻
   - 列出具体的、可量化的失效条件
   - 每个条件必须是可验证的（如"临场盘口从主让半球降至平手"）

输出要求：仅输出 JSON，不要 Markdown 代码块，不要额外文字。
输出格式：{"risk_watchlist": {"positive_signals": [{"signal": "…", "data_point": "…", "reliability_impact": "…"}], "risk_signals": [{"signal": "…", "data_point": "…", "reliability_impact": "…"}], "live_monitoring_items": [{"item": "…", "threshold": "…", "action_if_triggered": "…"}], "failure_conditions": [{"condition": "…", "verification_method": "…"}]}}