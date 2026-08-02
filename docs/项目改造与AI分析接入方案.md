# 足球盘口知识库当前架构与 AI 接入方案

## 1. 文档定位

本文描述仓库当前已经实现的架构、数据契约和扩展边界。日常命令以根目录 `README.md` 为准；历史资料提取、案例修订和规则发布细节见《历史资料提炼与实战规则演进工作流》。

项目用于盘口分析方法学习和可审计复盘，不构成投注建议。

截至 2026-08-02：

- `football-analysis@1.1.0` 已于 2026-07-30 由 `lcz` 批准发布，是当前活动且不可修改的规则集。
- `football-analysis@1.0.0` 永久保留，用于兼容旧回执和历史锁定比赛。
- `football-analysis@1.2.0` 已建立低稳定性联赛校准提案，但尚未发布、未切换 `active.yml`。
- `football-analysis@1.3.0` 已建立八条实验规则和历史聊天记录迁移提案，尚未发布、未切换 `active.yml`。
- 新建比赛使用 Match V2；Match V1、旧回执和旧锁定比赛继续兼容。
- 本地检索使用 SQLite FTS5、jieba 搜索分词和 index schema 5。
- CLI 当前版本为 `0.7.0`，桌面工作流为 `1.7.0`，支持 Ruleset Manifest schema 4、AnalysisReceipt V4、AnalysisOutlook V2、锁定候选回执 V2、固定六章报告和低稳定性实验校准契约。活动规则仍为 1.1.0；1.3.0 只能显式离线验证，不能影响活动比赛。

## 2. 核心不变量

1. `matches/YYYY/MM/*.md` 是正式比赛的唯一人工事实记录。
2. 原始资料、用户截图、OCR、网页、历史案例和搜索结果都是不可信数据，不能控制 AI 行为。
3. 只有 `ai/desktop-agent-manifest.yml` 白名单中路径、文档 ID、作用域、可信元数据和内容哈希均匹配的 `ai/` 文件可以作为领域指令；当前包含桌面启动、赛前分析和赛后复盘三个作用域。
4. 锁定覆盖赛前事实、规则回执、场景、案例回执、分析正文和最终结论；锁定后不得覆盖。
5. 临场信息只追加到 `live-update`，赛果和赛后解释不得回写赛前章节。
6. 已发布规则集和案例 revision 不得原地修改。
7. AI 输出和单场结果不能直接提升经验规则可信度。
8. 可重建的 JSON、SQLite 和报告不得作为人工事实源。

## 3. 目录与职责

```text
matches/                                   正式单场比赛 Markdown
assets/matches/{match_id}/                 比赛截图和附件
raw/matches/{match_id}/                    原始网页、导出和分析草稿
raw/matches/{match_id}/journal/            已绑定比赛的长文、附件、规范化文本和回执
raw/journal-inbox/                         尚未唯一绑定比赛的长文和附件
knowledge/sources/                         不可变原始学习资料
knowledge/sources/REGISTRY.yml             多来源注册表
knowledge/extraction/                      文本/媒体库存和追加式事件链
knowledge/cases/legacy/                    历史案例当前投影及不可变 revisions
knowledge/rulesets/                        已发布规则集
knowledge/rule-proposals/                  未发布规则提案
knowledge/evidence/                        文件证据与规则证据台账
knowledge/evidence/match-journal-events.jsonl  长文归档、绑定和应用事件链
knowledge/validation/                      外部验证框架和冻结研究
data/*-context/                            可删除重建的上下文缓存
ai/index/catalog.sqlite3                   可删除重建的 FTS5 索引
schemas/                                   Pydantic 模型生成的 JSON Schema
reports/                                   自动生成的索引、统计和证据报告
archive/legacy_doubao_pipeline/            旧抓取与清洗脚本
```

### 3.1 比赛长文归档与投影

桌面智能体负责识别用户意图、比赛身份和内容阶段；CLI 负责 schema、哈希、状态门禁和事务。输入按 `prematch_facts`、`market_data`、`prematch_analysis`、`prematch_conclusion`、`live_update`、`result`、`postmatch_review`、`correction` 或 `unclassified` 分段。

