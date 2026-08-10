# 足球盘口学习与比赛分析日志

本项目用于整理足球盘口学习资料，并以“一场比赛一个 Markdown”的方式记录赛前事实、推演、临场更新、赛果和复盘。项目只用于赛事数据学习，不构成投注建议。

## 环境安装

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\odds-journal.exe --help
```

下文的 `odds-journal` 命令默认已激活项目虚拟环境；不希望激活时可统一改用 `.\scripts\odds-journal.ps1`。

四端桌面 AI 智能体统一从 [AI_START_HERE.md](AI_START_HERE.md) 开始。推荐使用仓库包装脚本，避免依赖全局 PATH：

```powershell
.\scripts\bootstrap-agent.ps1
.\scripts\odds-journal.ps1 agent doctor
```

项目更新后先查看变更分类：

```powershell
.\scripts\odds-journal.ps1 agent changes
```

资料和案例更新只需重建索引；兼容规则更新不重装 Skill。工作流、CLI/schema、可信指令、治理或 Skill 变化才需要同步。`agent changes` 报告 `workflow_breaking` 或缺少基线时，在干净 Git 工作树直接执行同步：

```powershell
# WorkBuddy 无法唯一定位时先显式配置，不猜测目录
.\scripts\odds-journal.ps1 agent configure --product workbuddy --skill-root "C:\Users\lcz\.workbuddy\skills"
.\scripts\odds-journal.ps1 agent sync
.\scripts\odds-journal.ps1 agent certify status
```

Trae CN 不再假定读取根目录 `AGENTS.md`。先在独立测试项目确认其实际项目指令加载与刷新机制，再保存安装路径和仓库外指令目标，并记录真实客户端载入验证：

```powershell
.\scripts\odds-journal.ps1 agent configure --product trae-cn `
  --installation-path "D:\ProgramFiles\Trae CN" `
  --instruction-target "C:\TraeCnTestProject\PROJECT_INSTRUCTIONS.md"
.\scripts\odds-journal.ps1 agent certify record-load-validation `
  --file integrations\certification\trae-cn-load-validation-template.yml
```

载入验证记录必须绑定 Trae CN 版本、配置目标、刷新步骤和证据哈希，不得包含 token、JWT、会话或截图原文。验证未完成时 `agent sync` 不会同步 Trae CN，也不会将它写为已成功。telosWork 同步后仅生成 `dist/football-odds-journal.skill`；通过产品界面导入后，先登记为待认证状态，再执行当前 workflow `1.13.0` 声明的十二项认证：

```powershell
.\scripts\odds-journal.ps1 agent configure --product teloswork `
  --confirm-import --imported-version 3.8.4
