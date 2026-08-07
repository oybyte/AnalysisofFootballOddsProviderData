# Phase 2：AI 独立实验轨

## 目标

在 Phase 0/1 已证明回放无时间泄漏的前提下，构建可冻结、可审计、与正式轨隔离的 AI 研究产物。任何 AI 失败都不阻断已完成的正式分析和锁定。

## 与规则引擎的关系

AI 实验轨与规则引擎是**并行对比关系**，不是"替代"或"融合"。

```text
同一场比赛、同一时间点、同一盘口数据：
  ├─ 规则引擎 → 预测 A
  └─ AI 实验轨 → 预测 B

比赛结束后：
  ├─ 预测 A：对/错
  ├─ 预测 B：对/错
  └─ 记录到 analytics，用于后续对比
```

**前 30 场的目标**：积累足够数据，回答：
1. AI 在哪些市场/场景下系统性优于规则？
2. 优势有多大？（准确率差异 >10% 才值得考虑）
3. 成本如何？（AI 单次推理成本 vs 规则引擎）

**30 场后的决策树**：
```
IF AI 在某市场准确率 > 规则 + 10% AND 样本 >= 30:
    → 进入第二阶段：人工分析 AI 成功案例，提炼新规则
ELIF AI 在某市场准确率 > 规则 + 5%:
    → 继续积累到 60 场再判断
ELSE:
    → 该市场继续用规则，AI 仅作研究
```

## 配置契约

### Sandbox

`AISandboxConfigV1` 只用于快速 Prompt 和输出 Schema 试验。它仅接受合成夹具与 fake/offline provider，结果写入忽略的临时位置。Sandbox 命令必须拒绝真实 `MATCH_PATH`、CaseReceipt、网络、凭据和权威台账写入。

```powershell
odds-journal ai sandbox validate --config DRAFT.yml
odds-journal ai sandbox run --config DRAFT.yml --fixture tests/fixtures/ai/SYNTHETIC.yml
```

### Pilot 与 Confirmatory

真实数据 AI 配置使用 `AIExperimentConfigSnapshotV1`，并新增 `research_track: pilot | confirmatory`。快照冻结以下内容：

```yaml
schema_version: 1
config_id: string
snapshot_sha256: string             # canonical payload 哈希，排除本字段
research_track: pilot | confirmatory
provider_id: string
model_id: string
llm_parameters: provider-specific object
prompt_manifest: [{stage, path, sha256}]
case_profile: strict_validation | exploratory_research
reasoning_profile_id: string
reasoning_profile_sha256: string
output_schema_sha256: string
evaluation_algorithm_version: string
outbound_data_policy_sha256: string
provider_pricing_snapshot_sha256: string | null
budget: {max_total_tokens: int, max_total_cost: float | null, currency: USD}
runtime_limits: {stage_timeout_seconds: int, max_retries_per_stage: int}
```

快照只能由 lcz 通过追加式激活事件启用或停用。纯 sandbox 不进入激活台账；pilot 快照仅能运行 `diagnostic`；confirmatory 快照需要赛果前的 Study 预注册才能运行 `primary`。

```powershell
odds-journal ai experiment config validate CONFIG.yml
odds-journal ai experiment config activate CONFIG.yml --approved-by lcz --confirm-ai-experiment
odds-journal ai experiment config deactivate CONFIG_SHA256 --approved-by lcz --confirm-ai-experiment
```

## 逻辑阶段与降级

保留五阶段的研究语义：盘口事实、规则解读、案例对比、综合预测、风险清单。在 LLM 调用前，确定性编译器先生成结构化事实、规则结果、案例候选和冻结证据 ID。

| 模块 | 级别 | 失败处理 |
|---|---|---|
| 结构化输入校验 | 必需 | 运行失败，不生成 Outlook |
| 阶段一事实叙述 | 可选增强 | 标记 `unavailable`，阶段四改用确定性事实输入 |
| 阶段二规则解读 | 可选增强 | 标记 `unavailable`，保留原始规则事件 |
| 阶段三案例对比 | 可选增强 | 标记 `no_case_comparison`，不允许虚构案例 |
| 阶段四结构化预测 + EvidenceRef 校验 | 必需 | 运行失败，不生成 Outlook |
| 阶段五风险清单 | 可选增强 | Outlook 可保留，但标记 `risk_watchlist: unavailable` |

每个运行都必须冻结 `capability_profile`、模块状态和降级原因。Study 事先声明所需模块，报告将完整与降级样本分层，不得混合成一个命中率。

### Prompt 模板的降级分支

阶段三（案例对比）失败时，阶段四的 Prompt 必须处理"无案例输入"的情况。示例：

```markdown
# ai/ai-experiment-prompts/v1/stage4_prediction.md

## 综合推理与预测

你已收到：
- 阶段一：盘口事实梳理
- 阶段二：规则引擎结果解读

{{#if stage_3_available}}
- 阶段三：历史案例对比
  {{stage_3_output}}
{{else}}
- 阶段三：历史案例检索失败或无合格案例
  请仅基于盘口特征和规则信号进行推理，不得虚构案例。
{{/if}}

请输出结构化预测（JSON Schema 见下）...
```

**降级样本的统计处理**：
- 完整运行（五阶段全成功）：进入"完整 capability"分母
- 降级运行（阶段三失败）：进入"降级 capability"分母
- 两者分开报告，不混合计算命中率

## Receipt、Bundle 与 Outlook

`AIExperimentReceiptV1` 在第一次 LLM 调用前原子写入。它包含 `match_id`、`kickoff_at`、`as_of`、`run_role`、`run_nonce`、AI 快照哈希、正式 receipt/outlook/evaluation 引用、观测集、feature、CaseReceipt、重排结果和全部输入哈希。`primary` 必须绑定 `LockCandidateReceipt` 且 `run_nonce` 为空。

`AIExperimentBundleV1` 记录每阶段的状态、响应哈希、provider 报告模型、token、成本、重试和校验错误。原始响应是否保留取决于出站策略，但响应哈希始终必须存在。provider 实际模型标识与快照不符时 fail closed。

`AIExperimentOutlookV1` 与 `AnalysisOutlookV5` 共享五市场 `assessed | pass` 语义，但存储、统计和生命周期完全独立。每个 `assessed` 声明必须带支持和反证 EvidenceRef。任一引用缺失、跨 cutoff、冲突或未冻结时，对应市场强制 `pass`。

## 不可变运行和 CLI

```text
raw/matches/{match_id}/ai-experiments/{receipt_id}/
  receipt.yml
  request-manifest.yml
  responses/                 # 仅 response_storage=repository
  events.jsonl
  bundle.yml
  outlook.yml                # 只在核心运行成功时存在
  run-manifest.yml           # 封存所有其他文件的哈希与终态
```

`run-manifest.yml` 写入后目录不可修改。内容哈希计算排除 manifest 自身。运行在开赛、赛果出现、正式输入 stale 或配置停用后不得恢复。

```powershell
odds-journal ai experiment run MATCH_PATH --role diagnostic --nonce RUN_NONCE
odds-journal ai experiment run MATCH_PATH --role primary --study STUDY_ID
odds-journal ai experiment status
odds-journal ai experiment evaluate MATCH_PATH --receipt RECEIPT_ID
odds-journal ai experiment dispose --file DISPOSITION.yml
```

正式轨必须先完成 `agent start -> evaluate-draft -> validate-draft -> render-draft -> prepare-lock -> lock`。AI 运行不得回写或重启这条链路。
