# 实现真实 LLM Provider Adapter 与激活配置

## 摘要

本项目 AI 实验轨的治理层、回放层、研究生命周期已全部实现，但被 `ai_research.py:450-451` 硬编码阻断——仅允许 `fake-offline` provider。本计划实现真实 LLM provider adapter，移除硬编码约束，创建必要配置文件，并指导 lcz 激活配置和预注册 Study。

---

## 一、当前状态分析

### 1.1 硬编码阻断点

```python
# ai_research.py:450-451
def _validate_run_config(config: AIExperimentConfigSnapshotV1) -> None:
    ...
    if config.provider_id != "fake-offline":
        raise ValueError("当前实现只允许默认拒绝网络的 fake-offline provider")
```

```python
# ai_research.py:454-455
def _compile_stages(...) -> ...:
    provider = FakeProvider()  # 硬编码
```

### 1.2 现有基础设施（已就绪）

| 组件 | 位置 | 状态 |
|------|------|------|
| `LLMProvider` Protocol | `ai_governance.py:215-218` | `def run(self, *, model_id: str, payload: dict) -> dict` |
| `FakeProvider` | `ai_governance.py:221-231` | 参考实现 |
| `AIExperimentConfigSnapshotV1` | `ai_governance.py:150-178` | 完整（含 provider_id, model_id, budget, runtime_limits） |
| `OutboundDataPolicyV1` | `ai_governance.py:90-112` | 完整（含 network_access: allow/deny） |
| `BudgetV1` / `RuntimeLimitsV1` | `ai_governance.py:135-147` | 完整 |
| `activate_config` | `ai_governance.py:298-342` | 完整（内容寻址快照 + 追加台账） |
| `register_study` | `ai_research.py:328-340` | 完整 |
| `run` | `ai_research.py:476-569` | 完整（除 provider 硬编码） |
| 五阶段 Prompt 模板 | `ai/ai-experiment-prompts/v1/` | 存根（需补充实质性内容） |
| 输出 Schema | `ai/ai-experiment-schemas/outlook-v1.json` | 存根（需补充五市场定义） |
| 推理 Profile | `ai/ai-experiment-profiles/v1.yml` | 存根 |
| 出站策略 | `ai/ai-experiment-policies/fake-offline.yml` | 仅 fake-offline |
| 桌面智能体清单 | `ai/desktop-agent-manifest.yml` | 已注册 8 个受信 AI 资产 |

### 1.3 需要新增/修改的文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/odds_journal/llm_provider.py` | **新增** | 真实 LLM provider adapter |
| `src/odds_journal/ai_research.py` | **修改** | 移除硬编码，使用 provider factory |
| `ai/ai-experiment-policies/openai-gpt4o-mini.yml` | **新增** | 出站数据策略（network_access: allow） |
| `ai/ai-experiment-policies/provider-pricing.yml` | **新增** | 价格快照 |
| `ai/ai-experiment-prompts/v1/stage1-5.md` | **修改** | 补充实质性 Prompt 内容 |
| `ai/ai-experiment-schemas/outlook-v1.json` | **修改** | 补充五市场 JSON Schema |
| `ai/desktop-agent-manifest.yml` | **修改** | 注册新策略和定价快照 |
| `knowledge/ai-experiments/config-proposals/` | **新增** | AI 实验配置提案 |
| `knowledge/ai-experiments/study-proposals/` | **新增** | Study 预注册文件 |
| `tests/test_llm_provider.py` | **新增** | Provider 测试 |
| `tests/test_ai_research.py` | **修改** | 更新以适配新 provider |

---

## 二、修改详情

### 步骤 1：新增 `src/odds_journal/llm_provider.py`

**目标**：创建可扩展的 LLM Provider 实现，支持 OpenAI 兼容 API。

