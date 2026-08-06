# Phase 4：前瞻性影子运行

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
