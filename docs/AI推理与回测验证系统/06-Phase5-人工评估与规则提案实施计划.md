# Phase 5：人工评估与规则提案实施计划

## 目标与审查结论

将 AI 研究结果转为可审计的人类研究材料，而非自动规则。审查后固定：AI 成功样本只能提出假设；提炼出的新规则必须在未参与假设生成的独立样本上验证；示例版本 `1.9.0` 不是预设发布号。

## 实施步骤

1. 在 AI Outcome 生成后提供只读研究报告，按市场、联赛、capability、规则/AI 一致与分歧、support/counterexample/ambiguous 分类展示，并链接 sealed Receipt、Outlook、Outcome 和 EvidenceRef。
2. 增加 `AIExperimentDispositionEventV1` 的追加式人工错误分类，字段包括 outcome ID、分类枚举、说明、反证引用、评估人和时间。处置不得修改代码结算、AI Outlook、正式 Outcome 或 Study 分母。
3. 以 paired、分市场的比较报告代替只看总体准确率：同一合格 fixture 的 AI 与正式结果逐项对比，报告覆盖率、差异、比赛 cluster 区间和排除原因。5%/10% 仅为人工进入下一研究阶段的探索阈值，不声明统计显著性。
4. 人工从已封存研究中写出独立文本规则和研究备忘录。备忘录保存 AI 结果为不可信证据候选，明确适用市场、输入、反证、失效条件和数据血缘；不得把模型自然语言、概率或单场结果直接编译成 RuleSpec。
5. 新文本继续走既有 `rules intake ingest -> inspect -> scaffold -> proposal-validate`。只有被处置为 `advisory_candidate` 或人工批准的候选才进入新的实验提案 revision；不得直接调用 rules experiment activate。
6. 新实验规则的验证 cohort 必须与 AI 假设生成样本去重，冻结新 revision、规则 build manifest、对照规则和前瞻性/认证历史数据资格。旧正式规则、新实验规则和 AI 的三轨结果独立存储、独立分母、并列展示。
7. 规则晋级继续复用 `validation_studies.py` 的 30 个独立案例、跨联赛/时间窗口、多重反证、Wilson 下界和 lcz 发布批准。AI 报告或 disposition 不得满足这些门禁。

## 测试与验收

- Outcome 后才能记录处置；重复/篡改 Outcome、无 EvidenceRef、非 lcz actor 和赛后补建赛前 AI 结论均被拒绝。
- 验证研究报告不会把 pilot、diagnostic、in_sample、unknown 或 advisory 计入预测命中率。
- 验证从 AI 研究导出的 intake 仍产生行范围、原文哈希、atom disposition 和新 RuleBuildManifest。
- 验证假设生成样本与新规则验证 cohort 重叠时拒绝；新规则不能压制正式 `1.8.0` 或自动发布。

## 固定边界

- Phase 5 产出的是人工可复核的假设和提案证据，不是 AI 自动调参、自动激活或自动发布机制。
- 发布版本由 lcz 按当时版本治理决定，不预先承诺为 `1.9.0`。
