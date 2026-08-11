# football-analysis@2.0.0 隔离式知识引擎迁移与可插拔 AI 完整实施方案

## 一、目标与固定边界

在当前仓库内新增独立 knowledge_engine 子系统，通过 ports/adapters 读取现有权威数据。先作为只读旁路运行，达到前瞻验证门槛并由 lcz 批准后，再替换正式草稿决策来源。

~~~text
旁路阶段
1.8.0 正式流程 -> 正式 Outlook/锁定/结算
       └-> 冻结基线 -> Knowledge Engine V2 -> Study/AI Sidecar

发布阶段
agent build-draft -> Knowledge Engine V2
agent accept/evaluate/validate/render/prepare-lock/lock -> 现有生命周期
~~~

固定约束：

- 正式 football-analysis@1.8.0 在发布前保持不变。
- 1.9.0 原文件和哈希不修改，通过追加事件标记为被 2.0.0 取代。
- 历史 Contract 7/8、Receipt、Outlook、锁定、结算、复盘和 AI V1 保持可读。
- 活动 1.7.0 revision 2 从其不可变 snapshot 迁移，不读取可变 proposal 目录。
- AI 初始仅为 shadow_advisory；无 AI、无网络或无凭据时确定性流程完整可用。
- V2 只替换正式草稿的决策来源，不重建 Match、锁定、结算、复盘或正式统计体系。

## 二、隔离架构

新增包：

~~~text
src/odds_journal/knowledge_engine/
├── domain/
│   ├── features.py
│   ├── knowledge.py
│   ├── retrieval.py
│   ├── forecasts.py
│   ├── hypotheses.py
│   ├── decisions.py
│   └── studies.py
├── application/
│   ├── compile_features.py
│   ├── migrate_knowledge.py
│   ├── build_snapshot.py
│   ├── retrieve_knowledge.py
│   ├── adjudicate.py
│   ├── run_study.py
│   └── run_ai_advisory.py
├── ports/
│   ├── observations.py
│   ├── facts.py
│   ├── cases.py
│   ├── official_baseline.py
│   ├── knowledge.py
│   ├── index.py
│   ├── artifacts.py
│   ├── clock.py
│   └── reasoner.py
└── adapters/
    ├── current_observations.py
    ├── current_facts.py
    ├── current_cases.py
    ├── current_official_baseline.py
    ├── ruleset_source.py
    ├── sqlite_index.py
    ├── repository_artifacts.py
    ├── deterministic_reasoner.py
    ├── ai_reasoner.py
    └── formal_draft.py
~~~

依赖规则：

- domain/ 只依赖标准库、Pydantic 和同层领域类型。
- application/ 只依赖 domain/ 与 ports/。
- ports/ 只定义 Protocol、输入输出契约和领域异常。
- 只有 adapters/ 可以导入现有 observations、facts、cases、rules、AI governance、MatchDocument 和 RepositoryTransaction。
- V2 core 禁止读取路径、调用 CLI、生成当前时间或直接写 JSONL。
- Pydantic 领域对象使用 frozen=True；集合字段使用不可变 tuple。
- 内容哈希复用仓库现有规范 JSON 哈希方法，统一时区和时间字符串格式。
- 增加 AST/import-boundary 测试，发现反向依赖即失败。

## 三、公共契约与存储

### 1. 知识资产

新增：

- KnowledgeCardV1
- KnowledgeMigrationManifestV1
- KnowledgeConsolidationManifestV1
- KnowledgeSnapshotManifestV1
- KnowledgeIndexManifestV1
- DecisionAuthorityContractV1
- ProposalSupersessionEventV1

KnowledgeCardV1 必须冻结：

- card_id、版本、层级、市场、知识类别和来源轨道。
- 适用条件、必要特征、数值边界、解释内容。
- 支持条件、反证条件和失效条件。
- 允许效果、最大调整、provenance group。
- source family、observation lineage、冲突、反向卡和覆盖关系。
- 原规则、RuleSpec、atom、文件哈希和行范围。
- 状态及卡片内容哈希。

