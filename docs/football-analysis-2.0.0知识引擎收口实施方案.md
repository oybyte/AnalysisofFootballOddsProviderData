# Knowledge Engine 2.0 收口实施方案

## Summary

完成 `2.0.0` 发布前缺失的三项能力：

1. Study/AI CLI、不可变 artifact 与追加式台账完整闭环。
2. 基于前瞻 Study 的按市场发布门槛和 ReleaseEvidence 硬校验。
3. Contract 9 的正式 `Draft V4 / Bundle V4 / Outlook V7` 契约与完整工作流。

`football-analysis@1.8.0`、`1.7.0 revision 2`、历史 Receipt/Outlook/Lock/Settlement/Analytics 永不修改。`2.0.0` 在本实施完成后仍是未发布 proposal，只有 lcz 后续明确批准才可发布。

## 1. Study、AI 与台账闭环

### 台账和状态重建

在 `knowledge/knowledge-studies/` 固定使用：

```text
study-events.jsonl
primary-claim-events.jsonl
exposure-events.jsonl
outcome-events.jsonl
failure-events.jsonl
runs/{study_id}/{match_id}/{run_id}/
```

所有事件采用统一 `KnowledgeStudyLedgerEventV1`：

```yaml
schema_version: 1
event_id:
event_type: study_registered | primary_claimed | exposed | outcome_recorded | failure_recorded
aggregate_id:
idempotency_key:
recorded_at:
payload:
payload_sha256:
supersedes_event_id: null
event_sha256:
```

规则：

- 相同 `idempotency_key` 和相同 payload 返回既有 event。
- 相同 key、不同内容拒绝。
- `event_id` 重复且内容不同拒绝。
- JSONL 任一行不可解析、哈希错误或 supersedes 链断裂时 fail closed，报告文件与行号。
- 当前 Study、Primary、Outcome 状态仅从 ledger 重建，不能依赖目录扫描。
- artifact 与关联 event 必须处于同一 `RepositoryTransaction`；失败时恢复 artifact、ledger 和临时文件。
- Run artifact 采用内容寻址且不可覆盖；相同内容复用，内容冲突拒绝。

### Study 状态机

固定状态：

```text
registered
-> baseline_ready
-> primary_sealed
-> exposed
-> official_locked
-> completed
-> evaluated
-> reported
```

允许 `primary_sealed -> official_locked`，即默认 blind 不要求 expose。

拒绝条件：

- 非 `registered` Study 不得运行。
- 未完成正式 `validate/render` 不得冻结基线。
- `prepare-lock` 或 `lock` 后不得补建 Primary。
- `run_at >= kickoff_at`、已有赛果或正式输入不完整时拒绝 Primary。
- 每个 `study_id + match_id + snapshot_sha256` 只能有一个 Primary Claim。
- 未 `journal finish` 且无权威 Settlement 不得 `evaluate`。
- Outcome 只能 supersede，不得原地修改。
- counterfactual Run 只用于诊断，不能作为 Primary、发布证据或正式统计输入。

### Pre-lock Official Baseline

替换当前要求已锁定文件的基线适配器，新增 `RenderedOfficialBaselineV1`：

```yaml
match_id:
as_of:
kickoff_at:
analysis_receipt_sha256:
draft_input_sha256:
evaluation_bundle_sha256:
analysis_outlook_sha256:
rendered_report_sha256:
validated_at:
rendered_at:
baseline_sha256:
```

冻结条件：

- Receipt 必须是正式已发布 `1.8.0`、Contract 7/8 可解析版本。
- 已成功 `validate-draft`、`render-draft`。
- `as_of < validated_at <= rendered_at < kickoff_at`。
- 没有赛果、没有 post-kickoff observation。
- 不要求 lock，也不得把 lock 后产物作为 Primary 基线。
- Study run 前后，正式 Match、Draft、Bundle、Outlook、Report 分别计算 hash；运行完成后全部必须保持不变。

