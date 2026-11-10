"""TN-1 validation, publication and real loopback mutual-TLS tests; no live node."""
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import testnet_probe as probe

FIXTURES = Path(__file__).parent / "fixtures"
PARENT, PUZZLE = "11" * 32, "22" * 32
# Independent known amount encoding: 1000 = 0x03e8.
COIN_ID = hashlib.sha256(bytes.fromhex(PARENT + PUZZLE + "03e8")).hexdigest()


def replies():
    return {
        "get_version": {"success": True, "version": "2.7.5"},
        "get_network_info": {"success": True, "network_name": "testnet11", "network_prefix": "txch", "genesis_challenge": probe.GENESIS},
        "get_blockchain_state": {"success": True, "blockchain_state": {
            "sync": {"synced": True, "sync_mode": False}, "peak": {"height": 100, "header_hash": "33" * 32}}},
        "get_coin_record_by_name": {"success": True, "coin_record": {
            "coin": {"parent_coin_info": PARENT, "puzzle_hash": PUZZLE, "amount": 1000},
            "spent": False, "spent_block_index": 0, "confirmed_block_index": 10, "coinbase": False, "timestamp": 12345}},
    }


class ValidationTests(unittest.TestCase):
    def test_connection_and_coin_observations(self):
        for coin in (None, COIN_ID):
            calls = []
            def call(route, request):
                calls.append((route, request))
                return replies()[route]
            result = probe.observe(call, coin, PUZZLE if coin else None, 1000 if coin else None)
            self.assertEqual(result["validation"], "rpc-observation-only")
            self.assertFalse(result["atomic_snapshot"])
            self.assertFalse(result["spend_validated"])
            self.assertEqual(result["transactions_submitted"], 0)
            self.assertEqual(len(calls), 5 if coin else 4)
            if coin:
                self.assertEqual(result["coin"]["amount"], "1000")
                self.assertEqual(calls[3], ("get_coin_record_by_name", {"name": "0x" + COIN_ID}))

    def test_identity_and_chain_failures(self):
        cases = [
            ("get_version", ["version"], "2.7.4"),
            ("get_network_info", ["network_name"], "mainnet"),
            ("get_network_info", ["network_prefix"], "xch"),
            ("get_network_info", ["genesis_challenge"], "aa" * 32),
            ("get_network_info", ["genesis_challenge"], "nothex"),
            ("get_blockchain_state", ["blockchain_state", "peak"], None),
            ("get_blockchain_state", ["blockchain_state", "sync", "synced"], False),
            ("get_blockchain_state", ["blockchain_state", "sync", "sync_mode"], True),
            ("get_blockchain_state", ["blockchain_state", "peak", "height"], True),
            ("get_blockchain_state", ["blockchain_state", "peak", "height"], -1),
            ("get_version", ["success"], 1),
        ]
        for route, path, value in cases:
            with self.subTest(route=route, path=path, value=value):
                data = replies()
                target = data[route]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                with self.assertRaises(probe.ProbeError):
                    probe.observe(lambda r, q: data[r])

    def test_coin_failures(self):
        for key, value in [("spent", True), ("spent_block_index", 2), ("confirmed_block_index", 101),
                           ("coinbase", 0), ("timestamp", -1), ("spent", 0)]:
            with self.subTest(key=key):
                data = replies()
                data["get_coin_record_by_name"]["coin_record"][key] = value
                with self.assertRaises(probe.ProbeError):
                    probe.observe(lambda r, q: data[r], COIN_ID)
        for amount in [True, -1, 2**64, "1000", 999]:
            data = replies()
            data["get_coin_record_by_name"]["coin_record"]["coin"]["amount"] = amount
            with self.assertRaises(probe.ProbeError):
                probe.observe(lambda r, q: data[r], COIN_ID)
        for puzzle, amount in [("00" * 32, 1000), (PUZZLE, 999)]:
            with self.assertRaises(probe.ProbeError):
                probe.observe(lambda r, q: replies()[r], COIN_ID, puzzle, amount)
        with self.assertRaises(probe.ProbeError):
            probe.observe(lambda r, q: replies()[r], puzzle=PUZZLE)

    def test_missing_coin_distinct_from_rpc_error(self):
        for code, expected in [("COIN_RECORD_NOT_FOUND", "Coin not found"), ("API_ERROR", "RPC request failed")]:
            data = replies()
            data["get_coin_record_by_name"] = {"success": False, "structuredError": {"code": code}, "traceback": "SECRET"}
            with self.assertRaisesRegex(probe.ProbeError, expected):
                probe.observe(lambda r, q: data[r], COIN_ID)

    def test_peak_changes_rejected(self):
        data = replies()
        count = 0
        def call(route, request):
            nonlocal count
            result = copy.deepcopy(data[route])
            if route == "get_blockchain_state":
                count += 1
                if count == 2:
                    result["blockchain_state"]["peak"]["header_hash"] = "44" * 32
            return result
        with self.assertRaisesRegex(probe.ProbeError, "Peak changed"):
            probe.observe(call, COIN_ID)

    def test_coin_encoding_boundaries(self):
        for amount, atom in [(0, ""), (127, "7f"), (128, "0080"), (2**64-1, "00ffffffffffffffff")]:
            expected = hashlib.sha256(bytes.fromhex(PARENT + PUZZLE + atom)).hexdigest()
            self.assertEqual(probe.coin_id(PARENT, PUZZLE, amount), expected)

    def test_endpoint_restrictions(self):
        for value in ["http://127.0.0.1:8555", "https://localhost:8555", "https://example.com:8555",
                      "https://192.0.2.1:8555", "https://127.0.0.1", "https://127.0.0.1:8555/push_tx",
                      "https://a:b@127.0.0.1:8555", "https://127.0.0.1:8555/?x=1", "https://127.0.0.1:8555/#x"]:
            with self.subTest(value=value), self.assertRaises(probe.ProbeError):
                probe.endpoint(value)
        self.assertEqual(probe.endpoint("https://[::1]:8555"), ("::1", 8555))

    def test_json_boundaries(self):
        for data in [b'{"success":true,"success":true}', b'{"success":NaN}', b'[]', b'null', b'\xff',
                     b'{"success":true,"a":Infinity}', b'x' * (probe.MAX_RESPONSE + 1)]:
            with self.assertRaises(probe.ProbeError):
                probe.decode(data)
        self.assertEqual(probe.decode(b'{"success":true,"amount":18446744073709551615}')["amount"], 2**64-1)

    def test_failed_run_removes_success_and_redacts(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text('{"old":true}')
            args = ["probe", "--endpoint", "https://127.0.0.1:8555", "--ca-cert", "SECRET", "--client-cert", "SECRET2", "--client-key", "SECRET3", "--report", str(report)]
            with patch.object(sys, "argv", args), patch.object(probe, "Transport", side_effect=OSError("SECRET")), patch.object(sys, "stderr") as err:
                self.assertEqual(probe.main(), 1)
            self.assertFalse(report.exists())
            self.assertNotIn("SECRET", str(err.write.call_args_list))

    def test_failed_observation_invalidates_previous_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text('{"old":true}')
            args = ["probe", "--endpoint", "https://127.0.0.1:8555", "--ca-cert", "CA", "--client-cert", "CERT", "--client-key", "KEY", "--report", str(report)]
            with patch.object(sys, "argv", args), patch.object(probe, "Transport") as transport, patch.object(sys, "stderr"):
                transport.return_value.call.return_value = {"success": True, "version": "unexpected"}
                self.assertEqual(probe.main(), 1)
            self.assertFalse(report.exists())

    def test_report_cannot_delete_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / "key"
            key.write_text("test credential")
            args = ["probe", "--endpoint", "https://127.0.0.1:8555", "--ca-cert", str(key), "--client-cert", str(key), "--client-key", str(key), "--report", str(key)]
            with patch.object(sys, "argv", args), patch.object(sys, "stderr"):
                self.assertEqual(probe.main(), 1)
            self.assertEqual(key.read_text(), "test credential")


class TLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seen = []
        cls.mode = "normal"
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cls.seen.append((self.path, request))
                if cls.mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://192.0.2.1:8555/push_tx")
                    self.end_headers()
                    return
                if cls.mode == "timeout":
                    threading.Event().wait(0.3)
                    return
                data = b'x' * (probe.MAX_RESPONSE + 1) if cls.mode == "large" else json.dumps(replies()[self.path[1:]]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (OSError, ssl.SSLError):
                    pass
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(FIXTURES / "server.crt", FIXTURES / "server.key")
        context.load_verify_locations(FIXTURES / "ca.crt")
        context.verify_mode = ssl.CERT_REQUIRED
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"https://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        assert not cls.thread.is_alive()

    def setUp(self):
        type(self).mode = "normal"
        self.seen.clear()

    def client(self, ca="ca.crt", timeout=2):
        return probe.Transport(self.url, FIXTURES / ca, FIXTURES / "client.crt", FIXTURES / "client.key", timeout)

    def test_actual_mutual_tls_cli_and_proxy_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            env = dict(os.environ, HTTPS_PROXY="http://192.0.2.1:1", ALL_PROXY="http://192.0.2.1:1", NO_PROXY="")
            p = subprocess.run([sys.executable, str(Path(probe.__file__)), "--endpoint", self.url,
                "--ca-cert", str(FIXTURES / "ca.crt"), "--client-cert", str(FIXTURES / "client.crt"),
                "--client-key", str(FIXTURES / "client.key"), "--coin-id", COIN_ID,
                "--expected-puzzle-hash", PUZZLE, "--expected-amount", "1000", "--report", str(report)],
                capture_output=True, env=env, timeout=15)
            self.assertEqual(p.returncode, 0, p.stderr)
            r = json.loads(report.read_text())
            self.assertEqual(r["coin"]["name"], COIN_ID)
            self.assertFalse(r["spend_validated"])
            self.assertNotIn(str(FIXTURES), report.read_text())
            self.assertEqual(len(self.seen), 5)

    def test_untrusted_server_rejected(self):
        with self.assertRaises(ssl.SSLError):
            self.client("wrong-ca.crt").call("get_version", {})
        self.assertEqual(self.seen, [])

    def test_client_certificate_required(self):
        c = self.client()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(FIXTURES / "ca.crt")
        c.context = context
        with self.assertRaises((ssl.SSLError, OSError)):
            c.call("get_version", {})
        self.assertEqual(self.seen, [])

    def test_redirect_rejected(self):
        type(self).mode = "redirect"
        with self.assertRaisesRegex(probe.ProbeError, "redirects"):
            self.client().call("get_version", {})
        self.assertEqual(len(self.seen), 1)

    def test_response_limit(self):
        type(self).mode = "large"
        with self.assertRaisesRegex(probe.ProbeError, "too large"):
            self.client().call("get_version", {})

    def test_socket_timeout(self):
        type(self).mode = "timeout"
        with self.assertRaises(TimeoutError):
            self.client(timeout=0.05).call("get_version", {})

    def test_mutating_route_blocked_before_io(self):
        for route in ["push_tx", "get_version/../push_tx", "get_private_key"]:
            with self.assertRaisesRegex(probe.ProbeError, "not allowed"):
                self.client().call(route, {})
        self.assertEqual(self.seen, [])


if __name__ == "__main__":
    unittest.main()
