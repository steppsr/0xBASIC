"""Actual confirmation CLI over local mutual TLS and public signed fixtures; no live node."""
import argparse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import threading

from prepare_fee import ROOT, cli, digest, prepare
from test_confirmation import Fixture
from confirmation import name
from testnet_probe import GENESIS, coin_id


def loopback_only(event, args):
    if event in {"socket.connect", "socket.bind"}:
        address = args[1]
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise RuntimeError("Only local fixture sockets allowed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    binary = parser.parse_args().binary.resolve()
    work = ROOT / ".work/testnet"
    work.mkdir(parents=True, exist_ok=True)
    destination = work / ("operator-confirmation-windows.json" if sys.platform == "win32" else "operator-confirmation-linux.json")
    destination.unlink(missing_ok=True)
    sys.addaudithook(loopback_only)
    sys.path.insert(0, str(ROOT / "simulator"))
    from smoke import preflight
    preflight()
    from chia_rs import AugSchemeMPL, PrivateKey
    key = PrivateKey.from_bytes((1).to_bytes(32, "big"))  # Public fixture, never custody material.
    certs = ROOT / "integration/fixtures"
    current, seen = [None], []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            route = self.path[1:]
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(route)
            body = json.dumps(current[0].call(route, request)).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = None
    positives, negatives = [], []
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certs / "server.crt", certs / "server.key")
        context.load_verify_locations(certs / "ca.crt")
        context.verify_mode = ssl.CERT_REQUIRED
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory(prefix="operator-confirmation-", dir=work) as temporary:
            base = Path(temporary)
            artifact = base / "artifact"
            cli(binary, "build", ROOT / "examples/payment-fee.bas", "--bindings", ROOT / "examples/payment-fee.bindings.json", "--out", artifact)
            manifest = artifact / "manifest.json"
            ph = json.loads(manifest.read_text())["puzzle"]["tree_hash"]
            op, sp, pp, rp, report = [base / (n + ".json") for n in ("obs", "solution", "preparation", "response", "report")]
            peak = {"height": 99, "header_hash": "46" * 32, "synced": True, "sync_mode": False}
            parent = "45" * 32
            obs = {"schema_version": 1, "validation": "rpc-observation-only", "node_version": "2.7.5", "compiler_profile": "chia-clvm-0.19-strict-v2",
                   "network": {"name": "testnet11", "prefix": "txch", "genesis_challenge": GENESIS},
                   "before": peak, "after": dict(peak), "coin": {"name": coin_id(parent, ph, 1000), "parent_coin_info": parent,
                   "puzzle_hash": ph, "amount": "1000", "confirmed_block_index": 90, "spent_block_index": 0, "spent": False,
                   "coinbase": False, "timestamp": 1}, "atomic_snapshot": False, "spend_validated": False, "transactions_submitted": 0}
            def reset(payment=600, fee=10):
                obs["observed_at"] = datetime.now(timezone.utc).isoformat()
                op.write_text(json.dumps(obs), encoding="utf-8")
                sp.write_text(json.dumps({"paymentAmount": str(payment), "feeAmount": str(fee)}), encoding="utf-8")
                prepared = prepare(binary, manifest, op, sp, 20)
                pp.write_text(json.dumps(prepared, sort_keys=True, indent=2), encoding="utf-8")
                request = prepared["signing_request"]
                response = {"schema_version": 1, "scheme": "AugSchemeMPL", "preparation_sha256": digest(pp.read_bytes()),
                            "public_key": request["public_key"], "message": request["message"],
                            "signature": bytes(AugSchemeMPL.sign(key, bytes.fromhex(request["message"]))).hex()}
                rp.write_text(json.dumps(response), encoding="utf-8")
                f = Fixture()
                unsigned = prepared["unsigned_coin_spend"]
                f.input = {**unsigned["coin"], "amount": int(unsigned["coin"]["amount"])}
                f.spend = {"coin": f.input, "puzzle_reveal": unsigned["puzzle_reveal"], "solution": unsigned["solution"]}
                f.children = [{"parent_coin_info": c["parent_coin_info"], "puzzle_hash": c["puzzle_hash"], "amount": int(c["amount"])} for c in prepared["expected_outputs"]]
                f.records = {name(f.input): f.record(f.input, 90, 100), **{name(c): f.record(c, 100, 0) for c in f.children}}
                current[0] = f
                seen.clear()
                return f
            def run(depth=3, extra=()):
                command = [sys.executable, str(ROOT / "integration/confirm_fee.py"), "--binary", str(binary), "--manifest", str(manifest),
                           "--observation", str(op), "--solution", str(sp), "--preparation", str(pp), "--signature-response", str(rp),
                           "--max-fee", "20", "--depth", str(depth), "--report", str(report),
                           "--endpoint", f"https://127.0.0.1:{server.server_port}", "--ca-cert", str(certs / "ca.crt"),
                           "--client-cert", str(certs / "client.crt"), "--client-key", str(certs / "client.key"), *extra]
                return subprocess.run(command, capture_output=True, timeout=60)
            for status in ("confirmed-partial", "confirmed-exact", "confirming", "unspent", "conflicting-spend", "reorged"):
                f = reset(990 if status == "confirmed-exact" else 600)
                depth, extra = 3, []
                if status == "confirming":
                    depth = 4
                elif status == "unspent":
                    f.records[name(f.input)] = f.record(f.input, 90, 0)
                elif status == "conflicting-spend":
                    f.spend["solution"] = "80"
                elif status == "reorged":
                    extra = ["--previous-height", "100", "--previous-header-hash", "cc" * 32]
                result = run(depth, extra)
                expected = "confirmed" if status.startswith("confirmed-") else status
                assert result.returncode == (0 if expected == "confirmed" else 3), (status, seen, result.stderr)
                saved = json.loads(report.read_text())
                assert saved["observation"]["status"] == expected and saved["transactions_submitted"] == 0 and not saved["chain_proof"]
                assert saved["signature_verified_offline"] is True and all(route.startswith("get_") for route in seen)
                positives.append(status)
            for case in ("invalid-signature", "stale-preparation-observation", "wrong-rpc-network", "wrong-child", "invalid-depth"):
                f = reset()
                report.write_text("stale success")
                if case == "invalid-signature":
                    response = json.loads(rp.read_text()); response["signature"] = "00" * 96; rp.write_text(json.dumps(response))
                elif case == "stale-preparation-observation":
                    changed = json.loads(op.read_text()); changed["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(); op.write_text(json.dumps(changed))
                elif case == "wrong-rpc-network":
                    f.override["get_network_info"] = {"success": True, "network_name": "mainnet", "network_prefix": "xch", "genesis_challenge": GENESIS}
                elif case == "wrong-child":
                    f.records[name(f.children[0])]["confirmed_block_index"] = 99
                result = run(0 if case == "invalid-depth" else 3)
                assert result.returncode == 1 and not report.exists(), case
                if case in ("invalid-signature", "stale-preparation-observation", "invalid-depth"):
                    assert not seen, case
                negatives.append(case)
    finally:
        if thread is not None:
            server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)
            assert not thread.is_alive()
    assert len(positives) == 6 and len(negatives) == 5
    evidence = {"schema_version": 1, "validation": "public-fixture-operator-confirmation", "positive_cases": positives,
                "negative_cases": negatives, "live_node_contacted": False, "resources_closed": True,
                "binary_sha256": digest(binary.read_bytes()), "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p.read_bytes())
                  for p in (Path(__file__), ROOT / "integration/confirm_fee.py", ROOT / "integration/confirmation.py",
                            ROOT / "integration/confirmation_transport.py", ROOT / "integration/testnet_probe.py",
                            ROOT / "integration/verify_signed_fee.py", ROOT / "integration/prepare_fee.py", ROOT / "integration/test_confirmation.py")}}
    destination.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: 6 positive / 5 negative operator confirmation cases over mutual TLS; resources closed. Report: {destination}")


if __name__ == "__main__":
    main()
