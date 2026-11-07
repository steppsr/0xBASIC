"""PC-2 coverage and fail-closed evidence publication checks without Chia imports."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import payment_change as pc


def outcomes():
    return [{"scenario": name, "resources_closed": True,
             "rejections": [{"error": pc.ERRORS[name], "status": "FAILED", "state_unchanged_after_farm": True,
                             "funding_change_unchanged": True, "children_count": 0, "active_mempool_empty": True}]
                            if name in pc.ERRORS else [],
             "confirmations": [{"payment_status": "SUCCESS", "child_count": 1 if name == "exact" else 2,
                                "input_spent": True, "funding_change_unchanged": True, "active_mempool_empty": True}],
             "other_coin_unspent_after_control": True}
            for name in pc.SCENARIOS]


class PaymentChangeReportingTests(unittest.TestCase):
    def test_complete_coverage(self):
        pc.audit(outcomes())

    def test_missing_duplicate_and_incomplete_evidence(self):
        for fault in ("missing", "duplicate", "rejection", "cleanup", "child-count", "other-coin"):
            with self.subTest(fault=fault):
                data = outcomes()
                if fault == "missing":
                    data.pop()
                elif fault == "duplicate":
                    data[-1] = copy.deepcopy(data[0])
                elif fault == "rejection":
                    data[2]["rejections"][0]["state_unchanged_after_farm"] = False
                elif fault == "cleanup":
                    data[0]["resources_closed"] = False
                elif fault == "child-count":
                    data[1]["confirmations"][0]["child_count"] = 2
                else:
                    next(r for r in data if r["scenario"] == "cross-coin-replay")["other_coin_unspent_after_control"] = False
                with self.assertRaises(RuntimeError):
                    pc.audit(data)

    def test_failed_or_different_runs_remove_previous_success(self):
        different = outcomes()
        different[0]["extra_observation"] = "changed"
        for effects, message in [([RuntimeError("scenario failed")], "scenario failed"),
                                 ([outcomes(), different], "fresh reruns differ")]:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                work = Path(temporary)
                binary = work / "compiler"
                binary.write_bytes(b"fixture")
                name = "windows" if pc.sys.platform == "win32" else "linux"
                destination = work / f"payment-change-{name}.json"
                destination.write_text('{"old_success": true}', encoding="utf-8")
                with patch.object(pc, "WORK", work), patch.object(pc.sys, "argv", ["payment_change.py", "--binary", str(binary)]), \
                        patch.object(pc, "preflight", return_value=({}, pc.BASE / "requirements-linux.lock", {})), \
                        patch.object(pc, "run_suite", new=AsyncMock(side_effect=effects)):
                    with self.assertRaisesRegex(RuntimeError, message):
                        pc.main()
                self.assertFalse(destination.exists())

    def test_preflight_failure_removes_previous_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            name = "windows" if pc.sys.platform == "win32" else "linux"
            destination = work / f"payment-change-{name}.json"
            destination.write_text('{"old_success": true}', encoding="utf-8")
            with patch.object(pc, "WORK", work), patch.object(pc.sys, "argv", ["payment_change.py"]), \
                    patch.object(pc, "preflight", side_effect=RuntimeError("bad profile")):
                with self.assertRaisesRegex(RuntimeError, "bad profile"):
                    pc.main()
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