**关键设计决策**：
- API 凭据从环境变量 `ODDS_JOURNAL_LLM_API_KEY` 读取，绝不出现在仓库中
- 支持自定义 `base_url`（环境变量 `ODDS_JOURNAL_LLM_BASE_URL`），兼容 OpenAI / DeepSeek / 其他兼容 API
- 默认使用 `https://api.openai.com/v1`
- 默认模型使用 `gpt-4o-mini`（成本可控）
- 实现 `LLMProvider` Protocol，与 `FakeProvider` 接口一致
- 超时、重试、费用计算全部实现

**文件内容**（概要）：

```python
# src/odds_journal/llm_provider.py

import os
import hashlib
import json
import time
from typing import Any

class OpenAICompatibleProvider:
    """OpenAI-compatible API provider. API key from ODDS_JOURNAL_LLM_API_KEY env var."""
    provider_id = "openai-compatible"

    def __init__(self) -> None:
        self._api_key = os.environ.get("ODDS_JOURNAL_LLM_API_KEY")
        if not self._api_key:
            raise ValueError("缺少 ODDS_JOURNAL_LLM_API_KEY 环境变量")
        self._base_url = os.environ.get("ODDS_JOURNAL_LLM_BASE_URL", "https://api.openai.com/v1")

    def run(self, *, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        # 1. 构建请求体（system prompt + user prompt）
        # 2. HTTP POST 到 {base_url}/chat/completions
        # 3. 超时处理（默认 120s）
        # 4. 重试逻辑（默认 2 次）
        # 5. 解析响应：model_id, response, input_tokens, output_tokens
        # 6. 计算费用（基于 pricing snapshot）
        # 7. 返回标准化的 dict
        ...


# Provider 注册表
PROVIDER_REGISTRY: dict[str, type] = {
    "fake-offline": FakeProvider,
    "openai-compatible": OpenAICompatibleProvider,
}


def get_provider(provider_id: str) -> LLMProvider:
    """工厂函数：根据 provider_id 返回对应的 provider 实例"""
    cls = PROVIDER_REGISTRY.get(provider_id)
    if cls is None:
        raise ValueError(f"未知 AI provider：{provider_id}")
    return cls()
```

**关键点**：
- API 凭据只存在于环境变量，不写入仓库任何文件
- `base_url` 可配置，支持 OpenAI / DeepSeek / 其他兼容 API
- 返回格式与 `FakeProvider.run()` 一致：`{"model_id", "payload_sha256", "response", "input_tokens", "output_tokens"}`

### 步骤 2：修改 `src/odds_journal/ai_research.py`

**变更 1**：修改 `_validate_run_config`，移除硬编码的 fake-offline 限制。

```python
# 原代码（第 450-451 行）：
if config.provider_id != "fake-offline":
    raise ValueError("当前实现只允许默认拒绝网络的 fake-offline provider")

# 替换为：
from .llm_provider import PROVIDER_REGISTRY
if config.provider_id not in PROVIDER_REGISTRY:
    raise ValueError(f"未知 AI provider：{config.provider_id}")
# 如果是真实 provider，必须检查出站策略允许网络访问
if config.provider_id != "fake-offline":
    policy = _load_policy(root, config.outbound_data_policy_sha256)
    if policy.network_access != "allow":
        raise ValueError("真实 provider 需要出站策略 network_access: allow")
```

**变更 2**：修改 `_compile_stages`，使用 provider 工厂。

```python
# 原代码（第 455 行）：
provider = FakeProvider()

# 替换为：
from .llm_provider import get_provider
provider = get_provider(config.provider_id)
```

**变更 3**：修改 `run` 函数中的 `_validate_run_config` 调用，传入 `root` 以读取策略。

```python
# 原代码（第 484 行）：
_validate_run_config(config)

# 替换为：
_validate_run_config(root, config)
```

### 步骤 3：新增出站数据策略

**新增文件**：`ai/ai-experiment-policies/openai-gpt4o-mini.yml`

