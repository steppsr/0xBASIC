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
import time

from prepare_fee import ROOT, cli, digest, prepare, _prepare_for_identity
from network_identity import PUBLIC_TESTNET
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
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ssl.SSLError):
                pass  # Expected when a monitor terminates its delayed worker.
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = None
    positives, negatives, monitor_positives, monitor_negatives = [], [], [], []
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
            def reset(payment=600, fee=10, historical=False, original_age=60):
                created = datetime.now(timezone.utc) - timedelta(days=2)
                obs["observed_at"] = ((created - timedelta(seconds=original_age)) if historical else datetime.now(timezone.utc)).isoformat()
                op.write_text(json.dumps(obs), encoding="utf-8")
                sp.write_text(json.dumps({"paymentAmount": str(payment), "feeAmount": str(fee)}), encoding="utf-8")
                if historical:
                    prepared = _prepare_for_identity(binary, manifest, op, sp, 20, PUBLIC_TESTNET, 3600, observation_now=created)
                    prepared["prepared_at"] = created.isoformat()
                else:
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
            def run(depth=3, extra=(), monitoring=False, duration=15):
                command = [sys.executable, str(ROOT / "integration" / ("monitor_fee.py" if monitoring else "confirm_fee.py")), "--binary", str(binary), "--manifest", str(manifest),
                           "--observation", str(op), "--solution", str(sp), "--preparation", str(pp), "--signature-response", str(rp),
                           "--max-fee", "20", "--depth", str(depth), "--report", str(report),
                           "--endpoint", f"https://127.0.0.1:{server.server_port}", "--ca-cert", str(certs / "ca.crt"),
                           "--client-cert", str(certs / "client.crt"), "--client-key", str(certs / "client.key"), *extra]
                if monitoring:
                    command += ["--duration", str(duration), "--interval", "0", "--max-attempts", "2"]
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
            for state in ("confirmed", "unspent", "reorged"):
                f = reset(historical=True)
                saved_inputs = {p: p.read_bytes() for p in (op, sp, pp, rp)}
                extra = ["--historical"]
                if state == "unspent":
                    f.records[name(f.input)] = f.record(f.input, 90, 0)
                elif state == "reorged":
                    extra += ["--previous-height", "100", "--previous-header-hash", "cc" * 32]
                result = run(extra=extra)
                assert result.returncode == (0 if state == "confirmed" else 3), result.stderr
                saved = json.loads(report.read_text())
                assert saved["verification_mode"] == "historical" and not saved["fresh_for_submission"]
                assert saved["observation"]["status"] == state
                assert all(p.read_bytes() == raw for p, raw in saved_inputs.items())
                positives.append("historical-" + state)
            for case in ("default-refuses-history", "historically-stale", "future-preparation", "reversed-time", "historical-wrong-signature"):
                reset(historical=True, original_age=600 if case == "historically-stale" else 60)
                report.write_text("stale success")
                if case in ("future-preparation", "reversed-time"):
                    prepared = json.loads(pp.read_text())
                    prepared["prepared_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat() if case == "future-preparation" else (datetime.fromisoformat(prepared["observation_time"]) - timedelta(seconds=1)).isoformat()
                    pp.write_text(json.dumps(prepared))
                    reply = json.loads(rp.read_text()); reply["preparation_sha256"] = digest(pp.read_bytes()); rp.write_text(json.dumps(reply))
                elif case == "historical-wrong-signature":
                    reply = json.loads(rp.read_text()); reply["signature"] = "00" * 96; rp.write_text(json.dumps(reply))
                result = run(extra=[] if case == "default-refuses-history" else ["--historical"])
                assert result.returncode == 1 and not report.exists() and not seen, case
                negatives.append(case)
            reset(historical=True)
            from sign_fee import review
            from testnet_probe import ProbeError
            try:
                review(binary, manifest, op, sp, pp, 20)
            except ProbeError:
                negatives.append("signing-review-refuses-history")
            else:
                raise RuntimeError("Signing review accepted expired observation")
            for case in ("confirmed", "pending-timeout", "progressing", "reorged", "worker-timeout"):
                f = reset(historical=True)
                depth, duration = 3, 15
                calls = [0]
                original_call = f.call
                if case == "pending-timeout":
                    f.records[name(f.input)] = f.record(f.input, 90, 0)
                if case in ("progressing", "reorged"):
                    depth = 4
                if case == "worker-timeout":
                    duration = 1
                def monitored_call(route, request):
                    if route == "get_version":
                        calls[0] += 1
                        if case == "worker-timeout":
                            time.sleep(2)
                        if calls[0] == 2 and case == "progressing":
                            f.peak["height"] = 103
                        if calls[0] == 2 and case == "reorged":
                            f.block["header_hash"] = "cc" * 32
                    return original_call(route, request)
                f.call = monitored_call
                result = run(depth, monitoring=True, duration=duration)
                expected = "confirmed" if case in ("confirmed", "progressing") else "reorged" if case == "reorged" else "timed-out"
                assert result.returncode == (0 if expected == "confirmed" else 3), (case, result.stderr)
                saved = json.loads(report.read_text())
                assert saved["outcome"]["status"] == expected and saved["workers_closed"] is True and not saved["automatic_resume_allowed"]
                assert saved["transactions_submitted"] == 0 and not saved["fresh_for_submission"]
                if case == "pending-timeout":
                    assert saved["outcome"]["reason"] == "attempt-limit" and calls[0] == 2
                if case in ("progressing", "reorged"):
                    assert saved["outcome"]["attempts"] == 2 and saved["outcome"]["last_anchor"]["header_hash"] == "bb" * 32
                if case == "worker-timeout":
                    assert saved["outcome"]["reason"] in ("observation-timeout", "deadline") and saved["outcome"]["last_observation"] is None
                    time.sleep(2)  # Let the test server finish its deliberately delayed response before resetting fixtures.
                monitor_positives.append(case)
            for case in ("invalid-signature-before-worker", "rpc-failure-no-retry"):
                f = reset(historical=True)
                report.write_text("old success")
                if case == "invalid-signature-before-worker":
                    reply = json.loads(rp.read_text()); reply["signature"] = "00" * 96; rp.write_text(json.dumps(reply))
                else:
                    f.override["get_version"] = {"success": True, "version": "wrong"}
                result = run(monitoring=True)
                assert result.returncode == 1 and not report.exists(), case
                assert seen.count("get_version") == (0 if case == "invalid-signature-before-worker" else 1)
                monitor_negatives.append(case)
    finally:
        if thread is not None:
            server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)
            assert not thread.is_alive()
    assert len(positives) == 9 and len(negatives) == 11
    assert len(monitor_positives) == 5 and len(monitor_negatives) == 2
    evidence = {"schema_version": 1, "validation": "public-fixture-operator-confirmation", "positive_cases": positives,
                "negative_cases": negatives, "monitor_positive_cases": monitor_positives, "monitor_negative_cases": monitor_negatives,
                "live_node_contacted": False, "resources_closed": True,
                "binary_sha256": digest(binary.read_bytes()), "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p.read_bytes())
                  for p in (Path(__file__), ROOT / "integration/confirm_fee.py", ROOT / "integration/monitor_fee.py", ROOT / "integration/confirmation.py",
                            ROOT / "integration/confirmation_transport.py", ROOT / "integration/testnet_probe.py",
                            ROOT / "integration/verify_signed_fee.py", ROOT / "integration/prepare_fee.py", ROOT / "integration/test_confirmation.py")}}
    destination.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: confirmation 9 positive / 11 negative, monitor 5 positive / 2 negative over mutual TLS; resources closed. Report: {destination}")


if __name__ == "__main__":
    main()
