# football-analysis 1.5.0 分层预测、规则代码化与分析数据库实施计划（完善版）

文档状态：目标设计，已建立部分离线实现基线（2026-08-04）。当前 CLI、Schema、桌面工作流和活动规则仍以仓库代码、`ai/desktop-agent-manifest.yml` 与 `knowledge/rulesets/football-analysis/active.yml` 为准。

## 实施状态（2026-08-04）

已完成的离线基础设施：

- 建立 `football-analysis@1.5.0` 提案目录、Manifest schema 5、Calibration Contract 4、AnalysisReceipt V6、AnalysisOutlook V4 与提案隔离；活动规则仍为 `1.3.0`。
- 建立 Contract 4 草稿输入、规则特征/阈值评估、内容寻址 Bundle 与 AI 处置接口；通过 `agent evaluate-draft --proposal` 运行，提案回执不能锁定。
- 建立可重建的初始 Analytics SQLite 投影及 `analytics build`、`validate`、`status`、`rule-report`、`export-dataset` 命令。
- 完成 Contract 1-3 兼容、规则提案校验和当前回归测试；CLI 为 `0.8.0`，桌面工作流为 `1.8.0`。

仍属后续范围：完整 intake 处置、完整 Analytics 目标表回填、赛后影子评价、全量历史规则回放、真实 `1.5.0` 影子比赛与发布门禁。下文未在本节列为已完成的项目均为目标设计，不能据此推定已经可用或已发布。

## 一、目标与固定决策

本次建设包含两个独立交付物：

1. **football-analysis@1.5.0**
   - 基础盘口分析架构；
   - 全赛事通用规则；
   - 联赛 Profile 专属规则；
   - AI 双向推理与候选处置；
   - 代码重新计算并验证最终结果。

2. **Analytics Database V1**
   - 从现有权威文件构建只读 SQLite 投影；
   - 用于规则回归、联赛对比、AI 处置评价和训练集导出；
   - 不成为日常比赛分析的运行时依赖。

固定决策：

- `1.5.0` 直接继承未发布 `1.4.0`，不先发布 `1.4.0`。
- 活动版本在单独获得 lcz 发布批准前保持 `1.3.0`。
- 默认分析模式为 `market_only`，基本面不是必要输入。
- 澳门亚盘三节点为完整模式门禁；缺失时允许 `degraded`，置信度不超过 `0.69`。
- 挪超和 MLS 保留八条 `lsl-*` 共享实验兼容层，再由精确联赛 Profile 分别覆盖。
- 文件、截图、Match、事件和回执是权威事实源；数据库仅为可重建投影。
- Contract 1-3、Receipt V1-V5、Outlook V1-V3、历史锁定与结算行为保持不变。
- 本阶段不训练正式预测模型，只提供无数据泄漏的 JSONL 数据集。
- 发布、切换 `active.yml` 和 `agent sync` 均不属于默认实施动作。
- 本文档只定义实施方案，不构成规则发布、活动版本切换、数据库迁移或产品同步授权。

## 二、版本与公共契约

### 1. 版本升级

新增：

- Ruleset Manifest Schema 5
- Calibration Contract 4
- AnalysisReceipt V6
- AnalysisOutlook V4
- AnalysisTrace V2
- AnalysisDraftInput V1
- RuleEvaluationBundle V1
- ReasoningDisposition V1
- Analytics Database Schema 1

保持：

- Match Schema V2
- LockCandidateReceipt V1/V2
- ReviewReceipt V2
- Index Schema 5
- Retrieval Contract 4

CLI 包版本升级为 `0.8.0`，desktop workflow 升级为 `1.8.0`。实现结束运行 `agent changes`，由它报告哪些产品认证过期；没有新的明确授权不执行 `agent sync`。

### 2. 表驱动契约矩阵

新增统一契约注册表，替换当前按规则版本号硬编码的判断：

| Manifest | Calibration | Receipt | Outlook | Proposal 可锁定 |
|---|---:|---:|---:|---|
| 4 | 1 | 4 | 2 | 否 |
| 4 | 2 | 4 | 2 | 否 |
| 4 | 3 | 5 | 3 | 否 |
| 5 | 4 | 6 | 4 | 否 |