知识层级固定为：

~~~text
foundation
general
market
competition
scenario
cross_market
~~~

知识类别固定为：

~~~text
policy_kernel
decision_policy
advisory
research_only
~~~

权威 proposal 资产保存到：

~~~text
knowledge/rule-proposals/football-analysis/2.0.0/knowledge/
~~~

### 2. 特征、检索与裁决

新增：

- FeatureSnapshotV2
- PolicyKernelBaselineV1
- MarketProbabilityForecastV1
- KnowledgeQueryPlanV1
- KnowledgeRetrievalReceiptV1
- HypothesisGraphV1
- KnowledgeEvaluationBundleV1
- KnowledgeDraftCandidateV1
- KnowledgeDraftBuildReceiptV1

FeatureSnapshotV2 冻结：

- match、as_of、kickoff、编译器版本和配置哈希。
- observation/fact/case IDs 及集合哈希。
- provider、market、line、odds format 维度的时序。
- opening/mid/late、节点精度、净变化、趋势纯度和冲突。
- 比赛类型、盘深、流动性、数据质量和缺失状态。
- 单位、舍入和 null 语义。

### 3. Study 与 Exposure

新增：

- OfficialBaselineSnapshotV1
- KnowledgeProspectiveStudyV1
- KnowledgeStudyRunV1
- KnowledgeStudyPrimaryClaimV1
- KnowledgeStudyExposureEventV1
- KnowledgeStudyOutcomeV1
- KnowledgeStudyFailureV1

研究事件保存到：

~~~text
knowledge/knowledge-studies/
├── study-events.jsonl
├── primary-claim-events.jsonl
├── exposure-events.jsonl
├── outcome-events.jsonl
├── failure-events.jsonl
└── runs/{study_id}/{match_id}/{run_id}/
~~~

Study、Primary 和 Run 不允许覆盖。Outcome 纠错必须追加带 supersedes_event_id 的新事件。

### 4. AI V2

新增：

- AIAdvisoryInputReceiptV1
- AIAnalysisCandidateV1
- AICandidateComparisonV1
- AIAdvisoryReceiptV1

AI V2 与 AI V1 使用独立模型和目录。不得迁移、重算或覆盖 AI V1 的 Study、Primary 和 Outcome。

### 5. 正式契约

2.0.0 使用：

- Manifest schema 10
- AnalysisReceipt V9
- Calibration Contract 9
- AnalysisDraftInput V4
- EvaluationBundle V4
- AnalysisOutlook V7

所有 Schema 都进入 schema registry、CLI 解析、Analytics 重建和历史兼容测试。

## 四、Ports 与 Adapters

### 数据读取端口

ObservationReaderPort：

- 按比赛、市场和 cutoff 返回合格观测。
- 返回认证状态、时间精度、冲突和来源血缘。
- 强制 received_at <= as_of < kickoff_at。
- 不暴露 cutoff 后观测和赛果。

FactReaderPort：

- 只让 authenticated 结构化事实影响决策。
- unverified 事实只用于展示。
- 禁止从球队名称、盘口或赛果反推实力、阵容或意图。

CaseContextReaderPort：

- 读取已冻结 Case Retrieval Receipt。
- 案例只能用于条件比较和解释。
- 案例不得直接创建候选或重新打开 pass。

OfficialBaselineReaderPort：

- 读取已 validate/render 的正式赛前 Outlook 和报告。
- 在任何知识或 AI 输出展示前生成 OfficialBaselineSnapshotV1。
- 基线不存在或已过期时，该场不得进入正式对照分母。

### 知识与索引端口

KnowledgeSourcePort：

- proposal 模式只允许显式指定 2.0.0。
- 正式模式只加载 Receipt 引用的已发布 Snapshot。
- Snapshot 缺失或哈希不符时 fail closed。

KnowledgeIndexPort：