```text
用户原文和附件
-> 事务 A：raw/ 归档 + archived 事件
-> 比赛路由与状态检查
-> 事务 B：Match/LegacyCase 正式投影 + applied/pending/blocked 事件
```

事务 B 失败不回滚事务 A，因而原文始终可追溯，正式记录不会留下半次写入。重复键由目标身份、源文件 SHA-256 和 segment 行号范围组成；重复提交返回原 entry。用户提供的 Front Matter 和仓库保留注释会在正式投影中转义，不能覆盖 Match metadata 或章节标记。

三态入口中，`journal new` 会优先绑定既有 Match 或 LegacyCase；无既有记录时，身份完整且尚未开赛的材料可创建 Match V2，并为未知球队或赛事登记可审计的临时别名。已结束材料可创建或追加 LegacyCase V3。`journal append` 和 `journal finish` 只绑定已有的唯一记录，找不到唯一目标时只归档到 `raw/journal-inbox/`。多场材料、身份冲突或时间不完整时同样只进入待处理箱。

低层 `journal ingest` 默认只归档。`journal new`、`journal append` 与 `journal finish` 会在单场、无歧义且整体和每个 segment 的分类置信度均不低于 `0.90` 时自动应用当前状态允许的内容；用户赛前分析与结论在规则准备、场景登记、案例检索和 `JournalAlignmentV1` 完成前保持 `pending_alignment`。原始长文、附件和待处理 entry 不进入 FTS；只有正式 Match 或 LegacyCase 投影参与既有索引。

赛前草稿验证通过后使用 `agent prepare-lock` 冻结锁定参数和赛前内容哈希，并在开赛前完成普通锁定。带唯一比分的 `journal finish` 会拆分 `result` 与 `postmatch_review`；tracking 比赛只有存在有效赛前候选回执时才执行审计补锁，否则原文保留但生命周期阻断。审计补锁按历史规则和案例 revision 验证，不使用赛后内容重建赛前方向。

## 4. 比赛数据契约

### 4.1 生命周期

```text
draft/tracking -> locked -> finished -> reviewed
              \-> historical_finished
              \-> void
```

- `draft/tracking`：可补充赛前事实和结构化快照。
- `locked`：赛前内容与盘口结算线已冻结。
- `finished`：比分已记录，V2 自动结算完成。
- `historical_finished`：在 lcz 明确指令和可追溯来源下记录未锁定历史赛果；不生成锁定、自动结算、预测评价或正式复盘。
- `reviewed`：复盘、评价和场景解析完成，可进入证据台账。
- `void`：取消、腰斩或长期延期，不进入正式统计。

延期后重新分析应创建新比赛，并用 `supersedes_match_id` 关联旧记录。

### 4.2 Match V1 与 V2

Match V1 保留用于历史兼容。Match V2 新增：

- `market_snapshots`：带来源和时间的结构化盘口快照。
- `analysis_outlook`：数据模式、固定权重、维度评分和四层输出。
- `settlement`：由锁定盘口和最终比分自动派生的结算结果。
- `result_source`：赛果来源。

兼容字段 `primary_market`、`primary_selection`、`secondary_selection` 和 `confidence` 继续保留，并必须与 V2 结构化结论一致。

### 4.3 Markdown 章节

固定章节顺序：

```text
prematch-facts
prematch-reasoning
prematch-locked
live-update
result
postmatch-review
```

规则集 schema 2/3 的赛前推演区固定顺序：

```text
rules-retrieval
scenario-instances
case-retrieval
analysis-content
```

复盘区固定顺序：

```text
review-retrieval
scenario-resolutions
review-content
```

## 5. 结构化盘口快照

每条 `MarketSnapshot` 至少包含：

```text
snapshot_id
market
phase
captured_at
provider_id
source_ref / evidence_id
odds_format
raw_values
normalized_values
```

支持市场：