已发布规则集仍按 `ruleset_origin: published` 进入锁定流程；任何 `ruleset_origin: proposal` 均拒绝 `prepare-lock`，不再依赖具体 Receipt 版本判断。

该注册表供以下模块共同使用：

- ruleset loader；
- proposal validator；
- agent start；
- validate-draft；
- rules release；
- lock lifecycle；
- desktop capability/changes。

### 3. Manifest Schema 5

Manifest Schema 5 必须冻结：

- calibration contract 4；
- AnalysisReceipt V6；
- calibration config 相对路径和 SHA-256；
- source coverage SHA-256；
- evidence snapshot SHA-256；
- 规则文档集合及其内容哈希；
- weight model、market contract、index 和 retrieval contract。

机器配置固定为一个文件：

```text
knowledge/rule-proposals/football-analysis/1.5.0/
  calibration/football-analysis-v4.yml
```

features、profiles、rules 和 controls 全部包含在该文件内，避免嵌套配置只冻结顶层路径却遗漏子文件哈希。

## 三、输入门禁与基础分析

### 1. analysis_input_mode

新增独立字段：

```text
market_only | full_context
```

它只描述输入范围，不替代 `complete/degraded/pass`。

### 2. market_only 门禁

`complete` 必须满足：

- 比赛身份、联赛代码、开赛时间和时区明确；
- 数据截止时间早于开赛；
- 四个维度均可评估：亚盘、欧赔、凯利、大小球；
- 澳门亚洲让球存在按时间排序的 opening/mid/late 三节点；
- 所有引用盘口具有 provider、格式、原始值、规范值和来源；
- 不存在未解决的比赛身份或盘口格式冲突。

`degraded`：

- 澳门缺失或不足三个节点；
- 任一维度缺失并按零贡献处理；
- 其他认可机构数据仍足以形成基础方向；
- 置信度强制 `<=0.69`；
- 缺失输入的专项规则返回 `insufficient_data`。

`pass`：

- 比赛身份、开赛时间或数据截止边界冲突；
- 无法确认赔率格式或主客方向；
- 所有可选主市场第一顺位并列；
- 基础证据冲突且无法形成可反证假设；
- 可用数据不足以形成任何主市场。

其他机构的三节点可以参与评分、共识和反证，但不能伪装成需要澳门输入的规则证据，也不能把整场从 degraded 提升为 complete。

### 3. full_context

在 market_only 的全部要求上增加基本面材料。基本面只进入支持、反证和解释字段，不得替代盘口快照，不得从盘口反推伤停或资金事实。

### 4. 防止重复计权

每个 FeatureSpec 增加：

- `feature_owner: baseline | calibration | shared_correlated`
- `correlation_key_policy`
- `incremental_effect_allowed`

每个规则事件增加：

- `already_reflected_in_baseline`
- `incremental_evidence_ids`

处理规则：

- 已完整计入基础评分的同一信号，实验规则默认只能提供解释或风险候选；
- 只有新增独立 provider、独立市场或独立时间信息时，才允许形成额外排序作用；
- 欧赔与凯利共享 provider + evidence ID 时按相关信号处理；
- 同一快照不能通过不同规则重复形成两份换锚支持。

## 四、规则引擎代码化

### 1. 模块结构

新增：

```text
src/odds_journal/rule_engine/
  config.py
  features.py
  evaluators.py
  profiles.py
  conflicts.py
  candidates.py
  evaluation.py
  audit.py
```

职责：

- `config.py`：RuleSpec、FeatureSpec、ProfileSpec、ControlSpec。
- `features.py`：统一盘口特征计算。
- `evaluators.py`：确定性规则白名单。
- `profiles.py`：Profile 继承和适用规则解析。
- `conflicts.py`：同源去重、冲突抵消和换锚门禁。
- `candidates.py`：排名、总进球、比分和风险候选。
- `evaluation.py`：赛后规则效果判定。
- `audit.py`：稳定哈希和审计事件。