.\scripts\odds-journal.ps1 agent certify status
```

同步器会将受管 Skill 同步到已配置的 Codex/WorkBuddy 目标目录，将已验证的 Trae CN 指令源原子写入其配置目标，并生成 telosWork 导入包。它自动运行并记录 Codex Desktop 的十二项认证，随后只提交同步基线、Codex 认证结果和自动化报告；Trae CN、WorkBuddy、telosWork 不会被自动标记通过。它不驱动 telosWork 的产品界面导入。生成包、完成产品导入、完成 Trae CN 指令验证和通过认证是不同状态。

## 目录说明

- `knowledge/`：经过分级的概念、方法、经验规则和原始学习资料。
- `knowledge/rulesets/`：不可原地覆盖的版本化分析规则集。
- `knowledge/rule-proposals/`：尚未发布、可继续人工审查的规则提案。
- `knowledge/rule-experiments/`：由已校验提案生成的不可变实验快照和当前实验指针；不属于正式规则集。
- `knowledge/extraction/`：文本/媒体库存及声明、处置、冲突、案例事件链。
- `knowledge/cases/legacy/`：由案例事件台账重建的历史案例投影。
- `knowledge/evidence/`：用户文件证据注册表和 reviewed 比赛追加的规则证据台账。
- `knowledge/validation/`：外部验证框架、冻结研究和逐场验证案例。
- `matches/`：人工维护的单场比赛主记录。
- `assets/matches/`：比赛截图等附件。
- `raw/matches/`：原始网页、数据导出等证据。
- `raw/journal-inbox/`：尚未唯一绑定比赛的长文和附件归档。
- `data/matches/`：从 Markdown 自动生成的 JSON，不人工修改。
- `data/analysis-context/`：分析前规则上下文缓存，可删除重建。
- `data/case-context/`、`data/review-context/`：案例检索和复盘上下文缓存。
- `ai/index/`：本地 SQLite 中文检索索引，可删除重建。
- `ai/analytics/`：从权威 Match 与离线评估产物重建的 SQLite 分析投影，可删除重建，不是日常分析前置条件。
- `templates/xiaohongshu-prematch-analysis.md`：正式赛前分析完成后的外部发布稿写作模板，不属于 Match、规则或锁定回执。
- `reports/`：比赛索引和统计报告。
- `archive/`：旧版豆包抓取与文档生成脚本。

## 比赛长文保存

用户提供赛前分析、盘口叙述、临场更新、赛果、纠错或复盘时，先生成 `JournalIngestRequestV1`，再归档原文。低层 `journal ingest` 默认只归档；三态入口会在单场、无歧义且分类置信度达到 0.90 时自动应用当前状态允许的内容：

现在优先使用三态入口：首次记录使用 `journal new`，已有赛前/临场材料使用 `journal append`，已有比赛的赛果或赛后材料使用 `journal finish`。无法进入正式章节的同场材料仍会追加到比赛文档的“用户材料归档”区。`journal review` 仅为兼容旧调用保留；正式赛后评价继续使用顶层 `review`。

完整盘口表和完赛全量数据使用 `MatchDataBundleV1`：

```powershell
odds-journal journal finish --bundle knowledge/match-data-bundles/MATCH.yml --match matches/YYYY/MM/MATCH.md --actor lcz
odds-journal market observations show-series --match matches/YYYY/MM/MATCH.md
odds-journal market observations conflicts --all
```

该入口分别提交原文归档、规范化观测和赛果生命周期。观测台账保存实际报价时间、来源形成时间与仓库接收时间；同刻同值只追加来源，同刻异值形成冲突，不同时间同值仍保留。赛后补录可以形成完整趋势，但默认不具备历史正式预测资格；实验回执会冻结观测集合与 `MarketFeatureSnapshotV2`，正式 `1.8.0` 以 Contract 7 独立评估总进球与比分的 `pass` 状态。

已进入 `historical_finished` 的 Match 正文不会回填赛前表格或结论；完整盘口仍保留在 Bundle 与观测台账中，可用 `market observations show-series --match MATCH_PATH` 查看。这一显示边界防止赛后材料被误写为赛前分析链。

正式赛前分析通过 `agent validate-draft` 后，应在开赛前执行 `agent prepare-lock` 并使用生成的候选回执锁定。带唯一比分的 `journal finish` 会自动拆分赛果和赛后材料：已锁定比赛自动录入赛果；tracking 比赛仅在存在有效赛前候选回执时执行审计补锁。缺少候选回执时只归档，不根据赛果补造赛前方向。

对赛前未锁定的历史 Match，只有 lcz 明确要求完结且提供可追溯赛果来源时才能使用 `finish-historical`。它写入 `historical_finished`，不会生成锁定、自动结算、预测评价或正式复盘：

```powershell
odds-journal finish-historical matches/YYYY/MM/比赛.md `
  --score 1-0 --source journal:ENTRY_ID
```