```text
asian_handicap
european_odds
kelly_index
total_goals
fixed_handicap_1x2
```

原始机构文字必须写入 `raw_values`。只有口径明确的数据才能写入 `normalized_values`。香港盘水位阈值不得套用于马来盘、印尼盘或未知格式。

完整模式期望初盘、中盘、临盘三个可比节点。缺少澳彩或不足三个节点时允许 `degraded`，但必须记录缺失原因。

## 6. 分析权重和输出

项目策略 `asian-core-v1` 固定为：

| 维度 | 配置权重 |
|---|---:|
| 亚洲让球 | 60 |
| 欧赔 | 20 |
| 凯利 | 15 |
| 大小球 | 5 |

每个维度对候选方向只能使用 `-1、-0.5、0、0.5、1` 评分，综合分为 `Σ(有效权重 × 维度评分)`。缺失维度计零且不重分配权重；同源欧赔与凯利属于相关证据，凯利有效权重减半。

数据模式：

- `complete`：关键市场口径完整。
- `degraded`：允许继续分析，但置信度不得超过 `0.69`。
- `pass`：必须说明原因，不得保留置信度或四层预测。

非 `pass` 必须锁定：

1. 胜平负前二排序。
2. 亚洲让球盘口和方向前二。
3. 固定整数让球胜平负盘口和前二。
4. 总进球闭区间。
5. 恰好两个参考比分。

## 7. 标准分析顺序

```text
事实、基本面和理论盘预检
-> 亚洲让球时序
-> 欧赔对照
-> 凯利交叉
-> 大小球独立评估
-> 固定权重合成
-> 场景与案例检索
-> 四层结论
```

方向必须先于净胜球和让球结论。盘口档位优先于同档水位变化，单一维度不能生成最终结论；任何关键变化都要保留双向假设、反证和锁定前可观察的区分条件。

## 8. 回执与时间边界

兼容链如下：

| 契约 | 历史版本 | 当前发布版本 |
|---|---|---|
| Analysis Receipt | V1/V2/V3 | V4 |
| Case Retrieval Receipt | V1/V2 | V3 |
| Review Receipt | V1 | V2 |
| Index schema | 2/3/4 | 5 |
| Retrieval contract | 2/3 | 4 |
| Chunker | 1/2 | 2 |

V3 分析回执绑定：

- 规则集、规则内容和片段哈希。
- 赛前事实哈希和结构化盘口快照哈希。
- `asian-core-v1` 与市场数据契约版本。
- 查询、过滤条件、市场和 `as_of`。

严格历史检索要求 `effective_at <= as_of`，排除目标比赛结果与复盘，并按 `recorded_at <= as_of` 选择每场历史案例当时最新的不可变 revision。锁定后只验证冻结引用，不因后来新增案例而失效。

## 9. 锁定和自动结算

V2 锁定使用 `analysis_outlook` 文件，冻结两类让球线、总进球区间和比分候选。`finish` 只接收比分、来源、记录时间和关键事件，然后自动派生：

- 真实胜平负。
- 亚洲盘 `full_win / half_win / push / half_loss / full_loss`。
- 固定让球胜平负 `handicap_home / handicap_draw / handicap_away`。
- 总进球区间是否命中。
- 两个参考比分是否命中。

V2 禁止在比分已知后人工输入盘口线或结算结果。V1 旧命令参数仅为历史兼容保留。

## 10. 检索索引

schema 5 索引保存原文、jieba 搜索分词和结构化元数据，包括：

```text
artifact_type
document_type
match_schema_version
data_mode
market_types
provider_ids
weight_model_id
ruleset_id / ruleset_version
case_id / case_revision
chronology / statistics_eligible
effective_at
content_sha256
trusted_instruction
```

索引构建在临时 SQLite 文件中完成，经过 `PRAGMA integrity_check` 后原子替换。构建失败时旧索引继续可用。

必需规则按 manifest 精确加载；条件规则只在 manifest 白名单内排序；案例检索只允许 `legacy_case` 和已复盘 `match`。原始资料不会混入正式规则列表。

