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
- `matches/`：人工维护的单场比赛主记录。
- `assets/matches/`：比赛截图等附件。
- `raw/matches/`：原始网页、数据导出等证据。
- `data/matches/`：从 Markdown 自动生成的 JSON，不人工修改。
- `data/analysis-context/`：分析前规则上下文缓存，可删除重建。
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

先填写客观事实，再生成规则上下文：

```powershell
odds-journal prepare-analysis matches/2026/07/比赛文件.md `
  --market handicap `
  --as-of "2026-07-30T17:30:00+08:00"
```

该命令只检索规则、写入回执，不生成比赛预测。阅读上下文后填写赛前推演和最终结论，再锁定：

```powershell
odds-journal lock matches/2026/07/比赛文件.md `
  --market handicap --selection away_handicap --confidence 0.62
git add matches assets raw
git commit -m "analysis: lock fc seoul vs ulsan hd"
```

记录赛果、手工填写复盘正文，再完成评价：

```powershell
odds-journal finish matches/2026/07/比赛文件.md `
  --score 1-1 --result-1x2 draw --handicap-result away_handicap

odds-journal review matches/2026/07/比赛文件.md `
  --primary correct --handicap correct `
  --total-goals-range correct --score-range partial `
  --confidence-calibration partial
```

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

详细设计见 [项目改造与AI分析接入方案](docs/项目改造与AI分析接入方案.md)。
