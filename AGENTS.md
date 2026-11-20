# 健康管理测试工作台开发交接

从仓库根目录工作。新机安装、启动和本地数据转移步骤见 [README.md](README.md)。参考项目 clouddoc-autotest 的迁移已完成，本仓自包含；换电脑后可直接克隆 main。接手时先查看 git status 和最近提交，确认当前工作基线。

## 当前产品范围

工作台运行在 127.0.0.1:8878。测试人员创建任务，导入规格并审阅需求、方案和用例；确认的用例可手工执行或关联测试脚本。自动化资产纳入套件后按固定版本执行，报告记录逐条结果并支持重跑。

用户决定暂时留空产品地址、登录资料和接口契约。当前产品资产仅有健康检查接口和首页冒烟；合成记录闭环用于验证测试基础设施。真实业务流程和准入条件见 [接入与验收](docs/acceptance.md)。脚本生成仍为演示，模型分析依赖本机 CLI 登录，健康管理执行器支持串行、取消和重跑。后续有真实规格时，先确认一个业务流程、预期结果、合成数据和清理方式，再扩展产品资产。

## 修改入口

| 工作内容 | 源码和验证入口 |
| --- | --- |
| 启动、HTTP 接口、工作台网页 | workbench/server.py 加载 docs/test-workbench/demo/；这个目录是正在使用的前端。 |
| 任务、AI 设计和审阅 | workbench/workspace.py、jobs.py、contracts.py、providers.py 和 experts/。手工批次与报告在 workbench/execution.py。 |
| 产品资产 | api/testcases/health/ 与 ui/testcases/home/ 提供 case_spec.json 和 test_main.py 示例。workbench/ui_inventory.py 扫描两个工程；脚本准入、绑定、套件和版本管理在 automation.py。 |
| 自动化执行 | server.py 注入 HealthExecutor；改健康管理执行逻辑从 workbench/health_execution.py 开始。ui_execution.py 提供共享结果归并及迁移保留的 UI 实现。 |
| 环境、CLI 与 CI | config.example.json、scripts/bootstrap.py、scripts/run.py 和 .github/workflows/verify.yml。API 与 UI 使用各自的 .venv，工作台回归需要两个环境。 |

## 已修复的回归及验证

- 批量执行在启动前检查绑定，运行前再次核对脚本。每条结束后写入结果；已完成、阻断和未执行项在批次中断后分别保留。用 workbench/test_health_execution.py 验证执行、恢复、版本漂移和异常分类。
- 无效规格或空脚本只影响对应资产。workbench/test_assets.py 验证扫描结果；API 用例沿用同一套资产、套件、报告机制。
- ui/tests/framework/test_record_flow.py 使用本机临时 HTTP 服务验证 API 创建、UI 修改、API 回读及清理。CI 的三个作业独立运行，各自输出 outputs/<suite>/verify.xml。
- 修改前端流程时，从正常页面入口检查相应操作；后台单测覆盖不到浏览器交互。可在临时工作目录调用 make_server(0, folder) 启动隔离实例。

开发完成后按 README 的三条检查命令验证依赖、API/UI 框架和工作台。产品冒烟需要填写 config.local.json，再显式运行 python scripts/run.py product。真实业务验收状态随产品契约更新到 docs/acceptance.md。本机任务、令牌、产品配置和报告均由 .gitignore 排除。