```yaml
schema_version: 1
provider_id: openai-compatible
network_access: allow
approved_by: lcz
approved_at: <lcz 填写审批时间>
allowed_payload_fields:
  - fixture_identity
  - market_features
  - official_receipt
  - official_evaluation
  - official_outlook
  - case_receipt
  - output_schema
  - rendered_prompt
response_storage: hash_only
```

### 步骤 4：新增价格快照

**新增文件**：`ai/ai-experiment-policies/provider-pricing.yml`

```yaml
schema_version: 1
provider_id: openai-compatible
model_id: gpt-4o-mini
input_cost_per_1k: 0.00015
output_cost_per_1k: 0.0006
currency: USD
effective_at: <lcz 填写生效时间>
pricing_sha256: "0" * 64
```

### 步骤 5：补充 Prompt 模板内容

**修改文件**：`ai/ai-experiment-prompts/v1/stage1_facts.md` 至 `stage5_risk.md`

当前 Prompt 存根只有一句话（如 `Summarize only the supplied structured market facts...`），需要补充为可用的 Prompt 模板。每个 Prompt 文件需包含：

- **stage1_facts.md**：要求 LLM 基于盘口特征数据，用中文描述 opening/mid/late 三阶段的水位、盘口档位、欧赔变化，标记异常
- **stage2_rules.md**：要求 LLM 解释规则引擎触发/未触发的原因，分析共振/冲突
- **stage3_cases.md**：要求 LLM 对比历史案例的相似点与差异，注明参考局限
- **stage4_prediction.md**：要求 LLM 输出五市场 assessed/pass 判断 + 推理链 + 置信度（使用 `{{stage_3_output}}` 等占位符支持降级分支）
- **stage5_risk.md**：要求 LLM 输出正向强化信号、风险预警、临场观测清单、失效条件

### 步骤 6：补充输出 Schema

**修改文件**：`ai/ai-experiment-schemas/outlook-v1.json`

