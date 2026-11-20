# 健康管理云服务自动化测试

本项目包含健康管理云服务的本地测试工作台、API 和 UI 两个独立的 Python 测试工程。开发交接从 [AGENTS.md](AGENTS.md) 开始。

## 在新电脑继续开发

以下命令适用于安装了 Git 和 Python 3.12 的 Windows PowerShell。首次安装需要下载 Python 依赖和 Chromium。

```powershell
git clone https://github.com/c903648678-sys/healthmanager-autotest.git
cd healthmanager-autotest
$env:PYTHONUTF8 = "1"
python scripts/bootstrap.py
python scripts/run.py doctor
python scripts/run.py verify
.\ui\.venv\Scripts\python.exe -m pytest workbench -q --junitxml=outputs/workbench/verify.xml
python -m workbench.server --open
```

旧电脑上的工作台任务、运行历史和资料保存在本地。如果要接续这些数据，请在两台电脑都停止工作台且无执行任务时，将旧仓的 `.local/workbench` 私下复制到新克隆的同名空目录，再启动服务。若目标已有数据，请先备份。虚拟环境在新电脑重新安装；产品配置按下文填写，使用 AI 分析时在新电脑自行登录所选 CLI。

## 测试工作台

双击 `start-workbench.cmd`，或运行 `python -m workbench.server --open`。访问 http://127.0.0.1:8878/，与原工作台的 8877 端口隔离。

工作台提供：任务生命周期、规格导入、需求分析与审阅、测试方案、用例思维导图审阅、知识库、资产版本、套件与执行计划、手工结果、缺陷、测试报告和备份。数据保存在本仓库 `.local/workbench`。

自动化页刷新脚本目录后，可纳入健康管理首页冒烟资产，建立 UI 套件并执行；执行器真实调用本项目 UI pytest，核对脚本版本并将结果归入工作台报告。当前配置为空，运行前会阻断。API 健康检查同样支持扫描、绑定和套件执行。

AI 分析使用本机已登录的 Codex/Claude CLI，候选需人工确认；本次迁移未调用真实模型服务。正式用例库的「设计并生成脚本」按表单生成 API/UI pytest 代码，预览后发布为用例新版本。健康管理执行器当前支持串行、有界超时、取消和重跑，暂不支持暂停、并行和登录态管理。产品端到端业务流程仍需真实规格与环境。

详细迁移说明见 [工作台迁移](docs/workbench-migration.md)。

## 从用例设计到运行报告

1. 创建任务、导入规格并确认需求、方案和用例，或在测试资产中纳入已有的冒烟用例。
2. 在正式用例库选择 API 或 UI 用例，点击「设计并生成脚本」。API 填写相对路径、HTTP 方法、JSON 请求和预期状态码，可断言 JSON 对象字段。UI 填写页面路径，按 test ID 设置点击或填写步骤，断言目标文本或页面标题。输入使用合成数据；表单和源码会保存在本机。
3. 查看生成的 Python 源码，可返回修改。确认发布后，脚本和规格写入对应工程的 testcases/_generated/，用例获得绑定此脚本的新版本。旧套件保留原版本；需要执行新版时更新套件。
4. 在「自动化执行」选择该版本建立套件，选择测试环境并运行，在「测试报告」查看结果。首次在「自动化执行 → 环境」点击「配置测试环境」，也可以按下文编辑本地配置。迁移已生成脚本时，同时携带对应的 _generated 目录与工作台数据。

## 验证范围

`verify` 运行 API/UI 框架测试，包括本机 HTTP 服务上的合成记录创建、浏览器修改、API 回读和清理。工作台回归通过上面的 pytest 命令单独执行。GitHub Actions 在 Windows 上分 API、UI、工作台三组运行，各自生成 JUnit 报告。

## 接入产品

```powershell
Copy-Item config.example.json config.local.json
# 填写真实测试环境、已确认健康检查路径和页面标题
python scripts/run.py product
# 或单独执行
python scripts/run.py product --project api
```

模板中的产品地址、路径和标题留空，product 会预检失败并返回非零，不会将未接入记为通过。可选 Bearer 凭据通过环境变量 `HM_API_TOKEN` 注入；其他认证机制须在确认实际契约后实现。不要把密码、token、真实健康数据写入仓库。健康检查仅验证明确配置的端点返回 200，页面用例仅验证首页响应与标题，均不代表完整业务验收。

## 分层与扩展

- `api/src/healthmanager_api/`：HTTP 客户端，无隐式重试，保留状态供用例判断。
- `api/testcases/`、`ui/testcases/`：产品用例，显式执行。
- `api/tests/framework/`、`ui/tests/framework/`：默认离线门禁。
- `config.example.json`：可提交配置模板；`config.local.json`：忽略的本机配置。
- `docs/acceptance.md`：业务接入清单与验收标准。

业务 UI 接入后按页面封装稳定的 role/test-id 定位器；API 按真实 OpenAPI 契约编写断言。需要写操作时为每次执行生成唯一合成数据，并登记逆序清理，清理失败必须让测试失败。当前不自动采集截图、trace 或响应正文，以免报告携带健康信息；如需启用，只使用合成数据并设置访问与保留策略。
