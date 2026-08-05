# 四端认证记录

认证必须逐产品、逐版本执行 `scenarios.yml` 当前 workflow 声明的全部场景。workflow 1.11.0 为十一项；历史 workflow 结果继续可解析。`passed` 要求对应 suite 的场景唯一且全部通过；telosWork 还要求先在产品界面导入 `.skill` 包，运行 `agent configure --product teloswork --confirm-import --imported-version VERSION`，并在结果中设置 `telos_import_confirmed: true`。

`agent sync` 在 `workflow_breaking` 时自动运行 Codex Desktop 的十一项仓库认证并提交受限生成物。自动结果明确标记 `certification_method: automated`，并绑定不可变运行报告及哈希；TRAE Work、WorkBuddy、telosWork 仍使用人工结果。可单独诊断或重试 Codex 自动认证：

```powershell
.\scripts\odds-journal.ps1 agent certify auto --product codex-desktop
.\scripts\odds-journal.ps1 agent certify status --product codex-desktop
```

1. 运行 `agent changes --json` 获取工作流版本、Git 提交和全部哈希。
2. 从 `result-template.yml` 建立本次结果文件，填写真实测试时间和观察说明。
3. 运行 `agent certify record --file RESULT.yml`。命令会验证结果与当前仓库绑定，并写入不可覆盖的版本路径。
4. 运行 `agent certify status` 查看当前四端状态。

认证结果路径：

```text
integrations/certification/results/{product_id}/{platform}-{product_version}-{workflow_version}[-manifesthash-runid].yml
```

产品版本变化只使该产品结果过期。工作流、manifest、Skill、治理或可信指令变化使相关四端结果过期。数据与兼容规则集更新仍保留认证，但必须按 `agent changes` 的动作重建索引和校验规则。
