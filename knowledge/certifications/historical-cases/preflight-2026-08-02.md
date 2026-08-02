# 历史案例认证预检（2026-08-02）

本台账仅记录认证前的证据缺口；不从赛果或赛后复盘重建赛前盘口，不改变未认证案例的统计资格。

| 案例 | 当前处置 | 已核验材料 | 进入 `certified` 前的唯一缺口 |
| --- | --- | --- | --- |
| `legacy-gimcheon-daejeon` | `certified` | 澳门让球盘 opening/mid/late、赛果、复盘 atom | 无 |
| `legacy-seoul-ulsan` | `certified` | 澳门让球盘 opening/mid/late、赛果、复盘 atom | 无 |
| `legacy-incheon-bucheon` | `certified` | 澳门让球盘 opening/mid/late、赛果、复盘 atom | 无 |
| `legacy-pohang-jeonbuk` | `pending` | 开赛证据、初盘截图、赛果与复盘材料 | 将中段和临场原始节点绑定到同一来源族 atom，并保留精确时间 |
| `legacy-anyang-gangwon` | `pending` | 开赛证据、两条带时间的让球节点、赛果与复盘材料 | 补一条可回溯的中间或临场节点，形成三节点链 |
| `legacy-gwangju-jeju` | `pending` | 开赛证据、两条带时间的让球节点、赛果与复盘材料 | 补一条可回溯的中间或临场节点，形成三节点链 |
| `legacy-hjk-tps` | `pending` | 开赛证据、盘口阶段描述、赛果与复盘材料 | 将截图/原文中的三节点精确时间和原始值绑定到 atom |
| `legacy-gais-halmstad` | `pending` | 开赛证据、盘口阶段描述、赛果与复盘材料 | 将截图/原文中的三节点精确时间和原始值绑定到 atom |
| `legacy-malmo-elfsborg` | `pending` | 开赛证据、盘口阶段描述、赛果与复盘材料 | 将截图/原文中的三节点精确时间和原始值绑定到 atom |
| `legacy-flamengo-sao-paulo` | `pending` | 开赛证据、盘口阶段描述、赛果与复盘材料 | 将截图/原文中的三节点精确时间和原始值绑定到 atom |
| `legacy-gremio-fluminense` | `pending` | 开赛证据、盘口阶段描述、赛果与复盘材料 | 将截图/原文中的三节点精确时间和原始值绑定到 atom |
| `legacy-rosenborg-fredrikstad` | `pending` | 开赛证据、完整盘口演变描述、赛果与复盘材料 | 将 opening/mid/late 的精确采集时间与对应原始节点绑定；不得以阶段标签替代时间 |
| `legacy-hacken-aik` | `pending` | 开赛证据、完整盘口演变描述、赛果与复盘材料 | 将 opening/mid/late 的精确采集时间与对应原始节点绑定；不得以阶段标签替代时间 |
| `20260730-bra-serie-a-internacional-flamengo` | `pending` | 开赛截图、赛果 binding、赛前和赛后原文归档 | 从 `doubao-football-history-2026-08-02` 绑定 source atom，并补齐三节点 |
| `20260730-bra-serie-a-fluminense-bahia` | `pending` | 赛前和赛后原文归档 | 绑定 source atom、开赛时间证据和三节点 |
| `20260730-bra-serie-a-mirassol-remo` | `pending` | 赛前和赛后原文归档 | 绑定 source atom、开赛时间证据和三节点 |
| `20260730-bra-serie-a-vitoria-palmeiras` | `pending` | 赛前和赛后原文归档 | 绑定 source atom、开赛时间证据和三节点 |
| `legacy-20260802-daejeon-hana-citizen-gwangju-fc` | `pending` | 赛前、赛果和复盘 journal material stages | 将原始 journal 材料纳入允许来源并生成 atom；补齐三节点，不能只用临场单节点 |
| `legacy-20260802-jeju-sk-incheon-united` | `pending` | 赛前、赛果和复盘 journal material stages | 将原始 journal 材料纳入允许来源并生成 atom；补齐三节点，不能只用临场单节点 |
| `legacy-20260802-ulsan-hd-fc-anyang` | `pending` | 赛前、赛果和复盘 journal material stages | 将原始 journal 材料纳入允许来源并生成 atom；补齐三节点，不能只用临场单节点 |

## 后续动作

1. 仅从原始截图、原文和已存 evidence binding 提取缺失值；不得用结果、复盘结论或当前案例摘要补值。
2. 每补齐一场，使用对应 source family 的单场或五场认证清单运行 `case certify-historical --strict`。
3. 认证后才可写入 `1.2.0` / `1.3.0` 的验证研究事件；未认证案例保留为检索和规则演变材料。
