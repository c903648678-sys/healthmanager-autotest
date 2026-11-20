# 共享测试专家

本目录是工作台、API/UI/端侧流程共享的专家入口，与模型供应商解耦。

- `requirements-analyst/`：需求理解、风险和疑问分析，输出候选 JSON，不执行测试或写正式资产。
- `test-planner/`：从已确认需求基线生成测试方案与覆盖安排，保留人工结论和未决问题；不生成详细用例或执行脚本。
各专家的 manifest 引用本仓的 prompt 和方法片段。更新规则时同时核对 manifest 中的路径和章节边界。

专家定义职责和方法；`workbench/providers.py` 负责 Codex / Claude 调用。换模型不换业务规则。

- `test-case-designer`：基于已确认测试方案生成结构化用例，用于工作台思维导图审阅。
