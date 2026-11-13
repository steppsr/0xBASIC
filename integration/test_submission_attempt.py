"""Intent-before-dispatch and ambiguous outcomes, with disposable callbacks only."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import submission_attempt as attempt
from testnet_probe import ProbeError

CONTEXT = {key: f"{index:064x}" for index, key in enumerate(sorted(attempt.IDENTIFIERS), 1)}


class SubmissionAttemptTests(unittest.TestCase):
    def test_intent_precedes_single_dispatch_and_outcome_is_not_confirmation(self):
        for outcome in sorted(attempt.OUTCOMES - {"unknown"}):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "attempt.json"
                def dispatch():
                    saved = attempt.read_attempt(path)
                    self.assertIsNone(saved["outcome"])
                    self.assertEqual(saved["context"], CONTEXT)
                    return outcome
                callback = Mock(side_effect=dispatch)
                saved = attempt._attempt(path, CONTEXT, callback)
                callback.assert_called_once_with()
                self.assertEqual(saved["outcome"], outcome)
                self.assertFalse(saved["confirmation_established"])
                self.assertFalse(saved["automatic_retry_allowed"])
                self.assertTrue(saved["dispatch_may_have_occurred"])

    def test_existing_attempt_never_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attempt.json"
            path.write_bytes(b"previous evidence")
            callback = Mock()
            with self.assertRaises(FileExistsError):
                attempt._attempt(path, CONTEXT, callback)
            callback.assert_not_called()
            self.assertEqual(path.read_bytes(), b"previous evidence")

    def test_invalid_context_or_missing_directory_never_dispatches(self):
        with tempfile.TemporaryDirectory() as temp:
            for context in [{}, {**CONTEXT, "secret": "do not save"}, {**CONTEXT, "bundle_id": True},
                            {**CONTEXT, "bundle_id": "FF" * 32}]:
                callback = Mock()
                with self.assertRaises(ProbeError):
                    attempt._attempt(Path(temp) / "attempt.json", context, callback)
                callback.assert_not_called()
                self.assertEqual(list(Path(temp).iterdir()), [])
            callback = Mock()
            with self.assertRaises(FileNotFoundError):
                attempt._attempt(Path(temp) / "absent" / "attempt.json", CONTEXT, callback)
            callback.assert_not_called()

    def test_intent_sync_failure_prevents_dispatch_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attempt.json"
            callback = Mock()
            with patch.object(attempt.os, "fsync", side_effect=OSError("fixture")):
                with self.assertRaises(OSError):
                    attempt._attempt(path, CONTEXT, callback)
            callback.assert_not_called()
            self.assertTrue(path.exists())
            with self.assertRaises(FileExistsError):
                attempt._attempt(path, CONTEXT, callback)
            callback.assert_not_called()

    def test_transport_exception_interrupt_and_invalid_reply_are_unknown(self):
        for failure in [OSError("private detail"), KeyboardInterrupt(), None, {"success": True}]:
            with self.subTest(failure=type(failure)), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "attempt.json"
                callback = Mock(side_effect=failure) if isinstance(failure, BaseException) else Mock(return_value=failure)
                with self.assertRaises((OSError, KeyboardInterrupt, ProbeError)):
                    attempt._attempt(path, CONTEXT, callback)
                callback.assert_called_once_with()
                self.assertEqual(attempt.read_attempt(path)["outcome"], "unknown")
                self.assertNotIn("private detail", path.read_text())

    def test_outcome_sync_failure_preserves_intent_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attempt.json"
            callback = Mock(return_value="reply-success")
            with patch.object(attempt.os, "fsync", side_effect=[None, OSError("fixture")]):
                with self.assertRaises(OSError):
                    attempt._attempt(path, CONTEXT, callback)
            callback.assert_called_once_with()
            self.assertIsNone(attempt.read_attempt(path)["outcome"])
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_replace_failure_preserves_intent_without_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attempt.json"
            callback = Mock(return_value="reply-success")
            with patch.object(Path, "replace", side_effect=OSError("fixture")):
                with self.assertRaises(OSError):
                    attempt._attempt(path, CONTEXT, callback)
            callback.assert_called_once_with()
            self.assertIsNone(attempt.read_attempt(path)["outcome"])
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_external_change_aborts_publication_and_context_is_copied(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attempt.json"
            context = copy.deepcopy(CONTEXT)
            def dispatch():
                context["bundle_id"] = "a" * 64
                return "reply-success"
            self.assertEqual(attempt._attempt(path, context, dispatch)["context"], CONTEXT)
            other = Path(temp) / "changed.json"
            def changed():
                other.write_bytes(b"external change")
                return "reply-success"
            with self.assertRaises(ProbeError):
                attempt._attempt(other, CONTEXT, changed)
            self.assertEqual(other.read_bytes(), b"external change")

    def test_abrupt_dispatch_exit_leaves_ambiguous_intent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attempt.json"
            script = "import os,sys,json; from submission_attempt import _attempt; _attempt(sys.argv[1],json.loads(sys.argv[2]),lambda:os._exit(7))"
            result = subprocess.run([sys.executable, "-c", script, str(path), json.dumps(CONTEXT)],
                                    cwd=Path(__file__).parent, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 7, result.stderr)
            saved = attempt.read_attempt(path)
            self.assertIsNone(saved["outcome"])
            self.assertTrue(saved["dispatch_may_have_occurred"])

    def test_corruption_duplicate_keys_and_size_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attempt.json"
            attempt._attempt(path, CONTEXT, lambda: "reply-pending")
            original = path.read_bytes()
            malformed = [b'{"a":1,"a":2}', b'{"a":NaN}', original[:-4], b" " * (attempt.MAX_BYTES + 1)]
            for field, value in [("schema_version", True), ("outcome", "confirmed"), ("automatic_retry_allowed", True),
                                 ("sha256", "0" * 64), ("unexpected", 1), ("network", {})]:
                doc = json.loads(original)
                doc[field] = value
                malformed.append(json.dumps(doc).encode())
            for data in malformed:
                path.write_bytes(data)
                with self.assertRaises((ProbeError, ValueError)):
                    attempt.read_attempt(path)


if __name__ == "__main__":
    unittest.main()
