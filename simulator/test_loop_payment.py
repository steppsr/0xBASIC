"""Loop evidence publication must fail closed before or during validation."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import loop_payment


class LoopReportingTests(unittest.TestCase):
    def test_failed_or_different_runs_do_not_publish(self):
        for effects, message in [([RuntimeError("validation failed")], "validation failed"),
                                 ([{"cost": 1}, {"cost": 2}], "fresh reruns differ")]:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                binary = work / "compiler"
                binary.write_bytes(b"fixture")
                platform = "windows" if loop_payment.sys.platform == "win32" else "linux"
                destination = work / f"loop-payment-{platform}.json"
                destination.write_text('{"old_success": true}', encoding="utf-8")
                with patch.object(loop_payment, "WORK", work), \
                        patch.object(loop_payment.sys, "argv", ["loop_payment.py", "--binary", str(binary)]), \
                        patch.object(loop_payment, "preflight", return_value=(
                            {}, loop_payment.BASE / "requirements-linux.lock", {})), \
                        patch.object(loop_payment, "spendsim", new=AsyncMock(side_effect=effects)):
                    with self.assertRaisesRegex(RuntimeError, message):
                        loop_payment.main()
                self.assertFalse(destination.exists())

    def test_preflight_failure_removes_old_success(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            platform = "windows" if loop_payment.sys.platform == "win32" else "linux"
            destination = work / f"loop-payment-{platform}.json"
            destination.write_text(json.dumps({"old_success": True}), encoding="utf-8")
            with patch.object(loop_payment, "WORK", work), \
                    patch.object(loop_payment.sys, "argv", ["loop_payment.py"]), \
                    patch.object(loop_payment, "preflight", side_effect=RuntimeError("bad profile")):
                with self.assertRaisesRegex(RuntimeError, "bad profile"):
                    loop_payment.main()
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
