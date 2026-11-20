"""Offline unlimited batches, manual cancellation and historical deadline evidence."""
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from .ui_execution import UIExecutor, run_timeout_seconds


class RunTimeoutTests(unittest.TestCase):
    def test_batches_have_no_total_deadline(self):
        for count, workers in ((126, 5), (1130, 6), (10000, 1)):
            self.assertIsNone(run_timeout_seconds(count, workers))

    def execute_at(self, elapsed, cancel=False):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executor = UIExecutor(root)
            executor.ui.mkdir(parents=True)
            executor.python = root / "python.exe"
            executor.python.touch()
            snapshot = {"suite": {"content": {"layer": "UI"}},
                        "workers": 5, "cases": [{"assetId": str(i), "content": {"title": str(i)}} for i in range(1130)]}
            process = Mock()
            process.poll.side_effect = [None, 0]
            process.returncode = 0
            with (
                patch("workbench.ui_execution.subprocess.Popen", return_value=process),
                patch("workbench.ui_execution.subprocess.run"),
                patch("workbench.ui_execution.time.monotonic", side_effect=[0, elapsed]),
                patch.object(executor, "read_evidence", return_value={"status": "interrupted", "results": []}) as read,
            ):
                event = threading.Event()
                if cancel: event.set()
                executor.execute(snapshot, root / "output", event, lambda message: None)
                return process, read.call_args

    def test_batch_survives_previous_and_day_long_deadlines(self):
        for elapsed in (3601, 12241, 86401, 604800):
            process, call = self.execute_at(elapsed)
            process.wait.assert_not_called()
            self.assertFalse(call.args[2])
            self.assertIsNone(call.args[4])

    def test_unlimited_batch_still_honors_manual_stop(self):
        process, call = self.execute_at(12241, cancel=True)
        process.wait.assert_called_once()
        self.assertTrue(call.args[2])
        self.assertTrue(call.args[3])

    def test_timeout_message_reports_actual_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            result = UIExecutor.read_evidence(Path(temp), None, stopped=True, timeout_seconds=14460)
            self.assertIn("241 分钟", result["message"])
            cancelled = UIExecutor.read_evidence(Path(temp), None, stopped=True, cancelled=True, timeout_seconds=14460)
            self.assertEqual(cancelled["status"], "cancelled")
