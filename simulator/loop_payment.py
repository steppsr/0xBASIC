"""Loop-generated signed outputs through pinned SpendSim and the isolated full node."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import tomllib

from payment import MAX_COST, coin_json, condition_tree_json, invoke
from smoke import BASE, ROOT, WORK, preflight, require, simulator_constants

SOURCE = ROOT / "examples/loop-payment.bas"
TOTAL = 6


async def exercise(binary, directory, constants, manager, farm, submit, record, children, rewards):
    """One exact fixture and oracle, exercised through two real validation backends."""
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia.util.errors import Err
    from chia_rs import AugSchemeMPL, Coin, G2Element, SpendBundle, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_ints import uint64

    key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/loops/public-test-key/v1").digest())
    owner = key.get_g1()
    funding = Program.to(1)
    recipient = Program.to((1, []))
    recipient_hash = recipient.get_tree_hash()
    bindings = {"owner": {"hex": bytes(owner).hex()}, "total": str(TOTAL)}
    binding_file = directory / "bindings.json"
    binding_file.write_text(json.dumps(bindings), encoding="utf-8")
    out = directory / "payment"
    invoke(binary, "build", SOURCE, "--bindings", binding_file, "--out", out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    require(manifest["compiler"]["version"] == version, "Stale loop compiler")
    for name in ("template", "puzzle"):
        blob = (out / f"{name}.clvm").read_bytes()
        require(hashlib.sha256(blob).hexdigest() == manifest[name]["program_sha256"], "Loop artifact digest mismatch")
        require(Program.from_bytes(blob).get_tree_hash().hex() == manifest[name]["tree_hash"], "Loop tree hash mismatch")
    puzzle = Program.from_bytes((out / "puzzle.clvm").read_bytes())
    solution = Program.to([recipient_hash, 3])
    message = hashlib.sha256(b"0xBASIC/loop-payment/v1\x00" + bytes(owner) + bytes(recipient_hash)
                             + TOTAL.to_bytes(8, "big") + (3).to_bytes(4, "big")).digest()
    expected = Program.to([[73, TOTAL], [50, bytes(owner), message],
                           [51, recipient_hash, 1], [51, recipient_hash, 2], [51, recipient_hash, 3]])
    vm_cost, conditions = puzzle.run_with_cost(MAX_COST, solution)
    require(bytes(conditions) == bytes(expected), "Loop conditions differ from independent oracle")
    solution_file = directory / "solution.json"
    solution_file.write_text(json.dumps({"recipient": {"hex": recipient_hash.hex()}, "count": "3"}), encoding="utf-8")
    local = invoke(binary, "run", out / "manifest.json", "--solution", solution_file)
    require(local["validation"] == "clvm-execution-only" and local["tree"] == condition_tree_json(expected),
            "Loop CLI condition mismatch")
    require(int(local["cost"]) == vm_cost, "Loop CLI/upstream VM cost mismatch")

    await farm(funding.get_tree_hash())
    await farm(funding.get_tree_hash())
    funding_coin = min((r.coin for r in await rewards(funding.get_tree_hash()) if not r.spent and r.coin.amount > TOTAL),
                       key=lambda coin: (coin.amount, coin.name()))
    contract = Coin(funding_coin.name(), puzzle.get_tree_hash(), uint64(TOTAL))
    change = Coin(funding_coin.name(), funding.get_tree_hash(), uint64(funding_coin.amount - TOTAL))
    funding_bundle = SpendBundle([make_spend(funding_coin, funding, Program.to([
        [51, puzzle.get_tree_hash(), TOTAL], [51, funding.get_tree_hash(), funding_coin.amount - TOTAL]
    ]))], G2Element())
    status, error = await submit(funding_bundle)
    require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Loop funding failed: {status} {error}")
    await farm(funding.get_tree_hash(), [contract, change], [funding_coin])
    before = await record(contract.name())
    require(before is not None and before.coin == contract and not before.spent, "Loop contract not funded")
    expected_children = [Coin(contract.name(), recipient_hash, uint64(amount)) for amount in (1, 2, 3)]
    require(len({coin.name() for coin in expected_children}) == 3, "Duplicate loop output IDs")
    flags = int(get_flags_for_height_and_constants(manager.peak.height, constants)) | int(MEMPOOL_MODE)
    require(not flags & int(DONT_VALIDATE_SIGNATURE), "Loop signature validation bypass")
    final_message = message + bytes(contract.name()) + bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA)
    require(pkm_pairs_for_conditions_dict(conditions_dict_for_solution(puzzle, solution, MAX_COST), contract,
                                         constants.AGG_SIG_ME_ADDITIONAL_DATA) == [(owner, final_message)],
            "Loop independent signature message mismatch")
    signature = AugSchemeMPL.sign(key, final_message)
    require(AugSchemeMPL.verify(owner, final_message, signature), "Loop test signature invalid")

    async def unchanged():
        require(await record(contract.name()) == before, "Rejected loop spend changed input")
        require(not await children(contract.name()), "Rejected loop spend created children")
        require(not manager.mempool.all_item_ids(), "Rejected loop spend entered mempool")
        change_record = await record(change.name())
        require(change_record is not None and not change_record.spent, "Loop funding change consumed")

    cases = [
        ("missing-signature", solution, G2Element(), Err.BAD_AGGREGATE_SIGNATURE),
        ("changed-recipient-stale-signature", Program.to([funding.get_tree_hash(), 3]), signature, Err.BAD_AGGREGATE_SIGNATURE),
        ("zero-count", Program.to([recipient_hash, 0]), signature, Err.GENERATOR_RUNTIME_ERROR),
        ("count-over-limit", Program.to([recipient_hash, 4]), signature, Err.GENERATOR_RUNTIME_ERROR),
        ("incomplete-total", Program.to([recipient_hash, 2]), signature, Err.GENERATOR_RUNTIME_ERROR),
        ("malformed-solution", Program.to([recipient_hash]), signature, Err.GENERATOR_RUNTIME_ERROR),
    ]
    rejections = []
    for name, attempted, sig, expected_error in cases:
        rejected = SpendBundle([make_spend(contract, puzzle, attempted)], sig)
        status, error = await submit(rejected)
        require(status == MempoolInclusionStatus.FAILED and error == expected_error,
                f"{name}: unexpected loop rejection {status} {error}")
        await unchanged()
        await farm(funding.get_tree_hash(), [], [])
        await unchanged()
        rejections.append({"scenario": name, "status": status.name, "error": error.name,
                           "solution_hex": bytes(attempted).hex(), "signature": bytes(sig).hex(),
                           "bundle_id": rejected.name().hex(), "state_unchanged_after_farm": True})

    bundle = SpendBundle([make_spend(contract, puzzle, solution)], signature)
    status, error = await submit(bundle)
    require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Valid loop payment rejected: {status} {error}")
    item = manager.mempool.get_item_by_id(bundle.name())
    require(item is not None, "Accepted loop payment absent from mempool")
    cost = int(item.cost)
    inclusion = await farm(funding.get_tree_hash(), expected_children, [contract])
    after = await record(contract.name())
    require(after is not None and after.spent, "Loop contract not spent")
    records = await children(contract.name())
    require({r.coin for r in records} == set(expected_children) and len(records) == 3
            and all(not r.spent for r in records), "Loop children mismatch")
    require(sum(r.coin.amount for r in records) == TOTAL, "Loop amount conservation failed")
    require(all(r.confirmed_block_index == after.spent_block_index for r in records), "Loop confirmation heights differ")
    require(not (await record(change.name())).spent and not manager.mempool.all_item_ids(), "Loop final state mismatch")
    return {"manifest": manifest, "bindings": bindings, "solution_hex": bytes(solution).hex(),
            "conditions_hex": bytes(conditions).hex(), "application_message": message.hex(),
            "final_signing_message": final_message.hex(), "signature": bytes(signature).hex(),
            "signature_domain": constants.AGG_SIG_ME_ADDITIONAL_DATA.hex(), "flags": flags,
            "funding_coin": coin_json(funding_coin), "contract_coin": coin_json(contract),
            "change_coin": coin_json(change), "recipient_coins": [coin_json(c) for c in expected_children],
            "input_before": before.to_json_dict(), "input_after": after.to_json_dict(),
            "recipient_records": [r.to_json_dict() for r in sorted(records, key=lambda r: r.coin.amount)],
            "rejections": rejections, "payment_status": status.name, "bundle_id": bundle.name().hex(),
            "exactly_three_children": True, "change_unspent": True, "inclusion": inclusion,
            "local_cli_vm_cost": local["cost"], "upstream_program_vm_cost": str(vm_cost),
            "mempool_spend_cost": str(cost)}


async def spendsim(binary, directory, profile):
    from chia._tests.util.spend_sim import SpendSim, SimClient
    constants = simulator_constants(profile)
    async with SpendSim.managed(defaults=constants) as sim:
        client = SimClient(sim)

        async def farm(puzzle_hash, additions=None, removals=None):
            added, removed = await sim.farm_block(puzzle_hash)
            if additions is not None:
                require(set(added) == set(additions) and set(removed) == set(removals), "Loop SpendSim inclusion mismatch")
            return {"height": int(sim.block_height)}

        async def children(parent):
            return await client.get_coin_records_by_parent_ids([parent])

        result = await exercise(binary, directory, constants, sim.mempool_manager, farm, client.push_tx,
                                client.get_coin_record_by_name, children, client.get_coin_records_by_puzzle_hash)
    result["resources_closed"] = True
    return result


async def full_node(node, api, binary, directory):
    from chia.simulator.simulator_protocol import FarmNewBlockProtocol

    async def farm(puzzle_hash, additions=None, removals=None):
        block = await api.farm_new_transaction_block(FarmNewBlockProtocol(puzzle_hash))
        require(node.blockchain.get_peak().header_hash == block.header_hash, "Loop block not validated as peak")
        require(await node.block_store.get_full_block(block.header_hash) == block, "Loop block absent from store")
        if additions is not None:
            added = await node.coin_store.get_coins_added_at_height(block.height)
            removed = await node.coin_store.get_coins_removed_at_height(block.height)
            require({r.coin for r in added if not r.coinbase} == set(additions)
                    and {r.coin for r in removed} == set(removals), "Loop full-block inclusion mismatch")
            if removals:
                require(block.transactions_generator is not None, "Loop block lacks transaction generator")
        return {"height": int(block.height), "header_hash": block.header_hash.hex()}

    async def submit(bundle):
        # Same offline sync-readiness bypass as the existing payment gate; validation stays enabled.
        return await node.add_transaction(bundle, bundle.name(), test=True)

    async def children(parent):
        return await node.coin_store.get_coin_records_by_parent_ids(True, [parent])

    async def rewards(puzzle_hash):
        return await node.coin_store.get_coin_records_by_puzzle_hash(False, puzzle_hash)

    result = await exercise(binary, directory, node.constants, node.mempool_manager, farm, submit,
                            node.coin_store.get_coin_record, children, rewards)
    result["offline_sync_readiness_bypassed"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    platform_name = "windows" if sys.platform == "win32" else "linux"
    WORK.mkdir(parents=True, exist_ok=True)
    destination = WORK / f"loop-payment-{platform_name}.json"
    destination.unlink(missing_ok=True)
    profile, lock, versions = preflight()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    require(binary.is_file(), "Build CLI first or pass --binary")
    inputs = [SOURCE, Path(__file__), BASE / "payment.py", BASE / "smoke.py", ROOT / "Cargo.toml",
              BASE / "profile.json", lock, BASE / "build-requirements.lock", BASE / "tools.lock"]
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    results = []
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix="loop-payment-", dir=WORK) as temp:
            results.append(asyncio.run(spendsim(binary, Path(temp), profile)))
    require(results[0] == results[1], "Loop fresh reruns differ")
    require(hashlib.sha256(binary.read_bytes()).hexdigest() == binary_hash and all(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in hashes.items()), "Loop inputs changed")
    report = {"schema_version": 1, "validation": "spendsim-loop-payment", "identical_fresh_runs": 2,
              "python": platform.python_version(), "platform": sys.platform, "packages": versions,
              "profile": profile["profile"], "chia_commit": profile["chia_commit"], "source_hashes": profile["source_hashes"],
              "binary_sha256": binary_hash, "input_sha256": hashes, "outcome": results[0]}
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"PASS: loop payment, six rejections, three exact children; two identical fresh runs. Report: {destination}")


if __name__ == "__main__":
    main()
