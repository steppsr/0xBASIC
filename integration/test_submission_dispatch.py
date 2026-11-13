"""Dispatch ordering, refusal and actual child cleanup; no live transactions."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import submission_dispatch as dispatch
from submission_attempt import read_attempt
from test_submission_transport import BUNDLE
from testnet_probe import ProbeError


def args(root):
    values = {n: root / n for n in ("binary", "manifest", "observation", "solution", "preparation", "signature_response",
                                  "attempt", "ca_cert", "client_cert", "client_key")}
    return SimpleNamespace(**values, duration=10, timeout=2, max_fee=20, max_observation_age=300,
                           approved_bundle_id="11" * 32, endpoint="https://127.0.0.1:8555")


def verified():
    return {"bundle_id": "11" * 32, "bundle_sha256": "22" * 32, "preparation_sha256": "33" * 32,
            "signature_response_sha256": "44" * 32, "spend_bundle": BUNDLE,
            "preparation": {"observation_time": datetime.now(timezone.utc).isoformat()}}


class DispatchTests(unittest.TestCase):
    def test_approved_fresh_verification_precedes_intent_and_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            a = args(Path(temp))
            def verify(*inputs):
                self.assertFalse(a.attempt.exists())
                self.assertEqual(inputs[-2:], (20, 300))
                return verified()
            def worker(packet, duration):
                self.assertIsNone(read_attempt(a.attempt)["outcome"])
                self.assertEqual(packet["bundle"], BUNDLE)
                self.assertEqual(duration, 10)
                return "reply-success"
            with patch.object(dispatch, "verify_signed", side_effect=verify), patch.object(dispatch, "_worker_dispatch", side_effect=worker) as send:
                self.assertEqual(dispatch._dispatch(a)["outcome"], "reply-success")
                send.assert_called_once()

    def test_wrong_approval_verification_failure_and_alias_never_start_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            a = args(Path(temp))
            for failure in ("approval", "verification", "alias", "existing"):
                a = args(Path(temp))
                if failure == "approval":
                    a.approved_bundle_id = "ff" * 32
                if failure == "alias":
                    a.attempt = a.preparation
                if failure == "existing":
                    a.attempt.write_bytes(b"preserve")
                with patch.object(dispatch, "verify_signed", side_effect=ProbeError("fixture") if failure == "verification" else None,
                                  return_value=verified()), patch.object(dispatch, "_worker_dispatch") as send:
                    with self.assertRaises(ProbeError):
                        dispatch._dispatch(a)
                    send.assert_not_called()
                if failure == "existing":
                    self.assertEqual(a.attempt.read_bytes(), b"preserve")
                else:
                    self.assertFalse(a.attempt.exists())

    def test_timeout_or_interrupt_is_unknown_without_retry(self):
        for failure in (subprocess.TimeoutExpired("fixture", 1), KeyboardInterrupt()):
            with tempfile.TemporaryDirectory() as temp:
                a = args(Path(temp))
                with patch.object(dispatch, "verify_signed", return_value=verified()), patch.object(dispatch, "_worker_dispatch", side_effect=failure) as send:
                    with self.assertRaises(type(failure)):
                        dispatch._dispatch(a)
                    send.assert_called_once()
                self.assertEqual(read_attempt(a.attempt)["outcome"], "unknown")

    def test_invalid_bounds_fail_before_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            for field, value in [("duration", 0), ("duration", True), ("duration", float("nan")), ("duration", 601),
                                 ("timeout", 0), ("timeout", float("inf")), ("timeout", True)]:
                a = args(Path(temp))
                setattr(a, field, value)
                with patch.object(dispatch, "verify_signed") as verify, self.assertRaises(ProbeError):
                    dispatch._dispatch(a)
                verify.assert_not_called()

    def test_real_worker_timeout_and_failure_reap_and_close_pipes(self):
        original = subprocess.Popen
        for script, duration, error in [("import time;time.sleep(30)", .05, subprocess.TimeoutExpired),
                                        ("raise SystemExit(1)", 5, ProbeError)]:
            children = []
            def child(*unused, **kwargs):
                p = original([sys.executable, "-c", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                children.append(p)
                return p
            with patch.object(dispatch.subprocess, "Popen", side_effect=child), self.assertRaises(error):
                dispatch._worker_dispatch({}, duration)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(all(stream.closed for stream in (children[0].stdin, children[0].stdout, children[0].stderr)))

    def test_fresh_read_failure_and_expired_preparation_prevent_push(self):
        for failure in ("read", "expired"):
            packet = {"bundle": BUNDLE, "endpoint": "https://127.0.0.1:8555", "ca": "ca", "cert": "cert", "key": "key",
                      "socket_timeout": 2, "observation_time": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "max_age": 300}
            with patch.object(dispatch, "Transport"), patch.object(dispatch, "observe", side_effect=ProbeError("fixture") if failure == "read" else None,
                    return_value={"coin": BUNDLE["coin_spends"][0]["coin"]}), patch.object(dispatch, "_SubmissionTransport") as transport:
                with self.assertRaises(ProbeError):
                    dispatch._send(packet)
                transport.return_value.push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