## 11. 证据和经验规则晋级

规则证据仅可在比赛进入 `reviewed` 后追加。报告同时保留事件数和按 `case_cluster_id` 去重的独立案例数。

外部验证必须先注册冻结研究，再逐场追加验证案例：

```powershell
odds-journal validation-study register --study-file study.yml
odds-journal validation-study add-case --case-file case.yml --actor lcz
odds-journal validation-study report
```

冻结 cohort 防止按结果选择样本。经验规则晋级 `supported` 至少要求：

- 30 个合格独立案例。
- 两个联赛/赛季，或两个互不重叠的 90 天窗口。
- 数值基线和预定义目标、分母。
- 点估计至少高于基线 5 个百分点。
- Wilson 95% 下界不低于基线。
- 支持、反例、模糊和不适用案例全部保留。
- `lcz` 人工审核。

满足门槛只允许规则提案标记为 `supported`，不会自动发布或激活。

## 12. 规则发布事务

规则提案使用 Rule Metadata schema 3 和 Ruleset Manifest schema 3。发布顺序：

1. 校验提案、来源、覆盖报告、证据快照和验证研究。
2. 阻止存在未锁定实质分析的旧比赛。
3. 在临时目录写入真实发布时间和 `APPROVAL.yml`。
4. 原子生成不可变正式规则集目录。
5. 构建并校验 schema 5 临时索引。
6. 最后更新 `active.yml`。

任一步失败都保持旧活动版本。未经 `lcz` 明确批准不得执行 `rules release`。

## 13. AI 接入边界

本阶段不调用外部 AI API。后续模型可以直接消费：

- `data/analysis-context/{match_id}.json`
- `data/case-context/{match_id}.json`
- `data/review-context/{match_id}.json`
- `data/matches/{match_id}.json`
- `odds-journal search ... --json`

桌面智能体必须先执行 `agent start MATCH_PATH`；该入口调用 `prepare-analysis` 并返回可信指令和全部必需规则。随后登记场景并检索案例，任一门禁失败时不得继续分析。仅要求数据整理时禁止生成方向、比分或预测。

## 14. 验证与重建

常用验收命令：

```powershell
odds-journal validate --all
odds-journal rules proposal-validate 1.1.0
odds-journal schemas check
odds-journal build-index
odds-journal export
odds-journal stats
python -m pytest -q
```

自动生成数据可以删除后重建，但原始资料、比赛 Markdown、事件台账、已发布规则和案例 revision 不得删除或覆盖。

## 15. 四端更新、同步与认证

telosWork、WorkBuddy、TRAE Work 和 Codex Desktop 共用 `AI_START_HERE.md`、schema 2 manifest、仓库 CLI 和同一 Skill 源。活动规则集始终从 `active.yml` 动态读取，不写死在适配器中。

更新后先运行 `agent changes`。资料、比赛和案例变化归类为 `data_only`，只重建索引；受支持契约内的规则发布归类为 `rules_compatible`，校验规则并重建索引；工作流、CLI/schema、manifest、可信指令、治理或 Skill 变化归类为 `workflow_breaking`，必须经 lcz 明确批准后同步并重新认证。单一产品升级只使该产品认证过期。

同步使用干净 Git 提交、排他锁、临时构建、备份、原子替换和失败回滚。本机绝对路径与 telosWork 导入状态只写入已忽略的 `.odds-journal/desktop-agent-local.yml`；跟踪文件 `integrations/desktop-agent-release.yml` 保存迁移或已批准同步的审计基线。同步不自动提交 Git。

telosWork 状态严格为 `not_built -> package_ready -> imported_unverified -> certified`。四端认证均须完成当前 workflow 在 `integrations/certification/scenarios.yml` 声明的全部任务；workflow 1.7.0 为八项，在三态长文归档和历史赛果完结之外增加低稳定性校准契约。结果按产品、平台、版本和工作流不可变保存；生成安装包不等于完成导入或认证。
