"""Streamed SSH confirmation with synthetic RPC; no real node or private keys."""
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from confirmation import name
import ssh_confirmation
import ssh_probe
from test_confirmation import Fixture
from testnet_probe import ProbeError


class SSHConfirmationTests(unittest.TestCase):
    def packet(self, fixture):
        return {"endpoint": "https://127.0.0.1:8555", "ca": "/ca", "cert": "/cert", "key": "/key",
                "socket_timeout": 2, "spend": fixture.spend, "children": fixture.children,
                "depth": 3, "anchor": None}

    def test_invalid_expectations_never_start_ssh(self):
        with patch.object(ssh_confirmation, "_exchange") as exchange:
            for update in ({"depth": 0}, {"depth": True}, {"children": []},
                           {"anchor": {"input_id": "ff" * 32, "height": 1, "header_hash": "aa" * 32}}):
                with self.subTest(update=update), self.assertRaises(ProbeError):
                    ssh_confirmation.read_confirmation("LOBOT", dict(self.packet(Fixture()), **update), 5)
            exchange.assert_not_called()

    def test_parent_rejects_wrong_identity_input_depth_and_scope(self):
        fixture = Fixture()
        for update in ({"input_id": "ff" * 32}, {"network": {}}, {"required_depth": 4},
                       {"chain_proof": True}, {"transactions_submitted": 1},
                       {"validation": "isolated-rpc-confirmation-observation-only"},
                       {"previous_anchor": {}}):
            with self.subTest(update=update), patch.object(ssh_confirmation, "_exchange",
                    return_value={"observation": dict(fixture.run(), **update)}):
                with self.assertRaises(ProbeError):
                    ssh_confirmation.read_confirmation("LOBOT", self.packet(fixture), 5)

    def test_streamed_worker_confirmation_states_and_network_refusal(self):
        launch, read_text = subprocess.Popen, ssh_probe.Path.read_text
        fixture = Fixture()
        # Embed only the fixture callable; actual confirmation and transport
        # allowlist validation remain in the streamed modules.
        fixture_class = read_text(ssh_probe.HERE / "test_confirmation.py", encoding="utf-8")
        fixture_class = fixture_class[fixture_class.index("class Fixture:"):fixture_class.index("class ConfirmationTests")]

        def source(path, *args, **kwargs):
            value = read_text(path, *args, **kwargs)
            if path.name == "confirmation_transport.py":
                value += "\nimport copy\nfrom confirmation import name\nfrom testnet_probe import GENESIS\n" + fixture_class
                value += ("\n_f = Fixture()\n_f.records = " + repr(fixture.records)
                          + "\n_f.override = " + repr(fixture.override) + "\n_f.block = " + repr(fixture.block)
                          + "\nclass ConfirmationTransport(ConfirmationTransport):\n"
                          " def __init__(self, *args): pass\n"
                          " def call(self, route, request):\n"
                          "  self.validate_request(route, request)\n  return _f.call(route, request)\n")
            return value

        def local_worker(argv, **kwargs):
            prelude = "DURATION = 5\n"
            if os.name != "posix":
                prelude += ("import signal\nsignal.SIGALRM = signal.SIGTERM\n"
                            "signal.ITIMER_REAL = 0\nsignal.setitimer = lambda *args: None\n")
            return launch([sys.executable, "-I", "-B", "-c", prelude + ssh_probe.REMOTE], **kwargs)

        with patch.object(ssh_probe.Path, "read_text", source), \
                patch.object(ssh_probe.subprocess, "Popen", side_effect=local_worker):
            packet = self.packet(fixture)
            read = lambda: ssh_confirmation.read_confirmation("LOBOT", packet, 5)
            confirmed = read()
            self.assertEqual(confirmed["status"], "confirmed")
            self.assertEqual(len(confirmed["children"]), 2)
            packet["depth"] = 4
            self.assertEqual(read()["status"], "confirming")
            packet["anchor"] = confirmed["confirmation_anchor"]
            fixture.block["header_hash"] = "cc" * 32
            self.assertEqual(read()["status"], "reorged")
            packet["anchor"] = None
            fixture.records[name(fixture.input)]["spent"] = False
            fixture.records[name(fixture.input)]["spent_block_index"] = 0
            self.assertEqual(read()["status"], "unspent")
            fixture.records[name(fixture.input)] = fixture.record(fixture.input, 90, 100)
            fixture.override["get_puzzle_and_solution"] = {"success": True,
                "coin_solution": dict(fixture.spend, solution="02")}
            self.assertEqual(read()["status"], "conflicting-spend")
            fixture.override["get_version"] = {"success": True, "version": "2.7.4"}
            with self.assertRaises(ProbeError):
                read()


if __name__ == "__main__":
    unittest.main()