```powershell
# 首次记录 / 已有赛前或临场材料 / 已有赛果或复盘材料
odds-journal journal new `
  --source-file .odds-journal/inbox/REQUEST/source.md `
  --request-file .odds-journal/inbox/REQUEST/request.yml --json
odds-journal journal append `
  --source-file .odds-journal/inbox/REQUEST/source.md `
  --request-file .odds-journal/inbox/REQUEST/request.yml --json
odds-journal journal finish `
  --source-file .odds-journal/inbox/REQUEST/source.md `
  --request-file .odds-journal/inbox/REQUEST/request.yml `
  --attachment evidence.png --json
odds-journal journal validate --all
```

原文与附件永久保存在 `raw/`，正式 Match 或 LegacyCase 只接收符合当前状态门禁的结构化 segment。用户赛前分析在规则准备、场景登记、案例检索和 alignment 完成前保持 `pending_alignment`；仅保存请求不会生成新预测。

待处理材料先查看状态，再确认比赛绑定并应用允许的 segment：

```powershell
odds-journal journal status --entry-id ENTRY_ID --json
odds-journal journal resolve ENTRY_ID --match matches/YYYY/MM/比赛.md
odds-journal journal apply matches/YYYY/MM/比赛.md ENTRY_ID `
  --segment SEGMENT_ID --alignment-file alignment.yml --json
```

请求、segment、附件、entry 和 alignment 的字段以 `schemas/journal-*.schema.json` 为准。`canonical_chat_text` 保存桌面智能体接收到的 Unicode 文本经 UTF-8/LF 规范化后的字节，不宣称保存聊天平台网络层原始字节；`uploaded_file` 保存上传文本原字节和 SHA-256。

## 盘口截图提取、对比与归档

盘口截图先整理为 `MarketArchiveDraftV1`，预览只做校验和固定格式渲染，不写入比赛；只有用户明确要求“归档”后才执行保存：

```powershell
odds-journal journal market-archive preview --file DRAFT.yml
odds-journal journal market-archive archive --file DRAFT.yml --attachment SCREENSHOT.png --json
```

澳门机构名为红色选中状态且页面标题为“详细变化”时，右侧全部时间行作为 `macau_timeline` 归档；左侧其他机构名不能横向对应为右侧详细行。归档事务同步保存原始截图、预览、请求、回执和结构化快照，`macau_timeline` 是澳门让球详细走势的权威记录。该工作流只提取和归档数据，不生成预测、方向或比分。

已有比赛收到新截图时使用只读比较。当前任务中存在上一份已经视觉确认的草稿时显式传入；否则命令按比赛身份、主客队和开赛时间精确查找最近一个完整归档批次，不跨批次拼接基线：

```powershell
odds-journal journal market-archive compare `
  --file CURRENT.yml `
  --baseline-file PREVIOUS.yml `
  --json
```

省略 `--baseline-file` 表示允许回退到归档基线；两层基线都不存在时输出“首次采集，无历史基线”。输出固定保留完整最新数据，再依次展示澳门新增节点、让球、欧赔、大小球、凯利变化和不可比说明。同机构、同市场、同盘口档位才计算水位差；盘口换档只展示盘口变化，本次缺失机构只标记“本次未显示”。比较命令不会创建 Match、Journal、观测事件或归档记录。

赛前正文已经包含风险提示时，可人工整理 `PrematchRiskWatchlistDraftV1`，再冻结为内容寻址的不可变清单：

```powershell
odds-journal agent prepare-watchlist matches/YYYY/MM/比赛.md `
  --file watchlist.yml --json
```

每条数值条件必须明确绑定市场、机构、阶段、字段、比较符和阈值；首发、天气等事实使用 `structured_fact`，早进球、球员状态等赔率截图无法证明的条件使用 `manual_only`。清单原文必须真实存在于赛前推演，开赛后只能从哈希仍有效的赛前锁定候选补建。比较结果仅机械显示“已触发、接近触发、未触发、当前无法判断”，不会改变正式排序、置信度、锁定、结算或实验轨。字段契约见 `schemas/prematch-risk-watchlist.schema.json` 和 `schemas/market-archive-comparison.schema.json`。