旧 `calibration.py` 保留 Contract 1-3 的实现；Contract 4 只调用新引擎。

### 2. FeatureSpec

首批统一特征：

- 初盘、临盘盘口深度；
- 同档水位净变化；
- 盘口档位变化；
- 趋势净变化；
- 趋势最大回调；
- 趋势纯度；
- provider 共识比例；
- provider 异常距离；
- 欧赔变化率；
- 凯利差值和凯利区间；
- 平赔波动率；
- 距离开赛分钟数。

每项特征必须定义：

- 输入市场和字段；
- calculator ID；
- 是否要求同机构、同档、同格式；
- 精度和舍入方式；
- 缺失行为；
- cutoff 过滤；
- 单元测试边界。

禁止规则各自重复实现涨跌幅和盘口档位算法。

### 3. RuleSpec

每条规则必须声明：

- 规则 ID、版本、状态；
- 适用 Profile、市场、阶段、provider 和格式；
- feature IDs；
- evaluator ID；
- 阈值、单位和比较符；
- 影响面：ranking、handicap signal、total goals pool、score pool 或 outcome risk pool；
- 目标市场和候选；
- 最大排序移动；
- 是否允许参与换锚；
- 缺数据和不适用行为；
- source atom、claim、支持、反例和研究引用。

规则配置不得包含 Python 表达式，不使用 `eval`。calculator/evaluator ID 必须存在于受信代码白名单。

### 4. 规则效果评价契约

每条可回归规则还必须声明：

- `evaluation_market`
- `evaluation_selection`
- `settlement_basis`
- `baseline_comparator`
- `eligible_denominator`
- `push_policy`
- `random_event_policy`

默认处理：

- 亚洲让球规则按正式亚洲盘结算评价；
- 胜平负规则按正式 1X2 结果评价；
- 总进球规则按最终区间覆盖评价；
- 比分规则按候选覆盖评价，不按第一比分命中评价；
- 风险候选单独统计风险发生率，不计主预测命中率；
- push 按规则配置计为排除或独立类别，不自动算胜；
- 红牌、重大点球争议等被正式复盘标记为随机事件时保留记录，relation 为 ambiguous，不进入有效分母。

## 五、通用规则与联赛 Profile

### 1. 初始机器规则

继承 `1.4.0`，不改变阈值：

- 8 条 `lsl-*`；
- 6 条 global 实验规则；
- 2 条韩国实验规则。

新增五项赛前控制：

- `trend-purity-v1`：决定走势规则是否有效或降级，不直接改排名。
- `provider-consensus-divergence-v1`：登记共识、分歧和异常值，不单独换锚。
- `cross-dimension-netting-v1`：同市场支持与反证抵消。
- `late-market-anomaly-v1`：只进入结果风险池。
- `single-kelly-value-guard-v1`：禁止单一极低凯利直接定方向。

新增一项赛后方法：

- `postmatch-shadow-evaluation-v1`：分别评价基础、机械规则、AI 采纳和最终锁定。

### 2. Profile 链

固定 Profile：

```text
global
global -> korea-k1
global -> korea-k2
global -> legacy-low-stability -> norway-eliteserien
global -> legacy-low-stability -> mls
```

规则：

- 一场比赛只能匹配一个精确联赛 Profile；
- Profile 继承不得成环；
- `legacy-low-stability` 中八条规则保持 experimental；
- 共享层本身不得晋级 supported；
- 挪超和 MLS 可分别覆盖阈值、停用规则或新增专属规则；
- MLS 当前无验证案例，继承不代表已完成 MLS 验证；
- 其他联赛仅运行 global。

## 六、AI 推理与中间产物

### 1. AnalysisDraftInput V1

AI 先填写：

- analysis input mode；
- baseline gate；
- 四维多市场评分矩阵；
- 每个评分的快照、provider、evidence 和解释；
- 基础市场输出；
- 正反假设。

该文件不得包含规则触发结论。

### 2. agent evaluate-draft

新增命令：

