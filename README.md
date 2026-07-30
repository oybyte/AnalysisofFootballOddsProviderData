# 足球盘口学习与比赛分析日志

本项目用于整理足球盘口学习资料，并以“一场比赛一个 Markdown”的方式记录赛前事实、推演、临场更新、赛果和复盘。项目只用于赛事数据学习，不构成投注建议。

## 环境安装

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\odds-journal.exe --help
```

## 目录说明

- `knowledge/`：经过分级的概念、方法、经验规则和原始学习资料。
- `knowledge/rulesets/`：不可原地覆盖的版本化分析规则集。
- `knowledge/rule-proposals/`：尚未发布、可继续人工审查的规则提案。
- `knowledge/extraction/`：文本/媒体库存及声明、处置、冲突、案例事件链。
- `knowledge/cases/legacy/`：由案例事件台账重建的历史案例投影。
- `knowledge/evidence/`：用户文件证据注册表和 reviewed 比赛追加的规则证据台账。
- `matches/`：人工维护的单场比赛主记录。
- `assets/matches/`：比赛截图等附件。
- `raw/matches/`：原始网页、数据导出等证据。
- `data/matches/`：从 Markdown 自动生成的 JSON，不人工修改。
- `data/analysis-context/`：分析前规则上下文缓存，可删除重建。
- `data/case-context/`、`data/review-context/`：案例检索和复盘上下文缓存。
- `ai/index/`：本地 SQLite 中文检索索引，可删除重建。
- `reports/`：比赛索引和统计报告。
- `archive/`：旧版豆包抓取与文档生成脚本。

## 新比赛工作流

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

先填写客观事实，再生成规则上下文。当前 v1 规则集只要求规则回执；v2 规则集还要求场景和案例回执：

```powershell
odds-journal prepare-analysis matches/2026/07/比赛文件.md `
  --market handicap `
  --as-of "2026-07-30T17:30:00+08:00"
```

该命令只检索规则、写入回执，不生成比赛预测。v2 比赛接着登记场景并检索案例：

```powershell
odds-journal scenario add matches/2026/07/比赛文件.md --file scenario.yml
# 没有可靠场景时改用：
odds-journal scenario no-scenario matches/2026/07/比赛文件.md --reason "资料不足，无法稳定归类"
odds-journal retrieve-cases matches/2026/07/比赛文件.md
```

阅读规则与案例上下文后填写赛前推演和最终结论，再锁定：

```powershell
odds-journal lock matches/2026/07/比赛文件.md `
  --market handicap --selection away_handicap --confidence 0.62
git add matches assets raw
git commit -m "analysis: lock fc seoul vs ulsan hd"
```

锁定后如出现新结构，只能追加临场场景：

```powershell
odds-journal scenario add-live matches/2026/07/比赛文件.md --file live-scenario.yml
```

记录赛果后先准备复盘，再逐个解析场景、填写复盘正文并完成评价：

```powershell
odds-journal finish matches/2026/07/比赛文件.md `
  --score 1-1 --result-1x2 draw --handicap-result away_handicap

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

## 历史提炼与规则发布

```powershell
odds-journal source coverage
odds-journal evidence validate
odds-journal case validate
odds-journal schemas check
odds-journal rules proposal-validate 1.1.0
odds-journal evidence report
```

历史案例当前使用 V3 契约。原始资料按真实 `source_archived_at` 生效，案例 revision 按对应 case event 的 `recorded_at` 生效；严格检索会先选择 `as_of` 时每场最新的合格 revision，再执行 BM25。截图引用使用 `evidence_id + binding_id`，失效映射只追加纠错事件，不修改旧 revision。

`football-analysis@1.1.0` 当前位于 `knowledge/rule-proposals/`，已通过机器校验但尚未激活。lcz 完成人工审读后，才执行：

```powershell
odds-journal rules release 1.1.0 --approved-by lcz
```

发布命令将正式版本写入不可变目录、构建 schema 4 索引，并最后切换 `active.yml`；失败时旧活动版本保持不变。

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

详细设计见 [项目改造与AI分析接入方案](docs/项目改造与AI分析接入方案.md) 和 [历史资料提炼与实战规则演进工作流](docs/历史资料提炼与实战规则演进工作流.md)。
