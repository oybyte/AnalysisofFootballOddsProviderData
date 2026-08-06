# Phase 4：前瞻性影子运行实施计划

## 目标与审查结论

实现 AI 研究样本的赛前封存、赛后代码化评价和 Study 分母控制。审查后补充：Study 必须在其任何 Primary claim 前登记；Primary 只能绑定已经普通锁定的正式输入；`finish` 不得隐式运行或评价 AI。

## 实施步骤

1. 在 `ai_experiment.py` 定义 `AIExperimentStudyV1`、`AIExperimentPrimaryClaimEventV1` 和研究 eligibility 计算器。Study 冻结 config snapshot、cohort、市场指标、sample relation、所需 capability、停止条件和正式基线 schema 哈希；同 Study 的任何结果出现后不得原地改写，变更必须新 Study 并 supersede 旧项。
2. `ai experiment study register` 只允许 lcz，在首个 claim 前写入追加式台账。`ai experiment run --role primary` 验证 Study 已注册、Match 已普通锁定、`locked_at < kickoff`、赛果不存在、输入全量冻结且符合 cohort；不满足则拒绝而非降级为 pilot。
3. Primary claim 与 AI Receipt 在首次 provider 调用前同一事务提交，唯一键为 match ID。claim 后只允许同 receipt 在 kickoff 前恢复；正式 Outlook/候选/锁定哈希变化则标记 `stale_formal_input`，不得替换 Primary。
4. kickoff 后封存运行状态，禁止新增或补建 Primary。provider 失败、超时或 capability 不足保留审计记录，但不进入 Study 预测分母；pilot 单独报告运行性、费用和证据完整度。
5. 比赛完赛仍由既有 `journal finish`/`finish` 驱动。新增独立 `ai experiment evaluate` 只读取 sealed Outlook、冻结盘口线、确认的结果观测和 Study，生成 Outcome；不得由 finish 自动调用，也不得修改正式 Settlement/Review。
6. 评价结果按市场派生 `correct/incorrect/not_evaluated`、亚洲盘完整结算、区间/比分命中与 capability profile。只有 `primary + out_of_sample + study_eligible + stale=false + sealed_at < kickoff` 进入 AI 比较分母。
7. `ai experiment report` 按 Study、市场、联赛、capability、run 状态和 sample relation 输出覆盖率、pass、结算和成本；每十场仅输出中期描述性报告，不自动开启 Phase 5。

## 测试与验收

- 覆盖 Study 在 claim 后登记、未锁定、开赛后、赛果存在、cohort 不符和 capability 不符的拒绝。
- 覆盖并发 Primary claim、同 receipt 恢复、替换配置/nonce、正式输入 stale、停用配置及故障封存。
- 覆盖结果冲突、pass、not evaluated、亚盘四分之一盘和 Outcome 幂等；finish 运行前后 AI 文件不被自动创建或改写。
- 验证报告严格排除 diagnostic、pilot、in_sample、unknown、stale 和不合格 capability 样本。

## 固定边界

- 影子运行不延迟、不回滚、不重启正式流程。
- 20/30 场只用于运行性和探索对比；任何规则发布仍遵循独立验证研究门禁。
