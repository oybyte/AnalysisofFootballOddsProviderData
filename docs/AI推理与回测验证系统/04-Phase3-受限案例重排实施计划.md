# Phase 3：受限案例重排实施计划

## 前置与审查结论

本阶段可选，前 30 场默认继续使用现有 `retrieve_cases()` 的 BM25 结果。审查后固定：重排不是语义检索或模型判断，而是对已冻结候选的纯确定性排序；不能以少量 full/degraded 样本差异决定是否上线。

## 实施步骤

1. 新建 `case_rerank.py`，定义 `CaseProfile`、`CaseVectorSchemaV1`、`CaseRerankIndexManifestV1`、`CaseRerankReceiptV1`。索引只包含 versioned normalized market features、场景标签和资格元数据，不包含原文、规则全文、heuristics 或证据正文。
2. `strict_validation` 在向量化前筛选 `prematch_verified + statistics_eligible + approved` 案例；`exploratory_research` 可包含未认证项但固定 `research_only`，永不进入 Primary/正式比较分母。
3. 固定 V1 特征列、缺失值编码、标准化参数和距离算法。训练集统计只在 `index-manifest` 中冻结一次；查询不重新拟合。距离采用确定性加权数值距离，权重、向量 schema 和候选 corpus 指纹都写入 Receipt。
4. `case rerank run MATCH_PATH --config RERANK_CONFIG.yml` 根据冻结配置生成内容寻址结果；它必须验证已有 CaseReceipt 的 selected cases、cutoff、hash 和 profile，并且只重排该候选集，不扩大检索范围。
5. 同分按 case ID/revision 固定排序；缺失向量字段使用 schema 规定的缺失值和距离惩罚；无可比候选返回 `no_case_comparison`。失败不会伪造相似案例，也不阻断 AI 的其他阶段。
6. 对传给 AI 的候选摘要使用转义 `untrusted_case_data` 信封，只含白名单字段和结构化差异；不传原始案例 Markdown 或指令性文本。
7. 将索引/receipt 加入独立 Analytics 覆盖表和 AI run 指纹。是否实施由 30 场后的预先声明评估决定：检索失败率超过 30%，且同 capability/profile 的独立样本显示有稳定、可解释的增益，才提出启用申请。

## 测试与验收

- 同一 Corpus、schema、权重、CaseReceipt 和 query 必须得到相同候选和顺序。
- 未认证、cutoff 后、hash 不符、非 CaseReceipt 候选和 profile 越权案例均被拒绝。
- 覆盖缺失特征、完全同分、空候选、索引损坏和重排失败的降级状态。
- 证明重排不写规则、预测、正式 Outlook、锁定或正式统计；探索候选不会进入 strict 分母。

## 固定边界

- Phase 3 不使用 embedding、在线学习或 LLM 重排；若未来需要，必须建立新的隐私、版本和回放契约。
- “差异小于 5%”仅是停止投入的探索信号，不能视为统计结论。
