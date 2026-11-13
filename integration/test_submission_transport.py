"""Public fixture bytes sent only to a disposable mutual-TLS server."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from confirmation_transport import ConfirmationTransport
from submission_attempt import _attempt, read_attempt
from submission_transport import _SubmissionTransport, MAX_REQUEST
from test_submission_attempt import CONTEXT
from testnet_probe import MAX_RESPONSE, ProbeError, Transport

CERTS = Path(__file__).parent / "fixtures"
BUNDLE = {"coin_spends": [{"coin": {"parent_coin_info": "11" * 32, "puzzle_hash": "22" * 32,
           "amount": 100}, "puzzle_reveal": "01", "solution": "80"}], "aggregated_signature": "33" * 96}


class SubmissionTLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                cls.seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                mode = cls.mode
                if mode == "timeout":
                    threading.Event().wait(0.15)
                    return
                if mode == "disconnect":
                    self.close_connection = True
                    return
                status = 302 if mode == "redirect" else 200
                data = (b"x" * (MAX_RESPONSE + 1) if mode == "large" else
                        b'{"success":true,"success":false,"status":"SUCCESS"}' if mode == "duplicate" else
                        json.dumps(cls.reply).encode())
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain" if mode == "content" else "application/json")
                    self.send_header("Location", "https://192.0.2.1:8555/push_tx")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
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
        type(self).mode, type(self).seen = "normal", []
        type(self).reply = {"success": True, "status": "SUCCESS"}

    def client(self, **kwargs):
        return _SubmissionTransport(self.url, CERTS / "ca.crt", CERTS / "client.crt", CERTS / "client.key",
                                    copy.deepcopy(BUNDLE), **kwargs)

    def test_frozen_exact_bundle_and_one_call(self):
        bundle = copy.deepcopy(BUNDLE)
        client = _SubmissionTransport(self.url, CERTS / "ca.crt", CERTS / "client.crt", CERTS / "client.key", bundle)
        bundle["coin_spends"][0]["coin"]["amount"] = 999
        self.assertEqual(client.push(), "reply-success")
        self.assertEqual(self.seen, [("/push_tx", {"spend_bundle": BUNDLE})])
        with self.assertRaises(ProbeError):
            client.push()
        self.assertEqual(len(self.seen), 1)

    def test_pending_and_intent_before_tls_dispatch(self):
        type(self).reply = {"success": True, "status": "PENDING"}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "attempt.json"
            client = self.client()
            def dispatch():
                self.assertIsNone(read_attempt(path)["outcome"])
                return client.push()
            saved = _attempt(path, CONTEXT, dispatch)
            self.assertEqual(saved["outcome"], "reply-pending")
            self.assertFalse(saved["confirmation_established"])
            self.assertEqual(len(self.seen), 1)

    def test_false_contradictory_unknown_and_extended_replies_are_ambiguous(self):
        replies = [{"success": False, "error": "fixture"}, {"success": True, "status": "FAILED"},
                   {"success": True}, {"success": 1, "status": "SUCCESS"},
                   {"success": True, "status": "SUCCESS", "error": "contradiction"},
                   {"success": True, "status": []}]
        for reply in replies:
            type(self).reply = reply
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "attempt.json"
                client = self.client()
                with self.assertRaises(ProbeError):
                    _attempt(path, CONTEXT, client.push)
                self.assertEqual(read_attempt(path)["outcome"], "unknown")
                with self.assertRaises(ProbeError):
                    client.push()
        self.assertEqual(len(self.seen), len(replies))

    def test_http_failures_and_disconnect_never_retry(self):
        for mode in ("redirect", "large", "duplicate", "content", "disconnect", "timeout"):
            type(self).mode = mode
            client = self.client(timeout=0.03 if mode == "timeout" else 2)
            with self.subTest(mode=mode), self.assertRaises(Exception):
                client.push()
            with self.assertRaises(ProbeError):
                client.push()
        self.assertEqual(len(self.seen), 6)
        threading.Event().wait(0.2)  # Let the disposable delayed handler exit before next fixture.

    def test_mutating_route_is_separate_and_payload_cannot_change(self):
        for kind in (Transport, ConfirmationTransport):
            client = kind(self.url, CERTS / "ca.crt", CERTS / "client.crt", CERTS / "client.key")
            with self.assertRaises(ProbeError):
                client.call("push_tx", {"spend_bundle": BUNDLE})
        client = self.client()
        for route in ("get_version", "send_transaction", "push_tx/../get_version"):
            with self.assertRaises(ProbeError):
                client.call(route, {"spend_bundle": BUNDLE})
        changed = copy.deepcopy(BUNDLE)
        changed["coin_spends"][0]["coin"]["amount"] = 101
        with self.assertRaises(ProbeError):
            client.call("push_tx", {"spend_bundle": changed})
        self.assertEqual(self.seen, [])

    def test_invalid_and_oversize_bundles_fail_before_tls_setup(self):
        invalid = [{}, {**BUNDLE, "coin_spends": []}, {**BUNDLE, "aggregated_signature": "00"},
                   {**BUNDLE, "coin_spends": BUNDLE["coin_spends"] * 2}]
        for amount in (True, -1, 2**64, "100"):
            bundle = copy.deepcopy(BUNDLE)
            bundle["coin_spends"][0]["coin"]["amount"] = amount
            invalid.append(bundle)
        bundle = copy.deepcopy(BUNDLE)
        bundle["coin_spends"][0]["solution"] = "80" * MAX_REQUEST
        invalid.append(bundle)
        with patch.object(Transport, "__init__", side_effect=AssertionError("TLS setup reached")):
            for bundle in invalid:
                with self.assertRaises(ProbeError):
                    _SubmissionTransport(self.url, None, None, None, bundle)
        self.assertEqual(self.seen, [])

    def test_credentials_endpoint_and_timeout_restrictions(self):
        with self.assertRaises(ssl.SSLError):
            _SubmissionTransport(self.url, CERTS / "wrong-ca.crt", CERTS / "client.crt", CERTS / "client.key", BUNDLE).push()
        client = self.client()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.load_verify_locations(CERTS / "ca.crt")
        client.context = context
        with self.assertRaises((ssl.SSLError, OSError)):
            client.push()
        for url in ("http://127.0.0.1:8555", "https://localhost:8555", "https://192.0.2.1:8555"):
            with self.assertRaises(ProbeError):
                _SubmissionTransport(url, None, None, None, BUNDLE)
        for timeout in (0, 31, float("nan"), float("inf"), True):
            with self.assertRaises(ProbeError):
                self.client(timeout=timeout)
        self.assertEqual(self.seen, [])


if __name__ == "__main__":
    unittest.main()
