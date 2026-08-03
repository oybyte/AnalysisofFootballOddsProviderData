# 历史案例再认证

本目录保存对历史完赛案例的逐场认证清单。清单是人工审查输入，不得从赛果或赛后复盘反推赛前盘口。

认证命令：

```powershell
.\scripts\odds-journal.ps1 case certify-historical --manifest <batch>.yml --actor lcz --strict
```

通过认证的条目必须提供同一来源族的赛前、赛后、赛果 atom，以及早于开赛时间的 opening/mid/late 盘口节点。未能证明边界的条目使用 `needs_manual_split` 或 `rejected`，不进入统计分母。

每次认证会追加案例 revision 与 `knowledge/evidence/historical-case-certification-events.jsonl`，不会改写历史 revision。

截至 2026-08-03，20 场队列中已有 3 场认证通过：`legacy-gimcheon-daejeon`、`legacy-seoul-ulsan`、`legacy-incheon-bucheon`。其余 17 场保持 `pending`，需先按 [preflight-2026-08-02.md](preflight-2026-08-02.md) 补齐证据；不得因历史复盘或赛果存在而直接转正。认证仅开放离线规则回归资格，不会生成锁定、结算、正式复盘，也不改变活动 `football-analysis@1.3.0`。
