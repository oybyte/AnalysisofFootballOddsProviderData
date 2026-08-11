# 复盘→实验轨→正式轨 自动化流水线方案

## Context

当前复盘完成后，复盘内容仅存储在比赛文件的 `postmatch-review` 章节中，不会自动进入知识库。用户希望建立一条自动化流水线：复盘 → 自动提取证据和案例 → 证据累积到实验轨 → 满足条件后推进到正式轨提案。

**当前复盘内容格式**（已确认）：复盘内容为中文散文，有 `<!-- review-content:start/end -->` 标记，内部包含结构化章节（赛果与预测对照表、正确判断、错误判断、遗漏信号、错误分类、规则反例、可复用教训）。但 `scenario-resolutions` 区块为空（`resolutions: []`），因此不能依赖结构化数据提取。

## 治理约束（不可突破）

| 约束 | 来源 |
|------|------|
| 仅 lcz 可激活实验快照 | AGENTS.md + experiments.py |
| 正式发布须 lcz 单独批准 | AGENTS.md + rules_release.py |
| AI 结果不能直接生成活跃规则 | AGENTS.md |
| 已发布规则不可原地修改 | AGENTS.md |
| 证据快照不可变 | AGENTS.md |
| 规则提案须走完整 intake 流水线 | AGENTS.md |

## 整体架构

```
复盘完成(review_match)
    │
    ▼
[阶段1: 自动证据提取]  ← 全自动，review_match 末尾 hook
    │  解析 review-content 中的"规则反例"和"可复用教训"章节
    │  生成 EvidencePayload 追加到 rule-evidence.jsonl
    │  标记 extraction_source: "auto-extracted"
    │
    ▼
[阶段2: 证据累积监控]  ← 全自动，每次证据追加后运行
    │  统计各规则证据数量
    │  检查 promotion_gate 阈值
    │  阈值满足时通知 lcz
    │
    ▼
[阶段3: lcz 审批证据]  ← 手动，lcz 运行 review-auto 命令
    │  审核自动提取的证据
    │  批准/拒绝/修正
    │
    ▼
[阶段4: 实验轨推进]  ← 手动，lcz 运行 activate 命令
    │  更新实验快照的 evidence_snapshot
    │  激活实验
    │
    ▼
[阶段5: 正式轨发布]  ← 手动，lcz 运行 release 命令
    │  验证实验报告
    │  发布规则集
```

## 关键发现：复盘内容是散文，不是结构化数据

经过核实，当前复盘内容格式为：

```markdown
<!-- review-content:start -->

### 六、规则反例
本场比赛为以下规则提供了反例：
1. **趋势纯净度（trend-purity-v1）**：...
2. **机构共识分歧（provider-consensus-divergence-v1）**：...

### 七、可复用教训
1. **深盘"回盘降水" ≠ 穿盘信号**：...
2. **方向性分歧在深盘场景中权重应提升**：...
<!-- review-content:end -->
```

因此，证据提取不能依赖结构化数据（`scenario-resolutions` 为空），必须采用**基于章节标记的散文解析**策略。

## 详细设计

### 阶段1：自动证据提取

**新增文件**：`src/odds_journal/evidence_pipeline.py`

**核心函数**：

```python
def auto_extract_evidence_from_review(root: Path, path: Path) -> list[EvidencePayload]:
```

**解析逻辑**：
1. 读取 `postmatch-review` 章节
2. 定位 `<!-- review-content:start -->` 和 `<!-- review-content:end -->` 之间的内容
3. 解析"规则反例"章节：提取 `rule_id`（如 trend-purity-v1）和反例描述
4. 解析"可复用教训"章节：提取教训条目
5. 解析"赛果与预测对照"表格：提取各市场判定
6. 对每个提取的规则反例，生成一个 `EvidencePayload`：
   - `evidence_id`: `{match_id}-{rule_id}-{hash[:8]}` 确定性生成
   - `rule_id`: 从规则反例中提取
   - `case_type`: "match"
   - `case_id`: 比赛 match_id
   - `relation`: "counterexample"（从文中判断）
   - `target_definition`: 从规则反例描述中提取 target
   - `baseline_definition`: 从规则反例描述中提取 baseline
   - `summary`: 直接引用规则反例的描述文本
   - `reviewed_by`: "system"
   - `eligibility`: "eligible"（默认）
   - `extraction_source`: "auto-extracted"（新增字段）

