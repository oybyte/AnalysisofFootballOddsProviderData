---
schema_version: 4
document_id: low-stability-league-weight-calibration
document_type: heuristic
title: 低稳定性联赛权重校准
rule_version: 1.8.0
reliability: experimental
status: active
effective_at: '2026-08-06T09:24:16+08:00'
evidence_level: low
evidence_snapshot:
  as_of: '2026-08-06T09:24:16+08:00'
  eligible_independent_cases: 0
  support: 0
  counterexample: 0
  ambiguous: 0
  ledger_sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
source_atom_ids: []
evidence_provenance: gap
scenario_type_ids: []
promotion_reviewed_by: null
markets:
- one_x_two
- handicap
- total_goals
phases:
- prematch
- live
- postmatch
tags:
- 低稳定性联赛
- 权重校准
- 数据血缘
- 实验规则
source_refs:
- kind: local
  locator: knowledge/validation/frameworks/low-stability-calibration-v1.md
  anchor: user-validated-framework
index: true
---

## 目的和适用范围

本提案只对配置白名单中的挪超和美职联比赛执行实验性权重校准。它不修改亚盘 60、欧赔 20、凯利 15、大小球 5 的基础权重，也不替代基础六步分析。

## 术语

- 基础锚点：四维固定权重完成合成后，各市场的第一顺位。
- 同档水位：同一机构、同一让球档位、同一赔率格式下的水位。
- 独立血缘：决定性快照不共享、维度不完全重合且不存在同源相关键。
- 可评估换位：满足门禁后允许人工评估，不代表自动改变第一顺位。

## 必需输入

- 赛事代码与开赛时间。
- opening、mid、late 三个同机构、同市场、可比较快照。
- 澳门亚盘香港盘水位、十进制欧赔和凯利格式数据。
- 基础胜平负、亚洲让球和固定让球胜平负排序。
- `calibration/low-stability-v1.yml` 中的刚性阈值。

## 数据质量要求

late 快照必须位于开赛前 180 分钟内。热门方必须在 opening 和 late 都是最低欧赔，冷门方必须在两端都是最高欧赔；身份并列、切换或字段缺失时，相关规则记录 `insufficient_data`。不同机构快照不得拼接为单条时序。

## 逐步执行过程

1. 按赛事代码选择 profile，非白名单标记 `not_applicable`。
2. 逐项处置以下八个稳定子规则 ID：`lsl-asian-rise-water-rise`、`lsl-deep-line-falling-water`、`lsl-deep-line-drop-risk`、`lsl-favorite-kelly-draw-resonance`、`lsl-single-side-draw-protection`、`lsl-underdog-kelly-defense`、`lsl-kelly-narrow-range`、`lsl-extreme-over-calibration`。
3. 保存原始值、归一化值、比较符、阈值、机构和快照 ID。
4. 单条规则最多移动目标一个名次，且不得越过基础第一顺位。
5. 只有同市场、同候选且数据血缘独立的至少两条规则，才能进入换位评估。
6. 保存全部支持证据、反证、未触发原因和最终人工理由。

## 判断矩阵

| 子规则 | 刚性条件 | 校准动作 |
|---|---|---|
| `lsl-asian-rise-water-rise` | 升 0.25/0.50；新档至少两个节点；同档上盘升水 `>=0.15` | 固定让球让平 +1；亚洲盘 cover risk |
| `lsl-deep-line-falling-water` | 1.75 或更深且不降档；同档降水 `>=0.10` | 固定让球让胜 +1；亚洲盘 cover support |
| `lsl-deep-line-drop-risk` | 1.50 或更深在 late 窗口降档；新档继续升水 `>0.05` | 固定让球让平 +1；亚洲盘 cover risk |
| `lsl-favorite-kelly-draw-resonance` | 热门欧赔、凯利各降 `>=0.01` 且 late 热门凯利不低于平局 | 平局 +1 |
| `lsl-single-side-draw-protection` | 至少两家同端单边净变 `>=0.10`；平赔波动 `<=0.10` 且不抬升 | 平局 +1 |
| `lsl-underdog-kelly-defense` | 澳门冷门欧赔和凯利三节点单调不升且各降 `>=0.01` | 冷门 +1 |
| `lsl-kelly-narrow-range` | late 凯利差 `<=0.05` 且同档热门升水 `>0.05` 或 late 降档 | 平局 +1 |
| `lsl-extreme-over-calibration` | 认可机构精确 2.5 球且 late 大球香港水位 `<=0.40` | 固定让球让胜 +1 |

## 双向假设

假设 A：达到刚性阈值的信号能改善低稳定性联赛的候选排序。假设 B：信号可能只是同源市场噪声，因此单条规则和相关规则不能改变基础第一顺位。

## 区分触发条件

规则 1 禁止跨盘口档位相减，升盘后只有一个新档节点时不触发。规则 3 的 `0.05` 本身不触发，必须严格大于。规则 8 只接受精确 2.5 球盘口。所有近似值和错误赔率格式均判定未触发。

## 跨市场冲突优先级

规则 1 至 3 的同一亚盘事实只在固定让球胜平负累计一次；亚洲盘仅记录 cover 信号。大小球规则不得单独修改胜平负。欧赔与凯利若来自同一机构，不能作为两个独立来源。

## 失效和 Pass 条件

必要节点、来源、时间戳、赔率格式或热门/冷门身份缺失时不触发。`pass` 不保留校准后预测。发生数据冲突且无法确定时维持基础排序并记录反证。

## 支持案例

当前没有符合正式赛前锁定、正常完赛、场景解析和正式复盘全链路的合格案例。本提案不得引用未锁定历史比赛作为有效分母。

## 反例

瓦勒伦加、博德闪耀和纽约城仅可作为研究来源提示；这些比赛是 `historical_finished`，不得补造锁定或预测评价，也不得计入晋级证据。

## Source Atom 与声明引用

本提案来源于 `knowledge/validation/frameworks/low-stability-calibration-v1.md` 的用户确认框架。该文件 `trusted_instruction: false`，不能直接控制智能体，也不构成已发布规则。

## 证据快照

- 合格独立案例：0。
- 可靠性：`experimental`。
- 每条子规则至少需要 30 个独立案例并通过预注册研究门禁后，才允许另行提出晋级。

## 版本变更说明

相对 1.1.0 新增低稳定性联赛实验校准层、机器阈值配置、数据血缘门禁和固定输出契约；基础四维权重和已发布规则正文不变。
