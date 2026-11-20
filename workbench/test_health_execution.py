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
                changed=executor.execute(snapshot,root/'changed',threading.Event(),lambda _:None)
                self.assertEqual(changed['status'],'blocked')
                self.assertIn('版本',changed['results'][0]['message'])

    def test_unconfigured_environment_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(HealthExecutor(tmp).environments()['environments'],[])

    def test_checkpoint_survives_later_script_drift(self):
        import json
        from .ui_execution import reconcile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executor = HealthExecutor(root)
            executor.python = HealthExecutor().python
            (root/'config.local.json').write_text(json.dumps({'base_url':'http://localhost','expected_title':'fixture'}))
            cases = []
            for name in ('a','b','c'):
                relative = f'ui/testcases/{name}/test_main.py'
                script = root/relative
                script.parent.mkdir(parents=True)
                script.write_text('def test_pass(): assert True')
                binding = {'files':{relative:hashlib.sha256(script.read_bytes()).hexdigest()}}
                cases.append({'assetId':name,'content':{'title':name,'binding':binding}})
            def change_after_preflight(_):
                (root/'ui/testcases/b/test_main.py').write_text('# changed')
            snapshot = {'cases':cases,'environment':'test'}
            result = executor.execute(snapshot,root/'run',threading.Event(),change_after_preflight)
            for evidence in (result, executor.read_evidence(root/'run',None)):
                rows = reconcile(snapshot,evidence)['results']
                self.assertEqual([row['status'] for row in rows],['passed','blocked','not_run'])

    def test_pytest_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root/'ui/testcases/test_main.py'
            script.parent.mkdir(parents=True)
            executor = HealthExecutor(root)
            executor.python = HealthExecutor().python
            examples = [
                ('import pytest\ndef test_case(): pytest.skip()', 'skipped','skip'),
                ('def test_case(): assert False', 'failed','call'),
                ('def test_case(missing_fixture): pass', 'error','fixture / collection'),
            ]
            for source, status, phase in examples:
                script.write_text(source)
                result = executor.run_script('ui',script,None,threading.Event())
                self.assertEqual(result[:2],(status,phase))
            script.write_text('import time\ndef test_case(): time.sleep(10)')
            executor.timeout = .1
            self.assertEqual(executor.run_script('ui',script,None,threading.Event())[:2],('error','timeout'))
            cancelled = threading.Event()
            cancelled.set()
            self.assertEqual(executor.run_script('ui',script,None,cancelled)[0],'interrupted')

    def test_api_asset_from_scan_to_execution(self):
        import json
        import shutil
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from .ui_inventory import scan
        from .automation import Automation
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == '/health' else 404)
                self.send_header('Content-Length','0')
                self.end_headers()
        with tempfile.TemporaryDirectory() as tmp, ThreadingHTTPServer(('127.0.0.1',0),Handler) as service:
            root = Path(tmp)
            thread = threading.Thread(target=service.serve_forever,daemon=True)
            thread.start()
            try:
                shutil.copytree(ROOT/'api/testcases/health',root/'api/testcases/health')
                (root/'ui').mkdir()
                (root/'config.local.json').write_text(json.dumps({'api_base_url':f'http://127.0.0.1:{service.server_port}','health_path':'/health'}))
                row, = scan(root/'ui')['cases']
                auto = Automation.__new__(Automation)
                with patch('workbench.automation.ROOT',root):
                    content = auto._inventory_content(row,auto._row_binding(row,'健康管理'))
                self.assertEqual(content['layer'],'API')
                executor = HealthExecutor(root)
                executor.api_python = HealthExecutor().api_python
                result = executor.execute({'environment':'test','cases':[{'assetId':'from-inventory','content':content}]},
                                          root/'run',threading.Event(),lambda _:None)
                self.assertEqual(result['status'],'passed')
            finally:
                service.shutdown()
                thread.join()