## 新比赛工作流

### 未发布规则双轨实验

正式活动规则继续由 `knowledge/rulesets/football-analysis/active.yml` 决定。当前正式轨为 `football-analysis@1.8.0`，活动实验轨为 `football-analysis@1.7.0 revision 2`；实验指针和冻结哈希以 `knowledge/rule-experiments/football-analysis/active.yml` 为准。正式轨使用 Manifest 8、AnalysisReceipt V7、AnalysisOutlook V5 和 Contract 7；实验分析回执支持 V1-V4，Contract 6 的 V4 会额外冻结 RuleBuildManifest 哈希、提示规则和研究项。经 lcz 明确批准后，可将通过校验的未发布提案激活为新的内容寻址实验快照：

```powershell
odds-journal rules experiment activate 1.7.0 --approved-by lcz --confirm-experiment
odds-journal rules experiment status
odds-journal rules experiment report 1.7.0
```

后续 Intake 修改、阈值或处置变化都必须形成新的 `1.7.0` proposal revision；它只能由 lcz 以同一门禁激活：

```powershell
odds-journal rules experiment activate 1.7.0 --approved-by lcz --confirm-experiment
```

此操作不发布规则、不创建正式 `APPROVAL.yml`、不修改正式活动版本。提案修改后再次激活会创建新 revision；旧快照和已开始比赛冻结的 revision 保持不变。新比赛的 `agent start` 会同时冻结正式回执和实验回执；正式 `evaluate-draft` 完成后，使用 `agent evaluate-experiment --dispositions-file EXPERIMENT_DISPOSITIONS.yml` 生成独立实验预测。若快照声明提示规则，可附加 `--advisories-file ADVISORY_DISPOSITIONS.yml` 生成独立警示报告；提示不生成候选池、排序、比分或置信度。`prepare-lock` 只锁定正式轨，同时冻结赛前实验预测和提示状态；完赛后分别生成独立实验效果评价。实验结果只进入实验 analytics 投影和人工报告，不能参与正式锁定、结算、正式复盘或命中率。

需要停用实验时必须由 lcz 给出明确原因：

```powershell
odds-journal rules experiment deactivate --approved-by lcz --reason "停止当前实验"
```

先确保球队和联赛已登记：

```powershell
odds-journal aliases add-team --id fc-seoul --name "FC首尔" --alias "FC Seoul"
odds-journal aliases add-competition --code KOR-K1 --name "韩K联" --alias "K League 1"
```

创建比赛：

```powershell
odds-journal new `
  --kickoff "2026-07-30T18:30:00+08:00" `
  --competition-code KOR-K1 --competition "韩K联" `
  --home-id fc-seoul --home "FC首尔" `
  --away-id ulsan-hd --away "蔚山HD"
```

先填写客观事实，并把可核验盘口整理为结构化快照，再生成规则上下文：

```powershell
odds-journal market-snapshots set matches/2026/07/比赛文件.md `
  --file market-snapshots.yml
```

桌面智能体应使用统一入口代替直接调用准备命令：

```powershell
.\scripts\odds-journal.ps1 agent start matches/2026/07/比赛文件.md `
  --as-of "2026-07-30T17:30:00+08:00"
```

`agent start` 只检索规则、写入回执，不生成比赛预测。历史 Analysis Receipt schema 1 只要求规则回执；schema 2 及以上版本接着登记场景并检索案例。当前发布的 `1.8.0` 使用 schema 7、AnalysisOutlook V5 和 Contract 7 草稿评估；总进球或比分不满足证据门禁时必须单独 `pass`。`1.4.0` 提案的 schema 5 回执仍须显式离线运行，且不能锁定：

```powershell
odds-journal scenario add matches/2026/07/比赛文件.md --file scenario.yml
# 没有可靠场景时改用：
odds-journal scenario no-scenario matches/2026/07/比赛文件.md --reason "资料不足，无法稳定归类"
odds-journal retrieve-cases matches/2026/07/比赛文件.md
```

