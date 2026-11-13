"""TN-2 offline preparation for the reviewed fee-payment example; never signs or sends."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from testnet_probe import GENESIS, ProbeError, coin_id, hex32, require, uint
from network_identity import PUBLIC_TESTNET, validate as validate_identity

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/payment-fee.bas"
SOURCE_SHA256 = "c6d66ae96b1a3cce27ef0c2890b6211e98911304e088ca7a6c0d13b001333109"
PROFILE = "chia-clvm-0.19-strict-v2"
MAX_COST = 10_000_000
FILES = ("manifest.json", "template.clvm", "template.hex", "puzzle.clvm", "puzzle.hex")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def bad(_):
        raise ProbeError("Invalid JSON number")
    try:
        require(len(data) <= 1024 * 1024, "JSON input too large")
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad)
        require(type(value) is dict, "Expected JSON object")
        return value
    except (UnicodeError, ValueError, RecursionError):
        raise ProbeError("Malformed JSON input") from None


def amount(value):
    require(isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,19}", value) is not None, "Expected canonical decimal amount")
    return uint(int(value))


def observation(value, max_age=300, now=None):
    return _observation_for_identity(value, PUBLIC_TESTNET, max_age, now)


def _observation_for_identity(value, identity, max_age=300, now=None):
    validate_identity(identity)
    require(type(max_age) is int and 0 < max_age <= 3600, "Observation age must be 1..3600 seconds")
    label = "rpc-observation-only" if identity is PUBLIC_TESTNET else "isolated-rpc-observation-only"
    require(type(value.get("schema_version")) is int and value["schema_version"] == 1 and value.get("validation") == label
            and value.get("node_version") == identity.version and value.get("compiler_profile") == PROFILE,
            "Observation identity mismatch")
    require(value.get("spend_validated") is False and value.get("atomic_snapshot") is False
            and type(value.get("transactions_submitted")) is int and value["transactions_submitted"] == 0,
            "Observation scope mismatch")
    require(value.get("network") == identity.network(), "Observation network mismatch")
    try:
        observed = datetime.fromisoformat(value["observed_at"])
        require(observed.tzinfo is not None, "Observation timestamp needs timezone")
        age = ((now or datetime.now(timezone.utc)) - observed).total_seconds()
        require(0 <= age <= max_age, "Observation is stale or future-dated")
    except (KeyError, ValueError, TypeError):
        raise ProbeError("Invalid observation timestamp") from None
    before, after = value.get("before"), value.get("after")
    require(type(before) is dict and before == after and before.get("synced") is True
            and before.get("sync_mode") is False, "Observation peak mismatch")
    height = uint(before.get("height"), 32)
    hex32(before.get("header_hash"))
    c = value.get("coin")
    require(type(c) is dict and c.get("spent") is False and uint(c.get("spent_block_index"), 32) == 0,
            "Missing or spent observed coin")
    total = amount(c.get("amount"))
    require(total > 0 and uint(c.get("confirmed_block_index"), 32) <= height, "Invalid coin amount/height")
    require(type(c.get("coinbase")) is bool, "Malformed coinbase field")
    uint(c.get("timestamp"))
    require(coin_id(c.get("parent_coin_info"), c.get("puzzle_hash"), total) == hex32(c.get("name")), "Observed coin ID mismatch")
    return c, height


def cli(binary, *args):
    p = subprocess.run([str(binary), *map(str, args), "--json"], capture_output=True, timeout=30)
    require(p.returncode == 0 and not p.stderr, "Compiler rejected preparation input")
    r = read_json(p.stdout)
    require(r.get("schema_version") == 1 and r.get("ok") is True and r.get("diagnostics") == [], "Compiler envelope mismatch")
    return r["result"]


def prepare(binary, manifest_path, observation_path, solution_path, max_fee, max_age=300):
    return _prepare_for_identity(binary, manifest_path, observation_path, solution_path, max_fee, PUBLIC_TESTNET, max_age)


def _prepare_for_identity(binary, manifest_path, observation_path, solution_path, max_fee, identity, max_age=300, *, observation_now=None):
    validate_identity(identity)
    # Pin the existing independent runtime. No node, wallet or keychain is instantiated.
    sys.path.insert(0, str(ROOT / "simulator"))
    from smoke import preflight
    profile, lock, versions = preflight()
    from chia.consensus.constants import replace_str_to_bytes
    from chia.consensus.default_constants import DEFAULT_CONSTANTS
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.types.blockchain_format.program import Program
    from chia_rs import Coin, G1Element, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_bytes import bytes32
    from chia_rs.sized_ints import uint64

    binary = Path(binary).resolve()
    require(binary.is_file(), "Build CLI first or supply --binary")
    require(Path(manifest_path).name == "manifest.json", "Expected artifact manifest.json")
    blobs = {name: (Path(manifest_path).parent / name).read_bytes() for name in FILES}
    obs_bytes, solution_bytes = Path(observation_path).read_bytes(), Path(solution_path).read_bytes()
    obs, sol, manifest = read_json(obs_bytes), read_json(solution_bytes), read_json(blobs["manifest.json"])
    c, height = _observation_for_identity(obs, identity, max_age, observation_now)
    require(set(sol) == {"paymentAmount", "feeAmount"}, "Expected paymentAmount and feeAmount only")
    payment, fee, total = amount(sol["paymentAmount"]), amount(sol["feeAmount"]), amount(c["amount"])
    require(payment > 0 and payment + fee <= total and fee <= uint(max_fee), "Payment or fee exceeds bounds/budget")
    require(type(manifest.get("compiler")) is dict and manifest["compiler"].get("version") == "0.3.0-alpha.1" and manifest.get("language_version") == "0.3"
            and manifest.get("abi_version") == 1 and manifest.get("target_profile") == PROFILE, "Artifact identity mismatch")
    for role in ("template", "puzzle"):
        require(manifest[role]["binary"] == role + ".clvm" and manifest[role]["hex"] == role + ".hex", "Nonstandard artifact paths")
    source = SOURCE.read_bytes().replace(b"\r\n", b"\n")
    require(digest(source) == SOURCE_SHA256, "Unreviewed fee-payment source")
    bindings = manifest.get("bindings")
    require(type(bindings) is dict and set(bindings) == {"owner", "recipient", "changerecipient", "inputamount"}, "Wrong fixed bindings")
    require(amount(bindings["inputamount"]) == total, "Fixed input differs from observed coin")
    with tempfile.TemporaryDirectory(prefix="0xbasic offline preparation ") as temporary:
        work = Path(temporary)
        artifact = work / "input"
        artifact.mkdir()
        for name, blob in blobs.items():
            (artifact / name).write_bytes(blob)
        (work / "solution.json").write_bytes(solution_bytes)
        # CLI reader validates the snapshot's complete artifact contract before independent execution.
        local = cli(binary, "run", artifact / "manifest.json", "--solution", work / "solution.json")
        (work / "payment-fee.bas").write_bytes(source)
        (work / "bindings.json").write_text(json.dumps(bindings), encoding="utf-8")
        cli(binary, "build", work / "payment-fee.bas", "--bindings", work / "bindings.json", "--out", work / "rebuilt")
        for role in ("template", "puzzle"):
            require((work / "rebuilt" / (role + ".clvm")).read_bytes() == blobs[role + ".clvm"], "Artifact is not the reviewed fee contract")
    puzzle = Program.from_bytes(blobs["puzzle.clvm"])
    require(puzzle.get_tree_hash().hex() == hex32(c["puzzle_hash"]), "Observed puzzle differs from artifact")
    owner = bytes.fromhex(bindings["owner"]["hex"])
    recipient = bytes.fromhex(hex32(bindings["recipient"]["hex"]))
    change_hash = bytes.fromhex(hex32(bindings["changerecipient"]["hex"]))
    require(recipient != change_hash, "Destinations must differ")
    message = hashlib.sha256(b"0xBASIC/payment-fee/v1\x00" + owner + recipient + change_hash
                            + b"".join(v.to_bytes(8, "big") for v in (total, payment, fee))).digest()
    change = total - payment - fee
    expected = [[73, total], [50, owner, message], [52, fee], [51, recipient, payment]]
    if change:
        expected.append([51, change_hash, change])
    solution = Program.to([payment, fee])
    if identity is PUBLIC_TESTNET:
        constants = replace_str_to_bytes(DEFAULT_CONSTANTS, GENESIS_CHALLENGE=GENESIS, AGG_SIG_ME_ADDITIONAL_DATA=GENESIS,
                                        HARD_FORK_HEIGHT=0, SOFT_FORK8_HEIGHT=3755000, SOFT_FORK9_HEIGHT=3924000, TESTNET=True)
    else:
        # Exact pinned full-node test constants; never infer constants/domain from RPC metadata.
        from full_node_smoke import source_check
        source_check()
        from chia.simulator.block_tools import test_constants
        constants = test_constants
        require(constants.GENESIS_CHALLENGE.hex() == identity.genesis, "Isolated constants/identity mismatch")
    domain = bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA)
    flags = int(get_flags_for_height_and_constants(height, constants)) | int(MEMPOOL_MODE)
    require(not flags & int(DONT_VALIDATE_SIGNATURE), "Signature bypass flag is forbidden")
    vm_cost, actual = puzzle.run_with_cost(MAX_COST, solution, flags=flags)
    require(bytes(actual) == bytes(Program.to(expected)), "Independent network-flags condition oracle mismatch")
    # Also compare the local runner's exact condition tree; costs may differ by flags.
    def tree(p):
        return {"atom": p.atom.hex()} if p.pair is None else {"pair": [tree(p.first()), tree(p.rest())]}
    require(local["tree"] == tree(actual) and local["validation"] == "clvm-execution-only", "CLI/independent output mismatch")
    coin = Coin(bytes32.from_hexstr(c["parent_coin_info"]), bytes32.from_hexstr(c["puzzle_hash"]), uint64(total))
    require(coin.name().hex() == c["name"], "Independent coin ID differs")
    final_message = message + bytes(coin.name()) + domain
    require(pkm_pairs_for_conditions_dict(conditions_dict_for_solution(puzzle, solution, MAX_COST), coin, domain)
            == [(G1Element.from_bytes(owner), final_message)], "Independent signing pair mismatch")
    outputs = []
    for ph, value in [(recipient, payment), *([(change_hash, change)] if change else [])]:
        child = Coin(coin.name(), bytes32(ph), uint64(value))
        outputs.append({"name": child.name().hex(), "parent_coin_info": coin.name().hex(), "puzzle_hash": ph.hex(), "amount": str(value)})
    return {"schema_version": 1, "validation": "offline-unsigned-fee-preparation" if identity is PUBLIC_TESTNET else "isolated-offline-unsigned-fee-preparation", "network": obs["network"],
            "node_baseline": identity.version, "compiler_profile": PROFILE, "bindings": bindings, "solution_values": sol,
            "prepared_at": datetime.now(timezone.utc).isoformat(), "observed_peak": obs["after"],
            "observation_time": obs["observed_at"], "observation_is_trusted_chain_proof": False,
            "recheck_before_signing_and_submission": True, "source_sha256_lf": SOURCE_SHA256,
            "input_sha256": {**{name: digest(blob) for name, blob in blobs.items()},
                              "observation": digest(obs_bytes), "solution": digest(solution_bytes), "binary": digest(binary.read_bytes())},
            "runtime": {"chia": profile["chia_blockchain"], "chia_rs": versions["chia-rs"], "lock_sha256": digest(lock.read_bytes()),
                        "flags": flags, "local_vm_cost": str(local["cost"]), "network_flags_vm_cost": str(vm_cost),
                        **({"consensus_constants_sha256": digest(json.dumps(constants.to_json_dict(), sort_keys=True, separators=(",", ":")).encode())}
                           if identity is not PUBLIC_TESTNET else {})},
            "unsigned_coin_spend": {"coin": {"parent_coin_info": c["parent_coin_info"], "puzzle_hash": c["puzzle_hash"], "amount": str(total)},
                                    "coin_id": coin.name().hex(), "puzzle_reveal": bytes(puzzle).hex(), "solution": bytes(solution).hex()},
            "conditions_hex": bytes(actual).hex(), "signing_request": {"scheme": "AGG_SIG_ME", "public_key": owner.hex(),
                "application_message": message.hex(), "additional_data": domain.hex(), "message": final_message.hex()},
            "expected_outputs": outputs, "accounting": {"input": str(total), "payment": str(payment), "change": str(change),
                "fee": str(fee), "reserved_fee": str(fee), "maximum_fee": str(max_fee)},
            "signature_verified": False, "mempool_validated": False, "transactions_submitted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "manifest", "observation", "solution", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--max-fee", type=int, required=True)
    parser.add_argument("--max-observation-age", type=int, default=300)
    args = parser.parse_args()
    temporary = None
    try:
        protected = [args.binary, args.observation, args.solution, SOURCE, *[args.manifest.parent / n for n in FILES]]
        require(not args.out.is_symlink() and args.out.resolve() not in [p.resolve() for p in protected], "Output overlaps preparation input")
        args.out.unlink(missing_ok=True)
        result = prepare(args.binary, args.manifest, args.observation, args.solution, args.max_fee, args.max_observation_age)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.out.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
        temporary.replace(args.out)
        print("PASS: offline unsigned fee preparation; no signature verification or submission")
        return 0
    except (ProbeError, RuntimeError, OSError, ValueError, KeyError, TypeError, ImportError, subprocess.SubprocessError):
        print("FAIL: preparation input, artifact, runtime or execution check failed", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