- 普通 SQLite 表执行层级、市场、标签和数值范围过滤。
- FTS5 只对过滤后的小候选集执行 BM25。
- SQL 全部参数化，不接受原始 FTS 表达式。
- 同分按 card_id 排序。
- 强制补齐反证、互斥和冲突卡。

ArtifactStorePort：

- 提供内容寻址写入、追加事件、幂等键、事务和恢复。
- 校验路径不得越出受管目录，不跟随越界符号链接。
- 相同 ID、相同内容返回原产物；相同 ID、不同内容拒绝覆盖。

### Reasoner

~~~python
class KnowledgeReasoner(Protocol):
    def analyze(
        self,
        features: FeatureSnapshotV2,
        retrieval: KnowledgeRetrievalReceiptV1,
        baseline: PolicyKernelBaselineV1,
        authority: DecisionAuthorityContractV1,
    ) -> KnowledgeEvaluationBundleV1: ...
~~~

实现：

- DeterministicKnowledgeReasoner：正式必需、完全离线。
- AIKnowledgeReasoner：可选，只生成提示候选。

### 正式适配器

FormalDraftAdapter：

- 旁路阶段不注册到正式命令。
- 发布后只处理 Contract 9。
- 将 Knowledge Candidate 转换为 AnalysisDraftInput V4。
- 不直接 accept、evaluate、lock 或修改 Match。
- evaluate 阶段重新计算 Feature、Retrieval 和 Evaluation Bundle，并拒绝不一致候选。

## 五、知识检索与裁决

### 1. 强制 Policy Kernel

以下约束由代码和 Decision Contract 强制执行，不参与 BM25：

- 时间边界和赛后泄漏禁止。
- 来源认证和冲突门禁。
- 同机构、同市场、同盘口和同赔率格式限制。
- 市场隔离。
- pass 不可由知识或 AI 重新打开。
- advisory 零正式效果。
- research_only 赛前不适用。
- 总进球、比分和固定让球的独立证据要求。

检索结果拆分为：

~~~text
mandatory_policy_cards
retrieved_decision_cards
retrieved_explanation_cards
counter_and_conflict_cards
~~~

### 2. 分层检索

- foundation 卡按适用市场固定装载并缓存。
- general、market、competition、scenario 先做结构化过滤。
- cross_market 只能进入隔离审计，不进入其他市场候选生成。
- 每市场最多 12 张规范卡，整场最多 40 张。
- 反证和冲突卡不占普通 Top K 配额。
- 缓存键包含 Snapshot、Feature Snapshot、Query Policy 和 retriever version。
- 只使变化市场的缓存失效。

### 3. 裁决权限

优先级：

~~~text
force_pass
suppress_candidate
confidence_cap / degrade
bounded_rank_adjustment
support_existing_direction
explain
~~~

固定规则：

- 单张卡不能改变第一选择。
- 第一选择变化至少需要两个同市场、同选择、独立 provenance group。
- 共享 source family 或 observation lineage 只算一个来源。
- 正反卡不进行数值抵消。
- 同级冲突保留基线排序并降级；无法保留可靠核心方向时 pass。
- 第一选择改变后市场固定 degraded，置信度不超过 0.69。
- 2.0.0 知识只能维持或降低基线置信度。
- baseline pass 永远不能重新开放。
- advisory 只进入独立提示。
- research_only 只在赛后 Study 中评价。

### 4. 概率与发布指标

MarketProbabilityForecastV1 初版只用于胜平负：

- 基线概率来自合格机构最新欧赔去返还率后的跨机构中位概率。
- 三项概率必须在 [0,1]，总和误差不超过 1e-6。
- 机构不足或概率无法归一化时不生成概率 Forecast。
- 知识不允许任意修改概率数值。
- 若裁决合法改变排序，只允许按最终排序置换基线概率，保持概率集合和最大值不变。
- Brier 和 Log Loss 只比较同时存在有效概率 Forecast 的胜平负样本。