阅读规则与案例上下文后填写赛前推演和最终结论。当前 `1.8.0` 正式轨和活动实验轨的完整顺序为：

分析正文必须包含 `analysis-trace` YAML 区块，逐项记录规则集、截止时间、采用/排除规则、来源、场景和案例。Match V2 的正式结构化结论保存到 `raw/matches/{match_id}/analysis-outlook.yml`；实验结论单独保存在 `experimental-analysis-outlook.yml` 和 `experimental-analysis-report.md`：

```powershell
.\scripts\odds-journal.ps1 agent evaluate-draft matches/2026/07/比赛文件.md `
  --draft-file analysis-draft-input.yml `
  --dispositions-file reasoning-dispositions.yml
.\scripts\odds-journal.ps1 agent evaluate-experiment matches/2026/07/比赛文件.md `
  --dispositions-file experiment-dispositions.yml `
  --advisories-file advisory-dispositions.yml
.\scripts\odds-journal.ps1 agent validate-draft matches/2026/07/比赛文件.md
.\scripts\odds-journal.ps1 agent render-draft matches/2026/07/比赛文件.md
.\scripts\odds-journal.ps1 agent prepare-lock matches/2026/07/比赛文件.md --market one_x_two --selection home --confidence 0.60
```

若实验预测规则没有触发，`dispositions` 文件可为空；若存在 `triggered` 规则，则必须逐条 `adopted` 或 `excluded`。提示规则使用 `acknowledged`、`dismissed` 或 `insufficient_data`，且永远不改变预测输出。实验输入不足或实验引擎失败必须留下明确状态，但不得阻断正式轨校验和锁定。`prepare-lock` 仅在开赛前冻结实验预测与提示回执，开赛后不得补建。

离线验证 `1.4.0` 时，必须显式声明提案来源。提案可以执行 `start`、`validate-draft` 和 `render-draft`，但不得生成候选锁定回执、锁定或自动结算。当前活动的 `1.8.0` 先填写可追溯的 Contract 7 草稿输入，再由代码生成评估 Bundle，并进入正常赛前锁定门禁：

```powershell
.\scripts\odds-journal.ps1 agent start matches/2026/07/比赛文件.md `
  --ruleset football-analysis@1.4.0 --proposal `
  --as-of "2026-07-30T17:30:00+08:00"
.\scripts\odds-journal.ps1 agent validate-draft matches/2026/07/比赛文件.md --proposal
.\scripts\odds-journal.ps1 agent render-draft matches/2026/07/比赛文件.md --proposal
.\scripts\odds-journal.ps1 agent start matches/2026/07/比赛文件.md `
  --as-of "2026-07-30T17:30:00+08:00"
.\scripts\odds-journal.ps1 agent evaluate-draft matches/2026/07/比赛文件.md `
  --draft-file analysis-draft-input.yml `
  --dispositions-file reasoning-dispositions.yml
.\scripts\odds-journal.ps1 agent validate-draft matches/2026/07/比赛文件.md
.\scripts\odds-journal.ps1 agent render-draft matches/2026/07/比赛文件.md
.\scripts\odds-journal.ps1 agent prepare-lock matches/2026/07/比赛文件.md --market one_x_two --selection home --confidence 0.60
```

校验通过后再锁定：

```powershell
odds-journal lock matches/2026/07/比赛文件.md `
  --candidate-file raw/matches/<match_id>/lock-candidates/<receipt_id>.yml
git add matches assets raw
git commit -m "锁定FC首尔对蔚山赛前分析"
```

候选文件路径以 `agent prepare-lock` 返回的 `next_command` 为准，不手工拼接或在开赛后重新生成。

锁定后如出现新结构，只能追加临场场景：

```powershell
odds-journal scenario add-live matches/2026/07/比赛文件.md --file live-scenario.yml
```