```powershell
agent evaluate-draft MATCH_PATH --proposal
```

执行：

1. 读取 AnalysisDraftInput；
2. 验证快照、cutoff、provider 和评分矩阵；
3. 计算 Profile 链；
4. 计算 FeatureSnapshot；
5. 执行所有适用规则和 controls；
6. 生成候选池骨架；
7. 写入内容寻址文件：

```text
rule-evaluation-<bundle_sha256>.yml
```

Bundle 冻结：

- draft input SHA-256；
- market snapshots SHA-256；
- calibration config SHA-256；
- feature snapshot SHA-256；
- cutoff；
- Profile 链；
- 全部规则事件。

相同输入重复执行返回同一文件；不同哈希不得覆盖旧文件。

### 3. ReasoningDisposition V1

AI 对每个触发候选填写：

- adopted 或 excluded；
- 假设 A/B；
- 支持证据；
- 反证；
- provider 共识或异常解释；
- 排除理由；
- 置信度影响；
- 锁定前失效条件；
- actor、product ID、workflow version 和生成时间。

AI 不得修改机器特征、阈值、Profile、applicability 或 deterministic result。

### 4. Outlook V4 和 Trace V2

Outlook V4 保存：

- draft input SHA-256；
- RuleEvaluationBundle SHA-256；
- 基础、实验和最终排序；
- 全部 disposition；
- 候选池处置；
- 最终总进球和两个比分；
- 换锚理由。

AnalysisTrace V2 保存：

- 规则文档采用/排除；
- deterministic rule IDs；
- adopted/excluded disposition IDs；
- control IDs；
- Profile 链；
- evaluation bundle SHA-256。

`validate-draft` 必须重新计算 bundle 并比较所有机器字段。旧 bundle 可以保留，但只有 Outlook 引用且重算一致的 bundle 有效。

## 七、intake 处置

1. 将 19 份文档拆成原子声明。
2. 每项只能标记：
   - duplicate
   - supplement
   - new-experimental
   - conflict
   - invalid
   - deferred
3. 聚合稿和拆分稿重复内容只保留一条规则候选链。
4. `2.5 -> 2/2.5` 固定为降盘。
5. 以下内容标记 invalid 或 deferred：
   - 固定 `4:3:3`、`4:6` 概率；
   - Bet365 固定第二核心；
   - 不可验证的内幕资金结论；
   - 单规则直接改变第一顺位；
   - 大小球直接改变胜平负；
   - 无数据支撑的高置信度提升。
6. 只有与五项控制直接对应的声明进入本轮机器配置。
7. 其他新增方向规则全部 deferred，后续进入 `1.6.0` 候选。
8. 所有采用项绑定 source atom、claim、冲突处置和 proposal hash。

## 八、Analytics Database V1

### 1. 定位

生成文件：

```text
ai/analytics/football.sqlite3
```

将 `ai/analytics/` 加入 `.gitignore`。数据库不提交、不作为 agent start 的必要条件。

### 2. 数据表

以下是目标完整表集合。当前初始投影已实现 `build_metadata`、`fixtures`、`market_snapshots`、`snapshot_values`、`analysis_runs`、`results`、`evidence_links` 和 `validation_cases`；其余表待后续回填，不应假定已存在。

- `build_metadata`
- `fixtures`
- `market_snapshots`
- `snapshot_values`
- `analysis_runs`
- `baseline_market_scores`
- `rule_evaluations`
- `reasoning_dispositions`
- `candidate_pool_items`
- `predictions`
- `results`
- `settlements`
- `reviews`
- `evidence_links`
- `validation_cases`

`analysis_run_id` 由以下内容确定：

```text
match_id + ruleset_version + cutoff + receipt_digest + outlook_digest
```

同场不同规则版本或不同 cutoff 不互相覆盖。

`snapshot_values` 使用 `(snapshot_id, value_key)` 唯一键，同时保存 raw value 和 numeric value。

### 3. 构建流程

