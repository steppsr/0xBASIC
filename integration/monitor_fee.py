"""Bounded read-only confirmation monitoring with independently verified historical expectations."""
import argparse
import copy
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from confirmation import name, observe_confirmation, spend
from confirmation_transport import ConfirmationTransport
from confirm_fee import _report_path
from prepare_fee import FILES, SOURCE, read_json
from testnet_probe import require, uint, hex32
from verify_signed_fee import verify_historical_signed

STATES = {"unspent", "confirming", "confirmed", "reorged", "conflicting-spend"}


def bounds(duration, interval, attempts):
    require(type(duration) in (int, float) and math.isfinite(duration) and 0 < duration <= 600, "Duration must be finite and in (0,600]")
    require(type(interval) in (int, float) and math.isfinite(interval) and 0 <= interval <= duration, "Invalid interval")
    require(type(attempts) is int and 1 <= attempts <= 1000, "Attempts must be 1..1000")


def poll(read, input_id, anchor, *, duration, interval, max_attempts):
    bounds(duration, interval, max_attempts)
    start = time.monotonic()
    deadline = start + duration
    attempts, last = 0, None
    def result(status, reason):
        return {"status": status, "reason": reason, "attempts": attempts, "max_attempts": max_attempts,
                "duration_seconds": duration, "elapsed_seconds": time.monotonic() - start,
                "last_observation": last, "last_anchor": anchor, "transactions_submitted": 0}
    while attempts < max_attempts:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return result("timed-out", "deadline")
        attempts += 1
        try:
            observation = read(copy.deepcopy(anchor), remaining)
        except subprocess.TimeoutExpired:
            return result("timed-out", "observation-timeout")
        if time.monotonic() >= deadline:
            return result("timed-out", "deadline")
        require(type(observation) is dict and observation.get("status") in STATES
                and observation.get("input_id") == input_id and observation.get("chain_proof") is False
                and type(observation.get("transactions_submitted")) is int and observation["transactions_submitted"] == 0,
                "Invalid observation scope or input")
        last = copy.deepcopy(observation)
        if observation["status"] in {"confirming", "confirmed"}:
            candidate = observation.get("confirmation_anchor")
            require(type(candidate) is dict and set(candidate) == {"input_id", "height", "header_hash"}
                    and candidate["input_id"] == input_id, "Missing confirmation anchor")
            candidate = {"input_id": input_id, "height": uint(candidate["height"], 32), "header_hash": hex32(candidate["header_hash"])}
            require(anchor is None or candidate == anchor, "Observation changed the remembered inclusion anchor")
            anchor = candidate
        if observation["status"] in {"confirmed", "reorged", "conflicting-spend"}:
            return result(observation["status"], "terminal-observation")
        if attempts < max_attempts:
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
    return result("timed-out", "attempt-limit")


def worker_read(packet, remaining):
    deadline = time.monotonic() + remaining
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, _ = process.communicate(json.dumps(packet).encode(), timeout=max(0, deadline - time.monotonic()))
        require(process.returncode == 0, "Observation worker failed")
        return read_json(stdout)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def worker():
    """One RPC read only; no verification claims, compiler subprocess or signing."""
    try:
        p = read_json(sys.stdin.buffer.read(1024 * 1024 + 1))
        client = ConfirmationTransport(p["endpoint"], Path(p["ca"]), Path(p["cert"]), Path(p["key"]), p["socket_timeout"])
        observed = observe_confirmation(client.call, p["spend"], p["children"], p["depth"], p["anchor"])
        print(json.dumps(observed))
        return 0
    except Exception:
        print("FAIL: read-only observation worker failed", file=sys.stderr)
        return 1


def monitor(args):
    bounds(args.duration, args.interval, args.max_attempts)
    require(type(args.depth) is int and 1 <= args.depth <= 10000, "Invalid depth")
    require((args.previous_height is None) == (args.previous_header_hash is None), "Prior height/hash must be supplied together")
    if args.previous_height is not None:
        uint(args.previous_height, 32)
        hex32(args.previous_header_hash)
    verified = verify_historical_signed(args.binary, args.manifest, args.observation, args.solution,
                                       args.preparation, args.signature_response, args.max_fee, args.max_observation_age)
    require(len(verified["spend_bundle"]["coin_spends"]) == 1, "Expected single verified spend")
    expected = spend(verified["spend_bundle"]["coin_spends"][0])
    input_id = name(expected["coin"])
    children = [{"parent_coin_info": c["parent_coin_info"], "puzzle_hash": c["puzzle_hash"], "amount": int(c["amount"])}
                for c in verified["preparation"]["expected_outputs"]]
    anchor = None if args.previous_height is None else {"input_id": input_id, "height": args.previous_height, "header_hash": hex32(args.previous_header_hash)}
    packet = {"endpoint": args.endpoint, "ca": str(args.ca_cert), "cert": str(args.client_cert), "key": str(args.client_key),
              "socket_timeout": args.timeout, "spend": expected, "children": children, "depth": args.depth}
    outcome = poll(lambda prior, remaining: worker_read({**packet, "anchor": prior}, remaining), input_id, anchor,
                   duration=args.duration, interval=args.interval, max_attempts=args.max_attempts)
    return {"schema_version": 1, "validation": "historical-verified-read-only-monitor", "expected_bundle_id": verified["bundle_id"],
            "preparation_sha256": verified["preparation_sha256"], "signature_response_sha256": verified["signature_response_sha256"],
            "verification_mode": "historical", "outcome": outcome, "workers_closed": True,
            "fresh_for_submission": False, "chain_proof": False, "automatic_resume_allowed": False, "transactions_submitted": 0}


def main():
    if sys.argv[1:] == ["--worker"]:
        return worker()
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("binary", "manifest", "observation", "solution", "preparation", "signature-response", "ca-cert", "client-cert", "client-key", "report"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--max-fee", type=int, required=True)
    parser.add_argument("--depth", type=int, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--interval", type=float, required=True)
    parser.add_argument("--max-attempts", type=int, required=True)
    parser.add_argument("--max-observation-age", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--previous-height", type=int)
    parser.add_argument("--previous-header-hash")
    args = parser.parse_args()
    temporary = None
    try:
        protected = [args.binary, args.observation, args.solution, args.preparation, args.signature_response,
                     args.ca_cert, args.client_cert, args.client_key, SOURCE, *[args.manifest.parent / n for n in FILES]]
        report = _report_path(args.report, protected)
        report.unlink(missing_ok=True)
        result = monitor(args)
        status = result["outcome"]["status"]
        require(status in {"confirmed", "reorged", "conflicting-spend", "timed-out"}, "Invalid monitor result")
        report.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=report.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, sort_keys=True, indent=2)
            handle.write("\n")
        temporary.replace(report)
        print(f"MONITORED: {status}; read-only observations; no submission")
        return 0 if status == "confirmed" else 3
    except (Exception, KeyboardInterrupt):
        print("FAIL: verification, observation or monitor operation failed; no current result", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
