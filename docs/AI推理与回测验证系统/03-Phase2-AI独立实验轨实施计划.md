# Phase 2：AI 独立实验轨实施计划

## 前置与审查结论

仅在 Phase 00 治理和 Phase 01 确定性回放通过后实现。审查后固定：AI Receipt 必须在首次调用前封存；失败运行也必须 seal；真实 provider 选择和凭据部署是单独获批操作，代码默认只有 FakeProvider 可用。

## 实施步骤

1. 复用 Phase 00 的配置快照、受信 Prompt、出站策略、EvidenceRef 与 provider Protocol，在 `ai_experiment.py` 实现运行状态机：`prepared -> running -> sealed | failed | stale`。Receipt 使用 `match_id + locked candidate hash + config snapshot hash` 生成稳定身份；diagnostic 另加 nonce，primary 不允许 nonce。
2. `ai experiment run` 仅接受正式已锁定、未开赛、无确认赛果的 Match。它读取并冻结正式 AnalysisReceipt、EvaluationBundle、Outlook、LockCandidateReceipt、市场特征和合格 CaseReceipt；不得启动、重启或写回正式链路。
3. 在首次 provider 调用前以事务写入 `receipt.yml` 和 primary claim。confirmatory primary 以 `match_id` 为唯一键占位；失败只能在 kickoff 前恢复同一 receipt，不能用新模型/新配置替换。pilot 只允许 diagnostic，永不占用 Primary。
4. 实现五个阶段的确定性输入编译器：事实、规则、案例、结构化预测、风险。阶段一/二/三/五为可选能力，阶段四结构化输出和 EvidenceRef 校验为必需能力。每阶段写事件、响应哈希、模型回报 ID、token、成本、重试和降级原因。
5. 阶段三无合格案例时传入固定 `no_case_comparison` 分支，禁止模型虚构案例。所有案例文本置入转义的 `untrusted_case_data` 信封，禁用工具调用和可执行指令。
6. 输出使用独立 `AIExperimentOutlookV1`，复用五市场 `assessed | pass` 语义但不复用正式 Outlook 文件。每个 assessed 市场必须含支持与反证 EvidenceRef；引用失效时仅该市场 pass；核心阶段/Schema/provider 失败则无 Outlook。
7. 运行完成后写 `bundle.yml`、可选 `outlook.yml` 和包含全部文件哈希的 `run-manifest.yml`。sealed 目录永不修改；Outcome、人工处置和报告均写独立台账。实际模型 ID、价格快照、策略或预算不匹配时 fail closed。
8. 首版只交付 FakeProvider 与完整 contract/夹具；真实 adapter 必须单独实现、获得 lcz 配置批准，并仅从受控环境变量获取凭据，不写入配置、台账、响应或报告。

## 测试与验收

- 覆盖 sandbox、pilot diagnostic、confirmatory primary 的身份、时序、权限和唯一性门禁。
- 覆盖开赛后、赛果存在、未锁定、Study 缺失、正式输入哈希失效、配置停用、重复 claim 和恢复失败。
- 覆盖每个可选阶段降级、阶段四失败、Schema 错误、引用冲突、模型/价格/预算不符和 sealed 目录篡改。
- 证明 AI 成功、失败、超时和异常均不改变正式 Outlook、LockCandidate、锁定、结算、复盘或正式统计。
- 所有外部 provider 集成测试使用 fake transport；真实网络测试不进入默认 pytest。

## 固定边界

- AI 与规则是并行研究轨，不融合、不投票、不自动修改主市场或置信度。
- 单次或 30 场比较只产生研究线索；不自动发布规则或启用生产策略。
