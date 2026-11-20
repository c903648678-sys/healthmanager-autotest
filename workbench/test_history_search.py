from copy import deepcopy
from threading import RLock
import unittest
import json
import tempfile
from pathlib import Path
from .contracts import validate_input, validate_result
from .history_search import HistorySearch


class Store:
    def __init__(self, value):
        self.value = value
        self.lock = RLock()
        self.jobs = {}
    def get(self):
        return deepcopy(self.value)
    def refresh(self):
        return self.get()


class HistorySearchTests(unittest.TestCase):
    def setUp(self):
        self.knowledge = Store({'refreshedAt':'now','documents':[dict(id='d', name='字段规格', text='字段名称必须唯一', path='specs/ai_table/a.md', status='已确认', revision=1)]})
        self.assets = Store({'scannedAt':'now','cases':[dict(assetId='ui/cloud_docs/case_1', id='case_1', title='字段创建', specPath='ui/case_spec.json', product='Welink云文档', feature='ai_table/column', admission='待复核', steps='创建字段', expected='字段名称必须唯一'),dict(assetId='ui/doc_zip/case_2',id='case_2',title='字段创建',specPath='ui/other',product='DocZip',feature='ai_table',admission='静态可执行')]})
        self.search = HistorySearch(self.knowledge,self.assets,Store({'data':{'tasks':[]}}),Store({}))

    def test_retrieval_scope_and_stale_snapshot(self):
        response = self.search.search({'taskId':'t','product':'Welink云文档','query':'字段创建'})
        self.assertTrue(response['items'])
        self.assertFalse(any(r['product']=='DocZip' for r in response['items']))
        item = next(r for r in response['items'] if r['kind']=='知识规格')
        raw = {'taskId':'t','historyRefs':[{'id':item['id'],'hash':item['hash']}]}
        self.assertEqual(self.search.resolve(raw)[0]['text'],'字段名称必须唯一')
        self.knowledge.value['documents'][0]['status']='待确认'
        with self.assertRaises(ValueError):
            self.search.resolve(raw)
        self.assertEqual(self.search.search({'query':'totally_unrelated'})['items'], [])

    def test_cross_task_search_skips_unreviewed_jobs(self):
        self.search.workspace.value['data']['tasks'] = [
            {'id':'A','name':'字段'}, {'id':'B','name':'当前任务'}]
        confirmed = {'id':'confirmed','taskId':'A','kind':'test-plan','status':'succeeded',
                     'review':{'accepted':True,'draft':{'title':'字段方案'}}}
        for kind in ('test-plan','asset-mapping'):
            with self.subTest(kind=kind):
                self.search.store.jobs = {
                    'draft':{**confirmed,'id':'draft','kind':kind,'review':None},
                    'confirmed':confirmed}
                result = self.search.search({'taskId':'B','query':'字段'})
                plans = [r for r in result['items'] if r['kind']=='历史测试方案']
                self.assertEqual([r['id'] for r in plans], ['history:plan/confirmed'])
                self.assertEqual(self.search.resolve({'taskId':'B','historyRefs':plans})[0]['hash'],plans[0]['hash'])

    def test_evidence_cannot_promote_history_into_requirement(self):
        ref=self.search.catalog('t')[0]
        payload=validate_input({'taskId':'t','sources':[{'id':'s','name':'current','text':'允许创建字段'}],'references':[ref]})
        result={'summary':'分析','requirements':[dict(id='R1',title='创建字段',understanding='创建',acceptance='待确认',citations=[{'sourceId':'s','quote':'允许创建字段'}])], 'questions':[], 'risks':[dict(title='【复用建议】字段用例',impact='需确认规则',testDirection='核对旧规则',citations=[{'sourceId':ref['id'],'quote':'字段名称必须唯一'}])], 'warnings':[]}
        validate_result(result,payload)
        result['risks'][0]['citations'][0]['quote']='不存在的原文'
        with self.assertRaises(ValueError):validate_result(result,payload)
        result['risks']=[]
        result['requirements'][0]['citations']=[{'sourceId':ref['id'],'quote':'字段名称必须唯一'}]
        with self.assertRaises(ValueError):validate_result(result,payload)

    def test_missing_and_unselected_references(self):
        self.assertEqual(self.search.resolve({'taskId':'t'}),[])
        with self.assertRaises(ValueError):self.search.resolve({'taskId':'t','historyRefs':[{'id':'history:missing','hash':'bad'}]})
        self.knowledge.value['documents'][0]['missing']=True
        self.assertFalse(any(r['kind']=='知识规格' for r in self.search.catalog('t')))

    def test_reference_snapshot_reaches_model_and_next_stage(self):
        from .jobs import JobStore
        from .contracts import digest
        from .test_workbench import payload, result, plan_result, wait_job
        ref = self.search.catalog('t')[0]
        prompts = []
        def runner(*args):
            prompts.append(args[2])
            candidate = result()
            candidate['questions'] = []
            return candidate
        with tempfile.TemporaryDirectory() as folder:
            store = JobStore(folder, runner=runner)
            job = wait_job(store, store.create({**payload(), 'references':[ref]})['id'])
            self.assertEqual(job['status'],'succeeded')
            saved = json.loads(Path(folder,job['id'],'input.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['references'][0]['hash'], ref['hash'])
            self.assertEqual(job['references'][0]['name'],ref['name'])
            self.assertTrue(any(ref['id'] in str(prompt) for prompt in prompts))
            reviewed = store.review(job['id'], {'inputDigest':job['inputDigest'],'accepted':True,'answers':[]})
            store.runner=lambda *args:plan_result()
            plan = wait_job(store, store.create({**payload(),'kind':'test-plan','analysisJobId':job['id'], 'analysisReviewDigest':digest(reviewed['review'])})['id'])
            self.assertEqual(plan['status'],'succeeded')
            inherited=json.loads(Path(folder,plan['id'],'input.json').read_text(encoding='utf-8'))
            self.assertEqual(inherited['references'],saved['references'])


if __name__=='__main__':unittest.main()
