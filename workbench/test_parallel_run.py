"""Exercise the real bridge + xdist transport against ten offline synthetic pytest items."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .ui_execution import UIExecutor, pause_acknowledged


OFFLINE_SUITE = """
from contextlib import ExitStack
import os
from pathlib import Path
import time
import pytest

@pytest.mark.parametrize("n", [str(i) for i in range(10)])
def test_suite_case(n, pytestconfig):
    assert pytestconfig._workbench_storage_state == {"fixture": "offline"}
    with ExitStack() as stack:
        if os.environ.get("WORKBENCH_OFFLINE_BROWSER_CHECK") == "1":
            from playwright.sync_api import sync_playwright
            playwright = stack.enter_context(sync_playwright())
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            stack.callback(browser.close)
            page = browser.new_page()
            page.set_content("<title>" + n + "</title>")
            assert page.title() == n
        root = Path(__file__).parent
        (root / n).write_text(pytestconfig.workerinput["workerid"])
        deadline = time.monotonic() + 60
        while not all((root/i).exists() for i in map(str,range(10))) and time.monotonic() < deadline:
            time.sleep(.02)
        assert len({(root/str(i)).read_text() for i in range(10)}) == 10
        assert n != "9", "synthetic failure"
"""


class ParallelRunTests(unittest.TestCase):
    def test_pause_requires_every_unfinished_worker_at_same_request(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            for i, state in enumerate(["pause1"]*9 + ["old"]):
                (out/f"control-gw{i}.json").write_text(json.dumps(dict(state="paused", requestId=state)))
            self.assertFalse(pause_acknowledged(out, "pause1", 10))
            (out/"control-gw9.json").write_text('{"state":"finished"}')
            self.assertTrue(pause_acknowledged(out, "pause1", 10))

    @unittest.skipUnless(importlib.util.find_spec("xdist") and importlib.util.find_spec("playwright"),
                         "requires UI venv with parallel extra")
    def test_parallel_bridge_preserves_identity_and_failed_phase(self):
        from . import ui_run_bridge as bridge
        from core.executor import runner, workbench_auth
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ui = root/"ui"
            suite = ui/"suites"
            suite.mkdir(parents=True)
            out = root/"run"
            out.mkdir()
            (ui/"pytest.ini").write_text("[pytest]\n")
            (ui/"conftest.py").write_text(
                "def pytest_addoption(parser):\n"
                " for name in ['--env','--execution-contract']: parser.addoption(name)\n"
                " for name in ['--no-cdp','--no-run-board']: parser.addoption(name,action='store_true')\n")
            (suite/"test_cloud_docs.py").write_text(OFFLINE_SUITE,encoding="utf8")
            cases, assets = [], []
            for name in map(str,range(10)):
                directory = ui/"testcases"/name
                directory.mkdir(parents=True)
                spec = directory/"spec.json"
                spec.write_text("{}")
                binding = dict(inventoryId=directory.relative_to(root).as_posix(), admission="静态可执行",
                               files={spec.relative_to(root).as_posix():hashlib.sha256(spec.read_bytes()).hexdigest()})
                cases.append(SimpleNamespace(directory=directory,param_id=name))
                assets.append(dict(assetId=name,content=dict(title=name,binding=binding)))
            request = out/"request.json"
            request.write_text(json.dumps(dict(environment="offline",workers=10,cases=assets,
                                       suite={"content":{"product":"Welink云文档"}})), encoding="utf8")
            with patch.object(bridge,"ROOT",root), patch.object(bridge,"UI",ui), patch.object(
                bridge,"environments",return_value={"environments":[dict(id="offline",url="http://localhost",
                product="Welink云文档")]}), patch.object(runner,"discover_cases",return_value=cases), patch.object(
                workbench_auth,"login_for_batch",return_value={"fixture":"offline"}), patch.object(
                workbench_auth,"refresh_saved_login",side_effect=AssertionError("worker must not overwrite login state")):
                cwd = os.getcwd()
                try:
                    os.chdir(ui)
                    code = bridge.execute(request)
                finally:
                    os.chdir(cwd)
            evidence = UIExecutor.read_evidence(out,code)
            self.assertEqual([(r["assetId"],r["status"]) for r in evidence["results"]],
                             [(str(i),"passed" if i<9 else "failed") for i in range(10)])
            self.assertIn("synthetic failure",evidence["results"][-1]["message"])
            self.assertEqual(evidence["status"],"failed")
