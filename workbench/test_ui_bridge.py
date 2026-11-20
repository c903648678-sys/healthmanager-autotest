"""Run the real pytest bridge against a disposable offline suite, never a product site."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from .contracts import ROOT
from . import ui_run_bridge

class BridgeTests(unittest.TestCase):
    def test_atomic_write_retries_locked_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'progress.json';path.write_text('{"old":true}')
            original=Path.replace;attempts=[]
            def replace(source,dest):
                attempts.append(source)
                if len(attempts)<3:raise PermissionError('simulated reader lock')
                return original(source,dest)
            with patch.object(Path,'replace',replace),patch.object(ui_run_bridge.time,'sleep'):
                ui_run_bridge.write(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'new':True})
            self.assertEqual(len(attempts),3)
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])

    def test_required_write_failure_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'result.json';path.write_text('{"old":true}')
            with patch.object(Path,'replace',side_effect=PermissionError('locked')),patch.object(ui_run_bridge.time,'sleep'):
                with self.assertRaises(PermissionError):ui_run_bridge.write(path,{'new':True})
            self.assertEqual(json.loads(path.read_text()),{'old':True})
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])

    @unittest.skipUnless((ROOT/'ui/.venv/Scripts/python.exe').exists(),'UI pytest environment unavailable')
    def test_real_pytest_phase_evidence_and_exact_batch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);ui=root/'ui'
            files={
                'config/__init__.py':'', 'core/__init__.py':'','core/executor/__init__.py':'',
                'core/executor/workbench_auth.py':"from config.auth_state import auth_state_path\ndef login_for_batch(env,mode,progress):\n if not auth_state_path(env).exists():raise ValueError('missing fixture auth')\n return {'cookies':[], 'origins':[]}",
                'core/executor/login_vault.py':"def status(env,origin):return {'saved':False}",
                'config/settings.py':"def list_environments():return ['fixture']",
                'config/urls.py':"from types import SimpleNamespace\ndef resolve_env(name):return SimpleNamespace(entry_url='http://localhost/offline',origin='http://localhost')",
                'config/auth_state.py':"from pathlib import Path\ndef auth_state_path(name):return Path(__file__).parents[1]/'.auth/fixture.json'",
                '.auth/fixture.json':json.dumps({'origins':[{'origin':'http://localhost','localStorage':[]}]}),
                'core/executor/runner.py':"from pathlib import Path\nfrom types import SimpleNamespace\ndef discover_cases(product):\n root=Path(__file__).parents[2]\n return [SimpleNamespace(directory=root/'testcases'/x,param_id=x) for x in ('ok','fail','skip','error')]",
                'conftest.py':"from pathlib import Path\ndef pytest_addoption(parser):\n parser.addoption('--asyncio-mode');parser.addoption('--env');parser.addoption('--execution-contract');parser.addoption('--no-cdp',action='store_true')\ndef pytest_configure(config):\n p=Path('run_results/this-batch');p.mkdir(parents=True,exist_ok=True);(p/'proof.json').write_text('{}');config._run_board_ctx={'batch_dir':p.resolve()}",
                'suites/test_cloud_docs.py':"import pytest\n@pytest.mark.parametrize('kind',['ok','fail','skip','error'])\ndef test_suite_case(kind):\n if kind=='fail':assert False,'fixture assertion'\n if kind=='skip':pytest.skip('fixture skipped')\n if kind=='error':raise RuntimeError('fixture environment error')"
            }
            for name,body in files.items():
                p=ui/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body,encoding='utf-8')
            cases=[]
            for name in ('ok','fail','skip','error'):
                p=ui/'testcases'/name;p.mkdir(parents=True)
                cases.append({'assetId':name,'content':{'title':name,'binding':{'admission':'静态可执行','inventoryId':'ui/testcases/'+name,'files':{}}}})
            old=ui/'run_results/old-batch';old.mkdir(parents=True);(old/'old.json').write_text('{}')
            out=root/'output';out.mkdir();request=out/'request.json';request.write_text(json.dumps({'environment':'fixture','suite':{'content':{'product':'Welink云文档'}},'cases':cases}))
            script="""import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('bridge',sys.argv[1]);b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
