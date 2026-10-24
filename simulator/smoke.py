"""Offline SpendSim environment smoke; no contract/signature acceptance claim."""
import asyncio
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "simulator"
WORK = ROOT / ".work/m4"


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def preflight():
    require(sys.prefix != sys.base_prefix, "Use the isolated simulator virtual environment")
    require(Path(sys.prefix).resolve().is_relative_to(ROOT), "Simulator environment must be inside this project checkout")
    require(sys.version_info[:2] == (3, 13), "Python 3.13 required")
    require(platform.machine().lower() in {"amd64", "x86_64"}, "Only x86_64 is locked")
    require(sys.platform in {"win32", "linux"}, "Only Windows/Linux are locked")
    profile = json.loads((BASE / "profile.json").read_text(encoding="utf-8"))
    require(metadata.version("chia-blockchain") == profile["chia_blockchain"], "Chia profile mismatch")
    require(metadata.version("chia_rs") == profile["chia_rs"], "chia_rs profile mismatch")
    name = "windows" if sys.platform == "win32" else "linux"
    lock = BASE / f"requirements-{name}.lock"
    versions = dict(re.findall(r"^([a-zA-Z0-9_.-]+)==([^ ;\\\n]+)", lock.read_text(encoding="utf-8"), re.M))
    require(bool(versions), "Empty lock")
    for package, version in versions.items():
        require(metadata.version(package) == version.strip(), f"Version mismatch: {package}")
    chia = metadata.distribution("chia-blockchain")
    for relative, expected in profile["source_hashes"].items():
        data = Path(chia.locate_file(relative)).read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected, f"Pinned upstream source mismatch: {relative}")
    WORK.mkdir(parents=True, exist_ok=True)
    # Process-local roots only. SpendSim uses an in-memory database, not a node root.
    for key in ["CHIA_ROOT", "CHIA_KEYS_ROOT", "CHIA_SIMULATOR_ROOT"]:
        os.environ[key] = str(WORK / "unused-chia-roots" / key.lower())
    return profile, lock, versions


def simulator_constants(profile):
    from chia.consensus.default_constants import DEFAULT_CONSTANTS
    from chia_rs.sized_bytes import bytes32
    base = bytes.fromhex(profile["signature_domain_hex"])
    overrides = {"AGG_SIG_ME_ADDITIONAL_DATA": bytes32(base)}
    for code, name in enumerate(["PARENT", "PUZZLE", "AMOUNT", "PUZZLE_AMOUNT", "PARENT_AMOUNT", "PARENT_PUZZLE"], 43):
        overrides[f"AGG_SIG_{name}_ADDITIONAL_DATA"] = bytes32(hashlib.sha256(base + bytes([code])).digest())
    return DEFAULT_CONSTANTS.replace(**overrides)


async def smoke(profile):
    from chia._tests.util.spend_sim import SpendSim, SimClient
    from chia_rs import get_flags_for_height_and_constants, DONT_VALIDATE_SIGNATURE, MEMPOOL_MODE
    from chia_rs.sized_bytes import bytes32
    constants = simulator_constants(profile)
    recipient = bytes32(bytes.fromhex("11" * 32))
    async with SpendSim.managed(defaults=constants) as sim:
        client = SimClient(sim)
        require(not sim.block_records, "Expected fresh simulator")
        additions, removals = await sim.farm_block(recipient)
        require(len(sim.block_records) == 1 and not additions and not removals, "Unexpected first block")
        records = await client.get_coin_records_by_puzzle_hash(recipient)
        require(len(records) == 2, "Expected two reward coin records")
        for record in records:
            require(not record.spent and record.coin.amount > 0, "Invalid reward record")
            require(await client.get_coin_record_by_name(record.coin.name()) == record, "Coin lookup mismatch")
        require(not await client.get_all_mempool_tx_ids(), "Expected empty mempool")
        flags = int(get_flags_for_height_and_constants(sim.block_height, constants))
        mempool_flags = flags | int(MEMPOOL_MODE)
        require(not mempool_flags & int(DONT_VALIDATE_SIGNATURE), "Signature validation bypass flag")
        result = {"blocks_farmed": 1, "block_height": int(sim.block_height),
                  "previous_transaction_block_height": int(sim.block_records[-1].prev_transaction_block_height),
                  "flags_for_height": flags, "mempool_prevalidation_flags": mempool_flags, "constants": constants.to_json_dict(),
                  "reward_coins": sorted([{"coin_id": r.coin.name().hex(), "amount": str(r.coin.amount),
                    "confirmed_block_index": int(r.confirmed_block_index), "spent": r.spent} for r in records],key=lambda r:r["coin_id"])}
    result["resources_closed"] = True
    return result


def main():
    profile, lock, versions = preflight()
    outcome = asyncio.run(smoke(profile))
    report = {"schema_version": 1, "validation": "spendsim-environment-smoke-only",
              "profile": profile["profile"], "chia_commit": profile["chia_commit"],
              "python": platform.python_version(), "platform": sys.platform, "machine": platform.machine(),
              "requirements_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
              "lock_hashes": {name: hashlib.sha256((BASE / name).read_bytes()).hexdigest()
                              for name in [lock.name, "build-requirements.lock", "tools.lock", "profile.json"]},
              "resolver_selection": profile["resolver"],
              "packages": versions, "source_hashes": profile["source_hashes"], "outcome": outcome}
    destination = WORK / ("smoke-windows.json" if sys.platform == "win32" else "smoke-linux.json")
    destination.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"PASS: isolated SpendSim farmed one block, verified two reward coins and closed resources. Report: {destination}")


if __name__ == "__main__":
    main()