**新增字段**：`EvidencePayload` 增加 `extraction_source: Literal["manual", "auto-extracted"] = "manual"`，用于标记自动生成的证据，便于 lcz 审核时筛选。

**Hook 点**：修改 `services.py` 的 `review_match` 函数，在 `document.save()` 之后调用：

```python
try:
    from .evidence_pipeline import auto_extract_evidence_from_review
    auto_extract_evidence_from_review(root, path)
except Exception:
    pass  # 证据提取失败不阻断复盘
```

**去重**：用 `evidence_id` 作为唯一键，如果已存在则跳过。

### 阶段2：证据累积监控

**核心函数**：

```python
def check_evidence_thresholds(root: Path) -> dict[str, EvidenceThreshold]:
```

**阈值定义**：
- 每个规则至少 3 条 eligible evidence
- 至少 1 条 counterexample
- 所有 auto-extracted 证据必须已通过 lcz 审核

**输出**：
```python
class EvidenceThreshold(BaseModel):
    rule_id: str
    total_eligible: int
    supports: int
    counterexamples: int
    auto_extracted_pending: int  # 待 lcz 审核的自动证据
    threshold_met: bool
    blocking_reason: str | None
```

**CLI 命令**：
```bash
odds-journal pipeline check          # 查看所有规则证据状态
odds-journal pipeline check --rule-id trend-purity-v1  # 查看单个规则
```

### 阶段3：lcz 审批自动证据

**CLI 命令**：
```bash
# 列出所有待审自动证据
odds-journal evidence review-auto --list

# 批量批准
odds-journal evidence review-auto --rule-id trend-purity-v1 --action approve

# 拒绝
odds-journal evidence review-auto --evidence-id EVIDENCE_ID --action reject --reason "..."

# 修正（拒绝后重新录入）
odds-journal evidence link --rule-id ... --manual
```

**实现**：`evidence review-auto` 查找 `extraction_source == "auto-extracted"` 且未被审核的证据，更新 `reviewed_by` 字段。

### 阶段4：实验轨推进

**保持不变**：实验激活由 lcz 手动执行现有命令：
```bash
odds-journal experiment activate --version 1.7.0 --approved-by lcz
```

**新增辅助**：`pipeline propose-experiment` 生成实验激活建议：
```bash
odds-journal pipeline propose-experiment --rule-id trend-purity-v1
```
输出建议的激活参数（版本号、快照路径、证据摘要），但**不执行激活**。

### 阶段5：正式轨发布

**保持不变**：发布由 lcz 手动执行现有命令：
```bash
odds-journal release --version 1.9.0 --approved-by lcz --effective-at ...
```

**新增辅助**：`pipeline propose-release` 生成发布建议：
```bash
odds-journal pipeline propose-release --rule-id trend-purity-v1
```
输出建议的发布参数，但**不执行发布**。

## 文件修改清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/odds_journal/evidence_pipeline.py` | **新增** | 核心流水线模块（~200行） |
| `src/odds_journal/evidence.py` | **修改** | `EvidencePayload` 增加 `extraction_source` 字段 |
| `src/odds_journal/services.py` | **修改** | `review_match` 末尾 hook 调用自动提取 |
| `src/odds_journal/cli.py` | **修改** | 新增 `pipeline` 命令组 + `evidence review-auto` 命令 |

## 实施顺序

1. **步骤1**：修改 `EvidencePayload`，增加 `extraction_source` 字段
2. **步骤2**：新增 `evidence_pipeline.py`，实现 `auto_extract_evidence_from_review`（阶段1）
3. **步骤3**：修改 `services.py`，集成自动提取 hook
4. **步骤4**：实现 `check_evidence_thresholds`（阶段2）
5. **步骤5**：新增 `pipeline` CLI 命令组（阶段2-5 的 CLI）
6. **步骤6**：新增 `evidence review-auto` CLI 命令（阶段3）
7. **步骤7**：用已完成的 3 场比赛验证全流程

## 验证方案

1. 对已完成的 3 场比赛（天狼星/瓦斯特拉斯/圣克拉拉）手动触发 `auto_extract_evidence_from_review`
2. 验证生成的 `EvidencePayload` 正确提取了规则反例（trend-purity-v1, provider-consensus-divergence-v1 等）
3. 运行 `pipeline check` 查看证据状态
4. 运行 `evidence review-auto --list` 确认待审证据
5. 运行 `evidence review-auto --approve` 批准
6. 再次运行 `pipeline check` 确认阈值状态更新