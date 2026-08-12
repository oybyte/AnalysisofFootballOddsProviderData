# football-analysis 2.0.0 发布说明

## 发布状态

**当前状态**：未发布 proposal（`publication_status: proposal`）

- 正式活动规则集仍为 `football-analysis@1.8.0`（Contract 7）
- 活动实验轨仍为 `football-analysis@1.7.0 revision 2`（Contract 6）
- 2.0.0 取代 1.9.0 提案（`supersession-1.9.0.yml` 已登记）
- 1.7.0 revision 2 处置为 `continue_parallel`（等待 2.0.0 发布后处置）
- 发布需 lcz 明确批准，发布前不切换 active ruleset、不启用真实 LLM

## 版本概要

2.0.0 引入 Knowledge Engine 知识引擎子系统，以 ports/adapters 架构实现隔离式知识裁决，通过前瞻 Study 验证后可按市场启用知识决策。基线规则集为 1.8.0，所有历史 Receipt/Outlook/Lock/Settlement/Analytics 永不修改。

## 契约变更

| 契约 | 1.8.0（当前正式） | 2.0.0（proposal） |
|------|-------------------|-------------------|
| Manifest Schema | 8 | 10 |
| AnalysisReceipt Schema | 7 | 9 |
| Calibration Contract | 7 | 9 |
| AnalysisDraftInput | V3 | V4 |
| EvaluationBundle | V3 | V4 |
| AnalysisOutlook | V5 | V7 |
| DraftBuildReceipt | V1 | V2 |
| Retrieval Contract | — | 5 |
| Index Schema | — | 6 |

## 新增能力

### 1. Knowledge Engine 子系统

`src/odds_journal/knowledge_engine/` 采用 ports/adapters 四层架构：

