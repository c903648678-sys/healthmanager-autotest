"""Durable automation invariants, isolated from real product environments."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from .automation import Automation, TERMINAL
from .workspace import Conflict
from .contracts import validate_cases
from .test_design_assist import runner

class FakeExecutor:
    def environments(self):return {'environments':[{'id':'fixture'}]}
    def execute(self,snapshot,folder,event,progress):
        progress('开始独立上下文执行')
        return {'status':'failed','results':[{'assetId':c['assetId'],'title':c['content']['title'],'status':'failed' if i==0 else 'passed','message':'fixture assertion'} for i,c in enumerate(snapshot['cases'])]}

class AutomationTests(unittest.TestCase):
    def test_live_case_timing_is_read_only_and_scoped_to_suite(self):
        from datetime import datetime, timedelta, timezone
        rid='run-live-fixture'
        row={'id':rid,'status':'running','results':[],'executed':0,'snapshot':{'cases':[{'assetId':x,'content':{'title':x}} for x in ('a','b','c')]}}
        self.auto.state['runs'].append(row)
        self.assertEqual([r['status'] for r in self.auto.run(rid)['results']],['pending']*3)
        out=self.folder/'runs'/rid;out.mkdir(parents=True)
        (out/'live.json').write_text(json.dumps({'updatedAt':'fixture','results':[
            {'assetId':'a','status':'passed','durationSeconds':2},
            {'assetId':'b','status':'running','startedAt':(datetime.now(timezone.utc)-timedelta(seconds=3)).isoformat()},
            {'assetId':'not-in-suite','status':'passed'}]}))
        result=self.auto.run(rid)
        self.assertEqual(result['executed'],1)
        self.assertEqual(result['counts'],{'passed':1,'running':1,'pending':1})
        self.assertGreaterEqual(result['results'][1]['durationSeconds'],3)
        self.assertEqual(self.auto.get()['runs'][-1]['executed'],1)
        self.assertEqual(row['results'],[])
        (out/'live.json').write_text('temporarily unreadable')
        self.assertEqual(self.auto.run(rid)['counts'],{'passed':1,'running':1,'pending':1})
        row.update(status='passed',results=[{'assetId':'a','status':'passed','phases':[{'duration':1},{'duration':2}]}])
        historical=self.auto.run(rid)['results'][0]
        self.assertEqual(historical['durationSeconds'],3)
        self.assertTrue(historical['durationEstimated'])

    def test_screenshots_match_full_case_identity_and_existing_artifact(self):
        import hashlib
        run_id='run-screenshot-fixture';node='suite.py::case[one]'
        suffix=hashlib.sha256(node.encode()).hexdigest()[:16]
        image='evidence/artifacts/case--'+suffix+'/failure.png'
        wrong='evidence/artifacts/other--0123456789abcdef/failure.png'
        missing='evidence/artifacts/missing--'+suffix+'/failure.png'
        for name in (image,wrong):
            path=self.folder/'runs'/run_id/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
        self.auto.state['runs'].append({'id':run_id,'results':[{'nodeid':node},{'nodeid':'suite.py::case[two]'}],'artifacts':[image,wrong,missing]})
        result=self.auto.run(run_id)
        self.assertEqual(result['results'][0]['screenshots'],[image])
        self.assertEqual(result['results'][1]['screenshots'],[])
        self.assertNotIn('screenshots',self.auto.state['runs'][-1]['results'][0])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.plan={'coverage':[{'requirementId':'U1','disposition':'included','approach':'验证创建'}],'openItems':[]}
        self.cases=runner(None,{'properties':{}})
        self.jobs={'p':{'review':{'accepted':True,'draft':self.plan},'reviewDigest':'p1','basisCurrent':True},'c':{'review':{'accepted':True,'draft':self.cases},'reviewDigest':'c1','basisCurrent':True}}
        self.task={'id':'t','planner':{'job':{'id':'p'},'draft':deepcopy(self.plan)},'caseDesigner':{'job':{'id':'c'},'draft':deepcopy(self.cases)}}
        self.ws=SimpleNamespace(lock=threading.RLock(),get=lambda:{'data':{'tasks':[self.task]}},jobs=SimpleNamespace(get=lambda i:deepcopy(self.jobs[i])))
        self.auto=Automation(self.folder,self.ws,SimpleNamespace(get=lambda:{'cases':[]}),FakeExecutor())
    def tearDown(self):self.tmp.cleanup()
    def asset(self,**extra):return self.auto.publish({'taskId':'t','caseId':'TC1','product':'健康管理','subproduct':'表格','feature':'字段',**extra})
    def suite(self,assets):return self.auto.suite({'name':'fixture','layer':'UI','cases':[{'assetId':a['id'],'revision':a['revision']} for a in assets]})
    def wait(self,r):
        for _ in range(200):
            r=self.auto.run(r['id'])
            if r['status'] in TERMINAL:return r
            time.sleep(.01)
        self.fail('run did not finish')
    def test_intake_validates_whole_batch_and_rejects_duplicate_sources(self):
        item={'taskId':'t','caseId':'TC1','product':'健康管理','subproduct':'表格','feature':'字段'}
        initial=deepcopy(self.auto.state)
        with self.assertRaises(ValueError):
            self.auto.intake({'items':[item,{**item,'caseId':'missing'}]})
        self.assertEqual(self.auto.state,initial)
        with self.assertRaises(Conflict):
            self.auto.intake({'items':[item,item]})
        self.assertEqual(self.auto.intake({'items':[item]}),{'count':1})
        saved=self.auto.path.read_bytes()
        with self.assertRaises(Conflict):
            self.auto.intake({'items':[item]})
        self.assertEqual(self.auto.path.read_bytes(),saved)
        self.assertEqual(len(self.auto.state['assets']),1)

    def test_pause_resume_and_delete_waits_for_executor_exit(self):
        from .ui_run_bridge import wait_for_resume
        entered=threading.Event();boundary=threading.Event();continued=threading.Event();exited=threading.Event()
        class ControlledExecutor(FakeExecutor):
            def execute(inner,snapshot,folder,event,progress):
                folder.mkdir(parents=True,exist_ok=True)
                (folder/'console.log').write_text('fixture')
                entered.set()
                boundary.wait(3)
                progress('case · teardown · passed')
                wait_for_resume(folder)
                continued.set()
                event.wait(3)
                # Evidence must exist until the child has stopped.
                self.assertTrue((folder/'console.log').is_file())
                exited.set()
                return {'status':'cancelled','results':[]}
        self.auto.executor=ControlledExecutor()
        suite=self.suite([self.asset()])
        run=self.auto.start({'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture'})
        rid=run['id'];self.assertTrue(entered.wait(2))
        try:
            self.auto.control({'id':rid,'action':'pause'})
            self.assertEqual(self.auto.run(rid)['status'],'pausing')
            boundary.set()
            for _ in range(100):
                if self.auto.run(rid)['status']=='paused':break
                time.sleep(.02)
            self.assertEqual(self.auto.run(rid)['status'],'paused')
            self.assertFalse(continued.is_set())
            self.auto.control({'id':rid,'action':'resume'})
            self.assertEqual(self.auto.run(rid)['status'],'running')
            self.assertTrue(continued.wait(2))
            response=self.auto.delete_run({'id':rid});self.assertTrue(response['pending'])
            self.assertTrue(exited.wait(2))
            for _ in range(100):
                if not self.auto.get()['runs']:break
                time.sleep(.02)
            self.assertEqual(self.auto.get()['runs'],[])
            self.assertFalse((self.folder/'runs'/rid).exists())
            self.assertEqual(len(self.auto.get()['suites']),1)
            self.assertEqual(len(self.auto.get()['assets']),1)
        finally:
            boundary.set()
            from .ui_run_bridge import write
            folder=self.folder/'runs'/rid
            if folder.exists():write(folder/'control.json',{'action':'resume'})
            event=self.auto.events.get(rid)
            if event:event.set()

    def test_terminal_delete_scope_and_pause_rejected(self):
        suite=self.suite([self.asset()])
        run=self.wait(self.auto.start({'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture'}))
        with self.assertRaises(Conflict):self.auto.control({'id':run['id'],'action':'pause'})
        other=self.folder/'runs'/'other';other.mkdir(parents=True);(other/'keep.log').write_text('keep')
        self.auto.delete_run({'id':run['id']})
        self.assertTrue((other/'keep.log').exists())
        self.assertEqual(self.auto.get()['runs'],[])
        malicious={'id':'../escape','status':'passed'};self.auto.state['runs'].append(malicious)
        with self.assertRaises(ValueError):self.auto.delete_run({'id':'../escape'})

    def test_pins_suite_plan_run_and_rerun_versions(self):
        a,b=self.asset(),self.asset();s=self.suite([a,b]);p=self.auto.plan({'name':'daily','suiteId':s['id'],'suiteRevision':1,'environment':'fixture','build':'b1','trigger':'daily','schedule':'09:00'})
        self.asset(id=a['id'],expectedRevision=1,feature='新版字段')
        r=self.wait(self.auto.start({'planId':p['id'],'build':'b2'}))
        self.assertEqual(r['snapshot']['cases'][0]['revision'],1);self.assertEqual(r['planRevision'],1)
        self.assertEqual(r['counts'],{'failed':1,'passed':1});self.assertEqual(r['build'],'b2')
        retry=self.wait(self.auto.start({'suiteId':s['id'],'suiteRevision':1,'environment':'fixture','build':'b3','parentRunId':r['id']}))
        self.assertEqual(retry['total'],1);self.assertEqual(retry['snapshot']['cases'][0]['revision'],1)
        self.assertEqual(self.auto.run(r['id']),r)
        restored=Automation(self.folder,self.ws,self.auto.inventory,FakeExecutor())
        self.assertEqual(restored.run(r['id']),r)
    def test_retry_includes_unexecuted_cases_and_preserves_parent(self):
        assets=[self.asset() for _ in range(4)]
        suite=self.suite(assets)
        parent=self.wait(self.auto.start({'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture'}))
        stored=self.auto.find('runs',parent['id'])
        stored['status']='interrupted'
        for row,status in zip(stored['results'],('passed','failed','interrupted','not_run')):
            row['status']=status
        self.auto._save()
        before=deepcopy(stored)
        retry=self.wait(self.auto.start({'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','parentRunId':parent['id'],'workers':5}))
        self.assertEqual(retry['total'],3)
        self.assertEqual({row['assetId'] for row in retry['snapshot']['cases']},{a['id'] for a in assets[1:]})
        self.assertIsNone(retry['snapshot']['timeoutSeconds'])
        self.assertEqual(stored,before)

    def test_auto_build_and_ci_override(self):
        suite=self.suite([self.asset()]);raw={'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture'}
        a=self.wait(self.auto.start(raw));b=self.wait(self.auto.start(raw))
        self.assertNotEqual(a['build'],b['build']);self.assertEqual(a['buildSource'],'generated')
        plan=self.auto.plan({**raw,'name':'auto','trigger':'manual'})
        c=self.wait(self.auto.start({'planId':plan['id'],'build':'ci-123'}))
        self.assertEqual(c['build'],'ci-123');self.assertEqual(c['snapshot']['buildSource'],'provided')

    def test_browser_mode_defaults_and_plan_precedence(self):
        a=self.asset();suite=self.suite([a]);raw={'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','build':'b'}
        r=self.wait(self.auto.start(raw));self.assertEqual(r['snapshot']['browserMode'],'headless')
        r=self.wait(self.auto.start({**raw,'browserMode':'headed'}));self.assertEqual(r['snapshot']['browserMode'],'headed')
        with self.assertRaises(ValueError):self.auto.start({**raw,'browserMode':'invalid'})
        plan=self.auto.plan({**raw,'name':'CI','trigger':'manual','browserMode':'headless'})
        r=self.wait(self.auto.start({'planId':plan['id'],'browserMode':'headed'}))
        self.assertEqual(r['snapshot']['browserMode'],'headless')

    def test_parallel_plan_pins_worker_limit_and_rejects_headed(self):
        a=self.asset();suite=self.suite([a]);raw={'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture'}
        self.assertEqual(self.wait(self.auto.start(raw))['snapshot']['workers'],1)
        for invalid in (0,11,True,'1.5'):
            with self.assertRaises(ValueError):self.auto.start({**raw,'workers':invalid})
        with self.assertRaises(ValueError):self.auto.plan({**raw,'name':'p','workers':2,'browserMode':'headed'})
        p=self.auto.plan({**raw,'name':'p','workers':'10'})
        r=self.wait(self.auto.start({'planId':p['id'],'workers':1}))
        self.assertEqual(r['snapshot']['workers'],10)

    def test_suite_environment_persisted_and_validated(self):
        a=self.asset();raw={'name':'env suite','layer':'UI','cases':[{'assetId':a['id'],'revision':1}],'environment':'fixture'}
        suite=self.auto.suite(raw)
        self.assertEqual(suite['versions'][-1]['content']['environment'],'fixture')
        with self.assertRaises(ValueError):self.auto.suite({**raw,'environment':'missing'})
        self.auto.executor.environments=lambda:{'environments':[{'id':'fixture','product':'DocZip'}]}
        with self.assertRaises(ValueError):self.auto.suite(raw)
        self.assertEqual(self.auto.suite({**raw,'environment':''})['versions'][-1]['content']['environment'],'')

    def test_external_edit_blocks_publish(self):
        self.asset()
        original = self.auto.path.read_bytes()
        for changed in (original + b' ', b'{', None):
            if changed is None:
                self.auto.path.unlink()
            else:
                self.auto.path.write_bytes(changed)
            with self.assertRaises(Conflict):
                self.asset()
            self.assertEqual(len(self.auto.state['assets']), 1)
            self.assertEqual(self.auto.path.read_bytes() if self.auto.path.exists() else None, changed)

    def test_plan_rejects_wrong_product(self):
        suite = self.suite([self.asset()])
        self.auto.executor.environments = lambda: {'environments':[{'id':'fixture','product':'DocZip'}]}
        with self.assertRaises(ValueError):
            self.auto.plan({'name':'daily','suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','build':'1'})

    def test_blocked_inventory_cannot_bind(self):
        self.auto.inventory.get = lambda: {'cases':[{'assetId':'x','product':'健康管理','admission':'阻断','reason':'skip'}]}
        with self.assertRaisesRegex(ValueError, '准入'):
            self.auto.import_ui({'assetId':'x'})

    def test_run_poll_excludes_heavy_fields(self):
        suite = self.suite([self.asset()])
        run = self.wait(self.auto.start({'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','build':'1'}))
        summary = self.auto.run_summaries()[0]
        self.assertEqual(summary['counts'], run['counts'])
        self.assertFalse({'results','snapshot','events','report','artifacts'} & summary.keys())
        self.assertTrue(self.auto.run(run['id'])['results'])

    def test_large_suite_keeps_every_reference(self):
        sample=self.asset()
        assets=[]
        for i in range(250):
            asset=deepcopy(sample);asset['id']='bulk-'+str(i);assets.append(asset)
        self.auto.state['assets']=assets
        suite=self.suite(assets)
        self.assertEqual(len(suite['versions'][-1]['content']['cases']),250)
        restored=Automation(self.folder,self.ws,self.auto.inventory,FakeExecutor())
        self.assertEqual(len(restored.version('suites',suite['id'],1)['content']['cases']),250)
        with self.assertRaises(ValueError):self.suite(assets*41)

    def test_conflicting_version_and_mixed_products_rejected(self):
        a=self.asset()
        with self.assertRaises(Conflict):self.asset(id=a['id'],expectedRevision=0)
        with self.assertRaises(ValueError):self.asset(product='DocZip')
        with self.assertRaises(ValueError):self.auto.suite({'name':'bad','layer':'API','cases':[{'assetId':a['id'],'revision':1}]})
    def test_unconfirmed_and_changed_draft_cannot_publish(self):
        self.jobs['c']['basisCurrent']=False
        with self.assertRaises(ValueError):self.asset()
        self.jobs['c']['basisCurrent']=True;self.task['caseDesigner']['draft']['title']='changed'
        with self.assertRaises(ValueError):self.asset()
    def test_model_confirmation_and_coverage(self):
        m=self.auto.model('t')
        with self.assertRaises(ValueError):self.auto.generation_model('t')
        m=self.auto.save_model({**m,'expectedRevision':0,'confirmed':True})
        self.assertEqual(self.auto.generation_model('t'),m)
        candidate=deepcopy(self.cases);candidate['cases'][0].update(scenarioId='S1',testPointIds=['P1'])
        validate_cases(candidate,{'plan':self.plan,'designModel':m})
        missing=deepcopy(m);missing['scenarios'][0]['points'].append({'id':'P2','title':'边界','method':'边界值'})
        with self.assertRaises(ValueError):validate_cases(candidate,{'plan':self.plan,'designModel':missing})
        m['scenarios'][0]['requirementIds']=['UNKNOWN']
        with self.assertRaises(ValueError):self.auto.save_model({**m,'expectedRevision':1})
        self.task['planner']['draft']['coverage'][0]['approach']='未确认修改'
        with self.assertRaises(ValueError):self.auto.model('t')
    def test_malformed_model_rejected(self):
        m=self.auto.model('t')
        for scenes in ([None],[{'id':'S','title':'x','requirementIds':[{}]}]):
            with self.assertRaises(ValueError):self.auto.save_model({**m,'expectedRevision':0,'scenarios':scenes})
    def test_missing_results_are_unexecuted_and_artifact_contained(self):
        self.auto.executor.execute=lambda *a:{'status':'blocked','message':'no auth','results':[]}
        s=self.suite([self.asset()]);r=self.wait(self.auto.start({'suiteId':s['id'],'suiteRevision':1,'environment':'fixture','build':'b'}))
        self.assertEqual(r['executed'],0);self.assertEqual(r['counts'],{'not_run':1});self.assertTrue(r['report']['unexecuted'])
        with self.assertRaises(ValueError):self.auto.artifact(r['id'],'../../../state.json')
    def test_execution_continues_beyond_one_hour(self):
        from unittest.mock import Mock, patch
        from .ui_execution import UIExecutor
        executor = UIExecutor(self.folder)
        executor.python = Path(__file__)
        snapshot = {'suite': {'content': {'layer': 'UI'}},
                    'cases': [{'assetId': 'a', 'content': {'title': 'A'}}]}
        folder = self.folder / 'long-run'
        process = Mock()
        process.poll.side_effect = [None, None, 0]
        process.returncode = 0
        clock = [0]
        event = Mock()
        event.is_set.return_value = False

        def advance(_):
            clock[0] += 3700
            # A long batch is allowed while successive cases keep completing.
            (folder/'live.json').write_text(json.dumps({'results':[
                {'nodeid':str(clock[0]),'status':'passed'}]}),encoding='utf-8')
            return False

        event.wait.side_effect = advance
        result = {'status': 'passed', 'exitCode': 0,
                  'results': [{'assetId': 'a', 'status': 'passed'}]}
        with patch('workbench.ui_execution.subprocess.Popen', return_value=process), \
             patch('time.monotonic', side_effect=lambda: clock[0]), \
             patch.object(executor, 'read_evidence', return_value=result) as evidence:
            observed = executor.execute(snapshot, folder, event, lambda _: None)
        self.assertEqual(observed['status'], 'passed')
        self.assertGreater(clock[0], 7200)
        self.assertFalse(evidence.call_args.args[2])
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_crash_preserves_phase_evidence(self):
        import sys
        from .ui_execution import UIExecutor
        executor = UIExecutor(self.folder)
        executor.ui.mkdir()
        executor.python = Path(sys.executable)
        executor.bridge = self.folder / 'fixture.py'
        assets = [self.asset(), self.asset()]
        suite = self.suite(assets)
        self.auto.executor = executor
        for final_content in (None, "{", json.dumps({"status":"blocked","results":[]})):
            with self.subTest(final_content=final_content):
                executor.bridge.write_text(
                    "import json, sys\nfrom pathlib import Path\nout = Path(sys.argv[-1]).parent\n"
                    + f"(out/'node-map.json').write_text(json.dumps({{'node': {{'assetId': {assets[0]['id']!r}, 'title': 'A'}}}}))\n"
                    + "(out/'phases.json').write_text(json.dumps({'node':[{'phase':'call','outcome':'failed','message':'AssertionError: fixture'}]}))\n"
                    + (f"(out/'result.json').write_text({final_content!r})\n" if final_content else "")
                    + "sys.exit(3)\n", encoding='utf-8')
                run = self.wait(self.auto.start({'suiteId':suite['id'],'suiteRevision':1,
                                                'environment':'fixture','build':'offline'}))
                self.assertEqual(run['counts'], {'failed':1, 'not_run':1})
                self.assertEqual(run['status'], 'interrupted')
                self.assertEqual(run['exitCode'], 3)
                self.assertEqual(run['executed'], 1)
                self.assertIn('phases.json', run['artifacts'])

    def test_cancel_and_concurrency(self):
        entered=threading.Event()
        def execute(snapshot,folder,event,progress):
            entered.set();event.wait(2);return {'status':'cancelled','results':[]}
        self.auto.executor.execute=execute;s=self.suite([self.asset()]);raw={'suiteId':s['id'],'suiteRevision':1,'environment':'fixture','build':'b'}
        r=self.auto.start(raw);self.assertTrue(entered.wait(1))
        with self.assertRaises(Conflict):self.auto.start(raw)
        self.auto.cancel({'id':r['id']});self.assertEqual(self.wait(r)['status'],'cancelled')
    def test_start_uses_confirmed_plan_revision(self):
        suite=self.suite([self.asset()])
        raw={'name':'plan','suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','build':'1'}
        plan=self.auto.plan(raw)
        self.auto.plan({**raw,'id':plan['id'],'expectedRevision':1,'build':'2'})
        with self.assertRaises(Conflict):
            self.auto.start({'planId':plan['id'],'expectedPlanRevision':1})
        self.assertEqual(self.auto.state['runs'],[])

    def test_start_failure_leaves_run_retriable(self):
        from unittest.mock import patch
        suite=self.suite([self.asset()])
        raw={'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','build':'1'}
        with patch.object(Path,'replace',side_effect=OSError('disk busy')):
            with self.assertRaises(OSError):self.auto.start(raw)
        self.assertEqual(self.auto.state['runs'],[])
        self.assertEqual(self.auto.events,{})
        with patch.object(threading.Thread,'start',side_effect=RuntimeError('thread unavailable')):
            with self.assertRaisesRegex(ValueError,'线程'):self.auto.start(raw)
        self.assertEqual(self.auto.state['runs'][0]['status'],'interrupted')
        self.assertEqual(self.wait(self.auto.start(raw))['executed'],1)

    def test_inconsistent_pass_cannot_pass_run(self):
        suite=self.suite([self.asset()])
        aid=suite['versions'][0]['content']['cases'][0]['assetId']
        row={'assetId':aid,'status':'passed','title':'fixture'}
        for code,rows in [(3,[row]),(0,[]),(0,[row,row]),(0,[{**row,'assetId':'other'}]),(0,[{**row,'status':'failed'}])]:
            with self.subTest(code=code,rows=rows):
                self.auto.executor.execute=lambda *args:{'status':'passed','exitCode':code,'results':rows}
                r=self.wait(self.auto.start({'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','build':'1'}))
                self.assertEqual(r['status'],'incomplete')
                self.assertEqual(len(r['results']),1)

    def test_restart_reconciles_only_matching_snapshot(self):
        from .ui_execution import UIExecutor
        suite=self.suite([self.asset()])
        run=self.wait(self.auto.start({'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','build':'1'}))
        directory=self.folder/'runs'/run['id']
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'result.json').write_text(json.dumps({'status':'failed','results':run['results']}))
        for matching in (True,False):
            (directory/'request.json').write_text(json.dumps(run['snapshot'] if matching else {}))
            self.auto.state['runs'][0].update(status='running',counts={},results=[],executed=0,report=None)
            self.auto._save()
            self.auto=Automation(self.folder,self.ws,self.auto.inventory,UIExecutor(self.folder))
            recovered=self.auto.run(run['id'])
            self.assertEqual(recovered['counts'],{'failed':1} if matching else {'unknown':1})
            self.assertTrue(recovered['report'])
    def test_exit_code_unknown_and_mismatch_have_distinct_reasons(self):
        from .ui_execution import UIExecutor
        row={'assetId':'a','nodeid':'N','status':'passed','phases':[
            {'phase':phase,'outcome':'passed'} for phase in ('setup','call','teardown')]}
        (self.folder/'node-map.json').write_text(json.dumps({'N':{'assetId':'a'}}))
        (self.folder/'result.json').write_text(json.dumps({'status':'passed','exitCode':0,'results':[row]}))
        for observed,reason in ((None,'无法确认'),(3,'不一致')):
            with self.subTest(observed=observed):
                result=UIExecutor.read_evidence(self.folder,observed)
                self.assertEqual(result['status'],'incomplete')
                self.assertIn(reason,result['message'])
                self.assertEqual(result['results'][0]['status'],'passed')
        self.assertEqual(UIExecutor.read_evidence(self.folder,0)['status'],'passed')

    def test_recovery_waits_for_child_lease(self):
        from .ui_execution import UIExecutor
        from .lease import WorkspaceLease
        suite=self.suite([self.asset()])
        run=self.wait(self.auto.start({'suiteId':suite['id'],'suiteRevision':1,'environment':'fixture','build':'1'}))
        directory=self.folder/'runs'/run['id']
        directory.mkdir(parents=True)
        self.auto.state['runs'][0].update(status='running',results=[],counts={},report=None)
        self.auto._save()
        lease=WorkspaceLease(self.folder/'.local/workbench/ui-engine-lease')
        try:
            restored=Automation(self.folder,self.ws,self.auto.inventory,UIExecutor(self.folder))
            self.assertEqual(restored.run(run['id'])['status'],'running')
            self.assertFalse((directory/'recovered.flag').exists())
            (directory/'request.json').write_text(json.dumps(run['snapshot']))
            (directory/'result.json').write_text(json.dumps({'status':'failed','results':run['results']}))
        finally:
            lease.close()
        final=restored.run(run['id'])
        self.assertEqual(final['counts'],{'failed':1})
        self.assertTrue((directory/'recovered.flag').exists())

    def test_restart_does_not_claim_success(self):
        self.auto.state['runs'].append({'id':'orphan','status':'running'});self.auto._save()
        restored=Automation(self.folder,self.ws,self.auto.inventory,FakeExecutor())
        self.assertEqual(restored.run('orphan')['status'],'interrupted')

if __name__=='__main__':unittest.main()