亚洲让球和总进球不计算 Brier/Log Loss。复用现有结算逻辑生成：

~~~text
full_win = 1.00
half_win = 0.75
push = 0.50
half_loss = 0.25
full_loss = 0.00
~~~

比分和固定让球在没有独立正式规则时继续 pass。

## 六、前瞻 Study 顺序

每场 prospective Study 固定执行：

~~~text
1. 完成 1.8.0 正式 validate/render
2. 冻结 OfficialBaselineSnapshot
3. 编译 FeatureSnapshot
4. 冻结 PolicyKernelBaseline
5. 检索并冻结 Knowledge Candidate
6. 可选运行 AI V2
7. 默认保持 blind
8. 如需展示，执行显式 expose 并追加 Exposure Event
9. 正式 prepare-lock/lock
10. 完赛后追加各轨 Outcome
~~~

约束：

- 每个 study_id + match_id + snapshot_sha 只能有一个 primary run。
- Primary run 必须 run_at < kickoff_at。
- Snapshot 必须在该场运行前封存。
- counterfactual_current_knowledge 只用于历史诊断。
- prospective_out_of_sample 才进入发布证据。
- knowledge/AI 暴露前后的正式锁定分别统计。
- V2 Candidate 在 exposure 前已经冻结，人工行为不能反写 Candidate。
- 没有有效 Official Baseline 的比赛可进入 V2 coverage 报告，但不能进入与 1.8.0 的共同覆盖比较。
- 完赛只追加 Outcome，不更新卡片、Snapshot、索引或配置。

## 七、CLI

新增：

~~~powershell
rules proposal supersede 1.9.0 --by 2.0.0 --reason REASON

knowledge migrate scaffold --from-ruleset 1.8.0 --include-experiment 1.7.0@revision-2 --proposal 2.0.0
knowledge migrate validate --proposal 2.0.0
knowledge migrate coverage --proposal 2.0.0

knowledge snapshot validate 2.0.0
knowledge snapshot seal 2.0.0 --approved-by lcz --confirm-snapshot
knowledge build-index --snapshot SHA256
knowledge index status --snapshot SHA256

knowledge retrieve MATCH_PATH --proposal 2.0.0
knowledge inspect MATCH_PATH --proposal 2.0.0

knowledge study register --file STUDY.yml
knowledge study run MATCH_PATH --study STUDY_ID
knowledge study expose MATCH_PATH --run RUN_ID --approved-by lcz --confirm-exposure
knowledge study evaluate MATCH_PATH --run RUN_ID
knowledge study report --study STUDY_ID

ai analyze MATCH_PATH --mode shadow-advisory --study STUDY_ID
ai advisory show MATCH_PATH --run RUN_ID
ai compare MATCH_PATH --run RUN_ID

knowledge capability status
knowledge proposal-validate 2.0.0
~~~

持续知识接入复用现有 Rule Intake：

~~~text
rules intake ingest/inspect/disposition
-> knowledge intake import --intake INTAKE_ID --proposal VERSION
-> knowledge consolidate --proposal VERSION --file MANIFEST.yml
-> knowledge snapshot validate/seal
-> 新 Study
-> 新 ruleset proposal/release
~~~

任何已发布 Snapshot 变化都必须创建新的 ruleset proposal，不允许原地修改。

## 八、实施阶段

### 阶段 0：冻结基线

- 冻结 1.8.0、1.9.0、活动 1.7.0 revision 2 的哈希和黄金产物。
- 从活动 snapshot 记录精确 1000 个 RuleSpec 的 source inventory。
- 添加 1.9.0 supersession 事件模型和 validator。
- 更新目标实施方案文档，不覆盖 .trae/documents/。
- 提交：冻结知识引擎迁移基线。

### 阶段 1：建立隔离模块与 Ports

- 创建 package、领域模型、异常和 Protocol。
- 实现 Clock、ArtifactStore 测试替身。
- 添加 import-boundary 和 canonical hash 测试。
- 提交：建立知识引擎隔离边界。