记录赛果后先准备复盘，再逐个解析场景、填写复盘正文并完成评价：

```powershell
odds-journal finish matches/2026/07/比赛文件.md `
  --score 1-1 --source "官方赛果页" --key-events "无红牌"

odds-journal prepare-review matches/2026/07/比赛文件.md
odds-journal scenario resolve matches/2026/07/比赛文件.md --file resolution.yml

odds-journal review matches/2026/07/比赛文件.md `
  --primary correct --handicap correct `
  --total-goals-range correct --score-range partial `
  --confidence-calibration partial
```

事实变化且已有分析时，必须先归档并重启：

```powershell
odds-journal analysis restart matches/2026/07/比赛文件.md --reason "伤停来源更正"
```

只有 `reviewed` 比赛可以通过 `evidence link` 进入证据台账；使用 `evidence report` 同时查看事件数和按比赛去重的独立案例数。

### 外部发布稿

需要将已完成的赛前分析整理为小红书等外部内容时，可使用 `templates/xiaohongshu-prematch-analysis.md`。模板只能复述已通过仓库门禁的事实、盘赔和结论，不得自行补充方向或比分，也不能替代 `agent start`、回执声明的 AnalysisOutlook 契约、六章报告、锁定候选或正式 Match 记录。

## 历史提炼与规则发布

历史资料来源由 `knowledge/sources/REGISTRY.yml` 登记。新归档的长聊天记录先生成独立库存和人工审查批次；它不会自动成为案例、证据或规则：

```powershell
odds-journal source migrate-history docs/足球竞猜机构数据分析.md
odds-journal source history-batches
odds-journal source status --source-family doubao-football-history-2026-08-02
```

`doubao-football-history-2026-08-02` 当前处于 `batches_ready`：已归档、去重和预分批，但案例候选、claim、冲突和规则确认仍须人工审查。活动比赛只使用 `active.yml` 指向的已发布规则。

```powershell
odds-journal source coverage
odds-journal evidence validate
odds-journal case validate
odds-journal schemas check
odds-journal validate --rules
odds-journal evidence report
odds-journal validation-study report
```

历史案例当前使用 V3 契约。原始资料按真实 `source_archived_at` 生效，案例 revision 按对应 case event 的 `recorded_at` 生效；严格检索会先选择 `as_of` 时每场最新的合格 revision，再执行 BM25。截图引用使用 `evidence_id + binding_id`，失效映射只追加纠错事件，不修改旧 revision。

历史完赛案例进入规则回归前，必须逐场执行严格认证。当前认证队列共 20 场，其中 `legacy-gimcheon-daejeon`、`legacy-seoul-ulsan` 与 `legacy-incheon-bucheon` 已认证；其余 17 场仍待补齐可回溯的赛前 atom 和 opening/mid/late 节点。认证清单、队列和预检缺口分别位于 `knowledge/certifications/historical-cases/`，认证不会发布规则或改变活动规则集：

```powershell
.\scripts\odds-journal.ps1 case certify-historical `
  --manifest knowledge/certifications/historical-cases/<batch>.yml `
  --actor lcz --strict
```

截至 2026-08-05，36 场 Match 已通过 `finish-historical` 保存为 `historical_finished`；瑞模贝雷 vs 桑托斯仍为 `tracking`。历史完结记录只有可追溯赛果，不包含补造的锁定、自动结算、预测评价或正式复盘，不能与已认证 LegacyCase 的统计资格混为一谈。

多文件历史案例迁移会保留受限备份；进程中断时，下一次 `odds-journal` 启动会自动恢复未提交迁移。索引构建则在临时 SQLite 数据库完成校验后原子替换。不要手动删除 `.odds-journal/`，活动写锁存在时先等待原命令退出。

