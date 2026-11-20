from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from .contracts import digest, validate_result
from .jobs import JobStore
from .test_workbench import wait_job, PLAN_FIELDS
from .history_search import HistorySearch
from .test_history_search import Store

SOURCE={'id':'S1','name':'规格','text':'编辑者可以创建字段。'}
REF={'id':'history:case1','name':'字段用例','text':'字段名称必须唯一','hash':'version1'}
QUOTE={'sourceId':'S1','quote':SOURCE['text']}
HQUOTE={'sourceId':REF['id'],'quote':REF['text']}
CARD={'product':'Welink云文档','subproduct':'ai_table','objects':['字段'],'operations':['创建'],'keywords':['字段','权限'],
      'points':[{'id':'U1','title':'创建字段','rule':'编辑者创建','change':'待确认变化','impact':'字段管理','citations':[QUOTE]}],'questions':['名称约束是否变化']}
MAPPING={'rows':[{'id':'M1','pointId':'U1','action':'modify','area':'requirement','assetIds':[REF['id']],
    'reason':'历史有名称校验','changes':'核对当前规则并补充编辑权限验证','citations':[QUOTE,HQUOTE],'decision':'pending','reviewNote':''}],'warnings':[]}


def runner(*args):
    properties=args[-1]['properties']
    if 'points' in properties:return deepcopy(CARD)
    if 'items' in properties:return {'items':[{'assetId':REF['id'],'relation':'related','reason':'同一字段对象','citations':[HQUOTE]}],'warnings':[]}
    if 'rows' in properties:return deepcopy(MAPPING)
    if 'requirements' in properties:return {'summary':'字段创建','requirements':[{'id':'U1','title':'创建字段','understanding':'编辑者创建','acceptance':'创建成功','citations':[QUOTE]}],'questions':[],'risks':[],'warnings':[]}
    if 'coverage' in properties:return {**{key:'基于 M1 修改 '+REF['id'] for key in PLAN_FIELDS},'coverage':[{'requirementId':'U1','disposition':'included','approach':'沿用 M1 增量验证','reason':'当前规格明确要求'}],'openItems':[]}
    return {'title':'字段用例集','cases':[{'id':'TC1','group':'本次需求验证','title':'编辑者创建','requirementIds':['U1'],'layer':'UI','priority':'P1','preconditions':'编辑者登录','testData':'独立字段','steps':[{'action':'创建','expected':'创建成功'}],'cleanup':'删除字段','dependencies':'M1 / '+REF['id']}],'openItems':[]}


class GuidedDesignTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=JobStore(self.tmp.name,runner=runner)
        self.raw={'taskId':'t','provider':'codex','sources':[SOURCE]}
    def tearDown(self):self.tmp.cleanup()
    def create(self, kind, **extra):
        job=wait_job(self.store,self.store.create({**self.raw,'kind':kind,**extra})['id'])
        self.assertEqual(job['status'],'succeeded',job.get('message'))
        return job
    def review(self,job,draft=None):
        return self.store.review(job['id'],{'expectedReviewDigest':job['reviewDigest'],'inputDigest':job['inputDigest'],'accepted':True,'draft':draft or job['result'],'answers':[]})
    def card(self):return self.review(self.create('asset-understanding'))

    def test_full_card_rank_mapping_requirements_plan_cases_chain(self):
        card=self.card()
        basis={'understandingJobId':card['id'],'understandingReviewDigest':card['reviewDigest'],'references':[REF]}
        rank=self.create('asset-retrieval',**basis)
        self.assertEqual(rank['result']['items'][0]['relation'],'related')
        mapping=self.create('asset-mapping',**basis)
        draft=deepcopy(mapping['result']);draft['rows'][0].update(decision='adjusted',reviewNote='补充权限边界')
        mapping=self.review(mapping,draft)
        self.assertEqual(mapping['review']['feedback'][0]['reviewNote'],'补充权限边界')
        analysis=self.create('requirements',mappingJobId=mapping['id'],mappingReviewDigest=mapping['reviewDigest'],references=[REF])
        analysis=self.review(analysis)
        plan=self.review(self.create('test-plan',analysisJobId=analysis['id'],analysisReviewDigest=analysis['reviewDigest']))
        cases=self.create('test-cases',planJobId=plan['id'],planReviewDigest=plan['reviewDigest'])
        self.assertEqual(cases['designTrace'][0]['assetIds'],[REF['id']])
        inputs=json.loads(Path(self.tmp.name,cases['id'],'input.json').read_text(encoding='utf-8'))
        self.assertEqual(inputs['designContext']['mapping']['rows'][0]['decision'],'adjusted')
        restored=JobStore(self.tmp.name)
        self.assertEqual(restored.get(mapping['id'])['review']['feedback'],mapping['review']['feedback'])
        changed=deepcopy(CARD);changed['keywords']=['字段重名']
        self.review(card,changed)
        self.assertFalse(self.store.get(mapping['id'])['basisCurrent'])
        self.assertFalse(self.store.get(plan['id'])['basisCurrent'])
        self.assertFalse(self.store.get(cases['id'])['basisCurrent'])

    def test_reject_unreviewed_mapping_and_changed_references(self):
        card=self.card();basis={'understandingJobId':card['id'],'understandingReviewDigest':card['reviewDigest'],'references':[REF]}
        mapping=self.create('asset-mapping',**basis)
        with self.assertRaises(ValueError):self.review(mapping)
        draft=deepcopy(mapping['result']);draft['rows'][0].update(decision='rejected',reviewNote='不适用')
        with self.assertRaises(ValueError):self.review(mapping,draft)
        draft['rows'][0].update(decision='accepted')
        mapping=self.review(mapping,draft)
        with self.assertRaises(ValueError):self.store.create({**self.raw,'mappingJobId':mapping['id'],'mappingReviewDigest':mapping['reviewDigest'],'references':[]})
        with self.assertRaises(ValueError):self.store.create({**self.raw,'kind':'asset-mapping',**basis,'instructions':'变化范围'})

    def test_forged_semantic_candidate_and_missing_mapping_evidence(self):
        payload={**self.raw,'kind':'asset-retrieval','references':[REF]}
        with self.assertRaises(ValueError):validate_result({'items':[],'warnings':[]},payload)
        mapping=deepcopy(MAPPING);mapping['rows'][0]['assetIds']=['history:fake']
        with self.assertRaises(ValueError):validate_result(mapping,{**payload,'kind':'asset-mapping','understanding':CARD})

    def test_defects_execution_and_feedback_search_sources(self):
        card=self.card();mapping=self.create('asset-mapping',understandingJobId=card['id'],understandingReviewDigest=card['reviewDigest'],references=[REF])
        draft=deepcopy(MAPPING);draft['rows'][0]['decision']='accepted';mapping=self.review(mapping,draft)
        issue={'id':'i','taskId':'t','batchId':'b','caseId':'c','title':'字段权限错误','type':'产品缺陷','status':'待回归','attemptIds':['a']}
        batch={'id':'b','name':'字段回归','environment':'test','productVersion':'v1','cases':[], 'attempts':[{'id':'a','result':'失败','caseId':'c','at':'now','actual':'字段创建未拒绝'}]}
        execution=Store({'issues':[issue],'batches':[batch],'reports':[{'id':'r','taskId':'t','batch':batch,'counts':{'失败':1},'notes':'字段权限异常','frozenAt':'now','revision':1}]})
        search=HistorySearch(Store({'documents':[],'refreshedAt':'now'}),Store({'cases':[]}),Store({'data':{'tasks':[{'id':'t','name':'字段权限','product':'Welink云文档'}]}}),self.store,execution)
        kinds={r['kind'] for r in search.search({'taskId':'other','query':'字段权限'})['items']}
        self.assertTrue({'审阅反馈','历史缺陷/问题','执行证据'}<=kinds)


if __name__=='__main__':unittest.main()
