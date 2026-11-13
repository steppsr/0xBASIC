"""Interrupted histories remain reviewable prefixes, never automatic recovery authority."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import monitor_history as history
import monitor_fee
from test_monitor_fee import IDENTITY, observation
from testnet_probe import ProbeError


class HistoryTests(unittest.TestCase):
    def test_completed_snapshot_and_copy_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            context = {"input_id": IDENTITY}
            writer = history.History(path, context)
            context["input_id"] = "changed"
            value = {"attempt": 1, "observation": observation("confirmed")}
            writer.record("observation", value)
            value["attempt"] = 99
            writer.record("finished", {"status": "confirmed"})
            saved = history.read_history(path)
            self.assertEqual(saved["context"]["input_id"], IDENTITY)
            self.assertEqual(saved["records"][0]["value"]["attempt"], 1)
            self.assertFalse(saved["automatic_resume_allowed"])
            self.assertTrue(saved["fresh_chain_validation_required"])
            with self.assertRaises(ProbeError):
                writer.record("observation", {})

    def test_existing_file_refused_without_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            path.write_bytes(b"existing")
            with self.assertRaises(FileExistsError):
                history.History(path, {})
            self.assertEqual(path.read_bytes(), b"existing")

    def test_flush_failure_preserves_prefix_and_memory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            writer = history.History(path, {})
            writer.record("observation", {"attempt": 1})
            old, old_doc = path.read_bytes(), copy.deepcopy(writer.doc)
            with patch.object(history.os, "fsync", side_effect=OSError("fixture fsync")), self.assertRaises(OSError):
                writer.record("finished", {"status": "timed-out"})
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(writer.doc, old_doc)
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_external_edit_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            writer = history.History(path, {})
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(ProbeError):
                writer.record("observation", {})

    def test_invalid_json_order_hash_and_types(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            writer = history.History(path, {})
            writer.record("observation", {})
            for data in (b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}', path.read_bytes()[:-4]):
                with self.assertRaises((ValueError, ProbeError)):
                    history.decode(data)
            for mutation in (lambda d: d.update(schema_version=True), lambda d: d["records"][0].update(sequence=True),
                             lambda d: d["records"][0].update(previous="00"), lambda d: d["records"][0]["value"].update(changed=True)):
                doc = copy.deepcopy(writer.doc)
                mutation(doc)
                with self.assertRaises(ProbeError):
                    history.decode(history.encoded(doc))

    def test_size_failure_preserves_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            writer = history.History(path, {})
            old = path.read_bytes()
            with patch.object(history, "MAX_BYTES", len(old) + 10), self.assertRaises(ProbeError):
                writer.record("observation", {"data": "x" * 100})
            self.assertEqual(path.read_bytes(), old)

    def test_abrupt_process_exit_preserves_completed_record(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "history.json"
            code = "import os,sys; from monitor_history import History; h=History(sys.argv[1], {}); h.record('observation', {'attempt':1}); os._exit(7)"
            result = subprocess.run([sys.executable, "-c", code, str(path)], cwd=Path(__file__).parent, timeout=10)
            self.assertEqual(result.returncode, 7)
            saved = history.read_history(path)
            self.assertEqual(len(saved["records"]), 1)
            self.assertEqual(saved["records"][0]["kind"], "observation")

    def test_poll_persists_only_valid_ontime_observations(self):
        saved = []
        with patch.object(monitor_fee.time, "monotonic", side_effect=[0, 0, 2, 2]):
            result = monitor_fee.poll(lambda *args: observation("confirmed"), IDENTITY, None, duration=1,
                                      interval=0, max_attempts=1, checkpoint=lambda *record: saved.append(record))
        self.assertEqual(result["status"], "timed-out")
        self.assertEqual(saved, [])
        def failed(*args):
            raise OSError("checkpoint unavailable")
        with self.assertRaises(OSError):
            monitor_fee.poll(lambda *args: observation("unspent"), IDENTITY, None, duration=5,
                             interval=0, max_attempts=2, checkpoint=failed)


if __name__ == "__main__":
    unittest.main()
