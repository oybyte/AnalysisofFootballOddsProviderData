# Phase 4：前瞻性影子运行

## 第一阶段的典型工作流

Phase 4 是日常比赛分析中运行 AI 实验的入口。前 30 场的典型流程：

```powershell
# 1. 正式分析流程（规则引擎，已有）
.\scripts\odds-journal.ps1 agent start matches/2026/08/比赛.md
.\scripts\odds-journal.ps1 agent evaluate-draft matches/2026/08/比赛.md --draft-file draft.yml --dispositions-file disp.yml
.\scripts\odds-journal.ps1 agent validate-draft matches/2026/08/比赛.md
.\scripts\odds-journal.ps1 agent prepare-lock matches/2026/08/比赛.md --market one_x_two --selection home --confidence 0.60
odds-journal lock matches/2026/08/比赛.md --candidate-file raw/matches/{match_id}/lock-candidates/{receipt_id}.yml

# 2. AI 影子运行（仅在已激活、获批准的配置下；与正式轨并行）
odds-journal ai experiment study register --file STUDY.yml
odds-journal ai experiment run matches/2026/08/比赛.md --role primary --study STUDY_ID
# 当前 FakeProvider 只验证生命周期，不能产生可比较预测；未来真实 provider 运行成功或失败都不影响上面的正式锁定

# 3. 比赛结束后
odds-journal finish matches/2026/08/比赛.md --score 2-1 --source "官方" --key-events "无红牌"
odds-journal ai experiment evaluate matches/2026/08/比赛.md --receipt AI_RECEIPT_ID

# 4. 每 10 场看一次对比
odds-journal ai experiment report --study STUDY_ID
```

**关键点**：
- 正式轨（规则）和 AI 轨完全独立运行
- AI 失败不影响正式锁定
- 当前阶段只有正式 Outlook 可结算；AI 只有在真实 provider 获批、赛前封存且输出有效 Outlook 后才可独立评价
- 达到预注册样本量后才可产出对比报告

## 目标

在真实赛前场景积累 AI 研究样本，与正式轨并行但不交叉。正式轨完成锁定后，AI 才可在开赛前启动；AI 失败不回滚或延迟正式轨。

```text
agent start -> evaluate-draft -> validate-draft -> render-draft -> prepare-lock -> lock
                                                                        |
                                                                        v
                                             pilot diagnostic 或 confirmatory primary
                                                                        |
                                                                        v
                                                      开赛前封存 AI 运行
```

## Primary 唯一性

confirmatory Primary 在第一次 provider 调用前追加 `AIExperimentPrimaryClaimEventV1`：

```yaml
claim_id: string
match_id: string
receipt_id: string
ai_config_snapshot_sha256: string
formal_outlook_sha256: string
lock_candidate_receipt_sha256: string
claimed_at: datetime
claimed_by: system
```

以 `match_id` 为唯一键占用名额。名额被占用后，只能在 kickoff 前恢复同一 receipt，不能以新配置、新 nonce 或 diagnostic 替换。正式分析重启、Outlook 改变或锁定哈希不一致时，该 Primary 标记 `stale_formal_input`，且不得为该场补建新 Primary。

Primary 只有在 `sealed_at < kickoff_at`、Outlook 完整、正式输入未 stale 且满足 Study 所需 capability profile 时才可评价。失败、超时、赛后封存或运行期间不合格的样本保留审计记录，不进入分母。

## Study 预注册

每个 confirmatory 研究必须在首场赛果可见前追加 `AIExperimentStudyV1`：

```yaml
schema_version: 1
study_id: string
registered_at: datetime
registered_by: lcz
ai_config_snapshot_sha256: string
cohort:
  inclusion_criteria: []
  exclusion_criteria: []
  competitions: []
  sample_relation: out_of_sample
primary_run_policy: first_eligible_before_kickoff
required_capability_profile: []
market_metrics: []
formal_baseline_schema_sha256: string
minimum_independent_matches: int
stopping_conditions: []
status: registered | closed | superseded
```

研究登记后不可原地修改。变更 cohort、模块门禁、指标或停止条件时，必须追加新版并标记旧版 `superseded`。不得在看到赛果后回溯调整分母。

## 样本积累与报告

- pilot 可以在预先声明的小样本 cohort 上评估运行性、模块失败率、证据完整度和出站费用，不报告预测有效性。
- 20 场 confirmatory Primary 可以产出可运行性和错误类型报告，但不构成规则晋级证据。任何规则支持结论继续遵守项目既有的至少 30 个合格独立案例及跨联赛/时间窗口门禁。
- 报告分别显示完整与降级 capability profile，不将这两类样本合并为单一结论。