- **domain/**：领域模型（Study、AI V2、FeatureSnapshot、PolicyKernel、KnowledgeCard、Contract V9 模型、ReleaseEvidence）
- **ports/**：Protocol 契约（KnowledgeSource、KnowledgeIndex、ArtifactStore、ClockPort、Reasoner）
- **adapters/**：适配器实现（StudyLedger、OfficialBaselineBuilder、DeterministicKnowledgeReasoner、SQLiteIndex、AIReasonerAdapter、DraftWorkflowRegistry）
- **application/**：应用服务（run_study、run_ai_advisory、study_report、release_evidence、migrate_knowledge、build_snapshot、retrieve_knowledge、analytics）

### 2. Study 台账与前瞻闭环

- 统一 `KnowledgeStudyLedgerEventV1` 事件格式，追加式 JSONL 台账
- 幂等：相同 idempotency_key + 相同 payload 返回既有 event
- 哈希校验：event_sha256 + payload_sha256 双重校验
- JSONL 损坏 fail closed：报告文件与行号
- supersedes 链校验：断裂时报错
- 状态重建：从 ledger 重建 Study/Primary/Outcome 状态，不依赖目录扫描
- 原子事务：artifact 与 event 在同一 RepositoryTransaction 中，失败时回滚

### 3. AI V2 旁路

- 独立于 AI V1，使用独立模型和目录
- 固定失败枚举：unavailable / network_denied / timeout / budget_exceeded / schema_error / input_hash_mismatch / provider_error
- AI Input Receipt + AI Candidate/Advisory Receipt + AI Failure event
- AI failure 不得让 Study Run 伪装为成功
- 不改变正式 Draft、Outlook、Lock、Settlement、Review 或正式 Analytics

### 4. Contract 9 正式契约

- `AnalysisDraftInputV4`：冻结 10 项输入哈希（Draft Build Receipt / OfficialBaseline / FeatureSnapshot / PolicyKernelBaseline / KnowledgeSnapshot / IndexManifest / RetrievalReceipt / EvaluationBundle / Candidate / market enablement）
- `EvaluationBundleV4`：V7 市场语义验证
- `AnalysisOutlookV7`：三层 ranking（baseline_ranking / knowledge_ranking / final_ranking），knowledge_mode（enabled / baseline_only / pass），knowledge_change（none / reorder / confidence_cap / suppress）
- `DraftBuildReceiptV2`：accept-draft 必须由 lcz 确认 candidate hash
- 固定行为：baseline pass 不可重开、首选变化固定 degraded 置信度 ≤ 0.69、知识只能保持或下调基线置信度

### 5. 发布门槛校验

- `KnowledgeReleaseEvidenceV1`：内容寻址存放于 `evidence/` 目录
- 市场矩阵：fixed_handicap_1x2 和 score 永远 disabled
- 预检门禁：60+ prospective Outcome、每市场 20+ 样本、Brier ≤ +0.02、Log Loss ≤ +0.05、top-1 下降 ≤ 5pp、utility 下降 ≤ 0.05、applicability ≥ 100 项 ≥ 95%
- 未达标市场自动维持 baseline_only，不得自动升级为 enabled

### 6. RenderedOfficialBaseline

- 替代以锁定文件为基线的旧适配器
- 要求已成功 validate-draft 和 render-draft
- 时间排序：as_of < validated_at <= rendered_at < kickoff_at
- 无赛果、无赛后观测
- Study run 前后正式产物 hash 不变

## CLI 新增命令

```powershell
# Study 管理
knowledge study register --file STUDY.yml
knowledge study run MATCH_PATH --study STUDY_ID
knowledge study expose MATCH_PATH --run RUN_ID --approved-by lcz --confirm-exposure
knowledge study evaluate MATCH_PATH --run RUN_ID
knowledge study report --study STUDY_ID

# AI 旁路
knowledge ai analyze MATCH_PATH --study STUDY_ID --run RUN_ID --mode shadow-advisory
knowledge ai advisory-show MATCH_PATH --run RUN_ID
knowledge ai compare MATCH_PATH --run RUN_ID

# 发布证据
knowledge release-evidence build --proposal 2.0.0
knowledge release-evidence status --proposal 2.0.0
knowledge release-preflight --proposal 2.0.0

# 能力状态
knowledge capability-status
```

## JSON Schema 新增

- `analysis-draft-input.schema.json`：新增 V4
- `rule-evaluation-bundle.schema.json`：新增 V4
- `analysis-outlook.schema.json`：新增 V7
- `draft-build-receipt.schema.json`：新增 V2
- `calibration-config.schema.json`：新增 KnowledgeEnginePolicyV1

## 发布前必修步骤

1. 注册前瞻 Study
2. 对 60+ 场已锁定+已完赛的比赛运行 Study pipeline（每场需先完成正式 validate/render）
3. 完赛后运行 study evaluate 记录 Outcome
4. 通过全部指标门禁（Brier / Log Loss / top-1 / utility / applicability）
5. 构建 ReleaseEvidence
6. 记录人工审计（首选变化 / pass / degraded 变化）
7. 确认 1.7.0 revision 2 处置（continue_parallel 已登记，发布后执行 deactivate 或 archive）
8. lcz 明确批准发布
9. 执行 `rules release 2.0.0`

## 兼容性

- Contract 7（1.8.0）legacy 路由保持兼容
- Contract 8（1.9.0）V3 路由保持兼容
- 历史 Contract 1-8、Draft V1-V3、Bundle V1-V3、Outlook V1-V6 继续只读解析和哈希复验
- AI V1 实验轨不受影响，与 AI V2 完全隔离
- 正式 active ruleset 在发布前不切换

## 已知限制

- AI Provider 当前为 `controlled_disabled`，发布前不启用真实 LLM
- Study run 要求比赛已完成正式 validate-draft 和 render-draft
- study evaluate 要求比赛已完成 journal finish（有权威 Settlement）
- Contract 9 正式 Draft 在 2.0.0 发布前不可生成（proposal 隔离）

## 实现文件清单

核心新增文件（26 项，详见 `evidence/implementation-evidence.yml`）：

- `domain/`：contract_v9.py、release_evidence.py、studies.py（扩展）
- `adapters/`：study_ledger.py、official_baseline.py、deterministic_reasoner.py、draft_workflow_registry.py（扩展）、repository_artifacts.py（扩展）
- `application/`：run_study.py（重写）、run_ai_advisory.py（重写）、study_report.py、release_evidence.py
- `cli.py`：Study/AI/release-evidence 命令接通真实服务
- `tests/knowledge_engine/test_closure_plan.py`：122 个测试

## 验证状态

| 命令 | 结果 |
|------|------|
| `schemas check` | 通过 |
| `rules proposal-validate 2.0.0` | 通过 |
| `knowledge proposal-validate` | 通过 |
| `validate --all` | 通过 |
| `agent changes` | no_change |
| `knowledge capability-status` | shadow_ready |
| `knowledge release-preflight` | 未通过（0 个 Outcome，数据缺口） |
| 全部测试 | 通过 |
