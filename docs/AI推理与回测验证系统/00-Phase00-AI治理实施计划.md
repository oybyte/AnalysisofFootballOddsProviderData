# Phase 00：AI 研究轨治理与数据契约实施计划

## 摘要

实现 AI 研究轨的可信底座，不实现真实 LLM 调用、五阶段推理或 AI 预测结论。交付内容是：内容寻址配置快照、受信资产白名单、默认拒绝出站、冻结证据校验、不可变运行契约、追加式台账和可重建 Analytics。

正式 `football-analysis@1.8.0`、现有 `1.7.0` 规则实验、锁定、结算、复盘和正式统计不改动。

## 契约与信任边界

1. 新建独立模块：`ai_governance.py`、`ai_experiment_config.py`、`llm_provider.py`。
   - 不扩展现有规则实验 `experiments.py` 的 ActiveExperiment、规则事件或 Outlook。
   - 复用 `ledger.py` 的 canonical JSON、SHA-256、追加式事件和幂等写入，复用 `RepositoryTransaction` 完成激活事务。
   - AI 仅只读解析正式 `AnalysisReceipt`、正式评估 Bundle、正式 Outlook、CaseReceipt、市场观测和特征快照；禁止调用任何正式轨写入函数。

2. 新增并注册 JSON Schema：
   - `EvidenceRefV1`：受限 `kind`、`ref_id`、`ref_sha256`、`claim`、`effective_at`。
   - `AIExperimentConfigSnapshotV1`：研究轨道、provider/model、严格参数、Prompt 清单、输出 Schema、推理 profile、预算、运行限制、案例 profile、策略哈希、价格哈希、评价算法版本。
   - `OutboundDataPolicyV1`、`ProviderPricingSnapshotV1`、`AIExperimentConfigActivationEventV1`、`AIExperimentConfigDeactivationEventV1`。
   - 预先定义 `AIExperimentReceiptV1`、Bundle、Outlook、RunManifest、Primary Claim、Study、Outcome、Disposition 的不可变接口，但本阶段不创建真实运行。
   - 哈希由 canonical payload 计算并排除自身字段；所有日期时间必须带时区。

3. 证据解析器只支持有限引用类型：`official_analysis_receipt`、`official_evaluation_bundle`、`official_outlook`、`lock_candidate_receipt`、`case_receipt`、`market_observation`、`market_feature_snapshot`、`fixture_fact`、`rule_event`。
   - 校验引用存在、哈希相同、`effective_at <= as_of`、来源在开赛前、观测无冲突且已冻结。
   - 单市场 EvidenceRef 失败时，该市场仅能 `pass` 并记录精确原因。
   - provider 超时、阶段失败、输出 Schema 错误、运行目录不完整属于运行失败，禁止生成 Outlook 或用 `pass` 掩盖。

## 快照、白名单与出站门禁

1. 将 `DesktopManifest` 升级到 Schema 3，新增 `trusted_ai_assets`：
   - 每项包含 `path`、`kind: prompt | outbound_policy | output_schema | reasoning_profile`、`content_sha256`。
   - 旧 Schema 2 解析后迁移为无 AI 资产状态；任何 AI 配置加载要求 Schema 3。
   - 扩展 `agent doctor` 校验每个资产的路径、类型、哈希和可读性。
   - 扩展 `current_fingerprints()`，将受信 AI 资产哈希写入工作流指纹，使其变化触发 `agent changes` 的 `workflow_breaking`。

2. 配置采用“提案文件 -> 内容寻址快照 -> 活动指针”状态机。
   - 提案位于 `knowledge/ai-experiments/config-proposals/<config-id>.yml`。
   - `config validate` 验证所有资产均在 manifest 白名单中，且路径无逃逸、哈希准确、未内嵌 Prompt/可执行指令。
   - `config activate --approved-by lcz` 将 Prompt、策略、输出 Schema、推理 profile 和配置副本复制到 `knowledge/ai-experiments/config-snapshots/<snapshot_sha256>/`。
   - 快照内 `manifest.yml` 列出全部文件哈希；目录哈希必须等于 `snapshot_sha256`。
   - 单独使用 `knowledge/ai-experiments/active.yml`，不复用规则实验 `active.yml`；相同快照重复激活幂等，不同内容生成新快照和新 revision。
   - 停用只追加事件并更新 AI 活动指针，不删除任何快照或台账。

