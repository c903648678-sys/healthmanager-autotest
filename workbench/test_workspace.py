import json
from pathlib import Path
import tempfile
import unittest

from .jobs import JobStore
from .workspace import Workspace, Conflict


def task_record():
    return {'id':'TASK-test','name':'生命周期联调','version':'V1','requirementNo':'REQ-1','stage':'设计中',
            'cases':[{'id':'TC-1','confirmed':True}], 'issues':[], 'attempts':[], 'runs':[]}


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jobs=JobStore(Path(self.tmp.name)/'jobs')
        self.path=Path(self.tmp.name)/'workspace.json'
        self.store=Workspace(self.path,self.jobs)
        self.store.save({'revision':0,'data':{'tasks':[task_record()], 'docs':[{'name':'共享知识'}]}})

    def action(self, action, **values):
        return self.store.transition('TASK-test', action, {'revision':self.store.get()['revision'],**values})

    def test_purge_requires_trash_name_and_removes_only_owned_jobs(self):
        with self.assertRaises(ValueError):self.action('purge',confirmName=task_record()['name'])
        self.action('delete')
        with self.assertRaises(ValueError):self.action('purge',confirmName='wrong')
        for key, owner in [('owned','TASK-test'),('other','TASK-other')]:
            self.jobs.jobs[key]={'id':key,'taskId':owner,'status':'succeeded'}
            self.jobs._persist(self.jobs.jobs[key])
        value=self.action('purge',confirmName=task_record()['name'])
        self.assertEqual(value['data']['tasks'],[])
        self.assertEqual(len(value['data']['docs']),1)
        self.assertFalse((self.jobs.folder/'owned').exists())
        self.assertTrue((self.jobs.folder/'other').exists())
        self.assertNotIn('owned',self.jobs.jobs)
        self.assertEqual(json.loads(self.path.with_suffix('.previous.json').read_text(encoding='utf-8'))['data']['tasks'],[])
        resurrect=self.store.get();resurrect['data']['tasks']=[task_record()]
        with self.assertRaises(Conflict):self.store.save(resurrect)
        reloaded=Workspace(self.path,self.jobs)
        with self.assertRaises(Conflict):reloaded.save(resurrect)

    def test_purge_resumes_after_cleanup_interruption(self):
        from unittest.mock import patch
        self.action('delete')
        self.jobs.jobs['owned']={'id':'owned','taskId':'TASK-test','status':'succeeded'}
        self.jobs._persist(self.jobs.jobs['owned'])
        with patch('workbench.workspace.shutil.rmtree',side_effect=OSError('busy')):
            with self.assertRaises(OSError):
                self.action('purge',confirmName=task_record()['name'])
        restored=Workspace(self.path, JobStore(self.jobs.folder))
        self.assertEqual(restored.get()['data']['tasks'], [])
        self.assertFalse((self.jobs.folder/'owned').exists())

    def test_purge_blocks_active_jobs_and_stale_revision(self):
        self.action('delete');old=self.store.get()
        self.jobs.jobs['active']={'taskId':'TASK-test','status':'running'}
        with self.assertRaises(ValueError):self.action('purge',confirmName=task_record()['name'])
        self.jobs.jobs.clear();self.action('restore');self.action('delete')
        with self.assertRaises(Conflict):self.store.transition('TASK-test','purge',{**old,'confirmName':task_record()['name']})

    def test_pause_resume_cancel_reopen_and_complete(self):
        self.action('pause')
        with self.assertRaises(ValueError):self.store.assert_editable('TASK-test')
        self.action('resume')
        self.store.assert_editable('TASK-test')
        with self.assertRaises(ValueError):self.action('cancel')
        self.action('cancel',reason='需求撤回')
        self.action('reopen')
        value=self.action('complete',reason='本轮工作结束，未执行项保留')
        lc=value['data']['tasks'][0]['lifecycle']
        self.assertEqual(lc['status'],'completed')
        self.assertEqual(lc['completion']['attemptCount'],0)
        self.assertEqual(len(lc['history']),5)

    def test_delete_restore_preserves_all_assets_and_location(self):
        before=self.store.get()['data']
        value=self.action('delete')
        self.assertEqual(value['data']['tasks'][0]['cases'],before['tasks'][0]['cases'])
        self.assertEqual(value['data']['docs'],before['docs'])
        self.assertEqual(self.action('restore')['data']['tasks'][0]['lifecycle']['status'],'active')
        self.action('cancel',reason='不再开展')
        self.action('archive')
        self.action('delete')
        self.assertEqual(self.action('restore')['data']['tasks'][0]['lifecycle']['location'],'archive')
        self.action('unarchive')
        self.action('reopen')
        self.store.assert_editable('TASK-test')

    def test_version_conflict_prevents_lost_update(self):
        stale=self.store.get()
        self.action('edit',name='改名',requirementNo='REQ-2',description='说明')
        with self.assertRaises(Conflict):self.store.save(stale)
        with self.assertRaises(Conflict):self.store.transition('TASK-test','delete',stale)
        self.assertEqual(Workspace(self.path,self.jobs).get()['data']['tasks'][0]['name'],'改名')
        self.assertTrue(self.path.with_suffix('.previous.json').exists())

    def test_inflight_job_prevents_state_changes(self):
        self.jobs.jobs['job']={'taskId':'TASK-test','status':'running'}
        for action in ('pause','cancel','complete','delete'):
            with self.assertRaises(ValueError):self.action(action,reason='测试')
        self.jobs.jobs['job']['status']='cancelled'
        self.action('delete')

    def test_cannot_remove_records_or_forge_lifecycle(self):
        raw=self.store.get();raw['data']['tasks']=[]
        with self.assertRaises(ValueError):self.store.save(raw)
        raw=self.store.get();raw['data']['tasks'][0]['lifecycle']['status']='completed'
        with self.assertRaises(ValueError):self.store.save(raw)
        self.action('pause')
        raw=self.store.get();raw['data']['tasks'][0]['name']='不能写入'
        self.store.save(raw)
        self.assertEqual(self.store.get()['data']['tasks'][0]['name'],'生命周期联调')

    def test_design_completion_requires_confirmed_current_cases(self):
        with self.assertRaises(ValueError):self.action('complete',reason='设计完成',designOnly=True)

    def test_empty_workspace_remains_empty_after_restart(self):
        path=Path(self.tmp.name)/'empty.json'
        store=Workspace(path,self.jobs)
        store.save({'revision':0,'data':{'tasks':[]}})
        self.assertEqual(Workspace(path,self.jobs).get()['data']['tasks'],[])
        with self.assertRaises(ValueError):store.assert_editable('unknown')


if __name__=='__main__':unittest.main()