### CLI 真实闭环

固定知识引擎命名空间，避免影响已有顶层 `ai` 实验轨：

```powershell
knowledge study register --file STUDY.yml
knowledge study run MATCH_PATH --study STUDY_ID
knowledge study expose MATCH_PATH --run RUN_ID --approved-by lcz --confirm-exposure
knowledge study evaluate MATCH_PATH --run RUN_ID
knowledge study report --study STUDY_ID

knowledge ai analyze MATCH_PATH --study STUDY_ID --run RUN_ID --mode shadow-advisory
knowledge ai advisory-show MATCH_PATH --run RUN_ID
knowledge ai compare MATCH_PATH --run RUN_ID
```

`knowledge study run` 固定流程：

```text
正式 validate/render
-> Read RenderedOfficialBaseline
-> Compile FeatureSnapshot
-> Freeze PolicyKernelBaseline
-> Read sealed Snapshot/index
-> Retrieve Knowledge
-> Deterministic adjudication
-> Write Run artifact + Primary Claim event
```

`knowledge study evaluate` 不接受比分、赛果、结算参数，必须读取：

```text
MatchDocument
-> journal finish result source
-> authoritative Settlement
-> existing formal outcome data
-> Study Outcome
```

pass 市场写入 `not_evaluated`，不进入该市场的 Outcome 分母；AI 不在 evaluate 阶段自动运行。

### AI V2

AI V2 仅绑定已封存的 Study Run，输入白名单限定为：

- FeatureSnapshot
- RetrievalReceipt
- Knowledge Candidate
- Policy baseline
- Official baseline 摘要
- case ID 与 evidence ID

固定失败枚举：

```text
unavailable
network_denied
timeout
budget_exceeded
schema_error
input_hash_mismatch
provider_error
```

每次 AI 调用均生成 AI Input Receipt；成功写 AI Candidate/Advisory Receipt，失败写 AI Failure event。AI failure 不得让 Study Run 伪装为成功，不得改变正式 Draft、Outlook、Lock、Settlement、Review 或正式 Analytics。

## 2. 研究报告、能力状态与发布证据

### Study Report

`knowledge study report` 从事件 ledger 重建：

- registered Study
- 有效 Primary Run
- exposure 状态
- 未被 supersede 的 Outcome
- failure/not_run/counterfactual 排除项
- Snapshot、市场、cohort、暴露状态分层

固定统计口径：

- 同一 `study_id + match_id + snapshot_sha256` 仅计一次有效 Primary。
- 被 supersede 的 Outcome 不进入分母。
- 只有 `prospective_out_of_sample` 进入发布指标。
- 无有效正式基线的 Run 可以计 coverage，不能进入与 `1.8.0` 的共同覆盖比较。
- 1X2 仅在基线与知识均有有效概率 forecast 时计算 Brier、Log Loss。
- 亚洲让球、总进球只计算既有 Settlement utility。
- AI exposure 与 blind Run 必须独立分层，不能合并为发布主指标。

### 能力状态

`knowledge capability status` 改为读取真实 ledger 和 Snapshot/index，输出：

```text
implemented_disabled
shadow_ready
study_active
release_eligible
formal_active
```

并细分：

```text
snapshot
logical_index
local_index
study_count
primary_count
evaluated_outcome_count
failure_count
release_evidence
contract_9
ai_provider
formal_isolation
```

禁止以单一 `verified-current` 掩盖禁用或未完成状态。

### ReleaseEvidence

新增 `KnowledgeReleaseEvidenceV1`，内容寻址存放于：

```text
knowledge/rule-proposals/football-analysis/2.0.0/evidence/
```

固定字段：

