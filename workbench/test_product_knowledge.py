from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
import unittest
from zipfile import ZipFile
from .knowledge import Knowledge
from .knowledge_suggestions import KnowledgeSuggestions
from .workspace import Conflict
from .backup import backup

class ProductKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        (self.source/'rules.md').write_text('# 字段规则\n字段名称唯一',encoding='utf-8')
        self.k=Knowledge(self.root/'knowledge',{'ui-specs':self.source});self.k.refresh()
        self.doc={'id':'local-one','name':'music.md','text':'# 文生音乐\n支持生成音乐'}
    def tearDown(self):self.temp.cleanup()
    def save(self,**changes):return self.k.organization_save({'revision':self.k.organization_get()['revision'],'meta':{},'local':[self.doc],**changes})
    def test_archive_refresh_restart_backup(self):
        self.save(meta={'local-one':{'product':'AIGC','subproduct':'文生音乐','feature':'生成','title':'音乐规格'}})
        self.k.refresh();restored=Knowledge(self.root/'knowledge',{'ui-specs':self.source})
        d=next(x for x in restored.get()['documents'] if x['id']=='local-one')
        self.assertEqual(d['metadata']['product'],'AIGC');self.assertEqual(d['text'],self.doc['text'])
        with ZipFile(BytesIO(backup(self.root))) as z:self.assertIn('knowledge/organization.json',z.namelist())
    def test_conflicting_tabs_do_not_overwrite(self):
        self.save()
        with self.assertRaises(Conflict):self.save(revision=0)
    def test_review_cannot_be_forged_by_organization_save(self):
        s=self.save();d=s['local'][0]
        self.k.review({'id':d['id'],'hash':d['hash'],'status':'已确认','note':'依据当前产品规格核对'})
        self.save(local=[{**self.doc,'status':'已失效','revision':99}])
        self.assertEqual(self.k.organization_get()['local'][0]['status'],'已确认')
        with self.assertRaises(ValueError):self.save(local=[{**self.doc,'text':'覆盖正文'}])
        with self.assertRaises(ValueError):self.save(local=[])
    def test_invalid_file_and_metadata(self):
        for local in ([{**self.doc,'text':'a'*210000}],[{**self.doc,'name':'script.exe'}],[self.doc,self.doc]):
            with self.assertRaises(ValueError):self.save(local=local)
        with self.assertRaises(ValueError):self.save(meta={'x':{'title':{}}})
    def test_suggestion_requires_evidence_and_never_saves(self):
        self.save();before=self.k.organization_get()
        for quote,expected in [('支持生成音乐','succeeded'),('不存在的原文','failed')]:
            scratch=[]
            def runner(*a,**kw):
                scratch.append(a[3])
                (a[3]/'prompt.txt').write_text('private fixture')
                return {'product':'AIGC','subproduct':'文生音乐','feature':'生成','reason':'正文提到音乐','quote':quote}
            s=KnowledgeSuggestions(self.k,runner);j=s.create({'documentId':'local-one','provider':'codex'})
            for _ in range(100):
                j=s.get(j['id'])
                if j['status']!='running':break
                time.sleep(.01)
            self.assertEqual(j['status'],expected);self.assertEqual(before,self.k.organization_get())

            self.assertFalse(scratch[0].exists())

    def test_legacy_provider_files_excluded_from_backup(self):
        folder=self.k.folder/'suggestions'/'legacy'
        folder.mkdir(parents=True)
        (folder/'stdout.log').write_text('private fixture')
        with ZipFile(BytesIO(backup(self.root))) as archive:
            self.assertNotIn('knowledge/suggestions/legacy/stdout.log',archive.namelist())
