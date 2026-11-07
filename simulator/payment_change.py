"""PC-2: signed payment/change scenarios in isolated, pinned SpendSim."""
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

SOURCE = ROOT / "examples/payment-change.bas"
AMOUNT = 1000
ERRORS = {
    "missing-signature": "BAD_AGGREGATE_SIGNATURE",
    "wrong-owner": "BAD_AGGREGATE_SIGNATURE",
    "wrong-network-domain": "BAD_AGGREGATE_SIGNATURE",
    "changed-payment-stale-signature": "BAD_AGGREGATE_SIGNATURE",
    "cross-coin-replay": "BAD_AGGREGATE_SIGNATURE",
    "wrong-coin-amount": "ASSERT_MY_AMOUNT_FAILED",
    "zero-payment": "GENERATOR_RUNTIME_ERROR",
    "overspend": "GENERATOR_RUNTIME_ERROR",
    "malformed-solution": "GENERATOR_RUNTIME_ERROR",
    "noncanonical-amount": "GENERATOR_RUNTIME_ERROR",
}
SCENARIOS = ("partial", "exact", *ERRORS)


async def scenario(binary, directory, profile, name):
    from chia._tests.util.spend_sim import SpendSim, SimClient
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia_rs import AugSchemeMPL, Coin, G2Element, SpendBundle, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_ints import uint64

    require(name in SCENARIOS, "Unknown payment/change scenario")
    constants = simulator_constants(profile)
    key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/payment-change/public-test-key/v1").digest())
    owner = key.get_g1()
    funding = Program.to(1)
    recipient = Program.to((1, [])).get_tree_hash()
    change_hash = Program.to((1, [[83, 0]])).get_tree_hash()
    require(recipient != change_hash and change_hash != funding.get_tree_hash(), "Destinations not distinct")
    bindings = {"owner": {"hex": bytes(owner).hex()}, "recipient": {"hex": recipient.hex()},
                "changeRecipient": {"hex": change_hash.hex()}, "inputAmount": str(AMOUNT)}
    binding_file = directory / "bindings.json"
    binding_file.write_text(json.dumps(bindings), encoding="utf-8")
    out = directory / "artifact"
    invoke(binary, "build", SOURCE, "--bindings", binding_file, "--out", out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    require(manifest["compiler"]["version"] == version, "Stale payment/change compiler")
    for part in ("template", "puzzle"):
        blob = (out / f"{part}.clvm").read_bytes()
        require(hashlib.sha256(blob).hexdigest() == manifest[part]["program_sha256"], "Artifact digest mismatch")
        require(Program.from_bytes(blob).get_tree_hash().hex() == manifest[part]["tree_hash"], "Artifact tree hash mismatch")
    puzzle = Program.from_bytes((out / "puzzle.clvm").read_bytes())

    def application_message(value):
        return hashlib.sha256(b"0xBASIC/payment-change/v1\x00" + bytes(owner) + bytes(recipient) + bytes(change_hash)
                              + AMOUNT.to_bytes(8, "big") + value.to_bytes(8, "big")).digest()

    records = {"scenario": name, "manifest": manifest, "bindings": bindings,
               "constants": constants.to_json_dict(), "funding": [], "rejections": [], "confirmations": []}
    async with SpendSim.managed(defaults=constants) as sim:
        client = SimClient(sim)
        await sim.farm_block(funding.get_tree_hash())
        await sim.farm_block(funding.get_tree_hash())
        funding_changes = []

        async def get(coin):
            record = await client.get_coin_record_by_name(coin.name())
            require(record is not None and record.coin == coin, "Missing/mismatched coin record")
            return record

        async def children(coin):
            return await client.get_coin_records_by_parent_ids([coin.name()])

        async def fund(amount=AMOUNT):
            rewards = await client.get_coin_records_by_puzzle_hash(funding.get_tree_hash(), include_spent_coins=False)
            reserved = {c.name() for c in funding_changes}
            parent = min((r.coin for r in rewards if r.coin.amount > amount and r.coin.name() not in reserved),
                         key=lambda c: (c.amount, c.name()))
            coin = Coin(parent.name(), puzzle.get_tree_hash(), uint64(amount))
            change = Coin(parent.name(), funding.get_tree_hash(), uint64(parent.amount - amount))
            bundle = SpendBundle([make_spend(parent, funding, Program.to([
                [51, coin.puzzle_hash, amount], [51, change.puzzle_hash, change.amount]
            ]))], G2Element())
            status, error = await client.push_tx(bundle)
            require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Funding rejected: {status} {error}")
            added, removed = await sim.farm_block()
            require(len(added) == 2 and set(added) == {coin, change} and removed == [parent], "Wrong funding inclusion")
            require((await get(parent)).spent and not (await get(coin)).spent and not (await get(change)).spent,
                    "Wrong funding records")
            require(not await client.get_all_mempool_tx_ids(), "Funding remains in mempool")
            funding_changes.append(change)
            records["funding"].append({"parent": coin_json(parent), "coin": coin_json(coin), "change": coin_json(change)})
            return coin

        first = await fund()
        target = await fund(AMOUNT + 1 if name == "wrong-coin-amount" else AMOUNT) if name in {"wrong-coin-amount", "cross-coin-replay"} else first
        change_before = [await get(c) for c in funding_changes]
        if name == "cross-coin-replay":
            require(first.name() != target.name() and first.parent_coin_info != target.parent_coin_info
                    and first.puzzle_hash == target.puzzle_hash and first.amount == target.amount, "Invalid replay fixture")

        async def unchanged_funding():
            require([await get(c) for c in funding_changes] == change_before, "Contract spend changed funding change")

        def flags():
            value = int(get_flags_for_height_and_constants(sim.mempool_manager.peak.height, constants)) | int(MEMPOOL_MODE)
            require(not value & int(DONT_VALIDATE_SIGNATURE), "Signature checking bypassed")
            return value

        def message(coin, amount):
            final = application_message(amount) + bytes(coin.name()) + bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA)
            pairs = pkm_pairs_for_conditions_dict(conditions_dict_for_solution(puzzle, Program.to([amount]), MAX_COST),
                                                 coin, constants.AGG_SIG_ME_ADDITIONAL_DATA)
            require(pairs == [(owner, final)], "Independent signature message differs from upstream")
            return final

        def signed(coin, amount):
            final = message(coin, amount)
            sig = AugSchemeMPL.sign(key, final)
            require(AugSchemeMPL.verify(owner, final, sig), "Positive signature self-check failed")
            return sig

        async def reject(coin, solution, signature, expected_error):
            before = await get(coin)
            require(not before.spent and not await children(coin), "Negative input already used")
            bundle = SpendBundle([make_spend(coin, puzzle, solution)], signature)
            context = {"peak_height": int(sim.block_height), "flags": flags()}
            status, error = await client.push_tx(bundle)
            require(status == MempoolInclusionStatus.FAILED and error is not None and error.name == expected_error,
                    f"{name}: expected {expected_error}, got {status} {error}")

            async def unchanged():
                require(await get(coin) == before and not await children(coin), "Rejection changed contract state")
                require(not await client.get_all_mempool_tx_ids(), "Rejected attempt entered active mempool")
                await unchanged_funding()

            await unchanged()
            added, removed = await sim.farm_block()
            require(not added and not removed, "Rejected attempt was included")
            await unchanged()
            records["rejections"].append({"status": status.name, "error": error.name, "coin": coin_json(coin),
                "bundle_id": bundle.name().hex(), "solution_hex": bytes(solution).hex(), "signature": bytes(signature).hex(),
                "context": context, "input_before": before.to_json_dict(), "state_unchanged_after_farm": True,
                "funding_change_unchanged": True, "children_count": 0, "active_mempool_empty": True})

        async def confirm(coin, amount):
            expected = [[73, AMOUNT], [50, bytes(owner), application_message(amount)], [51, recipient, amount]]
            expected_coins = [Coin(coin.name(), recipient, uint64(amount))]
            if amount < AMOUNT:
                expected.append([51, change_hash, AMOUNT - amount])
                expected_coins.append(Coin(coin.name(), change_hash, uint64(AMOUNT - amount)))
            solution = Program.to([amount])
            vm_cost, conditions = puzzle.run_with_cost(MAX_COST, solution)
            require(bytes(conditions) == bytes(Program.to(expected)), "Independent payment/change conditions differ")
            values = directory / "solution.json"
            values.write_text(json.dumps({"paymentAmount": str(amount)}), encoding="utf-8")
            local = invoke(binary, "run", out / "manifest.json", "--solution", values)
            require(local["tree"] == condition_tree_json(Program.to(expected)) and int(local["cost"]) == vm_cost
                    and local["validation"] == "clvm-execution-only", "Local/upstream execution differs")
            before = await get(coin)
            require(not before.spent and not await children(coin), "Positive input already used")
            sig = signed(coin, amount)
            bundle = SpendBundle([make_spend(coin, puzzle, solution)], sig)
            context = {"peak_height": int(sim.block_height), "flags": flags()}
            status, error = await client.push_tx(bundle)
            require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Positive rejected: {status} {error}")
            item = sim.mempool_manager.mempool.get_item_by_id(bundle.name())
            require(item is not None, "Positive bundle absent from mempool")
            cost = int(item.cost)
            added, removed = await sim.farm_block()
            require(len(added) == len(expected_coins) and set(added) == set(expected_coins) and removed == [coin],
                    "Confirmed payment/change differs from exact expected coins")
            after = await get(coin)
            outputs = await children(coin)
            require(after.spent and len(outputs) == len(expected_coins) and {r.coin for r in outputs} == set(expected_coins),
                    "Unexpected child records")
            require(all(not r.spent and r.confirmed_block_index == after.spent_block_index for r in outputs), "Invalid child status/height")
            require(sum(r.coin.amount for r in outputs) == coin.amount, "Value not fully allocated")
            require(not await client.get_all_mempool_tx_ids(), "Positive bundle remains in mempool")
            await unchanged_funding()
            records["confirmations"].append({"coin": coin_json(coin), "children": [coin_json(c) for c in expected_coins],
                "payment_amount": str(amount), "change_amount": str(AMOUNT - amount), "child_count": len(outputs),
                "input_before": before.to_json_dict(), "input_after": after.to_json_dict(),
                "output_records": [(await get(c)).to_json_dict() for c in expected_coins],
                "bundle_id": bundle.name().hex(), "signature": bytes(sig).hex(), "context": context,
                "application_message": application_message(amount).hex(), "final_signing_message": message(coin, amount).hex(),
                "conditions_hex": bytes(conditions).hex(), "local_vm_cost": str(vm_cost), "simulator_spend_cost": str(cost),
                "payment_status": status.name, "input_spent": bool(after.spent),
                "funding_change_unchanged": True, "active_mempool_empty": True})

        amount = 1000 if name == "exact" else 700 if name == "changed-payment-stale-signature" else 600
        if name in ERRORS:
            solution, sig = Program.to([amount]), signed(target, amount)
            if name == "missing-signature":
                sig = G2Element()
            elif name == "wrong-owner":
                other = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/payment-change/other-test-key/v1").digest())
                sig = AugSchemeMPL.sign(other, message(target, amount))
            elif name == "wrong-network-domain":
                domain = bytes.fromhex("bb" * 32)
                require(domain != bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA), "Wrong domain equals real domain")
                sig = AugSchemeMPL.sign(key, application_message(amount) + bytes(target.name()) + domain)
            elif name == "changed-payment-stale-signature":
                sig = signed(target, 600)
            elif name == "cross-coin-replay":
                sig = signed(first, amount)
                records["signature_source_coin"] = coin_json(first)
                records["signature_source_message"] = message(first, amount).hex()
            elif name == "zero-payment":
                solution = Program.to([0])
            elif name == "overspend":
                solution = Program.to([AMOUNT + 1])
            elif name == "malformed-solution":
                solution = Program.to([])
            elif name == "noncanonical-amount":
                solution = Program.from_bytes(bytes.fromhex("ff82000180"))
            if ERRORS[name] == "BAD_AGGREGATE_SIGNATURE":
                require(not AugSchemeMPL.verify(owner, message(target, amount), sig), "Negative signature is valid")
            await reject(target, solution, sig, ERRORS[name])
        await confirm(first if name == "wrong-coin-amount" else target, amount)
        if name in {"wrong-coin-amount", "cross-coin-replay"}:
            untouched = target if name == "wrong-coin-amount" else first
            require(not (await get(untouched)).spent and not await children(untouched), "Control spent the unrelated coin")
            records["other_coin_unspent_after_control"] = True
    records["resources_closed"] = True
    return records


