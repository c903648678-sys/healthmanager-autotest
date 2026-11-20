import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from . import template_assets as templates
from .jobs import JobStore
from .test_design_assist import runner, SOURCE
from .test_workbench import wait_job


class TemplateTests(unittest.TestCase):
    def test_archive_integrity_and_ids(self):
        entries=templates.catalog()['templates']
        self.assertEqual(len(entries),9)
        self.assertEqual(sum(t['nodeCount'] for t in entries),1819)
        for item in entries:
            self.assertEqual(hashlib.sha256(templates.original(item['id']).read_bytes()).hexdigest(),item['sha256'])
            self.assertTrue(templates.snapshot([item['id']])[0]['text'])
        for value in ([], ['e2e','e2e'], ['../manifest'], ['e2e','api','app','security'], 'e2e', [{}]):
            with self.assertRaises(ValueError):templates.snapshot(value)

    def test_plan_selection_is_frozen_and_cases_inherit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=JobStore(tmp,runner=runner)
            base={'taskId':'t','provider':'codex','sources':[SOURCE]}
            def create(kind,**extra):
                job=wait_job(store,store.create({**base,'kind':kind,**extra})['id'])
                self.assertEqual(job['status'],'succeeded',job.get('message'))
                return job
            def review(job):
                return store.review(job['id'],{'accepted':True,'inputDigest':job['inputDigest'],'draft':job['result'],'answers':[]})
            analysis=review(create('requirements'))
            self.assertEqual(analysis['designTemplates'][0]['id'],'e2e')
            plan=review(create('test-plan',analysisJobId=analysis['id'],analysisReviewDigest=analysis['reviewDigest'],templateIds=['api','security']))
            self.assertEqual([t['id'] for t in plan['designTemplates']],['api','security'])
            # Existing confirmed snapshots must remain usable even if the library is unavailable.
            with patch.object(templates,'snapshot',side_effect=AssertionError('must use parent snapshot')):
                cases=create('test-cases',planJobId=plan['id'],planReviewDigest=plan['reviewDigest'],templateIds=['performance'])
            def inputs(job):return json.loads(Path(tmp,job['id'],'input.json').read_text(encoding='utf-8'))
            self.assertEqual(inputs(plan)['designTemplates'],inputs(cases)['designTemplates'])
            self.assertNotIn('text',cases['designTemplates'][0])
            self.assertTrue(inputs(cases)['designTemplates'][0]['text'])

    def test_outline_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'e2e').mkdir()
            (root/'manifest.json').write_text(json.dumps(templates.catalog()),encoding='utf-8')
            (root/'e2e'/'outline.md').write_text('modified',encoding='utf-8')
            with patch.object(templates,'ARCHIVE',root),self.assertRaises(ValueError):templates.snapshot()

if __name__=='__main__':unittest.main()