```yaml
schema_version: 1
evidence_id:
proposal_sha256:
manifest_sha256:
calibration_config_sha256:
snapshot_sha256:
logical_index_sha256:
study_ids: []
primary_run_ids: []
valid_outcome_ids: []
study_report_sha256:
manual_audit_sha256:
experiment_disposition_sha256:
market_enablement:
  one_x_two: enabled | baseline_only | disabled
  asian_handicap: enabled | baseline_only | disabled
  fixed_handicap_1x2: disabled
  total_goals: enabled | baseline_only | disabled
  score: disabled
gate_results:
evidence_sha256:
```

### 发布预检

新增：

```powershell
knowledge release-evidence build --proposal 2.0.0
knowledge release-evidence status --proposal 2.0.0
knowledge release-preflight --proposal 2.0.0
```

预检必须验证：

- 至少 60 个独立 prospective Outcome。
- 每个 `enabled` 且存在行为变化的市场至少 20 个 evaluated 样本。
- 时间泄漏、正式轨串写、哈希错误、赛后补建均为 0。
- 1X2 Brier 增量 `<= +0.02`。
- 1X2 Log Loss 增量 `<= +0.05`。
- 共同覆盖 top-1 准确率下降不超过 5pp。
- 亚洲让球与总进球 utility 下降不超过 `0.05`。
- 首选变化、pass/degraded 变化均有不可变人工审计记录。
- 其他适用性抽样至少 100 项且正确率 `>= 95%`。
- `1.7.0 revision 2` 已有绑定其 immutable snapshot 的 `continue_parallel`、`deactivate_after_2_0_release` 或 `archive_without_activation` 处置。
- Snapshot、逻辑索引、Study report、人工审计和市场矩阵哈希一致。

未达标市场自动维持 `baseline_only` 或 `disabled`，不得自动升级为 `enabled`。

## 3. Contract 9 正式契约

### 模型与 Schema

新增并注册：

- `AnalysisDraftInputV4`
- `EvaluationBundleV4`
- `AnalysisOutlookV7`
- `DraftBuildReceiptV2`
- Contract 9 Calibration Config parser
- 对应 JSON Schema
- schema registry、Analytics rebuild parser、render/lock/settlement/review parser

修复 CalibrationConfig 对 schema version 9 的完整解析；删除发布器对 `2.0.0` 跳过 calibration 校验的特殊分支。

历史 Contract 1-8、Draft V1-V3、Bundle V1-V3、Outlook V1-V6 必须继续只读解析和哈希复验。

### V4 Draft

`AnalysisDraftInputV4` 必须冻结：

```text
Draft Build Receipt
OfficialBaselineSnapshot
FeatureSnapshot
PolicyKernelBaseline
KnowledgeSnapshot
KnowledgeIndexManifest
KnowledgeRetrievalReceipt
KnowledgeEvaluationBundle
KnowledgeDraftCandidate
market enablement matrix
```

候选重新构建时，任一冻结哈希变化必须产生新 candidate；`accept-draft` 必须由 lcz 确认 candidate hash，输入变化即拒绝接受。

### V7 市场语义

保留现有正式市场状态：

```text
status: assessed | degraded | pass
```

新增独立知识状态：

```text
knowledge_mode: enabled | baseline_only | pass
knowledge_change: none | reorder | confidence_cap | suppress
baseline_ranking: []
knowledge_ranking: []
final_ranking: []
```

固定行为：

- `enabled`：知识裁决可在权限边界内影响最终排名。
- `baseline_only`：使用 `1.8.0` 基线排名，知识可解释但不得改变正式方向。
- `pass`：市场无独立正式证据，禁止候选、锁定与统计。
- `knowledge_mode: pass` 必须对应 `status: pass`。
- baseline `pass` 永远不能被知识或 AI 重开。
- 首选变化至少需两个同市场、同选择、独立 provenance group；共享 source family 或 observation lineage 只算一个来源。
- 发生首选变化固定 `degraded`，置信度不超过 `0.69`。
- 知识只能保持或下调基线置信度。
- advisory、research_only、AI 产物永远不能写入正式排名。