def audit(results):
    require([r["scenario"] for r in results] == list(SCENARIOS), "Missing, duplicate or reordered payment/change scenarios")
    for r in results:
        name = r["scenario"]
        require(r["resources_closed"] and len(r["confirmations"]) == 1, "Missing positive control or cleanup")
        require(len(r["rejections"]) == (1 if name in ERRORS else 0), "Wrong rejection count")
        for bad in r["rejections"]:
            require(bad["error"] == ERRORS[name] and bad["status"] == "FAILED" and bad["state_unchanged_after_farm"]
                    and bad["funding_change_unchanged"] and bad["children_count"] == 0 and bad["active_mempool_empty"], "Incomplete rejection evidence")
        good = r["confirmations"][0]
        require(good["payment_status"] == "SUCCESS" and good["child_count"] == (1 if name == "exact" else 2)
                and good["input_spent"] and good["funding_change_unchanged"] and good["active_mempool_empty"], "Incomplete positive evidence")
        if name in {"wrong-coin-amount", "cross-coin-replay"}:
            require(r["other_coin_unspent_after_control"], "Missing unaffected coin evidence")


async def run_suite(binary, directory, profile):
    results = []
    for name in SCENARIOS:
        case = directory / name
        case.mkdir()
        results.append(await scenario(binary, case, profile, name))
        print(f"PASS: payment/change {name}", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    platform_name = "windows" if sys.platform == "win32" else "linux"
    destination = WORK / f"payment-change-{platform_name}.json"
    destination.unlink(missing_ok=True)
    profile, lock, versions = preflight()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    require(binary.is_file(), "Build CLI first or pass --binary")
    inputs = [SOURCE, Path(__file__).resolve(), BASE / "payment.py", BASE / "smoke.py", ROOT / "Cargo.toml",
              ROOT / "Cargo.lock", BASE / "profile.json", lock, BASE / "tools.lock", BASE / "build-requirements.lock"]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    runs = []
    for _ in range(2):
        with tempfile.TemporaryDirectory(prefix="payment-change-", dir=WORK) as temporary:
            result = asyncio.run(run_suite(binary, Path(temporary), profile))
        audit(result)
        runs.append(result)
    require(runs[0] == runs[1], "Payment/change fresh reruns differ")
    require(hashlib.sha256(binary.read_bytes()).hexdigest() == binary_hash and all(
        hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h for n, h in hashes.items()), "Inputs changed during verification")
    report = {"schema_version": 1, "validation": "spendsim-payment-change", "identical_fresh_runs": 2,
              "scenario_count": len(SCENARIOS), "confirmed_payments_per_run": len(SCENARIOS), "rejections_per_run": len(ERRORS),
              "platform": sys.platform, "python": platform.python_version(), "packages": versions,
              "profile": profile["profile"], "chia_commit": profile["chia_commit"], "source_hashes": profile["source_hashes"],
              "binary_sha256": binary_hash, "input_sha256": hashes, "outcome": runs[0]}
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"PASS: {len(SCENARIOS)} payment/change scenarios, {len(ERRORS)} rejections, {len(SCENARIOS)} confirmed controls per run; two identical fresh runs. Report: {destination}")


if __name__ == "__main__":
    main()