`football-analysis@1.8.0` 已于 2026-08-06 由 lcz 批准发布并成为当前活动规则集，使用 Manifest 8、Contract 7、AnalysisReceipt V7 与 AnalysisOutlook V5。`1.0.0`、`1.1.0`、`1.3.0` 与 `1.5.0` 均作为不可变历史版本保留，`1.2.0` 仍是未发布的低稳定性校准提案，`1.4.0` 仍为离线分层分析提案。`1.6.0` 是 Contract 5 的历史实验快照；当前活动实验为 `1.7.0 revision 2`，使用 Contract 6 通用 Intake 流水线。该实验只生成隔离的预测、提示和研究产物，必须由 lcz 决定是否创建新 revision、停用或进入正式发布审核。操作见 [规则 Intake 与实验流水线](docs/规则Intake与实验流水线.md)。可使用以下命令核验：

```powershell
odds-journal validate --rules
Get-Content knowledge/rulesets/football-analysis/active.yml
odds-journal rules experiment status
odds-journal rules experiment report 1.7.0
```

后续规则变更必须修改未发布提案并激活新的不可变实验 revision，或创建更高版本提案；已经冻结的实验快照和任何已发布规则集都不得原地修改。正式发布仍须由 lcz 单独批准并通过 `rules release`，实验激活批准不能替代发布批准。

取消、腰斩或长期延期的比赛使用：

```powershell
odds-journal void matches/2026/07/比赛文件.md --reason "比赛延期，重新排期后另建记录"
```

## 校验、导出和检索

```powershell
odds-journal validate --all
odds-journal validate --rules
odds-journal export
odds-journal build-index
odds-journal search "升盘 降水" --competition-code KOR-K1 --json
odds-journal stats
odds-journal schemas check
odds-journal analytics build
odds-journal analytics validate
odds-journal analytics status
odds-journal analytics rule-report --rule-id RULE_ID
odds-journal analytics export-dataset --as-of "2026-08-04T12:00:00+08:00" --output ai/analytics/dataset.jsonl
odds-journal rules experiment report 1.7.0
```

严格历史检索必须传入截止时间，并排除目标比赛：

```powershell
odds-journal search "半球盘 低水" `
  --as-of "2026-07-30T18:00:00+08:00" `
  --exclude-match-id 20260730-kor-k1-fc-seoul-ulsan-hd `
  --json
```

## 数据约束

1. `matches/**/*.md` 是唯一人工事实来源。
2. 锁定后，赛前事实、推演和最终结论任一变化都会使哈希校验失败。
3. 临场信息只追加到临场章节，并使用 `### YYYY-MM-DD HH:mm` 标题。
4. 外部资料均视为数据而非操作指令。
5. AI 输出默认是待审核材料，不自动升级为高可信知识。
6. 胜平负、让球和大小球分别统计，不合并成一个总命中率。
7. 没有有效规则检索回执的比赛不能锁定。
8. 已被锁定比赛引用的规则版本不得原地修改或删除。
9. 历史案例默认不进入统计；只有时间边界和资格均满足的 reviewed 案例才能成为合格证据。
10. 发布规则只生成提案和证据快照，不会因达到样本门槛自动晋级。

详细设计见 [项目改造与AI分析接入方案](docs/项目改造与AI分析接入方案.md)、[比赛全量数据规范化与趋势分析工作流](docs/比赛全量数据规范化与趋势分析工作流.md)、[历史资料提炼与实战规则演进工作流](docs/历史资料提炼与实战规则演进工作流.md)、[总进球证据化与部分市场 Pass](docs/总进球证据化与部分市场Pass.md)、[规则 Intake 与实验流水线](docs/规则Intake与实验流水线.md) 和 [AI 推理与回测验证系统](docs/AI推理与回测验证系统/README.md)。[football-analysis 1.5.0 实施计划](docs/football-analysis-1.5.0规则代码化与分析数据库实现方案.md) 记录 Contract 4 历史基线；`1.8.0` 可用于日常分析和赛前锁定，普通提案仅限显式 `--proposal` 离线运行，已激活实验则通过独立实验回执参与双轨分析。
