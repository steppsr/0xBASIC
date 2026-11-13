"""Internal verified dispatch with one bounded worker; no operator submission CLI."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from confirmation import name
from confirm_fee import _report_path
from prepare_fee import FILES, SOURCE, read_json
from submission_attempt import _attempt
from submission_transport import _SubmissionTransport, _freeze
from testnet_probe import Transport, observe, require
from verify_signed_fee import verify_signed


def _worker_dispatch(packet, duration):
    deadline = time.monotonic() + duration
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        stdout, _ = process.communicate(json.dumps(packet).encode(), timeout=max(0, deadline - time.monotonic()))
        require(time.monotonic() < deadline and process.returncode == 0, "Submission worker failed or exceeded deadline")
        result = read_json(stdout)
        require(type(result) is dict and set(result) == {"outcome"}
                and result["outcome"] in {"reply-success", "reply-pending"}, "Invalid worker outcome")
        return result["outcome"]
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()


def _send(packet):
    """Worker trusts parent's verified bytes; performs fresh read checks before push."""
    bundle = packet["bundle"]
    _freeze(bundle)
    coin = bundle["coin_spends"][0]["coin"]
    tls = (packet["endpoint"], Path(packet["ca"]), Path(packet["cert"]), Path(packet["key"]))
    reader = Transport(*tls, packet["socket_timeout"])
    observed = observe(reader.call, name(coin), coin["puzzle_hash"], coin["amount"])
    require(observed["coin"]["parent_coin_info"] == coin["parent_coin_info"].removeprefix("0x").lower(), "Input parent differs")
    sender = _SubmissionTransport(*tls, bundle, packet["socket_timeout"])
    # Original preparation freshness must still hold immediately before dispatch.
    observed_at = datetime.fromisoformat(packet["observation_time"])
    require(observed_at.tzinfo is not None and 0 <= (datetime.now(timezone.utc) - observed_at).total_seconds()
            <= packet["max_age"], "Preparation expired before dispatch")
    return sender.push()


def _dispatch(args):
    require(type(args.duration) in (int, float) and math.isfinite(args.duration)
            and 0 < args.duration <= 600, "Invalid worker duration")
    require(type(args.timeout) in (int, float) and 0 < args.timeout <= 30, "Invalid socket timeout")
    protected = [args.binary, args.manifest, args.observation, args.solution, args.preparation, args.signature_response,
                 args.ca_cert, args.client_cert, args.client_key, SOURCE, *[args.manifest.parent / n for n in FILES]]
    path = _report_path(args.attempt, protected)
    require(not path.exists(), "Existing attempt cannot be reused")
    verified = verify_signed(args.binary, args.manifest, args.observation, args.solution, args.preparation,
                             args.signature_response, args.max_fee, args.max_observation_age)
    require(type(args.approved_bundle_id) is str and args.approved_bundle_id == verified["bundle_id"], "Bundle approval differs")
    # Copy before persisting intent; worker never rereads artifact or signing inputs.
    bundle = json.loads(_freeze(verified["spend_bundle"]))["spend_bundle"]
    context = {"bundle_id": verified["bundle_id"], "bundle_sha256": verified["bundle_sha256"],
               "input_id": name(bundle["coin_spends"][0]["coin"]), "preparation_sha256": verified["preparation_sha256"],
               "signature_response_sha256": verified["signature_response_sha256"]}
    packet = {"bundle": bundle, "endpoint": args.endpoint, "ca": str(args.ca_cert), "cert": str(args.client_cert),
              "key": str(args.client_key), "socket_timeout": args.timeout,
              "observation_time": verified["preparation"]["observation_time"], "max_age": args.max_observation_age}
    return _attempt(path, context, lambda: _worker_dispatch(packet, args.duration))


if __name__ == "__main__":
    if sys.argv[1:] != ["--worker"]:
        raise SystemExit("Internal worker only; no operator submission CLI")
    try:
        packet = read_json(sys.stdin.buffer.read(2 * 1024 * 1024 + 1))
        print(json.dumps({"outcome": _send(packet)}))
    except Exception:
        print("FAIL: submission worker failed; outcome may be unknown", file=sys.stderr)
        raise SystemExit(1)
