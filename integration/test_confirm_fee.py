"""Operator confirmation wiring, publication and authenticated read-only transport."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import confirm_fee
from confirmation import name
from test_confirmation import Fixture
import test_confirmation_transport as tls
from testnet_probe import ProbeError


def verified(f):
    return {"spend_bundle": {"coin_spends": [copy.deepcopy(f.spend)]},
            "preparation": {"expected_outputs": [{**c, "amount": str(c["amount"])} for c in f.children]},
            "bundle_id": "ab" * 32, "preparation_sha256": "cd" * 32, "signature_response_sha256": "ef" * 32}


class OperatorConfirmationTests(unittest.TestCase):
    def test_verified_expectations_and_all_statuses(self):
        for status, depth in (("confirmed", 3), ("confirming", 4), ("unspent", 3), ("conflicting-spend", 3), ("reorged", 3)):
            f = Fixture()
            expected = verified(f)
            kwargs = {}
            if status == "unspent":
                f.records[name(f.input)] = f.record(f.input, 90, 0)
            if status == "conflicting-spend":
                f.spend["solution"] = "01"
            if status == "reorged":
                kwargs = {"previous_height": 100, "previous_hash": "cc" * 32}
            with patch.object(confirm_fee, "verify_signed", return_value=expected):
                r = confirm_fee.confirm(f.call, None, None, None, None, None, None, 20, depth, **kwargs)
            self.assertEqual(r["observation"]["status"], status)
            self.assertEqual(r["expected_bundle_id"], expected["bundle_id"])
            self.assertEqual(r["transactions_submitted"], 0)
            self.assertTrue(all(route.startswith("get_") for route, _ in f.calls))

    def test_failed_signature_never_contacts_rpc(self):
        f = Fixture()
        with patch.object(confirm_fee, "verify_signed", side_effect=ProbeError("invalid")):
            with self.assertRaises(ProbeError):
                confirm_fee.confirm(f.call, None, None, None, None, None, None, 20, 3)
        self.assertEqual(f.calls, [])

    def test_invalid_depth_anchor_before_verification_or_rpc(self):
        for depth, kwargs in [(0, {}), (True, {}), (10001, {}), (3, {"previous_height": 100}),
                              (3, {"previous_height": -1, "previous_hash": "cc" * 32})]:
            f = Fixture()
            with patch.object(confirm_fee, "verify_signed") as verify:
                with self.assertRaises(ProbeError):
                    confirm_fee.confirm(f.call, None, None, None, None, None, None, 20, depth, **kwargs)
                verify.assert_not_called()
            self.assertEqual(f.calls, [])

    def test_report_aliases_preserve_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            source, alias = Path(temp) / "source", Path(temp) / "alias"
            source.write_text("keep")
            os.link(source, alias)
            for report in (source, alias):
                with self.assertRaises(ProbeError):
                    confirm_fee._report_path(report, [source])
            self.assertEqual(source.read_text(), "keep")

    def test_cli_exit_status_and_stale_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = root / "report.json"
            argv = ["confirm_fee", "--endpoint", "https://127.0.0.1:8555", "--max-fee", "20", "--depth", "3", "--report", str(report)]
            for key in ("binary", "manifest", "observation", "solution", "preparation", "signature-response", "ca-cert", "client-cert", "client-key"):
                argv.extend(["--" + key, str(root / key)])
            for status in ("confirmed", "confirming", "unspent", "conflicting-spend", "reorged"):
                with patch.object(sys, "argv", argv), patch.object(confirm_fee, "ConfirmationTransport"), \
                        patch.object(confirm_fee, "confirm", return_value={"observation": {"status": status}}), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(confirm_fee.main(), 0 if status == "confirmed" else 3)
                self.assertEqual(json.loads(report.read_text())["observation"]["status"], status)
            with patch.object(sys, "argv", argv), patch.object(confirm_fee, "ConfirmationTransport"), \
                    patch.object(confirm_fee, "confirm", side_effect=ProbeError("secret path")), contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(confirm_fee.main(), 1)
            self.assertFalse(report.exists())
            self.assertNotIn("secret path", error.getvalue())


class OperatorConfirmationTLSTests(unittest.TestCase):
    setUpClass = classmethod(tls.ConfirmationTLSTests.setUpClass.__func__)
    tearDownClass = classmethod(tls.ConfirmationTLSTests.tearDownClass.__func__)
    setUp = tls.ConfirmationTLSTests.setUp
    client = tls.ConfirmationTLSTests.client

    def test_verified_confirmation_over_real_mutual_tls(self):
        with patch.object(confirm_fee, "verify_signed", return_value=verified(self.fixture)):
            r = confirm_fee.confirm(self.client().call, None, None, None, None, None, None, 20, 3)
        self.assertEqual(r["observation"]["status"], "confirmed")
        self.assertTrue(all(route.startswith("get_") for route, _ in self.seen))


if __name__ == "__main__":
    unittest.main()
