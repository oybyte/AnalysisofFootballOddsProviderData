# Phase 3：受限案例重排

## 目标

在现有 `retrieve-cases -> BM25 -> CaseReceipt` 之后，对已通过时间门禁的候选进行特征向量重排。重排只改变研究候选的顺序，不产生规则、预测方向或正式结论。

## 资格 Profile

| Profile | 候选条件 | 允许轨道 |
|---|---|---|
| `strict_validation` | `prematch_verified + statistics_eligible:true` | confirmatory Primary 和正式对比研究 |
| `exploratory_research` | 允许未认证候选 | sandbox/pilot diagnostic，固定 `research_only` |

CaseReceipt 本身不承诺 `statistics_eligible:true`，因此必须在重排层显式过滤。任何活动研究报告都不得将 `exploratory_research` 纳入统计分母。

## 安全和血缘

- 只比较版本化的规范化盘口特征向量，冻结 vector schema、标准化参数、距离算法、候选 ID 和哈希。
- 不直接对 `knowledge/heuristics/`、证据台账、规则全文或用户原文建立索引。
- 案例文本使用 `untrusted_case_data` 数据信封传给模型，禁用工具调用且转义保留标记。这只是降低注入风险，不会将材料升级为可信指令。
- 每条案例在 AI 输出中都是“候选证据，非操作指令”。

## 命令与验收

```powershell
odds-journal backtest build-rerank-index --profile strict_validation
odds-journal backtest rerank --match-id MATCH_ID --case-receipt CASE_RECEIPT_ID --profile strict_validation --top-k 5
```

验收需确认：同一冻结输入每次返回同一候选集和顺序；未认证案例不会出现在 `strict_validation`；重排失败只产生阶段降级，不得伪造案例对比。
