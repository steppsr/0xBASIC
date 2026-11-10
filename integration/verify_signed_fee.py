"""TN-3a: revalidate a preparation and verify a detached BLS response, without keys or RPC."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import subprocess
import tempfile

from prepare_fee import FILES, SOURCE, digest, prepare, read_json
from testnet_probe import ProbeError, require


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def response_fields(response, preparation_hash, key, message):
    require(set(response) == {"schema_version", "scheme", "preparation_sha256", "public_key", "message", "signature"}, "Unexpected signature response fields")
    require(type(response["schema_version"]) is int and response["schema_version"] == 1
            and response["scheme"] == "AugSchemeMPL", "Wrong signature response identity")
    require(response["preparation_sha256"] == preparation_hash and response["public_key"] == key
            and response["message"] == message, "Signature response does not match reviewed request")
    require(isinstance(response["signature"], str) and re.fullmatch("[0-9a-f]{192}", response["signature"]) is not None,
            "Expected canonical 96-byte signature hex")
    return bytes.fromhex(response["signature"])


def verify_signed(binary, manifest, observation, solution, preparation, response, max_fee, max_age=300):
    original_bytes, response_bytes = Path(preparation).read_bytes(), Path(response).read_bytes()
    original, reply = read_json(original_bytes), read_json(response_bytes)
    regenerated = prepare(binary, manifest, observation, solution, max_fee, max_age)
    require(set(original) == set(regenerated), "Incomplete or extended preparation")
    try:
        created = datetime.fromisoformat(original["prepared_at"])
        observed = datetime.fromisoformat(original["observation_time"])
        require(created.tzinfo is not None and observed <= created <= datetime.now(timezone.utc), "Invalid preparation timestamp")
    except (ValueError, TypeError):
        raise ProbeError("Invalid preparation timestamp") from None
    # Only the recomputation timestamp changes. Type-exact canonical JSON avoids True == 1.
    regenerated["prepared_at"] = original["prepared_at"]
    require(canonical(original) == canonical(regenerated), "Preparation differs from independently revalidated inputs")
    signing = regenerated["signing_request"]
    signature_bytes = response_fields(reply, digest(original_bytes), signing["public_key"], signing["message"])
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia_rs import AugSchemeMPL, Coin, G1Element, G2Element, SpendBundle
    from chia_rs.sized_bytes import bytes32
    from chia_rs.sized_ints import uint64
    public_key = G1Element.from_bytes(bytes.fromhex(signing["public_key"]))
    signature = G2Element.from_bytes(signature_bytes)
    require(signature != G2Element() and AugSchemeMPL.verify(public_key, bytes.fromhex(signing["message"]), signature),
            "Detached signature verification failed")
    spend = regenerated["unsigned_coin_spend"]
    coin = spend["coin"]
    actual_coin = Coin(bytes32.from_hexstr(coin["parent_coin_info"]), bytes32.from_hexstr(coin["puzzle_hash"]), uint64(int(coin["amount"])))
    require(actual_coin.name().hex() == spend["coin_id"], "Signed input coin mismatch")
    bundle = SpendBundle([make_spend(actual_coin, Program.from_bytes(bytes.fromhex(spend["puzzle_reveal"])),
                                   Program.from_bytes(bytes.fromhex(spend["solution"])))], signature)
    encoded = bundle.to_json_dict()
    require(SpendBundle.from_json_dict(encoded) == bundle, "Spend bundle JSON round trip differs")
    return {"schema_version": 1, "validation": "offline-signature-verified-fee-bundle", "network": regenerated["network"],
            "preparation_sha256": digest(original_bytes), "signature_response_sha256": digest(response_bytes),
            "verified_at": datetime.now(timezone.utc).isoformat(), "preparation": regenerated,
            "spend_bundle": encoded, "bundle_id": bundle.name().hex(), "bundle_sha256": digest(bytes(bundle)),
            "signature_verified": True, "mempool_validated": False, "transactions_submitted": 0,
            "observation_is_trusted_chain_proof": False, "recheck_before_submission": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "manifest", "observation", "solution", "preparation", "signature-response", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--max-fee", type=int, required=True)
    parser.add_argument("--max-observation-age", type=int, default=300)
    args = parser.parse_args()
    temporary = None
    try:
        protected = [args.binary, args.observation, args.solution, args.preparation, args.signature_response, SOURCE,
                     *[args.manifest.parent / name for name in FILES]]
        require(not args.out.is_symlink() and args.out.resolve() not in [p.resolve() for p in protected], "Output overlaps signing input")
        args.out.unlink(missing_ok=True)
        result = verify_signed(args.binary, args.manifest, args.observation, args.solution, args.preparation,
                               args.signature_response, args.max_fee, args.max_observation_age)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.out.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(args.out)
        print("PASS: detached signature verified and bundle assembled offline; no node validation or submission")
        return 0
    except (ProbeError, RuntimeError, OSError, ValueError, KeyError, TypeError, ImportError, subprocess.SubprocessError):
        print("FAIL: signed preparation, runtime or signature verification failed", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
