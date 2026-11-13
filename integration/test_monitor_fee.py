"""Deadline, anchor, worker cleanup and publication policy without a live node."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

import monitor_fee as monitor
from testnet_probe import ProbeError

IDENTITY = "11" * 32
ANCHOR = {"input_id": IDENTITY, "height": 100, "header_hash": "22" * 32}


def observation(status):
    return {"status": status, "input_id": IDENTITY, "chain_proof": False, "transactions_submitted": 0,
            "confirmation_anchor": dict(ANCHOR) if status in {"confirming", "confirmed"} else None}


class MonitorTests(unittest.TestCase):
    def test_anchor_carried_until_confirmation(self):
        seen = []
        sequence = ["unspent", "confirming", "confirmed"]
        def read(anchor, remaining):
            seen.append(anchor)
            return observation(sequence[len(seen) - 1])
        r = monitor.poll(read, IDENTITY, None, duration=5, interval=0, max_attempts=5)
        self.assertEqual(r["status"], "confirmed")
        self.assertEqual(seen, [None, None, ANCHOR])
        self.assertEqual(r["last_anchor"], ANCHOR)

    def test_pending_attempt_limit(self):
        r = monitor.poll(lambda *args: observation("unspent"), IDENTITY, None, duration=5, interval=0, max_attempts=2)
        self.assertEqual((r["status"], r["reason"], r["attempts"]), ("timed-out", "attempt-limit", 2))

    def test_reorg_and_conflict_are_terminal(self):
        for status in ("reorged", "conflicting-spend"):
            read = Mock(return_value=observation(status))
            r = monitor.poll(read, IDENTITY, ANCHOR, duration=5, interval=0, max_attempts=3)
            self.assertEqual(r["status"], status)
            read.assert_called_once()

    def test_timeout_preserves_only_previous_valid_observation(self):
        read = Mock(side_effect=[observation("confirming"), subprocess.TimeoutExpired("fixture", 1)])
        r = monitor.poll(read, IDENTITY, None, duration=5, interval=0, max_attempts=3)
        self.assertEqual(r["reason"], "observation-timeout")
        self.assertEqual(r["last_observation"]["status"], "confirming")
        self.assertEqual(r["last_anchor"], ANCHOR)

    def test_late_confirmation_discarded(self):
        with patch.object(monitor.time, "monotonic", side_effect=[0, 0, 2, 2]):
            r = monitor.poll(lambda *args: observation("confirmed"), IDENTITY, None, duration=1, interval=0, max_attempts=1)
        self.assertEqual(r["reason"], "deadline")
        self.assertIsNone(r["last_observation"])

    def test_invalid_bounds_before_read(self):
        for args in ((0, 0, 1), (float("nan"), 0, 1), (True, 0, 1), (601, 0, 1), (1, -1, 1), (1, 2, 1), (1, 0, True), (1, 0, 1001)):
            read = Mock()
            with self.assertRaises(ProbeError):
                monitor.poll(read, IDENTITY, None, duration=args[0], interval=args[1], max_attempts=args[2])
            read.assert_not_called()

    def test_failure_and_wrong_identity_are_not_retried(self):
        for failure in (ProbeError("bad RPC"), {**observation("confirmed"), "input_id": "33" * 32},
                        {**observation("confirmed"), "transactions_submitted": True}):
            read = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
            with self.assertRaises(ProbeError):
                monitor.poll(read, IDENTITY, None, duration=5, interval=0, max_attempts=3)
            read.assert_called_once()

        changed = observation("confirmed")
        changed["confirmation_anchor"]["header_hash"] = "33" * 32
        with self.assertRaises(ProbeError):
            monitor.poll(Mock(side_effect=[observation("confirming"), changed]), IDENTITY, None,
                         duration=5, interval=0, max_attempts=3)

    def test_real_worker_timeout_terminates_and_reaps_child(self):
        original = subprocess.Popen
        children = []
        def sleeper(*args, **kwargs):
            p = original([sys.executable, "-c", "import time; time.sleep(30)"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            children.append(p)
            return p
        with patch.object(monitor.subprocess, "Popen", side_effect=sleeper):
            with self.assertRaises(subprocess.TimeoutExpired):
                monitor.worker_read({}, 0.05)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed and children[0].stderr.closed)

    def test_failed_worker_is_reaped(self):
        original = subprocess.Popen
        children = []
        def failure(*args, **kwargs):
            p = original([sys.executable, "-c", "raise SystemExit(1)"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            children.append(p)
            return p
        with patch.object(monitor.subprocess, "Popen", side_effect=failure), self.assertRaises(ProbeError):
            monitor.worker_read({}, 5)
        self.assertEqual(children[0].poll(), 1)

    def test_cli_status_and_failure_invalidate_stale_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "report.json"
            argv = ["monitor_fee", "--endpoint", "https://127.0.0.1:8555", "--max-fee", "20", "--depth", "3",
                    "--duration", "10", "--interval", "1", "--max-attempts", "2", "--report", str(report)]
            for key in ("binary", "manifest", "observation", "solution", "preparation", "signature-response", "ca-cert", "client-cert", "client-key"):
                argv.extend(["--" + key, str(root / key)])
            for status in ("confirmed", "timed-out", "reorged", "conflicting-spend"):
                with patch.object(sys, "argv", argv), patch.object(monitor, "monitor", return_value={"outcome": {"status": status}}), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(monitor.main(), 0 if status == "confirmed" else 3)
                self.assertEqual(json.loads(report.read_text())["outcome"]["status"], status)
            with patch.object(sys, "argv", argv), patch.object(monitor, "monitor", side_effect=KeyboardInterrupt), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(monitor.main(), 1)
            self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
