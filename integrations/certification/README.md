# 四端认证记录

认证必须逐产品、逐版本执行 `scenarios.yml` 当前 workflow 声明的全部场景。workflow 1.11.0 为十一项，新增赛前锁定就绪检查和缺候选禁止补建验证；历史 workflow 1.1.0 的五项结果、1.2.0 至 1.5.0 的六项结果、1.6.0 的七项结果、1.7.0/1.8.0 的八项结果、1.9.0 的九项结果和 1.10.0 的十项结果继续可解析。`passed` 要求对应 suite 的场景唯一且全部通过；telosWork 还要求先在产品界面导入 `.skill` 包，运行 `agent configure --product teloswork --confirm-import --imported-version VERSION`，并在结果中设置 `telos_import_confirmed: true`。

1. 运行 `agent changes --json` 获取工作流版本、Git 提交和全部哈希。
2. 从 `result-template.yml` 建立本次结果文件，填写真实测试时间和观察说明。
3. 运行 `agent certify record --file RESULT.yml`。命令会验证结果与当前仓库绑定，并写入不可覆盖的版本路径。
4. 运行 `agent certify status` 查看当前四端状态。

认证结果路径：

```text
integrations/certification/results/{product_id}/{platform}-{product_version}-{workflow_version}.yml
```

产品版本变化只使该产品结果过期。工作流、manifest、Skill、治理或可信指令变化使相关四端结果过期。数据与兼容规则集更新仍保留认证，但必须按 `agent changes` 的动作重建索引和校验规则。