### 阶段 2：实现只读 Adapters

- 实现 observation、fact、case 和 official baseline adapters。
- 增加 adapter contract、cutoff、认证和冲突测试。
- 此阶段禁止写正式数据。
- 提交：接入知识引擎只读适配器。

### 阶段 3：Feature 与基线编译

- 提取 Contract 8 可复用特征为纯函数。
- 实现 FeatureSnapshot、PolicyKernelBaseline 和胜平负概率 Forecast。
- 建立 Contract 8 黄金对照和显式差异清单。
- 提交：实现知识引擎特征与基线。

### 阶段 4：知识迁移和合并

- 从已发布 1.8.0 和活动实验不可变 snapshot 读取来源。
- 每个来源必须唯一处置为 migrated、consolidated、advisory、research、duplicate、invalid 或 deferred。
- 自动相似度只生成建议；合并由显式 Manifest 决定。
- 100% source disposition coverage 后才能继续。
- 提交：迁移并整合分析知识。

### 阶段 5：Snapshot 和 SQLite 检索

- 实现 Snapshot、关系图、逻辑索引 Manifest、FTS5 和缓存。
- SQLite file hash 只作为本地认证，不进入跨环境 Snapshot 哈希。
- 实现临时库、integrity check 和原子安装。
- 提交：实现分层知识检索。

### 阶段 6：确定性裁决

- 实现 Query Plan、Retrieval Receipt、Hypothesis Graph 和 Evaluation Bundle。
- 实现独立来源、反证、冲突、权限和市场隔离。
- 生成内容寻址 Candidate，不写正式 Match。
- 提交：实现确定性知识裁决。

### 阶段 7：Proposal Study

- 实现 Study、Primary、Exposure、Outcome 和 Failure 台账。
- 冻结 Official Baseline、Policy Baseline 和 Candidate。
- 验证 sidecar 前后正式文件哈希不变。
- 提交：实现知识引擎前瞻研究。

### 阶段 8：AI V2

- 接入现有 Provider、预算、出站和 Prompt 哈希治理。
- AI 输入仅包含白名单事实、知识、案例和证据 ID。
- 对不可信文本转义并隔离 Prompt 指令。
- 实现 unavailable/failed/not_run 封存。
- 提交：实现知识引擎AI旁路提示。

### 阶段 9：Analytics 与能力状态

- 增加迁移覆盖、检索性能、知识适用性、市场裁决、概率评分和 exposure 分层。
- Analytics 指纹覆盖权威 Manifest、Study、Outcome 和 AI Receipt，不覆盖派生 SQLite。
- capability 状态固定为 implemented_disabled、shadow_ready、study_active、release_eligible 和 formal_active。
- 提交：完善知识引擎分析验收。

### 阶段 10：Contract 9 与工作流注册

新增 DraftWorkflowRegistry，覆盖：

- build
- accept
- evaluate
- validate
- render
- Analytics parse

路由：

~~~text
Contract 7 -> legacy
Contract 8 -> current formal draft V3
Contract 9 -> knowledge V4
~~~

agent start 必须显示 Snapshot、逻辑索引、本地索引、AI 和 Study 状态。Contract 9 索引未就绪时 fail closed。

提交：接入知识引擎正式草稿入口。

### 阶段 11：前瞻验证与发布

- 封存首个 primary Snapshot。
- 注册受影响市场、cohort、停止条件和排除条件。
- 完成至少 60 场 prospective 样本。
- 生成正式发布证据。
- lcz 记录 1.7.0 处置并单独批准 2.0.0。
- 执行 rules release 2.0.0。

## 九、失败与兼容行为