1. 枚举全部权威 Match、回执、规则事件、认证案例和验证案例。
2. 计算 source fingerprint。
3. 构建临时 SQLite。
4. 开启 foreign keys。
5. 校验唯一键、外键、源文件哈希和行数。
6. 执行 `PRAGMA integrity_check`。
7. 写入 schema、build version、source fingerprint 和业务数据摘要。
8. 原子替换正式数据库。
9. 相同 fingerprint 直接返回，不重复构建。

数据库失败不影响权威文件，也不阻止日常分析，只阻止 analytics 查询、回归和导出。

### 4. CLI

新增：

```powershell
analytics build
analytics validate
analytics status
analytics rule-report --rule-id RULE_ID
analytics export-dataset --as-of DATE --format jsonl
```

V1 仅支持 JSONL。导出记录必须包含：

- feature_available_at；
- cutoff；
- ruleset 和配置哈希；
- prediction_eligible；
- label_available_at；
- competition/Profile；
- 基础、机械、AI 采纳和最终结果。

只有开赛前锁定且正式结算的运行可设置 `prediction_eligible:true`。历史认证但未锁定案例只能进入规则研究数据集。

## 九、详细实施顺序

1. 更新并提交本设计文档，冻结旧版本测试结果。
2. 建立表驱动契约矩阵，移除新增版本对 SemVer 的硬编码判断。
3. 实现 Manifest 5、Contract 4、Receipt 6、Outlook 4、Trace 2 和中间产物模型。
4. 生成并校验全部 JSON Schema。
5. 实现 FeatureSpec、特征所有权和相关性去重。
6. 实现 RuleSpec 和规则效果评价契约。
7. 拆分 Contract 4 规则引擎，保持 Contract 1-3 原代码路径。
8. 实现 Profile 解析和精确联赛覆盖。
9. 迁移 16 条既有实验规则和 5 项控制。
10. 完成 intake 原子处置矩阵。
11. 实现 AnalysisDraftInput 和内容寻址 evaluate-draft。
12. 扩展 validate-draft、render-draft 和 proposal 锁定拒绝。
13. 实现 postmatch shadow evaluation。
14. 建立 Analytics Database Schema、构建器和 CLI。
15. 回填全部现有 Match 和合格案例，不修改权威文件。
16. 使用历史数据执行规则回放。
17. 使用新比赛完成 `1.5.0 --proposal` 影子分析。
18. 运行全量校验和 `agent changes`。
19. 保持 proposal 和 `active.yml=1.3.0`，等待单独发布批准。

## 十、测试与验收

必须覆盖：

- Contract 1-3 历史行为完全不变；
- Manifest/Contract/Receipt/Outlook 非法组合被拒绝；
- proposal-origin 任意 Receipt 均不能锁定；
- market_only 无基本面可正常分析；
- 澳门三节点 complete、缺失时 degraded；
- 其他机构不能伪造澳门专项输入；
- cutoff 后快照完全不可见；
- 同机构、同市场、同格式、同档比较；
- 趋势回调、纯度、共识和异常值；
- Profile 继承无环且精确赛事唯一；
- 同源信号不重复计权；
- 已进入基础评分的信号不重复调整；
- AI 无法改变机器触发结果；
- 每个触发候选必须 adopted 或 excluded；
- 单规则不能换锚；
- 大小球和比分候选不污染胜平负；
- 最终恰好两个不同比分；
- bundle 内容寻址、幂等和过期检测；
- 数据库删除后可完整重建；
- 中断构建保留旧数据库；
- 数据库外键、源哈希和业务摘要一致；
- 未锁定历史案例不进入预测准确率；
- 随机事件案例保留但不进入有效规则分母；
- JSONL 不包含 cutoff 后或赛后特征；
- `1.3.0` 的 start、lock、finish、review 全流程回归通过。

最终验收必须证明每场比赛可以完整追踪：

```text
原始盘口
-> 规范化快照
-> 特征
-> 基础评分
-> 通用规则
-> 联赛规则
-> AI 处置
-> 最终预测
-> 赛前锁定
-> 赛果结算
-> 基础/规则/AI/最终四轨评价
```
