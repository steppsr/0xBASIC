"""Actual loopback mutual TLS carrying the confirmation read protocol."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import threading
import unittest
from unittest.mock import patch

from confirmation import observe_confirmation
from confirmation_transport import ConfirmationTransport
from test_confirmation import Fixture
from testnet_probe import MAX_RESPONSE, ProbeError, Transport

CERTS = Path(__file__).parent / "fixtures"


class ConfirmationTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                route = self.path[1:]
                cls.seen.append((route, request))
                if cls.mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", "https://192.0.2.1:8555/push_tx")
                    self.end_headers()
                    return
                if cls.mode == "timeout":
                    threading.Event().wait(0.15)
                    return
                if cls.mode == "large":
                    data = b"x" * (MAX_RESPONSE + 1)
                elif cls.mode == "duplicate":
                    data = b'{"success":true,"success":false}'
                else:
                    data = json.dumps(cls.fixture.call(route, request)).encode()
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
        context.load_cert_chain(CERTS / "server.crt", CERTS / "server.key")
        context.load_verify_locations(CERTS / "ca.crt")
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
        type(self).fixture = Fixture()
        type(self).seen = []
        type(self).mode = "normal"

    def client(self, ca="ca.crt", timeout=2, kind=ConfirmationTransport):
        return kind(self.url, CERTS / ca, CERTS / "client.crt", CERTS / "client.key", timeout)

    def observe(self, depth=3, anchor=None):
        return observe_confirmation(self.client().call, self.fixture.spend, self.fixture.children, depth, anchor)

    def test_complete_confirmed_observation_over_mutual_tls_ignores_proxy(self):
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://192.0.2.1:1", "ALL_PROXY": "http://192.0.2.1:1", "NO_PROXY": ""}):
            result = self.observe()
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["confirmations"], 3)
        self.assertEqual(len(result["children"]), 2)
        self.assertEqual(result["transactions_submitted"], 0)
        self.assertEqual([r for r, _ in self.seen], ["get_version", "get_network_info", "get_blockchain_state",
            "get_blockchain_state", "get_coin_record_by_name", "get_puzzle_and_solution", "get_block_record_by_height",
            "get_coin_record_by_name", "get_coin_record_by_name", "get_blockchain_state"])

    def test_depth_and_reorg_statuses_through_authenticated_transport(self):
        result = self.observe(4)
        self.assertEqual(result["status"], "confirming")
        self.fixture.block["header_hash"] = "cc" * 32
        result = self.observe(4, result["confirmation_anchor"])
        self.assertEqual(result["status"], "reorged")
        self.assertEqual(result["confirmations"], 0)

    def test_additional_routes_rejected_by_original_probe(self):
        for route, request in [("get_block_record_by_height", {"height": 100}),
                               ("get_puzzle_and_solution", {"coin_id": "11" * 32, "height": 100})]:
            with self.assertRaises(ProbeError):
                self.client(kind=Transport).call(route, request)
        self.assertEqual(self.seen, [])

    def test_mutating_private_and_path_routes_rejected_before_io(self):
        for route in ("push_tx", "send_transaction", "get_private_key", "get_block_record_by_height/../push_tx"):
            with self.subTest(route=route), self.assertRaises(ProbeError):
                self.client().call(route, {})
        self.assertEqual(self.seen, [])

    def test_request_schema_and_uint32_height_checked_before_io(self):
        for route in ("get_block_record_by_height", "get_puzzle_and_solution"):
            valid = {"height": 100}
            if route == "get_puzzle_and_solution":
                valid["coin_id"] = "11" * 32
            invalid = [{}, None, {**valid, "extra": 1}]
            invalid.extend({**valid, "height": x} for x in (-1, 2**32, True, "100", 100.0))
            if route == "get_puzzle_and_solution":
                invalid.append({**valid, "coin_id": "bad"})
            for request in invalid:
                with self.subTest(route=route, request=request), self.assertRaises(ProbeError):
                    self.client().call(route, request)
        self.assertEqual(self.seen, [])

    def test_wrong_ca_and_missing_client_certificate_rejected(self):
        with self.assertRaises(ssl.SSLError):
            self.client(ca="wrong-ca.crt").call("get_block_record_by_height", {"height": 100})
        client = self.client()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(CERTS / "ca.crt")
        client.context = context
        with self.assertRaises((ssl.SSLError, OSError)):
            client.call("get_block_record_by_height", {"height": 100})
        self.assertEqual(self.seen, [])

    def test_redirect_oversize_and_duplicate_json_rejected(self):
        for mode in ("redirect", "large", "duplicate"):
            type(self).mode = mode
            with self.subTest(mode=mode), self.assertRaises(ProbeError):
                self.client().call("get_block_record_by_height", {"height": 100})
        self.assertEqual(len(self.seen), 3)

    def test_socket_timeout_and_endpoint_constraints(self):
        type(self).mode = "timeout"
        with self.assertRaises(TimeoutError):
            self.client(timeout=0.03).call("get_block_record_by_height", {"height": 100})
        for endpoint in ("http://127.0.0.1:8555", "https://192.0.2.1:8555", "https://localhost:8555"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ProbeError):
                ConfirmationTransport(endpoint, CERTS / "ca.crt", CERTS / "client.crt", CERTS / "client.key")


if __name__ == "__main__":
    unittest.main()
