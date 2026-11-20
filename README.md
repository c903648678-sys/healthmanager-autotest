# 健康管理云服务自动化测试

参考 `D:/GitHub/clouddoc-autotest` 的 API/UI 独立 Python 工程、环境与凭据分离、离线门禁、JUnit 报告设计。已迁移参考项目的本地测试工作台及通用设计模板，不复制原工作台任务、账号和认证文件。

## 测试工作台

双击 `start-workbench.cmd`，或运行 `python -m workbench.server --open`。访问 http://127.0.0.1:8878/，与原工作台的 8877 端口隔离。

工作台提供：任务生命周期、规格导入、需求分析与审阅、测试方案、用例思维导图审阅、知识库、资产版本、套件与执行计划、手工结果、缺陷、测试报告和备份。数据保存在本仓库 `.local/workbench`。

自动化页刷新脚本目录后，可纳入健康管理首页冒烟资产，建立 UI 套件并执行；执行器真实调用本项目 UI pytest，核对脚本版本并将结果归入工作台报告。当前配置为空，运行前会阻断。API 暂时通过下方命令入口执行，尚未接入工作台资产执行。

AI 分析使用本机已登录的 Codex/Claude CLI，候选需人工确认；本次迁移未调用真实模型服务。自动生成脚本仍是原项目的演示能力。健康管理执行器当前支持串行、有界超时、取消和重跑，暂不支持暂停、并行和登录态管理。产品端到端业务流程仍需真实规格与环境。

详细迁移说明见 [工作台迁移](docs/workbench-migration.md)。

## 安装与验证

Python 3.11+，推荐 3.12。在仓库根目录运行：

```powershell
python scripts/bootstrap.py
python scripts/run.py doctor
python scripts/run.py verify
```

安装分别创建 `api/.venv` 和 `ui/.venv`，下载 Chromium。支持 pip 标准镜像配置。IDE 可分别打开 api 或 ui 并选择对应解释器。verify 只测试框架；UI 使用本地 HTML，不访问产品。报告输出到 `outputs/api/verify.xml` 和 `outputs/ui/verify.xml`。CI 执行同样的门禁。

## 接入产品

```powershell
Copy-Item config.example.json config.local.json
# 填写真实测试环境、已确认健康检查路径和页面标题
python scripts/run.py product
# 或单独执行
python scripts/run.py product --project api
```

当前配置全部留空，product 会预检失败并返回非零，不会将未接入记为通过。可选 Bearer 凭据通过环境变量 `HM_API_TOKEN` 注入；其他认证机制须在确认实际契约后实现。不要把密码、token、真实健康数据写入仓库。健康检查仅验证明确配置的端点返回 200，页面用例仅验证首页响应与标题，均不代表完整业务验收。

## 分层与扩展

- `api/src/healthmanager_api/`：HTTP 客户端，无隐式重试，保留状态供用例判断。
- `api/testcases/`、`ui/testcases/`：产品用例，显式执行。
- `api/tests/framework/`、`ui/tests/framework/`：默认离线门禁。
- `config.example.json`：可提交配置模板；`config.local.json`：忽略的本机配置。
- `docs/acceptance.md`：业务接入清单与验收标准。

业务 UI 接入后按页面封装稳定的 role/test-id 定位器；API 按真实 OpenAPI 契约编写断言。需要写操作时为每次执行生成唯一合成数据，并登记逆序清理，清理失败必须让测试失败。当前不自动采集截图、trace 或响应正文，以免报告携带健康信息；如需启用，只使用合成数据并设置访问与保留策略。
