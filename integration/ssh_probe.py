"""Read-only testnet probe over trusted SSH; no remote installation or submission."""
import argparse
import base64
import hashlib
import json
import math
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

from testnet_probe import ProbeError, require, hex32, uint, coin_id, endpoint as validate_endpoint

HERE = Path(__file__).resolve().parent
MODULES = ("network_identity", "testnet_probe")
MAX_PACKET = 256 * 1024
MAX_REPLY = 1024 * 1024

# SIGALRM bounds stdin transfer and the entire read sequence independently of SSH.
# No child process, compiler, signer, installation, or writable remote output.
REMOTE = r'''
import hashlib, json, os, signal, sys, types
from pathlib import Path
signal.signal(signal.SIGALRM, lambda *_: os._exit(124))
signal.setitimer(signal.ITIMER_REAL, DURATION)
try:
    raw = sys.stdin.buffer.read(262145)
    if len(raw) > 262144:
        raise ValueError()
    packet = json.loads(raw)
    modules = packet['modules']
    if set(modules) != {'network_identity', 'testnet_probe'}:
        raise ValueError()
    hashes = {}
    for name in ('network_identity', 'testnet_probe'):
        source = modules[name]
        hashes[name] = hashlib.sha256(source.encode('utf-8')).hexdigest()
        module = types.ModuleType(name)
        module.__file__ = '<streamed-' + name + '>'
        sys.modules[name] = module
        exec(compile(source, module.__file__, 'exec'), module.__dict__)
    probe = sys.modules['testnet_probe']
    request = packet['request']
    client = probe.Transport(request['endpoint'], Path(request['ca_cert']),
                             Path(request['client_cert']), Path(request['client_key']),
                             request['timeout'])
    expected = request.get('expected_coin')
    observation = (probe.observe(client.call) if expected is None else
                   probe.observe(client.call, expected['name'], expected['puzzle_hash'], expected['amount']))
    print(json.dumps({'nonce': packet['nonce'], 'sources': hashes,
                      'observation': observation}), flush=True)
except Exception:
    print('Remote read-only probe failed', file=sys.stderr)
    sys.exit(1)
'''


def command(target, duration):
    require(isinstance(target, str) and re.fullmatch(
        r"(?:[A-Za-z0-9][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.-]*", target),
        "Expected an explicit SSH host or user@host")
    require(type(duration) in (int, float) and math.isfinite(duration)
            and 0 < duration <= 120, "Duration must be in (0, 120] seconds")
    source = "DURATION = " + repr(duration) + "\n" + REMOTE
    encoded = base64.b64encode(source.encode()).decode("ascii")
    loader = "import base64; exec(base64.b64decode(" + repr(encoded) + "))"
    return ["ssh", "-T", "-a", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no", "-o",
            "PermitLocalCommand=no", "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-o", "ConnectTimeout=5", target,
            "/usr/bin/python3 -I -B -c " + shlex.quote(loader)]


def probe(target, endpoint, ca_cert, client_cert, client_key, duration=30, timeout=10,
          requested_coin=None, expected_puzzle_hash=None, expected_amount=None):
    argv = command(target, duration)
    validate_endpoint(endpoint)
    expected = None
    if any(value is not None for value in (requested_coin, expected_puzzle_hash, expected_amount)):
        require(all(value is not None for value in (requested_coin, expected_puzzle_hash, expected_amount)),
                "Coin ID, expected puzzle hash and expected amount must be supplied together")
        expected = {"name": hex32(requested_coin), "puzzle_hash": hex32(expected_puzzle_hash),
                    "amount": uint(expected_amount)}
    require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 30,
            "Socket timeout must be in (0, 30] seconds")
    for path in (ca_cert, client_cert, client_key):
        require(isinstance(path, str) and PurePosixPath(path).is_absolute()
                and not any(c in path for c in "\x00\r\n"), "Expected explicit remote absolute TLS paths")
    sources = {name: (HERE / (name + ".py")).read_text(encoding="utf-8") for name in MODULES}
    hashes = {name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()}
    nonce = secrets.token_hex(32)
    packet = json.dumps({"nonce": nonce, "modules": sources, "request": {
        "endpoint": endpoint, "ca_cert": ca_cert, "client_cert": client_cert,
        "client_key": client_key, "timeout": timeout, "expected_coin": expected}}).encode()
    require(len(packet) <= MAX_PACKET, "Worker packet is too large")
    deadline = time.monotonic() + duration
    transfer = tempfile.TemporaryFile()
    transfer.write(packet)
    transfer.seek(0)
    try:
        child = subprocess.Popen(argv, stdin=transfer, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except BaseException:
        transfer.close()
        raise
    try:
        remaining = deadline - time.monotonic()
        require(remaining > 0, "SSH startup exceeded deadline")
        stdout, _ = child.communicate(timeout=remaining)
        require(time.monotonic() < deadline, "SSH probe exceeded deadline")
        require(child.returncode == 0 and len(stdout) <= MAX_REPLY, "SSH probe failed")
        def pairs(items):
            result = {}
            for key, value in items:
                require(key not in result, "Duplicate worker reply key")
                result[key] = value
            return result
        def invalid_number(_):
            raise ProbeError("Invalid worker reply number")
        reply = json.loads(stdout, object_pairs_hook=pairs, parse_constant=invalid_number)
        require(type(reply) is dict and set(reply) == {"nonce", "sources", "observation"}
                and reply["nonce"] == nonce and reply["sources"] == hashes,
                "Worker reply does not match this request")
        observation = reply["observation"]
        require(type(observation) is dict and observation.get("validation") == "rpc-observation-only"
                and observation.get("transactions_submitted") == 0, "Unexpected observation")
        coin = observation.get("coin")
        if expected is None:
            require(coin is None, "Unexpected coin observation")
        else:
            require(type(coin) is dict and coin.get("name") == expected["name"]
                    and coin.get("puzzle_hash") == expected["puzzle_hash"]
                    and coin.get("amount") == str(expected["amount"])
                    and coin.get("spent") is False and type(coin.get("spent_block_index")) is int
                    and coin["spent_block_index"] == 0, "Coin observation does not match request")
            require(coin_id(coin.get("parent_coin_info"), expected["puzzle_hash"], expected["amount"])
                    == expected["name"], "Coin observation has inconsistent ID")
        return {"schema_version": 1, "validation": "ssh-read-only-probe",
                "sources": hashes, "observation": observation}
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate()
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()
        transfer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("ssh-target", "endpoint", "ca-cert", "client-cert", "client-key"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--coin-id")
    parser.add_argument("--expected-puzzle-hash")
    parser.add_argument("--expected-amount", type=int)
    args = parser.parse_args()
    try:
        result = probe(args.ssh_target, args.endpoint, args.ca_cert, args.client_cert,
                       args.client_key, args.duration, args.timeout,
                       args.coin_id, args.expected_puzzle_hash, args.expected_amount)
        print(json.dumps(result, indent=2))
        return 0
    except (ProbeError, OSError, ValueError, RecursionError, subprocess.SubprocessError, KeyboardInterrupt):
        print("FAIL: read-only SSH probe failed; no automatic retry", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
