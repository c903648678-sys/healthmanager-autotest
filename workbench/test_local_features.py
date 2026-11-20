import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from .knowledge import Knowledge
from .execution import Execution
from .jobs import JobStore
from .workspace import Workspace

class KnowledgeTests(unittest.TestCase):
    def test_change_review_move_delete_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'specs';root.mkdir();source=root/'a.md';source.write_text('# Rule A',encoding='utf-8')
            store=Knowledge(Path(tmp)/'catalog',{'specs':root})
            doc=store.refresh()['documents'][0]
            store.review({'id':doc['id'],'hash':doc['hash'],'status':'已确认','note':'产品规格确认'})
            source.rename(root/'moved.md')
            moved=store.refresh()['documents'][0]
            self.assertEqual(moved['id'],doc['id']);self.assertEqual(moved['status'],'已确认')
            (root/'moved.md').write_text('# Rule B',encoding='utf-8')
            changed=store.refresh()['documents'][0]
            self.assertEqual(changed['revision'],2);self.assertEqual(changed['status'],'待确认')
            self.assertEqual(changed['history'][0]['text'],'# Rule A')
            with self.assertRaises(ValueError):store.review({'id':doc['id'],'hash':doc['hash'],'status':'已确认','note':'stale'})
            (root/'moved.md').unlink()
            self.assertTrue(store.refresh()['documents'][0]['missing'])
            self.assertTrue(Knowledge(Path(tmp)/'catalog',{'specs':root}).get()['documents'][0]['missing'])

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        # These tests require regression attempts to occur strictly after failure;
        # fast Windows clocks may otherwise return an identical timestamp.
        ticks=count()
        clock=patch('workbench.execution.stamp',side_effect=lambda:(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(milliseconds=next(ticks))).isoformat())
        clock.start();self.addCleanup(clock.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.jobs=JobStore(self.folder/'jobs')
        self.workspace=Workspace(self.folder/'workspace.json',self.jobs)
        self.workspace.save({'revision':0,'data':{'tasks':[{'id':'task-1','name':'验证','version':'v1','cases':[{'id':'c1','title':'检查','steps':'操作','expected':'正确','confirmed':True}],'issues':[],'runs':[],'attempts':[]}]}})
        self.store=Execution(self.folder/'execution',self.workspace)
        self.batch=self.store.create({'taskId':'task-1','caseIds':['c1'],'name':'批次','environment':'local','productVersion':'v1'})

    def record(self,result,request_id,**extra):
        return self.store.record({'batchId':self.batch['id'],'caseId':'c1','result':result,'actual':'实际结果','requestId':request_id,**extra})

    def test_snapshots_attempts_issues_freeze_and_restart(self):
        value=self.workspace.get();value['data']['tasks'][0]['cases'][0]['steps']='new';self.workspace.save(value)
        failure=self.record('失败','req-1',files=[{'name':'log.txt','base64':'YWJj'}])
        self.assertEqual(self.record('失败','req-1')['id'],failure['id'])
        self.record('失败','req-2')
        passing=self.record('通过','req-3')
        value=self.store.get('task-1');self.assertEqual(len(value['issues']),1)
        self.assertEqual(value['batches'][0]['cases'][0]['steps'],'操作')
        self.assertEqual(self.store.evidence(failure['evidence'][0]['id']),b'abc')
        issue=value['issues'][0]
        with self.assertRaises(ValueError):self.store.review_issue({'issueId':issue['id'],'type':'产品缺陷','status':'已关闭','note':'done'})
        self.store.review_issue({'issueId':issue['id'],'type':'产品缺陷','status':'已关闭','note':'回归通过','regressionAttemptId':passing['id']})
        self.store.close_batch({'batchId':self.batch['id'],'conclusion':'完成'})
        report=self.store.freeze({'batchId':self.batch['id'],'notes':'性能未测'})
        self.assertEqual(report['counts']['通过'],1);self.assertEqual(report['attemptCount'],3);self.assertEqual(report['retryPassedCount'],1)
        with self.assertRaises(ValueError):self.record('通过','req-4')
        self.store.review_issue({'issueId':issue['id'],'type':'产品缺陷','status':'待处理','note':'重开'})
        self.assertEqual(self.store.get('task-1')['reports'][0]['issues'][0]['status'],'已关闭')
        restored=Execution(self.folder/'execution',self.workspace)
        self.assertEqual(len(restored.get('task-1')['reports']),1)

    def test_failed_commit_is_retriable(self):
        from unittest.mock import patch
        files = [{'name':'log.txt','base64':'YWJj'}]
        with patch.object(Path, 'replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.record('失败', 'retry', files=files)
        attempt = self.record('失败', 'retry', files=files)
        restored = Execution(self.store.folder, self.workspace)
        data = restored.get('task-1')
        self.assertEqual(data['batches'][0]['attempts'], [attempt])
        self.assertEqual(data['issues'][0]['attemptIds'], [attempt['id']])
        self.assertEqual(restored.evidence(attempt['evidence'][0]['id']), b'abc')
        self.assertEqual(len(list((self.store.folder/'evidence').iterdir())), 1)

    def test_invalid_results_evidence_readonly_and_unexecuted(self):
        with self.assertRaises(ValueError):self.record('模拟通过','a')
        with self.assertRaises(ValueError):self.record('通过','b',files=[{'name':'evil.html','base64':'YWJj'}])
        with self.assertRaises(ValueError):self.record('失败','c',actual='')
        self.store.close_batch({'batchId':self.batch['id'],'conclusion':'环境不可用'})
        self.assertEqual(self.store.freeze({'batchId':self.batch['id'],'notes':'全部未测'})['counts']['未执行'],1)
        self.workspace.transition('task-1','pause',{'revision':self.workspace.get()['revision']})
        with self.assertRaises(ValueError):self.store.freeze({'batchId':self.batch['id'],'notes':'blocked'})
    def test_same_timestamp_regression_uses_batch_order(self):
        from unittest.mock import patch
        with patch('workbench.execution.stamp',return_value='2026-01-01T00:00:00+00:00'):
            early=self.record('通过','early')
            self.record('失败','failure')
            late=self.record('通过','late')
        issue=self.store.get('task-1')['issues'][0]
        review={'issueId':issue['id'],'type':'产品缺陷','status':'已关闭','note':'回归通过'}
        with self.assertRaises(ValueError):
            self.store.review_issue({**review,'regressionAttemptId':early['id']})
        self.assertEqual(self.store.review_issue({**review,'regressionAttemptId':late['id']})['status'],'已关闭')

    def test_cross_batch_regression_requires_same_case_content(self):
        self.record('失败','first-failure')
        issue=self.store.get('task-1')['issues'][0]
        self.store.close_batch({'batchId':self.batch['id'],'conclusion':'Pending fix'})
        new=self.store.create({'taskId':'task-1','caseIds':['c1'],'name':'regression','environment':'local','productVersion':'v2'})
        passed=self.store.record({'batchId':new['id'],'caseId':'c1','result':'通过','actual':'fixed','requestId':'regression-pass'})
        reviewed=self.store.review_issue({'issueId':issue['id'],'type':'产品缺陷','status':'已关闭','note':'v2 verified','regressionAttemptId':passed['id']})
        self.assertEqual(reviewed['status'],'已关闭')
        self.store.review_issue({'issueId':issue['id'],'type':'产品缺陷','status':'待处理','note':'Recheck'})
        value=self.workspace.get();value['data']['tasks'][0]['cases'][0]['steps']='different steps';self.workspace.save(value)
        changed=self.store.create({'taskId':'task-1','caseIds':['c1'],'name':'changed','environment':'local','productVersion':'v3'})
        other=self.store.record({'batchId':changed['id'],'caseId':'c1','result':'通过','actual':'different','requestId':'different-pass'})
        with self.assertRaises(ValueError):
            self.store.review_issue({'issueId':issue['id'],'type':'产品缺陷','status':'已关闭','note':'wrong scope','regressionAttemptId':other['id']})

class ImportBackupTests(unittest.TestCase):
    def test_csv_multiline_and_validation(self):
        from .case_import import parse_csv
        result=parse_csv({'text':'title,priority,layer,basis,steps,expected\n"标题,逗号",P1,UI,REQ-1,"步骤一\n步骤二",结果'})
        self.assertEqual(result['cases'][0]['steps'],'步骤一\n步骤二')
        for text in ('title,title\na,b', 'title,priority,layer,basis,steps,expected\nt,P9,UI,b,s,e', 'title,priority,layer,basis,steps,expected\n'):
            with self.assertRaises(ValueError):parse_csv({'text':text})

    def test_backup_integrity_restore_and_traversal(self):
        from .backup import backup,verify_backup
        from .maintenance import restore_to
        import io, json
        from zipfile import ZipFile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'data';root.mkdir();(root/'workspace.json').write_text('{"revision":1,"data":null}',encoding='utf-8')
            (root/'secret.env').write_text('not part of backup')
            content=backup(root);manifest=verify_backup(content)
            self.assertEqual(set(manifest['files']),{'workspace.json'})
            archive=Path(tmp)/'backup.zip';archive.write_bytes(content)
            restored=Path(tmp)/'restored';restore_to(archive,restored)
            self.assertEqual((root/'workspace.json').read_bytes(),(restored/'workspace.json').read_bytes())
            with self.assertRaises(ValueError):restore_to(archive,restored)
            bad=io.BytesIO()
            with ZipFile(bad,'w') as z:
                z.writestr('../evil.txt','bad');z.writestr('manifest.json',json.dumps(manifest))
            with self.assertRaises(ValueError):verify_backup(bad.getvalue())

    def test_process_lease_rejects_second_writer(self):
        from .lease import WorkspaceLease
        with tempfile.TemporaryDirectory() as tmp:
            first=WorkspaceLease(tmp)
            try:
                with self.assertRaises(OSError):WorkspaceLease(tmp)
            finally:first.close()
            second=WorkspaceLease(tmp);second.close()

    def test_external_workspace_change_does_not_overwrite(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'workspace.json';jobs=JobStore(Path(tmp)/'jobs');workspace=Workspace(path,jobs)
            workspace.save({'revision':0,'data':{'tasks':[]}})
            stale=workspace.get()
            path.write_text(json.dumps({'revision':1,'data':{'tasks':[],'outside':'preserved'}}),encoding='utf-8')
            from .workspace import Conflict
            with self.assertRaises(Conflict):workspace.save(stale)
            self.assertEqual(workspace.get()['data']['outside'],'preserved')
    def test_feedback_requires_evidence_and_human_review(self):
        from .execution import Execution
        from .knowledge import Knowledge
        from .jobs import JobStore
        from .workspace import Workspace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ws=Workspace(root/'workspace.json',JobStore(root/'jobs'))
            ws.save({'revision':0,'data':{'tasks':[{'id':'t','name':'task','cases':[{'id':'c','title':'case','steps':'s','expected':'e','confirmed':True}],'issues':[],'attempts':[],'runs':[]}]}})
            ex=Execution(root/'execution',ws);knowledge=Knowledge(root/'knowledge',{'workbench-notes':root/'notes'})
            with self.assertRaises(ValueError):ex.propose_feedback({'reportId':'missing','title':'t','content':'c','basis':'b'})
            b=ex.create({'taskId':'t','caseIds':['c'],'name':'b','productVersion':'v1','environment':'local'})
            ex.close_batch({'batchId':b['id'],'conclusion':'not run'})
            r=ex.freeze({'batchId':b['id'],'notes':'none executed'})
            p=ex.propose_feedback({'reportId':r['id'],'title':'Setup prerequisite','content':'Check environment before execution.','basis':'No result; process advice only.'})
            self.assertEqual(knowledge.get()['documents'],[])
            from unittest.mock import patch
            with patch.object(knowledge, 'refresh', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    ex.review_feedback({'id':p['id'],'decision':'已采纳','note':'Scope limited to preparation'},knowledge)
            ex=Execution(root/'execution',ws)
            ex.resume_feedback(knowledge)
            self.assertEqual(ex.get('t')['feedback'][0]['status'],'已采纳')
            self.assertEqual(knowledge.get()['documents'][0]['status'],'已确认')
            self.assertTrue((root/'notes'/f"{p['id']}.md").exists())
            with self.assertRaises(ValueError):ex.review_feedback({'id':p['id'],'decision':'已采纳','note':'repeat'},knowledge)

    def test_http_local_features_and_no_cache(self):
        from .server import make_server
        import threading, json
        from urllib.request import Request, urlopen
        with tempfile.TemporaryDirectory() as tmp:
            server=make_server(0,Path(tmp)/'jobs')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                for route in ('/api/knowledge','/api/execution','/api/execution/missing','/api/diagnostics'):
                    with urlopen(base+route) as response:
                        self.assertEqual(response.status,200);json.load(response)
                with urlopen(base+'/execution.js?v=test') as response:
                    self.assertIn('no-store',response.headers['Cache-Control']);self.assertIn(b'create',response.read())
                payload=json.dumps({'text':'title,priority,layer,basis,steps,expected\nt,P1,UI,b,s,e'}).encode()
                with urlopen(Request(base+'/api/cases/parse-csv',data=payload,headers={'Content-Type':'application/json'})) as response:
                    self.assertEqual(len(json.load(response)['cases']),1)
                with urlopen(base+'/api/backup') as response:
                    from .backup import verify_backup
                    self.assertEqual(verify_backup(response.read())['version'],1)
            finally:
                server.shutdown();server.server_close();server.store.shutdown();thread.join()
