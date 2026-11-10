"""TN-1 read-only, explicit-loopback Chia testnet RPC observation."""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import re
import ssl
import sys
import tempfile
from urllib.parse import urlsplit

GENESIS = "37a90eb5185a9c4439a91ddc98bbadce7b4feba060d50116a067de66bf236615"
ROUTES = {"get_version", "get_network_info", "get_blockchain_state", "get_coin_record_by_name"}
MAX_RESPONSE = 1024 * 1024


class ProbeError(Exception):
    pass


def require(ok, message):
    if not ok:
        raise ProbeError(message)


def hex32(value):
    require(isinstance(value, str) and re.fullmatch(r"(?:0x)?[0-9a-fA-F]{64}", value) is not None, "Expected 32-byte hex")
    return value.removeprefix("0x").lower()


def uint(value, bits=64):
    require(type(value) is int and 0 <= value < 1 << bits, "Invalid unsigned integer")
    return value


def coin_id(parent, puzzle, amount):
    uint(amount)
    atom = b"" if amount == 0 else amount.to_bytes((amount.bit_length() + 8) // 8, "big", signed=True)
    return hashlib.sha256(bytes.fromhex(hex32(parent)) + bytes.fromhex(hex32(puzzle)) + atom).hexdigest()


def endpoint(value):
    try:
        u = urlsplit(value)
        require(u.scheme == "https" and u.username is None and u.password is None
                and u.path in {"", "/"} and not u.query and not u.fragment, "Require plain loopback HTTPS endpoint")
        require(ipaddress.ip_address(u.hostname).is_loopback and u.port is not None and 0 < u.port < 65536,
                "Require literal loopback IP and explicit port")
        return u.hostname, u.port
    except (ValueError, TypeError):
        raise ProbeError("Invalid loopback endpoint") from None


def decode(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def invalid(_):
        raise ProbeError("Invalid JSON number")
    try:
        require(len(data) <= MAX_RESPONSE, "RPC response too large")
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
        require(type(value) is dict and type(value.get("success")) is bool, "Malformed RPC envelope")
        return value
    except (UnicodeError, ValueError, RecursionError):
        raise ProbeError("Malformed RPC JSON") from None


class Transport:
    def __init__(self, url, ca, cert, key, timeout=10):
        self.host, self.port = endpoint(url)
        require(type(timeout) in (int, float) and 0 < timeout <= 30, "Timeout must be in (0,30] seconds")
        self.timeout = timeout
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.check_hostname = False  # Chia private certificates; explicit loopback and CA only.
        self.context.verify_mode = ssl.CERT_REQUIRED
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_verify_locations(cafile=str(ca))
        self.context.load_cert_chain(str(cert), str(key), password=lambda: "")

    def validate_request(self, route, request):
        require(route in ROUTES, "RPC route not allowed")
        require(request == {} if route != "get_coin_record_by_name" else
                type(request) is dict and set(request) == {"name"} and hex32(request["name"]), "Invalid RPC request")

    def call(self, route, request):
        self.validate_request(route, request)
        connection = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout, context=self.context)
        try:
            connection.request("POST", "/" + route, body=json.dumps(request).encode(),
                               headers={"Content-Type": "application/json", "Accept": "application/json"})
            response = connection.getresponse()
            require(response.status == 200, "Unexpected HTTP status; redirects are forbidden")
            require(response.getheader("Content-Type", "").split(";")[0].strip() == "application/json", "Unexpected content type")
            return decode(response.read(MAX_RESPONSE + 1))
        finally:
            connection.close()


def fetch(call, route, request=None):
    value = call(route, {} if request is None else request)
    require(type(value) is dict and type(value.get("success")) is bool, "Malformed RPC envelope")
    if not value["success"]:
        error = value.get("structuredError")
        if route == "get_coin_record_by_name" and type(error) is dict and error.get("code") == "COIN_RECORD_NOT_FOUND":
            raise ProbeError("Coin not found")
        raise ProbeError("RPC request failed")  # Do not echo server tracebacks or credential paths.
    return value


def state(call):
    s = fetch(call, "get_blockchain_state").get("blockchain_state")
    require(type(s) is dict and type(s.get("sync")) is dict and type(s.get("peak")) is dict, "Missing chain state or peak")
    require(s["sync"].get("synced") is True and s["sync"].get("sync_mode") is False, "Node is not synced")
    return {"height": uint(s["peak"].get("height"), 32), "header_hash": hex32(s["peak"].get("header_hash")),
            "synced": True, "sync_mode": False}


def observe(call, requested_coin=None, puzzle=None, amount=None):
    if requested_coin is not None:
        requested_coin = hex32(requested_coin)
    require(requested_coin is not None or (puzzle is None and amount is None), "Coin expectations require coin ID")
    if puzzle is not None:
        puzzle = hex32(puzzle)
    if amount is not None:
        uint(amount)
    version = fetch(call, "get_version").get("version")
    require(version == "2.7.5", "Unreviewed node version")
    network = fetch(call, "get_network_info")
    require(network.get("network_name") == "testnet11" and network.get("network_prefix") == "txch"
            and hex32(network.get("genesis_challenge")) == GENESIS, "Wrong network identity")
    before = state(call)
    coin = None
    if requested_coin is not None:
        r = fetch(call, "get_coin_record_by_name", {"name": "0x" + requested_coin}).get("coin_record")
        require(type(r) is dict and type(r.get("coin")) is dict, "Malformed coin record")
        c = r["coin"]
        parent, ph, value = hex32(c.get("parent_coin_info")), hex32(c.get("puzzle_hash")), uint(c.get("amount"))
        require(coin_id(parent, ph, value) == requested_coin, "Coin ID mismatch")
        require(r.get("spent") is False and uint(r.get("spent_block_index"), 32) == 0, "Coin is spent or inconsistent")
        confirmed = uint(r.get("confirmed_block_index"), 32)
        require(confirmed <= before["height"] and type(r.get("coinbase")) is bool, "Invalid coin confirmation record")
        timestamp = uint(r.get("timestamp"))
        require(puzzle is None or puzzle == ph, "Puzzle hash mismatch")
        require(amount is None or amount == value, "Amount mismatch")
        coin = {"name": requested_coin, "parent_coin_info": parent, "puzzle_hash": ph, "amount": str(value),
                "confirmed_block_index": confirmed, "spent_block_index": 0, "spent": False,
                "coinbase": r["coinbase"], "timestamp": timestamp}
    after = state(call)
    require(before == after, "Peak changed during observation; retry explicitly")
    return {"schema_version": 1, "validation": "rpc-observation-only", "node_version": version,
            "network": {"name": "testnet11", "prefix": "txch", "genesis_challenge": GENESIS},
            "compiler_profile": "chia-clvm-0.19-strict-v2", "observed_at": datetime.now(timezone.utc).isoformat(),
            "before": before, "after": after, "coin": coin, "atomic_snapshot": False,
            "spend_validated": False, "transactions_submitted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    for name in ("ca-cert", "client-cert", "client-key", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--coin-id")
    parser.add_argument("--expected-puzzle-hash")
    parser.add_argument("--expected-amount", type=int)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args()
    temporary = None
    try:
        protected = [p.resolve() for p in (args.ca_cert, args.client_cert, args.client_key)]
        require(not args.report.is_symlink() and args.report.resolve() not in protected, "Report overlaps credentials")
        args.report.unlink(missing_ok=True)
        client = Transport(args.endpoint, args.ca_cert, args.client_cert, args.client_key, args.timeout)
        result = observe(client.call, args.coin_id, args.expected_puzzle_hash, args.expected_amount)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.report.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, indent=2)
            handle.write("\n")
        temporary.replace(args.report)
        print("PASS: read-only RPC observation recorded; no spend validation or submission")
        return 0
    except ProbeError as error:
        print(f"FAIL: {error}", file=sys.stderr)
    except (OSError, ssl.SSLError, http.client.HTTPException):
        print("FAIL: TLS, connection, timeout or local file operation failed", file=sys.stderr)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
