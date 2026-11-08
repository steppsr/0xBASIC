"""FP-3 coverage and fail-closed evidence publication checks without Chia imports."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import fee_payment as pc


def outcomes():
    results = []
    for name in pc.SCENARIOS:
        fee = pc.POSITIVES[name][1] if name in pc.POSITIVES else 11 if name == "changed-fee-stale-signature" else 10
        removal, net, reserve, inputs, children, contracts = 1000, fee, fee, 1, 2, 1
        if name in ("exact", "zero-fee-exact"):
            children = 1
        if name in pc.AGGREGATES:
            removal, inputs, children = 1100, 2, 3
            net, reserve = {"reserved-offset": (10, 10), "additive-offset": (30, 30),
                            "unreserved-offset-control": (0, 0), "extra-fee": (20, 10)}[name]
            if name == "additive-offset":
                removal, inputs, children, contracts = 2100, 3, 5, 2
        bad = {"status": "FAILED", "error": pc.ERRORS.get(name), "state_unchanged_after_farm": True,
               "funding_change_unchanged": True, "active_mempool_empty": True, "accounting": None}
        if name in ("reserved-offset", "additive-offset"):
            bad["accounting"] = {"removal_amount": str(removal), "addition_amount": str(removal-reserve+10),
                                 "net_fee": str(reserve-10), "reserved_fee": str(reserve)}
        good = {"status": "SUCCESS", "input_count": inputs, "child_count": children,
                "contract_spends": [{} for _ in range(contracts)], "input_records": [{} for _ in range(inputs)],
                "output_records": [{} for _ in range(children)], "exact_coins_and_heights": True,
                "unaffected_inputs_unchanged": True, "funding_change_unchanged": True, "active_mempool_empty": True,
                "accounting": {"removal_amount": str(removal), "addition_amount": str(removal-net),
                               "net_fee": str(net), "reserved_fee": str(reserve)}}
        results.append({"scenario": name, "resources_closed": True,
                        "comparison_fixture": name == "unreserved-offset-control",
                        "reservation_enabled": name != "unreserved-offset-control",
                        "rejections": [bad] if name in pc.ERRORS else [], "confirmations": [good]})
    return results


class FeePaymentReportingTests(unittest.TestCase):
    def test_complete_coverage(self):
        pc.audit(outcomes())

    def test_missing_duplicate_and_incomplete_evidence(self):
        for fault in ("missing", "duplicate", "rejection", "cleanup", "child-count", "other-coin",
                      "net-fee", "additive-reserve", "rejected-accounting", "comparison", "input-count", "outputs"):
            with self.subTest(fault=fault):
                data = outcomes()
                aggregate = next(r for r in data if r["scenario"] == "additive-offset")
                if fault == "missing":
                    data.pop()
                elif fault == "duplicate":
                    data[-1] = copy.deepcopy(data[0])
                elif fault == "rejection":
                    data[4]["rejections"][0]["state_unchanged_after_farm"] = False
                elif fault == "cleanup":
                    data[0]["resources_closed"] = False
                elif fault == "child-count":
                    data[1]["confirmations"][0]["child_count"] = 2
                elif fault == "other-coin":
                    data[0]["confirmations"][0]["unaffected_inputs_unchanged"] = False
                elif fault == "net-fee":
                    data[0]["confirmations"][0]["accounting"]["net_fee"] = "9"
                elif fault == "additive-reserve":
                    aggregate["confirmations"][0]["accounting"]["reserved_fee"] = "20"
                elif fault == "rejected-accounting":
                    aggregate["rejections"][0]["accounting"]["net_fee"] = "30"
                elif fault == "comparison":
                    data[-2]["reservation_enabled"] = True
                elif fault == "input-count":
                    aggregate["confirmations"][0]["input_count"] = 2
                else:
                    aggregate["confirmations"][0]["output_records"].pop()
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
                destination = work / f"fee-payment-{name}.json"
                destination.write_text('{"old_success": true}', encoding="utf-8")
                with patch.object(pc, "WORK", work), patch.object(pc.sys, "argv", ["fee_payment.py", "--binary", str(binary)]), \
                        patch.object(pc, "preflight", return_value=({}, pc.BASE / "requirements-linux.lock", {})), \
                        patch.object(pc, "run_suite", new=AsyncMock(side_effect=effects)):
                    with self.assertRaisesRegex(RuntimeError, message):
                        pc.main()
                self.assertFalse(destination.exists())

    def test_preflight_failure_removes_previous_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            name = "windows" if pc.sys.platform == "win32" else "linux"
            destination = work / f"fee-payment-{name}.json"
            destination.write_text('{"old_success": true}', encoding="utf-8")
            with patch.object(pc, "WORK", work), patch.object(pc.sys, "argv", ["fee_payment.py"]), \
                    patch.object(pc, "preflight", side_effect=RuntimeError("bad profile")):
                with self.assertRaisesRegex(RuntimeError, "bad profile"):
                    pc.main()
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
