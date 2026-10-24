"""Failure-path tests for the reporting gate; no simulator dependencies required."""
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import verify


def reports():
    profile = {"profile": "test", "chia_commit": "commit", "source_hashes": {}}
    common = {"schema_version": 1, **profile, "platform": "test", "python": "3.13.7",
              "packages": {}, "lock_hashes": {}}
    smoke = {**common, "validation": "spendsim-environment-smoke-only",
             "outcome": {"resources_closed": True, "blocks_farmed": 1}}
    payments = {**common, "validation": "spendsim-height-signature-checks", "outcome": []}
    mutations = {**common, "validation": "spendsim-replay-mutation-checks", "outcome": []}
    names = [case["id"] for case in json.loads(verify.MATRIX.read_text(encoding="utf-8"))["cases"]]
    for index, name in enumerate(names):
        payment = index < 7
        entry = {"scenario": name, "resources_closed": True}
        rejection = {"error": verify.ERRORS.get(name), "status": "PENDING" if name == "premature-height" else "FAILED",
                     "input_unspent": True, "recipient_absent": True, "children_count": 0,
                     "active_mempool_empty": True, "state_unchanged_after_farm": True,
                     "spent_before_and_after": name == "double-spend", "children_before_and_after": 1 if name == "double-spend" else 0}
        confirmation = {"recipient_unspent": True, "exactly_one_child": True,
                        "simulator_total_spend_cost": "123", "input_spent": True}
        manifest = {"compiler": {"version": "test"}}
        entry["rejected_attempts" if payment else "rejections"] = [rejection] if name in verify.ERRORS else []
        if payment:
            entry.update(confirmation, payment_status="SUCCESS", payment_error=None,
                         input_spent_before=False, input_spent_after=True, manifest=manifest)
        else:
            entry.update(confirmations=[confirmation], fixtures={"original": {"manifest": manifest}})
        (payments if payment else mutations)["outcome"].append(entry)
    return [smoke, payments, mutations], profile


class ReportingTests(unittest.TestCase):
    def test_complete_coverage(self):
        data, profile = reports()
        self.assertEqual(len(verify.audit(data, profile, "test")), 15)

    def test_missing_duplicate_and_unknown_scenarios(self):
        for mode in ("missing", "duplicate", "unknown"):
            with self.subTest(mode=mode):
                data, profile = reports()
                if mode == "missing":
                    data[2]["outcome"].pop()
                elif mode == "duplicate":
                    data[2]["outcome"].append(copy.deepcopy(data[2]["outcome"][0]))
                else:
                    data[2]["outcome"][0]["scenario"] = "unknown"
                with self.assertRaises(RuntimeError):
                    verify.audit(data, profile, "test")

    def test_corrupt_evidence(self):
        for field, value in [("resources_closed", False), ("input_spent_after", False),
                             ("payment_status", "FAILED"), ("exactly_one_child", False)]:
            with self.subTest(field=field):
                data, profile = reports()
                data[1]["outcome"][0][field] = value
                with self.assertRaises(RuntimeError):
                    verify.audit(data, profile, "test")

    def test_wrong_error_or_state(self):
        for field, value in [("error", "UNKNOWN"), ("status", "SUCCESS"),
                             ("state_unchanged_after_farm", False), ("children_before_and_after", 1)]:
            with self.subTest(field=field):
                data, profile = reports()
                data[2]["outcome"][0]["rejections"][0][field] = value
                with self.assertRaises(RuntimeError):
                    verify.audit(data, profile, "test")

    def test_mixed_environment_and_stale_compiler(self):
        data, profile = reports()
        data[2]["python"] = "3.12.0"
        with self.assertRaises(RuntimeError):
            verify.audit(data, profile, "test")
        data, profile = reports()
        with self.assertRaises(RuntimeError):
            verify.audit(data, profile, "other")

    def test_child_failure_cannot_read_stale_report(self):
        with patch.object(Path, "unlink") as unlink, patch.object(Path, "read_text") as read:
            with patch.object(subprocess, "run", side_effect=subprocess.CalledProcessError(1, "child")):
                with self.assertRaises(subprocess.CalledProcessError):
                    verify.run_suite(Path("compiler"), "test")
            unlink.assert_called_once_with(missing_ok=True)
            read.assert_not_called()

    def test_preflight_failure_invalidates_old_success(self):
        with patch.object(verify.sys, "argv", ["verify.py"]), patch.object(Path, "mkdir"):
            with patch.object(Path, "unlink") as unlink, patch.object(verify, "preflight", side_effect=RuntimeError("preflight")):
                with self.assertRaisesRegex(RuntimeError, "preflight"):
                    verify.main()
                unlink.assert_called_once_with(missing_ok=True)

    def test_different_reruns_cannot_publish_success(self):
        data, profile = reports()
        second = copy.deepcopy(data)
        second[0]["extra_observation"] = "different"
        version = verify.tomllib.loads((verify.ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
        for suite in (data, second):
            for outcome in suite[1]["outcome"]:
                outcome["manifest"]["compiler"]["version"] = version
            for outcome in suite[2]["outcome"]:
                outcome["fixtures"]["original"]["manifest"]["compiler"]["version"] = version
        with patch.object(verify.sys, "argv", ["verify.py", "--binary", __file__]), \
             patch.object(Path, "mkdir"), patch.object(Path, "unlink"), \
             patch.object(Path, "write_text") as write, \
             patch.object(verify, "preflight", return_value=(profile, None, None)), \
             patch.object(verify, "run_suite", side_effect=[data, second]):
            with self.assertRaisesRegex(RuntimeError, "different evidence"):
                verify.main()
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
