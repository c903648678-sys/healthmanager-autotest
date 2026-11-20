import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from .health_execution import HealthExecutor
from .contracts import ROOT

class HealthExecutionTests(unittest.TestCase):
    def test_real_pytest_browser_and_script_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'ui/testcases/local';folder.mkdir(parents=True)
            script=folder/'test_main.py'
            script.write_bytes((ROOT/'ui/tests/framework/test_browser.py').read_bytes())
            executor=HealthExecutor(root);executor.python=ROOT/'ui/.venv'/('Scripts/python.exe' if __import__('os').name=='nt' else 'bin/python')
            snapshot={'environment':'local','cases':[{'assetId':'a','content':{'title':'合成浏览器验证','binding':{'files':{'ui/testcases/local/test_main.py':hashlib.sha256(script.read_bytes()).hexdigest()}}}}]}
            with patch('workbench.health_execution.validate'),patch.object(executor,'environments',return_value={'environments':[{'id':'local'}]}):
                result=executor.execute(snapshot,root/'run',threading.Event(),lambda _:None)
                self.assertEqual(result['status'],'passed')
                self.assertEqual(result['results'][0]['status'],'passed')
                script.write_text('def test_changed(): pass')
                with self.assertRaisesRegex(ValueError,'版本'):
                    executor.execute(snapshot,root/'changed',threading.Event(),lambda _:None)

    def test_unconfigured_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(HealthExecutor(tmp).environments()['environments'],[])