b.ROOT=Path(sys.argv[2]);b.UI=b.ROOT/'ui';sys.path.insert(0,str(b.UI))
raise SystemExit(b.execute(Path(sys.argv[3])))
"""
            result=subprocess.run([str(ROOT/'ui/.venv/Scripts/python.exe'),'-B','-c',script,str(ROOT/'workbench/ui_run_bridge.py'),str(root),str(request)],cwd=ui,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40,env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'})
            # Offline fixture disables third-party plugins, so provide the accepted asyncio flag.
            if not (out/'result.json').exists():self.fail(result.stdout+result.stderr)
            data=json.loads((out/'result.json').read_text(encoding='utf-8'))
            self.assertEqual([r['status'] for r in data['results']],['passed','failed','skipped','error'],result.stdout+result.stderr)
            self.assertEqual(data['status'],'failed')
            self.assertEqual(len(data['results'][0]['phases']),3)
            self.assertGreaterEqual(data['results'][0]['durationSeconds'],0)
            self.assertTrue(data['results'][0]['startedAt'])
            self.assertTrue(data['results'][0]['finishedAt'])
            live=json.loads((out/'live.json').read_text(encoding='utf-8'))
            self.assertEqual([r['status'] for r in live['results']],['passed','failed','skipped','error'])
            self.assertTrue((out/'evidence/proof.json').exists())
            self.assertFalse((out/'evidence/old.json').exists())
            ui_run_bridge.write(out/'control.json',{'requestId':'pause-fixture','action':'pause'})
            paused=subprocess.Popen([str(ROOT/'ui/.venv/Scripts/python.exe'),'-B','-c',script,str(ROOT/'workbench/ui_run_bridge.py'),str(root),str(request)],cwd=ui,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'})
            try:
                for _ in range(100):
                    if (out/'control-status.json').exists():break
                    time.sleep(.05)
                self.assertEqual(json.loads((out/'control-status.json').read_text())['state'],'paused')
                self.assertIsNone(paused.poll())
                self.assertTrue(all(r['status']=='pending' for r in json.loads((out/'live.json').read_text(encoding='utf-8'))['results']))
                ui_run_bridge.write(out/'control.json',{'requestId':'resume-fixture','action':'resume'})
                paused.wait(timeout=20)
                self.assertEqual([r['status'] for r in json.loads((out/'result.json').read_text(encoding='utf-8'))['results']],['passed','failed','skipped','error'])
            finally:
                if paused.poll() is None:paused.kill();paused.wait()

            fault_script=script.replace('raise SystemExit(b.execute', '''original=b.write
def locked(path,value):
 if path.name in ('progress.json','phases.json','live.json'):raise PermissionError('simulated WinError 5')
 return original(path,value)
b.write=locked
raise SystemExit(b.execute''')
            locked=subprocess.run([str(ROOT/'ui/.venv/Scripts/python.exe'),'-B','-c',fault_script,str(ROOT/'workbench/ui_run_bridge.py'),str(root),str(request)],cwd=ui,capture_output=True,timeout=40,env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'})
            data=json.loads((out/'result.json').read_text(encoding='utf-8'))
            self.assertEqual([r['status'] for r in data['results']],['passed','failed','skipped','error'],locked.stdout)
            self.assertEqual(set(data['telemetryWarnings']),{'progress.json','phases.json','live.json'})
            self.assertEqual(locked.returncode,1)
            suite=ui/'suites/test_cloud_docs.py'
            suite.write_text(suite.read_text().replace('fixture assertion','storage_state 无效'),encoding='utf-8')
            stopped=subprocess.run([str(ROOT/'ui/.venv/Scripts/python.exe'),'-B','-c',script,str(ROOT/'workbench/ui_run_bridge.py'),str(root),str(request)],cwd=ui,capture_output=True,timeout=40,env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'})
            self.assertEqual([r['status'] for r in json.loads((out/'result.json').read_text(encoding='utf-8'))['results']],['passed','auth','not_run','not_run'],stopped.stdout.decode('utf-8',errors='replace')+stopped.stderr.decode('utf-8',errors='replace'))
            with (ui/'conftest.py').open('a',encoding='utf-8') as handle:
                handle.write("\nimport pytest\n@pytest.hookimpl(trylast=True)\ndef pytest_runtest_logreport(report):\n if report.nodeid.endswith('[fail]') and report.when=='setup':raise RuntimeError('injected internal error')\n")
            interrupted=subprocess.run([str(ROOT/'ui/.venv/Scripts/python.exe'),'-B','-c',script,str(ROOT/'workbench/ui_run_bridge.py'),str(root),str(request)],cwd=ui,capture_output=True,timeout=40,env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'})
            data=json.loads((out/'result.json').read_text(encoding='utf-8'))
            self.assertEqual(interrupted.returncode,3)
            self.assertEqual(data['status'],'incomplete')
            self.assertEqual([r['status'] for r in data['results']],['passed','interrupted','not_run','not_run'])

            cases[0]['content']['binding']['admission']='阻断'
            snapshot=json.loads(request.read_text())
            snapshot['cases']=cases
            request.write_text(json.dumps(snapshot))
            subprocess.run([str(ROOT/'ui/.venv/Scripts/python.exe'),'-B','-c',script,str(ROOT/'workbench/ui_run_bridge.py'),str(root),str(request)],cwd=ui,capture_output=True,timeout=30)
            blocked=json.loads((out/'result.json').read_text(encoding='utf-8'))
            self.assertEqual(blocked['status'],'blocked')
            self.assertIn('准入',blocked['message'])
            (ui/'.auth/fixture.json').unlink()
            subprocess.run([str(ROOT/'ui/.venv/Scripts/python.exe'),'-B','-c',script,str(ROOT/'workbench/ui_run_bridge.py'),str(root),str(request)],cwd=ui,capture_output=True,timeout=30,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
            self.assertEqual(json.loads((out/'result.json').read_text(encoding='utf-8'))['status'],'blocked')