### Contract 9 工作流

更新 `DraftWorkflowRegistry`：

```text
Contract 7 -> legacy
Contract 8 -> formal draft V3
Contract 9 -> knowledge formal draft V4
```

实现：

```powershell
agent build-draft MATCH_PATH
agent accept-draft MATCH_PATH --candidate-sha SHA256 --approved-by lcz --confirm-draft
agent evaluate-draft MATCH_PATH --dispositions-file DISPOSITIONS.yml
agent validate-draft MATCH_PATH
agent render-draft MATCH_PATH
agent prepare-lock MATCH_PATH --market MARKET --selection SELECTION --confidence VALUE
```

Contract 9 条件：

- Receipt 必须引用已发布的 `2.0.0` Snapshot。
- proposal Receipt 只能运行 Study sidecar，禁止生成正式 Draft、Outlook、Lock 和统计。
- Snapshot/index 缺失、损坏或 hash 不一致时 fail closed。
- `prepare-lock` 仅能选择非 pass 市场。
- settlement/review 对 V7 读取 `status`，pass 市场写 `not_evaluated` 且排除统计分母。

## 4. 发布器、测试与验收

### 发布事务顺序

`rules release 2.0.0` 固定顺序：

```text
proposal validate
-> calibration/schema validate
-> knowledge release-preflight
-> ReleaseEvidence hash validate
-> Match migration preflight
-> build temporary ruleset directory
-> validate temporary published ruleset
-> atomically update active.yml
-> rebuild indexes
```

任何前置门禁失败都不得创建目标发布目录。后续失败时恢复 temporary directory、active pointer、索引和迁移文件。

### 测试

新增真实临时仓库与 `Typer CliRunner` 覆盖：

```text
正式 validate/render
-> knowledge study register
-> knowledge study run
-> knowledge ai analyze
-> knowledge study expose
-> prepare-lock/lock
-> journal finish
-> knowledge study evaluate
-> knowledge study report
-> knowledge release-evidence build
-> knowledge release-preflight
```

必须覆盖：

- 事件幂等、哈希错误、JSONL 损坏、事务失败恢复和孤立 artifact 拒绝。
- pre-lock baseline 时点、赛后补建、重复 Primary、Snapshot 变化、Outcome supersession。
- AI unavailable/network denied/timeout/budget/schema failure。
- 正式 Match、Draft、Bundle、Outlook、Lock hash 在 Study/AI 前后不变。
- Contract 7/8 兼容、Contract 9 V4/V7 正常链路和 proposal 隔离。
- `enabled/baseline_only/pass` 市场矩阵。
- pass 市场不候选、不锁定、不结算、不计分母。
- ReleaseEvidence 缺失、过期、样本不足、指标不达标、审计缺失、处置缺失、Snapshot/index 不一致等全部负例。

### 验收命令

```powershell
.\scripts\odds-journal.ps1 knowledge proposal-validate 2.0.0
.\scripts\odds-journal.ps1 rules proposal-validate 2.0.0
.\scripts\odds-journal.ps1 schemas check
.\scripts\odds-journal.ps1 analytics build
.\scripts\odds-journal.ps1 analytics validate
.\scripts\odds-journal.ps1 evidence validate
.\scripts\odds-journal.ps1 case validate
.\scripts\odds-journal.ps1 validate --all
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\odds-journal.ps1 agent changes
```

若 `agent changes` 返回 `workflow_breaking`，在工作区干净后执行 `agent sync`。本阶段完成后仅形成可验证的 `2.0.0` proposal 与前瞻研究轨，不发布、不启用真实 LLM、不切换正式 active ruleset。

### 提交顺序

1. `实现Study台账与前瞻闭环`
2. `接通知识引擎AI旁路`
3. `实现知识发布门槛校验`
4. `接入Contract9正式分析契约`
5. `完善知识引擎发布验收`
