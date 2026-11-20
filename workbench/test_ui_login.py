"""Login actions never require real credentials or a product connection in tests."""
import io
import time
import unittest
from unittest.mock import Mock, patch
from .ui_execution import UIExecutor


class LoginActionTests(unittest.TestCase):
    def test_invalid_action_and_environment_never_spawn(self):
        executor=UIExecutor()
        with patch.object(executor,'environments',return_value={'environments':[{'id':'fixture'}]}),patch('workbench.ui_execution.subprocess.Popen') as spawn:
            for raw in ({'environment':'fixture','action':'shell'},{'environment':'unknown','action':'login'}):
                with self.assertRaises(ValueError):executor.login_action(raw)
            spawn.assert_not_called()

    def test_async_progress_and_completion(self):
        executor=UIExecutor()
        process=Mock(stdout=io.StringIO('等待扫码\n登录验证成功，已加密保存\n'))
        process.wait.return_value=0
        with patch.object(executor,'environments',return_value={'environments':[{'id':'fixture'}]}),patch('workbench.ui_execution.subprocess.Popen',return_value=process) as spawn:
            executor.login_action({'environment':'fixture','action':'login'})
            deadline=time.monotonic()+3
            while executor.auth_operations['fixture']['status']=='running' and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(executor.auth_operations['fixture']['status'],'complete')
            self.assertIn('加密保存',executor.auth_operations['fixture']['message'])
            self.assertEqual(spawn.call_args.args[0][-3:],['auth','fixture','login'])
            self.assertNotIn('shell',spawn.call_args.kwargs)
