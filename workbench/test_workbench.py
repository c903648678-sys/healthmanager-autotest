"""Deterministic tests; no model calls or credentials required."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import sys
import unittest
from unittest.mock import patch

from .contracts import expert_context, validate_input, validate_result, PLAN_FIELDS, PLAN_SCHEMA, CASE_SCHEMA
from .jobs import JobStore
from .providers import ClaudeProvider, CodexProvider, ProviderError, ProgressReader, run_provider
from .server import make_server


def payload():
    return {"taskId": "test-task", "provider": "codex", "sources": [{"id": "S1", "name": "需求.md", "text": "编辑者可以创建字段。"}]}


def result():
    return {"summary": "分析字段创建", "requirements": [{"id": "R1", "title": "创建字段", "understanding": "编辑者创建字段", "acceptance": "创建成功", "citations": [{"sourceId": "S1", "quote": "编辑者可以创建字段。"}]}],
            "questions": [{"id": "Q1", "title": "长度上限", "reason": "未定义", "impact": "边界", "blocking": True, "suggestion": "请确认", "citations": []}], "risks": [], "warnings": []}


def fake_runner(*args):
    return result()


def plan_result():
    return {**{k:'针对本次需求的方案内容' for k in PLAN_FIELDS}, 'coverage':[{'requirementId':'R1','disposition':'included','approach':'验证创建后持久化','reason':'需求R1明确要求'}], 'openItems':[]}


def wait_job(store, job_id):
    for _ in range(100):
        job = store.get(job_id)
        if job["status"] in ("failed", "succeeded", "cancelled"):
            return job
        time.sleep(.02)
    raise AssertionError("job did not finish")


class ContractTests(unittest.TestCase):
    def test_input_duplicates_and_limits(self):
        value = payload()
        value["sources"] *= 2
        with self.assertRaises(ValueError):
            validate_input(value)
        value = payload()
        value["sources"][0]["text"] = "中" * 70000
        with self.assertRaises(ValueError):
            validate_input(value)

    def test_citations_must_match_original(self):
        validate_result(result(), payload())
        value = result()
        value["requirements"][0]["citations"][0]["quote"] = "只读用户可以创建"
        with self.assertRaises(ValueError):
            validate_result(value, payload())

    def test_reject_unknown_fields_and_duplicate_ids(self):
        value = result()
        value["requirements"] *= 2
        with self.assertRaises(ValueError):
            validate_result(value, payload())
        value = result()
        value["run_command"] = "anything"
        with self.assertRaises(ValueError):
            validate_result(value, payload())

    def test_legacy_expert_sections_loaded_not_copied(self):
        context, metadata = expert_context()
        self.assertIn("EARS", context)
        self.assertIn("三件套分工", context)
        self.assertEqual(len(metadata["digest"]), 64)
        self.assertNotIn("一条龙（生成→执行）", context)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(self.tmp.name, runner=fake_runner)

    def test_review_and_restart(self):
        job = wait_job(self.store, self.store.create(payload())["id"])
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual([e['stage'] for e in job['events']], ['preparing', 'validating', 'succeeded'])
        self.assertGreaterEqual(job['elapsedSeconds'], 0)
        request = {"inputDigest": job["inputDigest"], "accepted": True, "answers": []}
        with self.assertRaises(ValueError):
            self.store.review(job["id"], request)
        request["answers"] = [{"questionId": "Q1", "question": "长度上限", "status": "answered", "answer": "20", "basis": "产品确认"}]
        self.store.review(job["id"], request)
        restored = JobStore(self.tmp.name).get(job["id"])
        self.assertTrue(restored["review"]["accepted"])
        request["inputDigest"] = "stale"
        with self.assertRaises(ValueError):
            self.store.review(job["id"], request)

    def test_failed_review_commit_can_retry(self):
        job=wait_job(self.store,self.store.create(payload())['id'])
        raw={'expectedReviewDigest':job['reviewDigest'],'inputDigest':job['inputDigest'],'accepted':False,'answers':[]}
        with patch.object(Path,'replace',side_effect=OSError('busy')):
            with self.assertRaises(OSError):self.store.review(job['id'],raw)
        self.assertIsNone(self.store.get(job['id'])['review'])
        self.assertEqual(self.store.review(job['id'],raw).get('reviewHistory',[]),[])
    def test_stale_review_preserves_confirmed_answers(self):
        from .workspace import Conflict
        job = wait_job(self.store, self.store.create(payload())['id'])
        draft = {'inputDigest':job['inputDigest'], 'expectedReviewDigest':job['reviewDigest'],
                 'accepted':False, 'answers':[]}
        confirmed = self.store.review(job['id'], {**draft, 'accepted':True, 'answers':[
            {'questionId':'Q1','question':'长度','status':'answered','answer':'20','basis':'产品确认'}]})
        with self.assertRaises(Conflict):
            self.store.review(job['id'], draft)
        self.store.review(job['id'], {**draft, 'expectedReviewDigest':confirmed['reviewDigest']})
        restored = JobStore(self.tmp.name).get(job['id'])
        self.assertEqual(restored['reviewHistory'], [confirmed['review']])

    def test_cancellation_and_duplicate_prevention(self):
        def slow(*args):
            args[4].wait(2)
            return result()
        self.store.runner = slow
        job = self.store.create(payload())
        with self.assertRaises(ValueError):
            self.store.create(payload())
        self.store.cancel(job["id"])
        final = wait_job(self.store, job["id"])
        self.assertEqual(final["status"], "cancelled")
        self.assertIsNone(final["result"])

    def test_invalid_model_result_cannot_be_reviewed(self):
        self.store.runner = lambda *args: {"summary": "bad shape"}
        job = wait_job(self.store, self.store.create(payload())["id"])
        self.assertEqual(job["status"], "failed")
        with self.assertRaises(ValueError):
            self.store.review(job["id"], {})

    def test_restart_interrupts_unfinished_job(self):
        job = wait_job(self.store, self.store.create(payload())["id"])
        job["status"] = "running"
        self.store._persist(job)
        self.assertEqual(JobStore(self.tmp.name).get(job["id"])["status"], "interrupted")


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(self.tmp.name, fake_runner)
        self.parent = wait_job(self.store, self.store.create(payload())['id'])
        self.answers = [{'questionId':'Q1','question':'长度上限','status':'answered','answer':'20','basis':'合成确认'}]
        self.parent = self.store.review(self.parent['id'], {'expectedReviewDigest':self.parent['reviewDigest'],'inputDigest':self.parent['inputDigest'],'accepted':True,'answers':self.answers})
        self.request = {'taskId':'test-task','provider':'codex','kind':'test-plan','analysisJobId':self.parent['id'],'analysisReviewDigest':self.parent['reviewDigest']}
        self.store.runner = lambda *args: plan_result()

    def test_plan_uses_server_baseline_and_schema(self):
        captured = []
        def runner(*args):
            captured.append(args)
            return plan_result()
        self.store.runner = runner
        job = wait_job(self.store, self.store.create({**self.request,'sources':[{'id':'forged'}]})['id'])
        self.assertEqual(job['status'], 'succeeded')
        self.assertEqual(captured[0][7], PLAN_SCHEMA)
        saved = json.loads((Path(self.tmp.name)/job['id']/'input.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['sources'], payload()['sources'])
        self.assertEqual(saved['confirmedReview']['answers'], self.answers)

    def test_plan_rejects_unconfirmed_or_cross_task_baseline(self):
        for change in ({'taskId':'other-task'},{'analysisReviewDigest':'stale'}):
            with self.assertRaises(ValueError):
                self.store.create({**self.request,**change})
        self.store.review(self.parent['id'], {'expectedReviewDigest':self.parent['reviewDigest'],'inputDigest':self.parent['inputDigest'],'accepted':False,'answers':self.answers})
        with self.assertRaises(ValueError):
            self.store.create(self.request)

    def test_coverage_omissions_and_fabricated_ids_fail(self):
        for coverage in ([],[{**plan_result()['coverage'][0], 'requirementId':'fake'}]):
            self.store.runner=lambda *args: {**plan_result(),'coverage':coverage}
            job=wait_job(self.store,self.store.create(self.request)['id'])
            self.assertEqual(job['status'],'failed')

    def test_edited_plan_persists_and_stale_confirmation_rejected(self):
        job=wait_job(self.store,self.store.create(self.request)['id'])
        draft=plan_result();draft['objective']='人工修改的测试目标'
        request={'inputDigest':job['inputDigest'],'draft':draft,'accepted':False}
        saved=self.store.review(job['id'], request)
        self.store.review(job['id'], {**request,'expectedReviewDigest':saved['reviewDigest'],'accepted':True})
        restored=JobStore(self.tmp.name).get(job['id'])
        self.assertEqual(restored['review']['draft']['objective'], draft['objective'])
        self.assertTrue(restored['review']['accepted'])
        self.assertEqual(len(restored['reviewHistory']),1)
        self.store.review(self.parent['id'], {'expectedReviewDigest':self.parent['reviewDigest'],'inputDigest':self.parent['inputDigest'],'accepted':False,'answers':self.answers})
        self.assertFalse(self.store.get(job['id'])['basisCurrent'])
        with self.assertRaises(ValueError):
            self.store.review(job['id'], {**request,'accepted':True})

    def test_unresolved_questions_cannot_disappear(self):
        context={'kind':'test-plan','analysis':result(),'confirmedReview':{'answers':[]}}
        with self.assertRaises(ValueError):
            validate_result(plan_result(),context)
        validate_result({**plan_result(),'openItems':[{'questionId':'Q1','handling':'暂缓边界验证，等待产品确认'}]},context)


def case_result():
    return {'title': '字段创建用例集', 'cases': [{'id':'TC-001','group':'正常流程','title':'创建文本字段',
        'requirementIds':['R1'],'layer':'UI','priority':'P1','preconditions':'编辑者打开独立表',
        'testData':'备注','steps':[{'action':'创建字段并刷新','expected':'仅新增一个备注字段'}],
        'cleanup':'清理测试表','dependencies':'需准备测试环境'}], 'openItems':[]}


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(self.tmp.name, fake_runner)
        self.parent = wait_job(self.store,self.store.create(payload())['id'])
        self.parent = self.store.review(self.parent['id'], {'expectedReviewDigest':self.parent['reviewDigest'],'inputDigest':self.parent['inputDigest'], 'accepted':True,
            'answers':[{'questionId':'Q1','question':'长度','status':'answered','answer':'20','basis':'测试规格'}]})
        self.store.runner=lambda *args: plan_result()
        plan=wait_job(self.store,self.store.create({'kind':'test-plan','taskId':'test-task','analysisJobId':self.parent['id'],'analysisReviewDigest':self.parent['reviewDigest']})['id'])
        self.plan=self.store.review(plan['id'],{'inputDigest':plan['inputDigest'],'accepted':True,'draft':plan_result()})
        self.request={'kind':'test-cases','taskId':'test-task','planJobId':plan['id'],'planReviewDigest':self.plan['reviewDigest']}
        self.store.runner=lambda *args: case_result()

    def test_server_plan_and_case_schema(self):
        captured=[]
        def runner(*args):
            captured.append(args)
            return case_result()
        self.store.runner=runner
        job=wait_job(self.store,self.store.create({**self.request,'plan':{'forged':True}})['id'])
        self.assertEqual(job['status'],'succeeded')
        self.assertEqual(captured[0][7],CASE_SCHEMA)
        saved=json.loads((Path(self.tmp.name)/job['id']/'input.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['plan'],self.plan['review']['draft'])

    def test_unconfirmed_and_cross_task_rejected(self):
        for changes in ({'taskId':'other'},{'planReviewDigest':'old'}):
            with self.assertRaises(ValueError):self.store.create({**self.request,**changes})
        self.store.review(self.plan['id'],{'expectedReviewDigest':self.plan['reviewDigest'],'inputDigest':self.plan['inputDigest'],'accepted':False,'draft':plan_result()})
        with self.assertRaises(ValueError):self.store.create(self.request)

    def test_empty_duplicate_and_uncovered_cases_rejected(self):
        original=json.loads((Path(self.tmp.name)/self.plan['id']/'input.json').read_text(encoding='utf-8'))
        context={**original,'kind':'test-cases','plan':plan_result()}
        for change in ('empty','duplicate','unknown','step','open'):
            draft=case_result()
            if change=='empty':draft['cases']=[]
            if change=='duplicate':draft['cases']*=2
            if change=='unknown':draft['cases'][0]['requirementIds']=['fake']
            if change=='step':draft['cases'][0]['steps'][0]['expected']=''
            if change=='open':draft['openItems']=[{'questionId':'fake','handling':'待确认'}]
            with self.assertRaises(ValueError):validate_result(draft,context)
        context['plan']['coverage'].append({'requirementId':'R2','disposition':'included'})
        with self.assertRaises(ValueError):validate_result(case_result(),context)

    def test_review_restores_and_requirement_change_invalidates(self):
        job=wait_job(self.store,self.store.create(self.request)['id'])
        draft=case_result();draft['cases'][0]['title']='人工调整标题'
        review={'inputDigest':job['inputDigest'],'draft':draft,'accepted':True}
        self.store.review(job['id'],review)
        self.assertEqual(JobStore(self.tmp.name).get(job['id'])['review']['draft'],draft)
        self.store.review(self.parent['id'],{'expectedReviewDigest':self.parent['reviewDigest'],'inputDigest':self.parent['inputDigest'],'accepted':False,'answers':[]})
        self.assertFalse(self.store.get(job['id'])['basisCurrent'])
        with self.assertRaises(ValueError):self.store.review(job['id'],review)

    def test_plan_revision_invalidates_case_confirmation(self):
        job=wait_job(self.store,self.store.create(self.request)['id'])
        changed=plan_result();changed['strategy']='更新后的策略'
        self.store.review(self.plan['id'],{'expectedReviewDigest':self.plan['reviewDigest'],'inputDigest':self.plan['inputDigest'],'accepted':True,'draft':changed})
        self.assertFalse(self.store.get(job['id'])['basisCurrent'])
        with self.assertRaises(ValueError):
            self.store.review(job['id'],{'inputDigest':job['inputDigest'],'accepted':True,'draft':case_result()})

    def test_design_completion_checks_local_edits_and_current_baseline(self):
        from .workspace import Workspace
        job=wait_job(self.store,self.store.create(self.request)['id'])
        job=self.store.review(job['id'],{'inputDigest':job['inputDigest'],'accepted':True,'draft':case_result()})
        workspace=Workspace(Path(self.tmp.name)/'workspace.json',self.store)
        task={'id':'test-task','name':'设计完成验证','version':'V1','cases':[], 'issues':[], 'attempts':[], 'runs':[],
              'sources':payload()['sources'],'ai':{'job':self.parent,'answers':self.parent['review']['answers']},
              'planner':{'job':self.plan,'draft':self.plan['review']['draft']},'caseDesigner':{'job':job,'draft':job['review']['draft']}}
        workspace.save({'revision':0,'data':{'tasks':[task]}})
        raw=workspace.get();raw['data']['tasks'][0]['caseDesigner']['draft']['title']='未确认标题'
        workspace.save(raw)
        with self.assertRaises(ValueError):workspace.transition('test-task','complete',{'revision':2,'reason':'设计完成','designOnly':True})
        raw=workspace.get();raw['data']['tasks'][0]['caseDesigner']['draft']=job['review']['draft'];workspace.save(raw)
        value=workspace.transition('test-task','complete',{'revision':3,'reason':'设计已确认，尚未执行','designOnly':True})
        self.assertTrue(value['data']['tasks'][0]['lifecycle']['completion']['designOnly'])


class ProviderTests(unittest.TestCase):
    def test_progress_maps_events_without_leaking_content(self):
        messages = []
        reader = ProgressReader(Path('.'), 'codex', lambda *event: messages.append(event))
        reader.consume('stdout.log', json.dumps({'type':'thread.started'}))
        reader.consume('stdout.log', json.dumps({'type':'error','message':'Reconnecting... 2/5 private-token'}))
        reader.consume('stderr.log', 'falling back to HTTP private-token')
        reader.consume('stdout.log', json.dumps({'type':'item.completed','item':{'type':'reasoning','text':'private-token'}}))
        self.assertEqual([m[0] for m in messages], ['connecting','reconnecting','reconnecting','analyzing'])
        self.assertNotIn('private-token', str(messages))

    def test_progress_arrives_before_process_completion(self):
        events = []
        code = "import json,time; print(json.dumps({'type':'thread.started'}),flush=True); time.sleep(.4); open('result.json','w').write('{}')"
        with tempfile.TemporaryDirectory() as tmp, patch('workbench.providers.executable', return_value=sys.executable), patch.object(CodexProvider, 'command', return_value=[sys.executable, '-c', code]):
            run_provider('codex', '', 'synthetic', Path(tmp), threading.Event(), 3, lambda *event: events.append(event))
        self.assertIn('connecting', [e[0] for e in events])
        self.assertLess([e[0] for e in events].index('connecting'), len(events)-1)

    def test_codex_and_claude_contract_flags(self):
        folder = Path(tempfile.gettempdir())
        args = CodexProvider().command("codex.exe", folder, "model;echo not-a-command")
        self.assertIn("read-only", args)
        self.assertIn("--ignore-user-config", args)
        self.assertIn("model;echo not-a-command", args)
        args = ClaudeProvider().command("claude.exe", folder, "")
        self.assertEqual(args[args.index("--tools")+1], "")
        self.assertIn("--safe-mode", args)

    def test_claude_envelope_errors_and_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stdout.log"
            path.write_text(json.dumps({"is_error": False, "structured_output": result()}), encoding="utf-8")
            self.assertEqual(ClaudeProvider().result(Path(tmp)), result())
            path.write_text('{"is_error":true}', encoding="utf-8")
            with self.assertRaises(ProviderError):
                ClaudeProvider().result(Path(tmp))

    def test_timeout_stops_actual_child_process(self):
        with tempfile.TemporaryDirectory() as tmp, patch('workbench.providers.executable', return_value=sys.executable), patch.object(CodexProvider, 'command', return_value=[sys.executable, '-c', 'import time; time.sleep(30)']):
            start = time.monotonic()
            with self.assertRaisesRegex(ProviderError, '超过'):
                run_provider('codex', '', 'synthetic', Path(tmp), threading.Event(), timeout=.05)
            self.assertLess(time.monotonic() - start, 5)


class HTTPTests(unittest.TestCase):
    def test_workspace_routes_conflict_and_model_guard(self):
        from .test_workspace import task_record
        with tempfile.TemporaryDirectory() as tmp:
            server=make_server(0,tmp,fake_runner)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            def request(path, body=None):
                conn.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),{'Content-Type':'application/json'})
                response=conn.getresponse()
                return response.status,json.loads(response.read())
            try:
                self.assertEqual(request('/api/workspace')[1]['revision'],0)
                status,value=request('/api/workspace',{'revision':0,'data':{'tasks':[task_record()]}})
                self.assertEqual(status,200)
                self.assertEqual(request('/api/workspace',{'revision':0,'data':value['data']})[0],409)
                self.assertEqual(request('/api/tasks/TASK-test/pause',{'revision':1})[0],200)
                self.assertEqual(request('/api/jobs',{**payload(),'taskId':'TASK-test'})[0],400)
                self.assertEqual(request('/api/tasks/TASK-test/delete',{'revision':2})[0],200)
                self.assertEqual(request('/api/tasks/TASK-test/restore',{'revision':3})[1]['data']['tasks'][0]['lifecycle']['status'],'paused')
            finally:
                conn.close();server.shutdown();server.server_close()

    def test_local_api_roundtrip_and_origin_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = make_server(0, tmp, fake_runner)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(OSError):
                    make_server(server.server_port, tmp, fake_runner)
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", "/api/health")
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["service"], "healthmanager-workbench")
                conn.request("POST", "/api/jobs", json.dumps(payload()), {"Content-Type": "application/json", "Origin": "https://example.com"})
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                conn.request("POST", "/api/jobs", json.dumps(payload()), {"Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 202)
                job = json.loads(response.read())
                self.assertEqual(wait_job(server.store, job["id"])["status"], "succeeded")
                conn.request("GET", "/../../.auth/secret")
                response = conn.getresponse()
                self.assertEqual(response.status, 404)
                response.read()
                conn.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
