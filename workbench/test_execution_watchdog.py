import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from .ui_execution import ExecutionWatchdog, UIExecutor


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)

    def live(self, rows):
        (self.folder/'live.json').write_text(json.dumps({'results':rows}),encoding='utf-8')

    def test_stuck_case_times_out_even_when_other_workers_progress(self):
        guard=ExecutionWatchdog(600)
        stuck={'nodeid':'stuck','title':'复制链接','status':'running','phase':'setup'}
        self.live([stuck]);self.assertIsNone(guard.check(self.folder,0))
        self.live([stuck,{'nodeid':'other','status':'passed'}])
        self.assertIsNone(guard.check(self.folder,599))
        self.assertEqual(guard.check(self.folder,600)['nodeid'],'stuck')

    def test_phase_change_does_not_reset_case_deadline(self):
        guard=ExecutionWatchdog(600)
        self.live([{'nodeid':'x','status':'running','phase':'setup'}]);guard.check(self.folder,0)
        self.live([{'nodeid':'x','status':'running','phase':'teardown'}])
        self.assertEqual(guard.check(self.folder,600)['nodeid'],'x')

    def test_completed_case_releases_timer_and_long_batch_can_continue(self):
        guard=ExecutionWatchdog(600)
        for index in range(10):
            self.live([{'nodeid':str(index),'status':'running'}])
            self.assertIsNone(guard.check(self.folder,index*500))

    def test_paused_active_clock_does_not_expire(self):
        guard=ExecutionWatchdog(600)
        self.live([{'nodeid':'x','status':'running'}]);guard.check(self.folder,0)
        for _ in range(20):self.assertIsNone(guard.check(self.folder,599))
        self.assertIsNotNone(guard.check(self.folder,600))

    def test_missing_telemetry_and_stuck_finalization_are_bounded(self):
        guard=ExecutionWatchdog(600);guard.check(self.folder,0)
        self.assertIsNotNone(guard.check(self.folder,600))
        self.live([{'nodeid':'x','status':'passed'}])
        self.assertIsNone(guard.check(self.folder,601))
        self.assertIsNotNone(guard.check(self.folder,1201))

    def test_unlimited_run_can_stop_preserving_completed_evidence(self):
        phases=[{'phase':p,'outcome':'passed'} for p in ('setup','call','teardown')]
        (self.folder/'phases.json').write_text(json.dumps({'done':phases,'stuck':phases[:1]}))
        (self.folder/'node-map.json').write_text(json.dumps({n:{'assetId':n,'title':n} for n in ('done','stuck')}))
        result=UIExecutor.read_evidence(self.folder,1,stopped=True,timeout_seconds=None)
        self.assertEqual(result['status'],'interrupted')
        self.assertEqual({r['nodeid']:r['status'] for r in result['results']},{'done':'passed','stuck':'interrupted'})

    def test_parent_kills_hung_tree_and_reports_unfinished_cases(self):
        executor=UIExecutor(self.folder);executor.python=Path(__file__)
        process=Mock(pid=123456,returncode=1)
        process.poll.return_value=None
        event=Mock();event.wait.return_value=False;event.is_set.return_value=False
        self.live([{'nodeid':'stuck','title':'复制','status':'running'}])
        result={'status':'interrupted','results':[{'assetId':'a','nodeid':'stuck','status':'interrupted'}]}
        snapshot={'suite':{'content':{'layer':'UI'}},'cases':[
            {'assetId':'a','content':{'title':'复制'}}, {'assetId':'b','content':{'title':'未开始'}}]}
        with patch('workbench.ui_execution.subprocess.Popen',return_value=process), \
             patch('workbench.ui_execution.subprocess.run') as kill, \
             patch('workbench.ui_execution.time.monotonic',side_effect=[0,0,601]), \
             patch.object(executor,'read_evidence',return_value=result):
            observed=executor.execute(snapshot,self.folder,event,lambda _:None)
        self.assertEqual(observed['status'],'interrupted')
        self.assertIn('未完成',observed['message'])
        self.assertEqual([r['status'] for r in observed['results']],['error','not_run'])
        self.assertTrue((self.folder/'watchdog.json').is_file())
        import os
        if os.name=='nt':self.assertEqual(kill.call_args.args[0],['taskkill','/PID','123456','/T','/F'])
        else:process.terminate.assert_called_once()
        process.wait.assert_called_once()
