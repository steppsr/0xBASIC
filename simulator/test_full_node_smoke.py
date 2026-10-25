"""Isolation and fail-closed publication checks; no node or Chia imports."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import full_node_smoke as smoke


class FullNodeGateTests(unittest.TestCase):
    def test_paths_cannot_escape_root(self):
        root = Path.cwd() / ".work/m5"
        self.assertEqual(smoke.contained(root / "run/node", root), (root / "run/node").resolve())
        for path in [root / "../outside", root.parent]:
            with self.assertRaisesRegex(RuntimeError, "outside isolated root"):
                smoke.contained(path, root)

    def test_network_guard_rejects_external_and_wildcard(self):
        for event in ["socket.bind", "socket.connect"]:
            for host in ["", "0.0.0.0", "::", "example.com", "192.0.2.1"]:
                with self.assertRaisesRegex(RuntimeError, "Non-loopback"):
                    smoke.guard_network(event, (None, (host, 8444)))
            smoke.guard_network(event, (None, ("127.0.0.1", 0)))

    def test_failed_worker_invalidates_success(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            name = "windows" if smoke.sys.platform == "win32" else "linux"
            for mode in ("smoke", "payment"):
                with self.subTest(mode=mode):
                    report = work / f"full-node-{mode}-{name}.json"
                    report.write_text(json.dumps({"old_success": True}))
                    argv = ["full_node_smoke.py"] + (["--payment", "--binary", "test-cli"] if mode == "payment" else [])
                    with patch.object(smoke, "WORK", work), patch.object(smoke, "contained", side_effect=Path), \
                            patch.object(smoke.sys, "argv", argv), \
                            patch.object(smoke.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "worker")) as run:
                        with self.assertRaises(subprocess.CalledProcessError):
                            smoke.main()
                    self.assertFalse(report.exists())
                    command = run.call_args.args[0]
                    self.assertEqual("--payment" in command, mode == "payment")
                    if mode == "payment":
                        self.assertEqual(command[-1], str(Path("test-cli").resolve()))

    def test_source_mismatch_fails_preflight(self):
        with patch.object(smoke.metadata, "distribution") as distribution:
            distribution.return_value.locate_file.return_value = Path(__file__)
            with self.assertRaisesRegex(RuntimeError, "source mismatch"):
                smoke.source_check()


if __name__ == "__main__":
    unittest.main()
