"""Atomic history survives process exit and never becomes fresh chain evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from observation_journal import Journal, read_history, decode_history


class JournalTests(unittest.TestCase):
    def test_prefix_is_historical_and_inputs_are_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            context, observation = {"network": "fixture"}, {"height": 10}
            journal = Journal(path, context)
            journal.record("ready", observation)
            context["network"], observation["height"] = "changed", 11
            r = read_history(path)
            self.assertEqual(r["context"]["network"], "fixture")
            self.assertEqual(r["records"][0]["observation"], {"height": 10})
            self.assertTrue(r["fresh_chain_validation_required"])
            self.assertFalse(r["automatic_resume_allowed"])
            self.assertEqual(r["validation"], "historical-observations-only")

    def test_order_and_existing_file_fail_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            journal = Journal(path, {})
            journal.record("ready", {})
            old = path.read_bytes()
            with self.assertRaises(RuntimeError):
                journal.record("reconfirmed", {})
            with self.assertRaises(RuntimeError):
                Journal(path, {})
            self.assertEqual(path.read_bytes(), old)

    def test_corruption_and_truncation_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            j = Journal(path, {"network": "fixture"})
            j.record("ready", {"height": 1})
            j.record("fees-confirmed", {"bundle_ids": []})
            doc = json.loads(path.read_bytes())
            mutations = [lambda d: d["context"].update(network="other"),
                lambda d: d["records"][0]["observation"].update(height=2),
                lambda d: d["records"].reverse(), lambda d: d["records"][0].update(sequence=True),
                lambda d: d.update(schema_version=True)]
            for mutate in mutations:
                changed = copy.deepcopy(doc)
                mutate(changed)
                with self.assertRaises(RuntimeError):
                    decode_history(json.dumps(changed).encode())
            for raw in (path.read_bytes()[:-3], b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}'):
                with self.assertRaises((RuntimeError, ValueError)):
                    decode_history(raw)

    def test_failed_flush_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            journal = Journal(path, {})
            journal.record("ready", {})
            previous = path.read_bytes()
            with patch("observation_journal.os.fsync", side_effect=OSError("fixture disk error")):
                with self.assertRaises(OSError):
                    journal.record("fees-confirmed", {})
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(len(read_history(path)["records"]), 1)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_external_change_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            journal = Journal(path, {})
            path.write_bytes(path.read_bytes() + b" ")
            changed = path.read_bytes()
            with self.assertRaises(RuntimeError):
                journal.record("ready", {})
            self.assertEqual(path.read_bytes(), changed)

    def test_abrupt_process_exit_retains_complete_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            code = "import os,sys; from observation_journal import Journal; j=Journal(sys.argv[1], {'fixture':True}); j.record('ready', {'height':1}); j.record('fees-confirmed', {'bundle_ids':[]}); os._exit(17)"
            result = subprocess.run([sys.executable, "-c", code, str(path)], cwd=Path(__file__).parent,
                                    capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 17, result.stderr)
            r = read_history(path)
            self.assertEqual([v["stage"] for v in r["records"]], ["ready", "fees-confirmed"])
            self.assertTrue(r["fresh_chain_validation_required"])
            self.assertFalse(r["automatic_resume_allowed"])


if __name__ == "__main__":
    unittest.main()
