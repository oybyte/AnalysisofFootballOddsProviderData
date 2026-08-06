# AI 推理与回测验证系统

文档状态：待实施设计（2026-08-06）。当前仓库尚未实现 AI 实验轨、LLM provider 或确定性回放模块；本文档集是实施契约，不是已上线功能说明。

## 阅读顺序

1. [00-通用治理与数据契约](00-通用治理与数据契约.md)：信任边界、AI 运行轨道、出站策略、存储和统计隔离。
2. [01-Phase0-数据资格清单](01-Phase0-数据资格清单.md)和 [02-Phase1-确定性离线回放](02-Phase1-确定性离线回放.md)：是任何 AI 实验前提。
3. [03-Phase2-AI 独立实验轨](03-Phase2-AI独立实验轨.md)和 [04-Phase3-受限案例重排](04-Phase3-受限案例重排.md)：定义 sandbox、pilot、confirmatory 及可审计输出。
4. [05-Phase4-前瞻性影子运行](05-Phase4-前瞻性影子运行.md)和 [06-Phase5-人工评估与规则提案](06-Phase5-人工评估与规则提案.md)：定义研究分母和规则演进边界。
5. [07-实施门槛与验收矩阵](07-实施门槛与验收矩阵.md)：执行顺序、止损门槛和验证命令。

## 架构全景

```text
正式轨（现有）
agent start -> evaluate-draft -> validate-draft -> prepare-lock -> lock -> finish -> review
                                  |
                                  | 只读冻结引用
                                  v
AI 研究轨（新增，完全隔离）
sandbox -> pilot diagnostic -> confirmatory primary -> outcome/disposition
```

正式轨与 AI 轨之间没有反向写入通路。AI 产物可用于研究和人工规则提案，但不能改变任何已锁定或未锁定的正式结论。

## 当前事实

| 事实面 | 状态 | 说明 |
|---|---|---|
| 正式足球工作流 | verified-current | 正式规则为 `football-analysis@1.8.0`，实验为 `1.7.0 revision 1` |
| AI/回放代码 | pending | 本文档集中的模块、Schema 和 CLI 均待实现 |
| 比赛数据与现有规则 | out-of-scope | 本设计不迁移、不重写、不发布它们 |
| 桌面端同步与认证 | not-applicable | 文档拆分本身不运行 `agent sync` |

## 固定决策

- 权威回放数据集保留市场、时间点粒度；仅另行派生阅读摘要，不创建 Light 权威清单。
- sandbox 只用于离线快速探索；pilot 与 confirmatory 都需要 lcz 激活的内容寻址配置。
- 非核心 AI 模块可降级，但核心预测、结构化证据校验和赛前冻结不可降级。
