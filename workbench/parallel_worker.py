"""Worker-side hooks for the local parallel workbench run only."""
from pathlib import Path
import pytest


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    settings = getattr(config, "workerinput", {}).get("workbench")
    if settings is None:
        return
    config._workbench_storage_state = settings.pop("auth")
    config._workbench_capture_screenshots = False
    config._workbench_trace_snapshots = False
    config.option.headed = False
    # Route fixture failure evidence to this run. The UI standalone board is off.
    config._run_board_ctx = {"enabled": False, "batch_dir": Path(settings["out"]) / "evidence"}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_finish(session):
    settings = getattr(session.config, "workerinput", {}).get("workbench")
    if settings is None:
        return
    actual = [item.nodeid for item in session.items]
    if len(actual) != len(settings["targets"]) or set(actual) != set(settings["targets"]):
        raise pytest.UsageError("实际收集身份与套件快照不同，禁止执行")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    info = getattr(item.config, "workerinput", {})
    if "workbench" in info:
        from workbench.ui_run_bridge import wait_for_resume
        folder = Path(info["workbench"]["out"])
        wait_for_resume(folder, info["workerid"])
        if (folder / "auth-stop.flag").exists():
            pytest.exit("登录态失效，停止后续执行", returncode=2)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    result = yield
    report = result.get_result()
    settings = getattr(item.config, "workerinput", {}).get("workbench")
    if settings and report.failed and any(mark in str(report.longrepr).lower() for mark in
            ("停在登录", "storage_state 无效", "login.welink.huaweicloud.com", "缺少登录态")):
        (Path(settings["out"]) / "auth-stop.flag").touch()