当前存根仅 `{"type":"object","additionalProperties":false,"properties":{"markets":{"type":"object"}}}`，需要补充为完整的五市场 Schema：

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["market_statuses", "predictions"],
  "properties": {
    "market_statuses": {
      "type": "object",
      "additionalProperties": false,
      "required": ["one_x_two", "asian_handicap", "fixed_handicap_1x2", "total_goals", "score"],
      "properties": {
        "one_x_two": {"enum": ["assessed", "pass"]},
        "asian_handicap": {"enum": ["assessed", "pass"]},
        "fixed_handicap_1x2": {"enum": ["assessed", "pass"]},
        "total_goals": {"enum": ["assessed", "pass"]},
        "score": {"enum": ["assessed", "pass"]}
      }
    },
    "predictions": {
      "type": "object",
      "properties": {
        "one_x_two": {
          "type": "object",
          "properties": {
            "selection": {"enum": ["home", "draw", "away"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"}
          }
        },
        "asian_handicap": {
          "type": "object",
          "properties": {
            "selection": {"enum": ["home_handicap", "away_handicap"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"}
          }
        },
        "fixed_handicap_1x2": {
          "type": "object",
          "properties": {
            "selection": {"enum": ["home", "draw", "away"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reasoning": {"type": "string"}
          }
        },
        "total_goals": {
          "type": "object",
          "properties": {
            "minimum": {"type": "integer"},
            "maximum": {"type": "integer"},
            "reasoning": {"type": "string"}
          }
        },
        "score": {
          "type": "object",
          "properties": {
            "candidates": {
              "type": "array",
              "minItems": 2,
              "maxItems": 2,
              "items": {"type": "string"}
            },
            "reasoning": {"type": "string"}
          }
        }
      }
    }
  }
}
```

### 步骤 7：更新桌面智能体清单

**修改文件**：`ai/desktop-agent-manifest.yml`

在 `trusted_ai_assets` 末尾追加两条新资产：

```yaml
- path: ai/ai-experiment-policies/openai-gpt4o-mini.yml
  kind: outbound_policy
  content_sha256: <步骤 3 产物哈希>
- path: ai/ai-experiment-policies/provider-pricing.yml
  kind: outbound_policy
  content_sha256: <步骤 4 产物哈希>
```

同时更新 Prompt 文件和 Schema 的哈希（因为步骤 5、6 修改了内容）：

```yaml
# 更新 5 个 Prompt 的 content_sha256
# 更新 outlook-v1.json 的 content_sha256
```

### 步骤 8：创建 AI 实验配置提案

**新增文件**：`knowledge/ai-experiments/config-proposals/openai-pilot-v1.yml`

```yaml
config_id: openai-pilot-v1
research_track: pilot
provider_id: openai-compatible
model_id: gpt-4o-mini
llm_parameters:
  temperature: 0.0
  max_tokens: 4096
prompt_manifest:
  - stage: facts
    path: ai/ai-experiment-prompts/v1/stage1_facts.md
    sha256: <更新后哈希>
  - stage: rules
    path: ai/ai-experiment-prompts/v1/stage2_rules.md
    sha256: <更新后哈希>
  - stage: cases
    path: ai/ai-experiment-prompts/v1/stage3_cases.md
    sha256: <更新后哈希>
  - stage: prediction
    path: ai/ai-experiment-prompts/v1/stage4_prediction.md
    sha256: <更新后哈希>
  - stage: risk
    path: ai/ai-experiment-prompts/v1/stage5_risk.md
    sha256: <更新后哈希>
case_profile: exploratory_research
reasoning_profile_id: research-v1
reasoning_profile_sha256: <更新后哈希>
output_schema_sha256: <更新后哈希>
evaluation_algorithm_version: v1
outbound_data_policy_sha256: <步骤 3 产物哈希>
provider_pricing_snapshot_sha256: <步骤 4 产物哈希>
budget:
  max_total_tokens: 16000
  max_total_cost: 0.50
  currency: USD
runtime_limits:
  stage_timeout_seconds: 120
  max_retries_per_stage: 2
```

### 步骤 9：创建 Study 预注册文件

**新增文件**：`knowledge/ai-experiments/study-proposals/study-pilot-001.yml`

```yaml
schema_version: 1
study_id: study-pilot-001
config_snapshot_sha256: <步骤 8 激活后的 snapshot_sha256>
registered_by: lcz
registered_at: <lcz 填写登记时间>
sample_relation: out_of_sample
required_capability_profile: []
eligible_match_ids: []
official_baseline_schema_sha256: <AnalysisOutlook schema 哈希>
stopping_conditions:
  - "累计 30 场 primary 或 3 个月"
  - "任一市场 AI 准确率 > 规则 + 10% 时进入第二阶段"
status: registered
study_sha256: "0" * 64
```

### 步骤 10：lcz 手动执行步骤

以下步骤需要 lcz 在终端中执行，AI 无法代劳：

**10.1 设置 API 凭据**：
```powershell
$env:ODDS_JOURNAL_LLM_API_KEY = "sk-..."
$env:ODDS_JOURNAL_LLM_BASE_URL = "https://api.openai.com/v1"  # 或其他兼容 API
```

**10.2 验证配置**：
```powershell
odds-journal ai experiment config validate knowledge/ai-experiments/config-proposals/openai-pilot-v1.yml
```

**10.3 激活配置**：
```powershell
odds-journal ai experiment config activate knowledge/ai-experiments/config-proposals/openai-pilot-v1.yml --approved-by lcz --confirm-ai-experiment
```

**10.4 登记 Study**（在首场赛果可见前）：
```powershell
# 先更新 study-proposals/study-pilot-001.yml 中的 config_snapshot_sha256 为实际激活后的值
odds-journal ai experiment study register --file knowledge/ai-experiments/study-proposals/study-pilot-001.yml
```

**10.5 运行 AI sandbox 验证**：
```powershell
odds-journal ai sandbox run --config knowledge/ai-experiments/config-proposals/openai-pilot-v1.yml --fixture tests/fixtures/ai/SYNTHETIC.yml
```

**10.6 在日常比赛上运行 AI 实验**：
```powershell
# diagnostic 模式（不占用 Study）
odds-journal ai experiment run matches/2026/08/比赛.md --role diagnostic --nonce my-test-01

# primary 模式（占用 Study，需正式锁定后）
odds-journal ai experiment run matches/2026/08/比赛.md --role primary --study study-pilot-001
```

### 步骤 11：更新测试

**修改文件**：`tests/test_ai_research.py`

- 保持现有测试不变（仍使用 `fake-offline`）
- 新增 `test_real_provider_rejected_without_network_policy` 测试
- 新增 `test_openai_compatible_provider_mock` 测试（使用 mock HTTP 响应）

**新增文件**：`tests/test_llm_provider.py`

- `test_openai_compatible_provider_requires_api_key` — 缺少 API key 时抛错
- `test_openai_compatible_provider_builds_request` — 请求体构建正确
- `test_openai_compatible_provider_handles_timeout` — 超时重试
- `test_openai_compatible_provider_handles_rate_limit` — 速率限制处理
- `test_provider_registry` — 注册表正确

---

## 三、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Provider 实现方式 | 独立的 `llm_provider.py` 模块 + 注册表 | 与 `ai_governance.py` 解耦，Provider 可插拔 |
| API 凭据管理 | 环境变量 `ODDS_JOURNAL_LLM_API_KEY` | 不写入仓库，符合安全要求 |
| 支持的 API | OpenAI 兼容 API（可配置 base_url） | 兼容 OpenAI / DeepSeek / 其他兼容 API |
| 默认模型 | `gpt-4o-mini` | 成本可控（$0.15/1M input tokens） |
| Prompt 策略 | 先在 `v1/` 中补充实质性内容，后续可创建 `v2/` | 配合 Prompt 版本化机制 |
| 出站策略 | 新增 `openai-gpt4o-mini.yml`，`network_access: allow` | 需 lcz 审批 |
| 响应存储 | `hash_only`（仅保存哈希，不保存原始响应） | 控制仓库体积，符合出站策略 |
| 测试策略 | 真实 provider 测试用 mock，FakeProvider 测试不变 | 不依赖外部 API 运行 CI |

---

## 四、验证步骤

```powershell
# 1. 代码检查
.\.venv\Scripts\python.exe -m pytest tests/test_llm_provider.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_ai_research.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_ai_governance.py -q

# 2. Schema 校验
.\scripts\odds-journal.ps1 schemas check

# 3. 配置校验
odds-journal ai experiment config validate knowledge/ai-experiments/config-proposals/openai-pilot-v1.yml

# 4. Sandbox 验证（使用 FakeProvider，确保不调用真实 API）
odds-journal ai sandbox run --config knowledge/ai-experiments/config-proposals/openai-pilot-v1.yml --fixture tests/fixtures/ai/SYNTHETIC.yml

# 5. 激活后验证（lcz 执行）
odds-journal ai experiment config status
odds-journal ai experiment run matches/PATH --role diagnostic --nonce verify-01

# 6. 完整回归
.\.venv\Scripts\python.exe -m pytest -q
```

---

## 五、风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| `openai-compatible` provider 在 `sandbox_run` 中被调用 | `sandbox_run` 已有 `provider_id != "fake-offline"` 检查，独保持 fake-only |
| 真实 API 调用产生费用 | 预算门禁（`max_total_cost: 0.50`）+ 价格快照验证 |
| API 凭据泄漏 | 环境变量注入，不写入仓库；`.gitignore` 已排除 `.env` |
| Prompt 内容质量不足导致 AI 输出无效 | 先用 sandbox 迭代 Prompt，再进入 pilot 轨道 |
| 五阶段 Prompt 修改后哈希变化，需重新激活配置 | 配置快照内容寻址，变更需新增配置版本和激活事件 |