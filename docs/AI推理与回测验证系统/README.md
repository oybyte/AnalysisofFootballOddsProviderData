# AI 推理与回测验证系统

文档状态：已实现的受控研究能力。确定性回放、AI 治理、FakeProvider、影子 Study、人工处置和默认停用的案例重排均已实现。Gemini 与 OpenAI-compatible adapter、受信 Prompt 模板和内容寻址的活动 AI 配置也已具备；是否实际调用真实 provider 仍由活动出站策略、预算和本机 `ODDS_JOURNAL_LLM_API_KEY` 共同门禁。本机未配置该密钥时，真实调用保持 `controlled_disabled`。`football-analysis@1.9.0` 的确定性草稿编译器与 `2.0.0` 的知识引擎均仍是未发布提案，不能用于正式比赛锁定；本文档不构成发布或激活授权。

> 当前能力边界：正式活动版本仍为 `1.8.0`，需要人工提供 Draft Input。`1.9.0` 发布后才能在场景登记和案例检索完成后使用 `build-draft -> accept-draft -> evaluate-draft` 生成正式候选与确定性六段正文。`2.0.0` 已有可校验的知识 Snapshot 和本地索引，但只允许 Study/AI 旁路；FakeProvider、AI 研究或知识候选都不能驱动正式预测。

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
AI 研究轨（已实现，完全隔离）
sandbox -> pilot diagnostic -> confirmatory primary -> outcome/disposition
```

正式轨与 AI 轨之间没有反向写入通路。AI 产物可用于研究和人工规则提案，但不能改变任何已锁定或未锁定的正式结论。

## 演进路线

本系统设计支持三阶段渐进式演进，不要求在实施前确定 AI 与规则的最终关系。

### 第一阶段（0-30场）：双轨对比，发现基线
- 目标：搞清楚规则与 AI 各自的强弱项
- 实施：Phase 0-4，每场比赛同时运行规则轨与 AI 轨
- 产出：分市场、分联赛的准确率对比报告

### 第二阶段（31-60场）：提炼模式，演进规则
- 目标：从 AI 成功案例中提炼可代码化的规则
- 实施：Phase 5 + 规则 Intake 流水线
- 产出：由 lcz 创建的下一实验提案 revision，进入三轨对比验证；不得复用已存在的正式 proposal 版本号

### 第三阶段（61场+）：固化策略，按需分工
- 目标：基于数据确定各市场的最优预测来源
- 实施：编写 `prediction-strategy.yml` 配置
- 产出：
  - 按市场分工（让球用规则，比分用 AI）
  - 或 AI 审查规则输出
  - 或保持双轨研究

**关键原则**：权重占比不是事先设定的，而是由回测数据决定的。

## 当前事实

| 事实面 | 状态 | 说明 |
|---|---|---|
| 正式足球工作流 | verified-current | 正式规则仍为 `football-analysis@1.8.0`；`1.9.0` 确定性草稿编译器仅为未发布提案 |
| 正式草稿编译器 | controlled_disabled | Contract 8、市场级门禁和 FactBundle 已实现；只有发布 `1.9.0` 后才可正式使用 |
| 1.9.0 回测证据 | fail-closed | Dataset Manifest 已冻结；当前没有 Contract 8 赛前冻结决策，546 条预测均为 `pass`，不得声明命中率或显著性 |
| 2.0.0 知识引擎 | shadow_ready | Proposal 已封存 1 个内容寻址 Snapshot 和对应字节校验 SQLite 索引；Study/AI 旁路可用，但无 Study 或 Outcome，且未发布版本不得写入正式 AnalysisReceipt、草稿、锁定、结算或统计 |
| AI/回放代码 | verified-current | `backtest`、`ai sandbox`、`ai experiment`、`ai capability` 与 `case rerank` CLI 已实现；权威产物与正式轨隔离 |
| 真实 LLM provider adapter | ready | 已实现 Gemini 与 OpenAI-compatible adapter；密钥只从 `ODDS_JOURNAL_LLM_API_KEY` 环境变量读取，不写入配置、快照或台账 |
| 真实 LLM 调用与网络出站 | controlled_disabled | 当前活动配置为 lcz 批准的内容寻址快照；本机未设置密钥，`ai capability status` 因此拒绝真实调用。即使配置密钥，仍受冻结出站策略、字段白名单、超时与预算限制 |
| 活动 AI 配置 | ready | `openai-gpt56-terra-v1` 的活动快照冻结 `openai-compatible` provider、`gpt-5.6-terra` 模型、五阶段 Prompt、输出 Schema、价格策略和出站策略；模板只接收已冻结的结构化事实、规则评估、案例与正式 Outlook 引用 |
| 案例重排 | controlled_disabled | 默认 BM25；只有 lcz 明确批准且满足独立研究门槛的配置可调用候选封闭重排 |
| 比赛数据与现有规则 | out-of-scope | 本设计不迁移、不重写、不发布它们 |
| 桌面端同步与认证 | not-applicable | 文档拆分本身不运行 `agent sync` |

## 固定决策

- 权威回放数据集保留市场、时间点粒度；仅另行派生阅读摘要，不创建 Light 权威清单。
- sandbox 只用于离线快速探索；pilot 与 confirmatory 都需要 lcz 激活的内容寻址配置。
- 五阶段运行从活动快照加载并校验 Prompt 模板哈希；每个阶段传递受策略允许的实际冻结输入，后续阶段可引用前序阶段输出。该输出仍是独立研究材料，不能写入正式 Draft、锁定、结算或统计。
- 非核心 AI 模块可降级，但核心预测、结构化证据校验和赛前冻结不可降级。
- AI 与规则的最终关系（按市场分工、AI 审查、或继续双轨）在积累 60+ 场数据后由人工决定，不在实施阶段预设。
