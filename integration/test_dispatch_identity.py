"""Public and isolated dispatch cannot select identities from documents or RPC."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from network_identity import Identity, ISOLATED_REHEARSAL, PUBLIC_TESTNET
import submission_attempt as attempt
import submission_dispatch as dispatch
from test_submission_attempt import CONTEXT
from test_submission_dispatch import args, verified
from test_submission_transport import BUNDLE
from test_confirmation import Fixture
from confirmation import name
from testnet_probe import ProbeError


class DispatchIdentityTests(unittest.TestCase):
    def test_attempt_readers_reject_other_domain_and_preserve_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            for identity in (PUBLIC_TESTNET, ISOLATED_REHEARSAL):
                path = Path(temp) / identity.name
                saved = attempt._attempt_for_identity(path, CONTEXT, lambda: "reply-success", identity)
                self.assertEqual(saved["network"], identity.network())
                self.assertFalse(saved["automatic_retry_allowed"])
                self.assertFalse(saved["confirmation_established"])
                other = ISOLATED_REHEARSAL if identity is PUBLIC_TESTNET else PUBLIC_TESTNET
                with self.assertRaises(ProbeError):
                    attempt._read_for_identity(path, other)

    def test_copied_identity_objects_rejected_before_io(self):
        fake = Identity(**vars(PUBLIC_TESTNET))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "absent"
            for operation in (lambda: attempt._attempt_for_identity(path, CONTEXT, Mock(), fake),
                              lambda: attempt._read_for_identity(path, fake),
                              lambda: dispatch._dispatch_for_identity(None, fake),
                              lambda: dispatch._send_for_identity({}, fake),
                              lambda: dispatch._worker_for_identity({}, 1, fake)):
                with self.assertRaises(ValueError):
                    operation()
            self.assertFalse(path.exists())

    def test_isolated_dispatch_uses_fixed_verifier_worker_and_record(self):
        with tempfile.TemporaryDirectory() as temp:
            a = args(Path(temp))
            with patch.object(dispatch, "verify_signed", side_effect=AssertionError("public verifier")), \
                 patch.object(dispatch, "_verify_for_identity", return_value=verified()) as verify, \
                 patch.object(dispatch, "_worker_for_identity", return_value="reply-success") as worker:
                result = dispatch._dispatch_for_identity(a, ISOLATED_REHEARSAL)
            self.assertIs(verify.call_args.args[-2], ISOLATED_REHEARSAL)
            self.assertIs(worker.call_args.args[-1], ISOLATED_REHEARSAL)
            self.assertEqual(result["validation"], "isolated-submission-attempt-record-only")
            with self.assertRaises(ProbeError):
                attempt.read_attempt(a.attempt)

    def test_fresh_read_identity_cannot_be_overridden_by_packet(self):
        for identity in (PUBLIC_TESTNET, ISOLATED_REHEARSAL):
            fixture = Fixture()
            fixture.input = BUNDLE["coin_spends"][0]["coin"]
            fixture.records = {name(fixture.input): fixture.record(fixture.input, 90, 0)}
            fixture.override["get_version"] = {"success": True, "version": identity.version}
            fixture.override["get_network_info"] = {"success": True, "network_name": identity.name,
                "network_prefix": identity.prefix, "genesis_challenge": identity.genesis}
            packet = {"bundle": BUNDLE, "endpoint": "https://127.0.0.1:8555", "ca": "ca", "cert": "cert", "key": "key",
                      "socket_timeout": 2, "observation_time": datetime.now(timezone.utc).isoformat(), "max_age": 300,
                      "identity": identity.network()}
            with patch.object(dispatch, "Transport") as reader, patch.object(dispatch, "_SubmissionTransport") as sender:
                reader.return_value.call.side_effect = fixture.call
                sender.return_value.push.return_value = "reply-success"
                self.assertEqual(dispatch._send_for_identity(packet, identity), "reply-success")
                sender.return_value.push.assert_called_once()
                sender.reset_mock()
                other = PUBLIC_TESTNET if identity is ISOLATED_REHEARSAL else ISOLATED_REHEARSAL
                with self.assertRaises(ProbeError):
                    dispatch._send_for_identity(packet, other)
                sender.return_value.push.assert_not_called()

    def test_worker_script_is_fixed_by_identity_not_packet(self):
        for identity, script in ((PUBLIC_TESTNET, "submission_dispatch.py"), (ISOLATED_REHEARSAL, "isolated_dispatch.py")):
            process = Mock()
            process.communicate.return_value = (b'{"outcome":"reply-success"}', b'')
            process.returncode = 0
            process.poll.return_value = 0
            with patch.object(dispatch.subprocess, "Popen", return_value=process) as launch:
                dispatch._worker_for_identity({"worker_script": "untrusted.py"}, 10, identity)
            self.assertEqual(Path(launch.call_args.args[0][1]).name, script)


if __name__ == "__main__":
    unittest.main()
