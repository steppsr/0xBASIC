"""Operator argument contract, separate review and explicit single dispatch."""
import contextlib
import io
import json
import sys
import unittest
from unittest.mock import patch

import submit_fee
from test_submission_dispatch import verified


BASE = ["submit_fee", "--binary", "binary", "--manifest", "manifest", "--observation", "observation",
        "--solution", "solution", "--preparation", "preparation", "--signature-response", "response", "--max-fee", "20"]
SEND = ["--approve-bundle-id", "11" * 32, "--endpoint", "https://127.0.0.1:8555", "--ca-cert", "ca",
        "--client-cert", "cert", "--client-key", "key", "--attempt", "new.json", "--duration", "30", "--timeout", "10"]


class SubmitFeeTests(unittest.TestCase):
    def test_review_emits_full_preparation_and_identity_without_dispatch(self):
        value = {**verified(), "network": {"name": "fixture"}}
        output = io.StringIO()
        with patch.object(sys, "argv", BASE + ["--review-only"]), patch.object(submit_fee.sys, "addaudithook") as hook, \
             patch.object(submit_fee, "verify_signed", return_value=value), patch.object(submit_fee, "_dispatch") as dispatch, \
             contextlib.redirect_stdout(output):
            self.assertEqual(submit_fee.main(), 0)
        hook.assert_called_once_with(submit_fee.no_network)
        dispatch.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertEqual(result["preparation"], value["preparation"])
        self.assertEqual(result["bundle_id"], value["bundle_id"])
        self.assertEqual(result["transactions_submitted"], 0)

    def test_missing_or_mixed_modes_never_dispatch(self):
        for extra in ([], SEND + ["--review-only"], SEND[:-2], ["--review-only", "--attempt", "out"]):
            with patch.object(sys, "argv", BASE + extra), patch.object(submit_fee, "_dispatch") as dispatch, \
                 patch.object(submit_fee, "verify_signed") as verify, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    submit_fee.main()
                self.assertEqual(error.exception.code, 2)
                dispatch.assert_not_called()
                verify.assert_not_called()

    def test_success_pending_and_exception_exit_statuses(self):
        for outcome, code in (("reply-success", 0), ("reply-pending", 3), ("unknown", 1)):
            with patch.object(sys, "argv", BASE + SEND), patch.object(submit_fee, "_dispatch", return_value={"outcome": outcome}) as dispatch, \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(submit_fee.main(), code)
                dispatch.assert_called_once()
                self.assertEqual(dispatch.call_args.args[0].approved_bundle_id, "11" * 32)

    def test_failure_and_interrupt_do_not_retry_or_echo_details(self):
        for failure in (RuntimeError("private path detail"), KeyboardInterrupt()):
            output = io.StringIO()
            with patch.object(sys, "argv", BASE + SEND), patch.object(submit_fee, "_dispatch", side_effect=failure) as dispatch, \
                 contextlib.redirect_stderr(output):
                self.assertEqual(submit_fee.main(), 1)
            dispatch.assert_called_once()
            self.assertNotIn("private path detail", output.getvalue())
            self.assertIn("unknown", output.getvalue())


if __name__ == "__main__":
    unittest.main()
