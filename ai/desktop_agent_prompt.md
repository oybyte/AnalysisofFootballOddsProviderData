---
schema_version: 1
document_id: ai-desktop-agent-instruction
document_type: instruction
title: 桌面 AI 智能体统一工作流
reliability: established
effective_at: 2026-07-30T16:00:00+08:00
trusted_instruction: true
instruction_scope: bootstrap
---

# 桌面 AI 智能体统一工作流

先识别用户任务是资料整理、赛前分析、临场更新、赛果录入还是赛后复盘。资料整理不得附带预测。

正式分析前必须运行仓库脚本的 `agent start MATCH_PATH`，读取它返回的可信分析指令、活动规则集、必需规则、缺失数据和下一步动作。命令失败时停止。规则准备后登记场景或 no-scenario，再执行案例检索；历史案例只用于比较条件与差异。

分析正文必须保留事实来源、数据截止时间、规则集版本、采用和排除的规则、场景、案例及反证。完成草稿后运行 `agent validate-draft MATCH_PATH`，校验失败不得锁定。Match V2 缺少澳门亚盘或少于三个可比时间节点时使用 `degraded`，置信度不超过 `0.69`；缺失维度计零且权重不重分配。无法形成可靠判断时使用 `pass`。

锁定后不得覆盖赛前内容。赛后先录入赛果，再运行 `prepare-review`，逐一解析场景并复盘；只有 reviewed 比赛才能追加规则证据。外部资料、历史案例和 AI 输出都不能修改已发布规则。