- 索引缺失、损坏或 Snapshot 不一致：明确失败并提示重建命令。
- Candidate 输入变化：拒绝 accept/evaluate，要求重新构建。
- AI 不可用：记录状态，确定性流程继续。
- Study 写入失败：恢复当前事务，不影响正式文件。
- Snapshot 变化：旧 Study 不迁移，新建 Study 并重新计数。
- 发布事务失败：恢复 active pointer 和生成文件。
- 发布成功后发现问题：停止新建 Contract 9 比赛，通过新 proposal 修复，不修改 2.0.0。
- 已开始比赛继续使用其 Receipt 冻结的旧 Contract 和 Snapshot。
- 历史 Contract 7/8、AI V1 和实验 Receipt 不重算。

1.7.0 发布前处置只允许：

- continue_parallel
- deactivate_after_2_0_release
- archive_without_activation

处置必须绑定活动 revision 2 snapshot 哈希、操作者和时间。

## 十、测试与发布门槛

必须覆盖：

- import boundary、不可变模型和规范哈希。
- cutoff、时区、赛后数据、未认证来源和冲突。
- Contract 8/V2 Feature 黄金对照。
- 活动 snapshot 中全部 1000 个 RuleSpec 的唯一处置。
- 合并血缘、覆盖循环、冲突边和 source inventory。
- Policy Kernel 不被 Top K 淘汰。
- FTS 参数化、路径越界、缓存失效和索引恢复。
- 单卡不翻转、双独立来源、同源去重和冲突不净额。
- 总进球、比分、固定让球和跨市场隔离。
- 概率归一化、置换、Brier 和 Log Loss。
- Primary 唯一性、Exposure、Outcome supersession 和失败封存。
- AI 注入、超时、预算和 Schema 错误。
- Study 运行前后正式 Match 和全部正式产物哈希不变。
- Contract 7/8/9 全流程和 Analytics 历史重建。

发布门槛：

- 至少 60 场独立 prospective 比赛。
- 每个发生行为变化的市场至少 20 个 evaluated 样本。
- 时间泄漏、正式轨串写、哈希错误和赛后补建为 0。
- 胜平负 Knowledge Candidate 相对 V2 Policy Baseline：
  - Brier 增量不高于 +0.02。
  - Log Loss 增量不高于 +0.05。
- 与正式 1.8.0 共同覆盖样本相比：
  - 胜平负 top-1 准确率下降不超过 5 个百分点。
  - 亚洲让球和总进球平均 settlement utility 下降不超过 0.05。
- 所有首选变化和 pass/degraded 变化必须人工审计。
- 其他适用性判断采用分层抽样，合计至少 100 项；正确率至少 95%。
- Coverage、pass 减少、degraded 比例和 AI exposure 单独报告。
- 未达标市场关闭知识排序效果，允许其他达标市场继续候选验证。
- 1.7.0 处置已记录。
- lcz 明确批准正式发布。

## 十一、校验、提交与同步

每个阶段完成后：

1. 运行定向测试和全量 pytest。
2. 运行 Schema、Analytics 和仓库校验。
3. 审查时间泄漏、轨道隔离、内容寻址、事务回滚和历史兼容。
4. 修复全部确认问题。
5. 使用中文 commit 提交。
6. 执行 agent changes。
7. 如报告 workflow_breaking，在干净工作区立即执行 agent sync。

最终执行：

~~~powershell
.\scripts\odds-journal.ps1 rules proposal-validate 2.0.0
.\scripts\odds-journal.ps1 knowledge proposal-validate 2.0.0
.\scripts\odds-journal.ps1 schemas check
.\scripts\odds-journal.ps1 analytics build
.\scripts\odds-journal.ps1 analytics validate
.\scripts\odds-journal.ps1 evidence validate
.\scripts\odds-journal.ps1 case validate
.\scripts\odds-journal.ps1 validate --all
.\.venv\Scripts\python.exe -m pytest -q
.\scripts\odds-journal.ps1 agent changes
~~~

正式发布仍需 lcz 单独执行：

~~~powershell
.\scripts\odds-journal.ps1 rules release 2.0.0 --approved-by lcz --confirm-release
~~~