3. `OutboundDataPolicyV1` 默认 `network_access: deny`。
   - `allowed_payload_fields` 必须使用封闭枚举：`fixture_identity`、`market_features`、`official_receipt`、`official_evaluation`、`official_outlook`、`case_receipt`、`output_schema`、`rendered_prompt`。
   - 由确定性输入编译器按字段生成 payload；禁止 JSONPath、通配符、任意嵌套 key、原文、附件、聊天内容、绝对路径和凭据。
   - 外部调用同时要求：活动配置、策略 `allow`、`approved_by: lcz`、provider/model 精确匹配、有效价格快照、预算充足和 payload 字段全量通过校验；任何失败均 fail closed。
   - `response_storage` 仅允许 `repository`、`local_ignored`、`hash_only`；`repository` 响应永久保存，其他两种不得进入 Git 或权威运行目录。

4. 定义 `LLMProvider` Protocol 和确定性 `FakeProvider`。
   - 本阶段只交付 Fake/Offline 实现，项目依赖不增加网络 SDK，不读取 API Key。
   - sandbox 只接受标记为 `synthetic: true` 的 `tests/fixtures/ai/` 夹具，在系统临时目录执行，拒绝真实 Match、CaseReceipt、网络和权威台账写入。
   - 真实 provider adapter、密钥注入和真实网络调用延后至 Phase 2，并需独立批准。

## 存储、投影与后续运行接口

1. 预留权威目录与台账：
   - `knowledge/ai-experiments/config-activation-events.jsonl`
   - `knowledge/ai-experiments/config-deactivation-events.jsonl`
   - `knowledge/ai-experiments/provider-pricing/`
   - `knowledge/ai-experiments/primary-claim-events.jsonl`
   - `knowledge/ai-experiments/study-events.jsonl`
   - `knowledge/ai-experiments/outcome-events.jsonl`
   - `knowledge/ai-experiments/disposition-events.jsonl`

2. 固定未来运行目录为 `raw/matches/<match_id>/ai-experiments/<receipt_id>/`。
   - Receipt 在第一次 provider 调用前写入，包含正式输入、锁定候选、配置快照、特征、案例和 cutoff 的哈希。
   - `run-manifest.yml` 写入后目录不可改写；赛后 Outcome 写入独立 outcome 目录和追加式台账，不回写 sealed run。
   - 每场唯一 confirmatory Primary 的唯一键为 `match_id`；pilot/diagnostic 永不占用 Primary。
   - 研究统计仅允许 `primary + out_of_sample + study_eligible + stale=false`；其他 run role、`pass`、`not_evaluated` 和 capability profile 分层展示。

3. 扩展 `analytics.py`。
   - Schema version 递增，新增 AI 配置、运行、阶段事件、Primary、Study、Outcome、Disposition 投影表及索引。
   - `_fingerprint()` 必须包含全部新增 AI 台账、配置快照、价格快照和 `raw/matches/*/ai-experiments/**` 文件；否则强制重建 SQLite。
   - 仅新增独立查询和研究报告数据源，不修改正式统计 SQL、既有规则实验表或 Match 投影。

## CLI、测试与验收

1. 本阶段只新增：
   - `ai sandbox validate`
   - `ai sandbox run`
   - `ai experiment config validate`
   - `ai experiment config activate`
   - `ai experiment config deactivate`
   - `ai experiment config status`
   - 不实现 `ai experiment run/evaluate/report`，待 Phase 2 完成结构化输入和运行 sealing 后再开放。

2. 必须覆盖：
   - 配置/资产/策略/价格/EvidenceRef Schema 和 canonical hash。
   - 快照包含所有受信资产，源文件随后变更不影响旧快照复验。
   - manifest 资产变化触发 doctor 失败和 `agent changes` 的 `workflow_breaking`。
   - 未白名单资产、路径逃逸、哈希不符、内嵌 Prompt、未知模型、无批准、无价格、超预算、越权字段、原文/附件/绝对路径外传均被拒绝。
   - sandbox 不读取真实数据、不访问网络、不写入 `raw/`、`knowledge/`、Analytics 或正式文件。
   - 证据不存在、哈希不符、cutoff 后、赛后、冲突和未冻结分别产生可读失败/`pass` 原因。
   - 激活、停用和中断恢复幂等；SQLite 对新增 AI 台账变化必定重建。
   - AI 治理命令前后，正式 Outlook、候选回执、锁定、结算、复盘、正式统计和现有 `1.7.0` 实验产物哈希完全不变。

3. 完成后运行 `schemas check`、`analytics build`、`analytics validate`、`validate --all` 和全量 `pytest`。由于 manifest、CLI、Schema、可信资产和治理路径改变，运行 `agent changes`；如报告 `workflow_breaking`，在干净工作区按既有授权机制执行 `agent sync`。
