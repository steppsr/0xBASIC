"""FP-3: signed fee payments and aggregate reservation controls in pinned SpendSim."""
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

SOURCE = ROOT / "examples/payment-fee.bas"
AMOUNT = 1000
POSITIVES = {"partial": (600, 10), "exact": (990, 10), "zero-fee-partial": (600, 0), "zero-fee-exact": (1000, 0)}
SINGLE_ERRORS = {
    "missing-signature": "BAD_AGGREGATE_SIGNATURE",
    "wrong-owner": "BAD_AGGREGATE_SIGNATURE",
    "wrong-network-domain": "BAD_AGGREGATE_SIGNATURE",
    "changed-payment-stale-signature": "BAD_AGGREGATE_SIGNATURE",
    "changed-fee-stale-signature": "BAD_AGGREGATE_SIGNATURE",
    "cross-coin-replay": "BAD_AGGREGATE_SIGNATURE",
    "wrong-coin-amount": "ASSERT_MY_AMOUNT_FAILED",
    "zero-payment": "GENERATOR_RUNTIME_ERROR",
    "overspend": "GENERATOR_RUNTIME_ERROR",
    "fee-overrun": "GENERATOR_RUNTIME_ERROR",
    "malformed-solution": "GENERATOR_RUNTIME_ERROR",
    "noncanonical-fee": "GENERATOR_RUNTIME_ERROR",
}
AGGREGATES = ("reserved-offset", "additive-offset", "unreserved-offset-control", "extra-fee")
ERRORS = {**SINGLE_ERRORS, "reserved-offset": "RESERVE_FEE_CONDITION_FAILED", "additive-offset": "RESERVE_FEE_CONDITION_FAILED"}
SCENARIOS = (*POSITIVES, *SINGLE_ERRORS, *AGGREGATES)


async def scenario(binary, directory, profile, name):
    from chia._tests.util.spend_sim import SpendSim, SimClient
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia_rs import AugSchemeMPL, Coin, G2Element, SpendBundle, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_ints import uint64

    require(name in SCENARIOS, "Unknown fee-payment scenario")
    constants = simulator_constants(profile)
    key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/payment-fee/public-test-key/v1").digest())
    owner = key.get_g1()
    funding = Program.to(1)
    recipient = Program.to((1, [])).get_tree_hash()
    change_hash = Program.to((1, [[83, 0]])).get_tree_hash()
    bindings = {"owner": {"hex": bytes(owner).hex()}, "recipient": {"hex": recipient.hex()},
                "changeRecipient": {"hex": change_hash.hex()}, "inputAmount": str(AMOUNT)}
    binding_file = directory / "bindings.json"
    binding_file.write_text(json.dumps(bindings), encoding="utf-8")
    source = SOURCE
    reserve = name != "unreserved-offset-control"
    if not reserve:
        # Deliberately weakened comparison fixture; never overwrite the real example.
        text = SOURCE.read_text(encoding="utf-8")
        line = "    EMIT RESERVE_FEE(feeAmount)\n"
        require(text.count(line) == 1, "Cannot identify reservation in comparison fixture")
        source = directory / "unreserved-control.bas"
        source.write_text(text.replace(line, ""), encoding="utf-8")
    out = directory / "artifact"
    invoke(binary, "build", source, "--bindings", binding_file, "--out", out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    require(manifest["compiler"]["version"] == version, "Stale fee compiler")
    for part in ("template", "puzzle"):
        blob = (out / f"{part}.clvm").read_bytes()
        require(hashlib.sha256(blob).hexdigest() == manifest[part]["program_sha256"]
                and Program.from_bytes(blob).get_tree_hash().hex() == manifest[part]["tree_hash"], "Artifact identity mismatch")
    puzzle = Program.from_bytes((out / "puzzle.clvm").read_bytes())

    def app(amount, fee):
        return hashlib.sha256(b"0xBASIC/payment-fee/v1\x00" + bytes(owner) + bytes(recipient) + bytes(change_hash)
                              + AMOUNT.to_bytes(8, "big") + amount.to_bytes(8, "big") + fee.to_bytes(8, "big")).digest()

    def message(coin, amount, fee):
        final = app(amount, fee) + bytes(coin.name()) + bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA)
        pairs = pkm_pairs_for_conditions_dict(conditions_dict_for_solution(puzzle, Program.to([amount, fee]), MAX_COST),
                                             coin, constants.AGG_SIG_ME_ADDITIONAL_DATA)
        require(pairs == [(owner, final)], "Independent signature context mismatch")
        return final

    def sign(coin, amount, fee):
        final = message(coin, amount, fee)
        sig = AugSchemeMPL.sign(key, final)
        require(AugSchemeMPL.verify(owner, final, sig), "Positive signature self-check failed")
        return sig

    records = {"scenario": name, "manifest": manifest, "bindings": bindings, "constants": constants.to_json_dict(),
               "reservation_enabled": reserve, "comparison_fixture": not reserve,
               "funding": [], "rejections": [], "confirmations": []}
    async with SpendSim.managed(defaults=constants) as sim:
        client = SimClient(sim)
        await sim.farm_block(funding.get_tree_hash())
        await sim.farm_block(funding.get_tree_hash())
        changes, tracked = [], []

        async def get(coin):
            r = await client.get_coin_record_by_name(coin.name())
            require(r is not None and r.coin == coin, "Missing/mismatched coin")
            return r

        async def children(coin):
            return await client.get_coin_records_by_parent_ids([coin.name()])

        async def fund(amount=AMOUNT, reveal=None):
            reveal = puzzle if reveal is None else reveal
            rewards = await client.get_coin_records_by_puzzle_hash(funding.get_tree_hash(), include_spent_coins=False)
            parent = min((r.coin for r in rewards if r.coinbase and r.coin.amount > amount), key=lambda c: (c.amount, c.name()))
            coin = Coin(parent.name(), reveal.get_tree_hash(), uint64(amount))
            change = Coin(parent.name(), funding.get_tree_hash(), uint64(parent.amount - amount))
            bundle = SpendBundle([make_spend(parent, funding, Program.to([[51, coin.puzzle_hash, amount],
                                 [51, change.puzzle_hash, change.amount]]))], G2Element())
            status, error = await client.push_tx(bundle)
            require(status == MempoolInclusionStatus.SUCCESS and error is None, "Funding rejected")
            added, removed = await sim.farm_block()
            require(len(added) == 2 and set(added) == {coin, change} and removed == [parent], "Wrong funding inclusion")
            height = (await get(parent)).spent_block_index
            require((await get(parent)).spent, "Funding input not spent")
            for c in (coin, change):
                r = await get(c)
                require(not r.spent and r.confirmed_block_index == height, "Wrong funding output height")
            require(not await client.get_all_mempool_tx_ids(), "Funding remains in mempool")
            changes.append(change)
            tracked.append(coin)
            records["funding"].append({"parent": coin_json(parent), "coin": coin_json(coin), "change": coin_json(change)})
            return coin

        first = await fund()
        target = await fund(1001 if name == "wrong-coin-amount" else 1000) if name in {"wrong-coin-amount", "cross-coin-replay"} else first
        second = await fund() if name == "additive-offset" else None
        companion = await fund(100, funding) if name in AGGREGATES else None
        before = {c.name(): await get(c) for c in (*tracked, *changes)}

        async def unchanged_funding():
            for c in changes:
                require(await get(c) == before[c.name()], "Funding change modified")

        async def untouched(coins):
            for c in coins:
                require(await get(c) == before[c.name()] and not await children(c), "Unspent input or children changed")
            await unchanged_funding()

        def context():
            flags = int(get_flags_for_height_and_constants(sim.mempool_manager.peak.height, constants)) | int(MEMPOOL_MODE)
            require(not flags & int(DONT_VALIDATE_SIGNATURE), "Signature checks bypassed")
            return {"peak_height": int(sim.block_height), "flags": flags}

        async def reject(bundle, expected, accounting=None):
            await untouched(tracked)
            ctx = context()
            status, error = await client.push_tx(bundle)
            require(status == MempoolInclusionStatus.FAILED and error is not None and error.name == expected,
                    f"{name}: expected {expected}, got {status} {error}")
            await untouched(tracked)
            require(not await client.get_all_mempool_tx_ids(), "Rejected bundle entered active mempool")
            added, removed = await sim.farm_block()
            require(not added and not removed, "Rejected bundle was included")
            await untouched(tracked)
            require(not await client.get_all_mempool_tx_ids(), "Rejected bundle entered mempool after farm")
            records["rejections"].append({"status": status.name, "error": error.name, "bundle_id": bundle.name().hex(),
                "bundle": bundle.to_json_dict(), "context": ctx, "accounting": accounting,
                "inputs_before": [before[c.name()].to_json_dict() for c in tracked],
                "state_unchanged_after_farm": True, "funding_change_unchanged": True, "active_mempool_empty": True})

        def payment_spend(coin, amount, fee):
            expected = [[73, AMOUNT], [50, bytes(owner), app(amount, fee)]]
            if reserve:
                expected.append([52, fee])
            expected.append([51, recipient, amount])
            outputs = [Coin(coin.name(), recipient, uint64(amount))]
            change = AMOUNT - amount - fee
            if change:
                expected.append([51, change_hash, change])
                outputs.append(Coin(coin.name(), change_hash, uint64(change)))
            solution = Program.to([amount, fee])
            cost, actual = puzzle.run_with_cost(MAX_COST, solution)
            require(bytes(actual) == bytes(Program.to(expected)), "Independent condition oracle mismatch")
            values = directory / "solution.json"
            values.write_text(json.dumps({"paymentAmount": str(amount), "feeAmount": str(fee)}), encoding="utf-8")
            local = invoke(binary, "run", out / "manifest.json", "--solution", values)
            require(local["tree"] == condition_tree_json(Program.to(expected)) and int(local["cost"]) == cost
                    and local["validation"] == "clvm-execution-only", "CLI/upstream mismatch")
            return make_spend(coin, puzzle, solution), sign(coin, amount, fee), outputs, {
                "coin": coin_json(coin), "payment_amount": str(amount), "fee_amount": str(fee), "change_amount": str(change),
                "application_message": app(amount, fee).hex(), "signing_message": message(coin, amount, fee).hex(),
                "conditions_hex": bytes(actual).hex(), "local_vm_cost": str(cost)}

        def bundle_for(specs, companion_output=None):
            spends, sigs, outputs, details = [], [], [], []
            for coin, amount, fee in specs:
                spend, sig, children_expected, detail = payment_spend(coin, amount, fee)
                spends.append(spend)
                sigs.append(sig)
                outputs.extend(children_expected)
                details.append(detail)
            if companion_output is not None:
                require(companion is not None, "Missing aggregate companion")
                spends.append(make_spend(companion, funding, Program.to([[51, recipient, companion_output]])))
                outputs.append(Coin(companion.name(), recipient, uint64(companion_output)))
            inputs = [s.coin for s in spends]
            removal = sum(int(c.amount) for c in inputs)
            addition = sum(int(c.amount) for c in outputs)
            accounting = {"removal_amount": str(removal), "addition_amount": str(addition),
                          "net_fee": str(removal - addition), "reserved_fee": str(sum(f for _, _, f in specs) if reserve else 0)}
            return SpendBundle(spends, AugSchemeMPL.aggregate(sigs)), inputs, outputs, details, accounting

        async def confirm(specs, companion_output=None):
            bundle, inputs, outputs, details, accounting = bundle_for(specs, companion_output)
            await untouched(tracked)
            ctx = context()
            status, error = await client.push_tx(bundle)
            require(status == MempoolInclusionStatus.SUCCESS and error is None, f"{name}: positive rejected {status} {error}")
            item = sim.mempool_manager.mempool.get_item_by_id(bundle.name())
            require(item is not None, "Positive absent from mempool")
            require(int(item.fee) == int(accounting["net_fee"]) and int(item.conds.reserve_fee) == int(accounting["reserved_fee"])
                    and int(item.conds.removal_amount) == int(accounting["removal_amount"])
                    and int(item.conds.addition_amount) == int(accounting["addition_amount"]), "Mempool fee accounting mismatch")
            cost = int(item.cost)
            added, removed = await sim.farm_block()
            require(len(added) == len(outputs) and set(added) == set(outputs)
                    and len(removed) == len(inputs) and set(removed) == set(inputs), "Wrong aggregate additions/removals")
            for c in inputs:
                r = await get(c)
                expected = [o for o in outputs if o.parent_coin_info == c.name()]
                actual = await children(c)
                require(r.spent and r.spent_block_index == sim.block_height and len(actual) == len(expected)
                        and {x.coin for x in actual} == set(expected), "Wrong input/children records")
                require(all(not x.spent and x.confirmed_block_index == r.spent_block_index for x in actual), "Wrong child height/status")
            await untouched([c for c in tracked if c not in inputs])
            require(not await client.get_all_mempool_tx_ids(), "Confirmed bundle remains in mempool")
            records["confirmations"].append({"status": status.name, "bundle_id": bundle.name().hex(), "bundle": bundle.to_json_dict(),
                "contract_spends": details, "accounting": accounting, "context": ctx, "simulator_spend_cost": str(cost),
                "input_records": [(await get(c)).to_json_dict() for c in inputs], "output_records": [(await get(c)).to_json_dict() for c in outputs],
                "child_count": len(outputs), "input_count": len(inputs), "exact_coins_and_heights": True,
                "unaffected_inputs_unchanged": True, "funding_change_unchanged": True, "active_mempool_empty": True})

        if name in AGGREGATES:
            specs = [(first, 600, 10)] + ([(second, 600, 20)] if second is not None else [])
            if name in ERRORS:
                bundle, _, _, _, accounting = bundle_for(specs, 110)
                await reject(bundle, ERRORS[name], accounting)
            companion_output = 110 if name == "unreserved-offset-control" else 90 if name == "extra-fee" else 100
            await confirm(specs, companion_output)
        else:
            amount, fee = POSITIVES.get(name, (700 if name == "changed-payment-stale-signature" else 600,
                                            11 if name == "changed-fee-stale-signature" else 10))
            if name in ERRORS:
                solution, sig = Program.to([amount, fee]), sign(target, amount, fee)
                if name == "missing-signature":
                    sig = G2Element()
                elif name == "wrong-owner":
                    other = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/payment-fee/other-test-key/v1").digest())
                    sig = AugSchemeMPL.sign(other, message(target, amount, fee))
                elif name == "wrong-network-domain":
                    domain = bytes.fromhex("bb" * 32)
                    require(domain != bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA), "Wrong domain equals actual domain")
                    sig = AugSchemeMPL.sign(key, app(amount, fee) + bytes(target.name()) + domain)
                elif name == "changed-payment-stale-signature":
                    sig = sign(target, 600, fee)
                elif name == "changed-fee-stale-signature":
                    sig = sign(target, amount, 10)
                elif name == "cross-coin-replay":
                    sig = sign(first, amount, fee)
                    records["signature_source_coin"] = coin_json(first)
                elif name == "zero-payment":
                    solution = Program.to([0, 10])
                elif name == "overspend":
                    solution = Program.to([1001, 0])
                elif name == "fee-overrun":
                    solution = Program.to([1000, 1])
                elif name == "malformed-solution":
                    solution = Program.to([600])
                elif name == "noncanonical-fee":
                    solution = Program.from_bytes(bytes.fromhex("ff820258ff82000a80"))
                if ERRORS[name] == "BAD_AGGREGATE_SIGNATURE":
                    require(not AugSchemeMPL.verify(owner, message(target, amount, fee), sig), "Negative signature valid")
                await reject(SpendBundle([make_spend(target, puzzle, solution)], sig), ERRORS[name])
            await confirm([(first if name == "wrong-coin-amount" else target, amount, fee)])
    records["resources_closed"] = True
    return records


def audit(results):
    require([r["scenario"] for r in results] == list(SCENARIOS), "Missing, duplicate or reordered fee scenarios")
    for r in results:
        name = r["scenario"]
        require(r["resources_closed"] and len(r["confirmations"]) == 1, "Missing control or cleanup")
        require(r["comparison_fixture"] == (name == "unreserved-offset-control")
                and r["reservation_enabled"] == (name != "unreserved-offset-control"), "Wrong reservation fixture")
        require(len(r["rejections"]) == (1 if name in ERRORS else 0), "Wrong rejection count")
        for bad in r["rejections"]:
            require(bad["status"] == "FAILED" and bad["error"] == ERRORS[name] and bad["state_unchanged_after_farm"]
                    and bad["funding_change_unchanged"] and bad["active_mempool_empty"], "Incomplete rejection evidence")
            if name in ("reserved-offset", "additive-offset"):
                require(bad["accounting"] == ({"removal_amount": "1100", "addition_amount": "1100", "net_fee": "0", "reserved_fee": "10"}
                        if name == "reserved-offset" else {"removal_amount": "2100", "addition_amount": "2080", "net_fee": "20", "reserved_fee": "30"}),
                        "Wrong rejected aggregate fee evidence")
        good = r["confirmations"][0]
        fee = POSITIVES[name][1] if name in POSITIVES else 11 if name == "changed-fee-stale-signature" else 10
        removal, net, reserved, inputs, children = 1000, fee, fee, 1, (1 if name in ("exact", "zero-fee-exact") else 2)
        if name in AGGREGATES:
            removal, inputs, children = 1100, 2, 3
            net, reserved = {"reserved-offset": (10, 10), "additive-offset": (30, 30),
                             "unreserved-offset-control": (0, 0), "extra-fee": (20, 10)}[name]
            if name == "additive-offset":
                removal, inputs, children = 2100, 3, 5
        require(good["accounting"] == {"removal_amount": str(removal), "addition_amount": str(removal-net),
                                       "net_fee": str(net), "reserved_fee": str(reserved)}, "Incorrect positive fee accounting")
        require(good["status"] == "SUCCESS" and good["input_count"] == inputs and good["child_count"] == children
                and len(good["contract_spends"]) == (2 if name == "additive-offset" else 1)
                and len(good["input_records"]) == inputs and len(good["output_records"]) == children
                and good["exact_coins_and_heights"] and good["unaffected_inputs_unchanged"]
                and good["funding_change_unchanged"] and good["active_mempool_empty"], "Incomplete confirmed aggregate evidence")


async def run_suite(binary, directory, profile):
    results = []
    for name in SCENARIOS:
        case = directory / name
        case.mkdir()
        results.append(await scenario(binary, case, profile, name))
        print(f"PASS: fee-payment {name}", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    platform_name = "windows" if sys.platform == "win32" else "linux"
    destination = WORK / f"fee-payment-{platform_name}.json"
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
        with tempfile.TemporaryDirectory(prefix="fee-payment-", dir=WORK) as temporary:
            result = asyncio.run(run_suite(binary, Path(temporary), profile))
        audit(result)
        runs.append(result)
    require(runs[0] == runs[1], "Fee-payment fresh reruns differ")
    require(hashlib.sha256(binary.read_bytes()).hexdigest() == binary_hash and all(
        hashlib.sha256((ROOT / n).read_bytes()).hexdigest() == h for n, h in hashes.items()), "Inputs changed during verification")
    report = {"schema_version": 1, "validation": "spendsim-fee-payment", "identical_fresh_runs": 2,
              "scenario_count": len(SCENARIOS), "confirmed_bundles_per_run": len(SCENARIOS), "rejections_per_run": len(ERRORS),
              "platform": sys.platform, "python": platform.python_version(), "packages": versions,
              "profile": profile["profile"], "chia_commit": profile["chia_commit"], "source_hashes": profile["source_hashes"],
              "binary_sha256": binary_hash, "input_sha256": hashes, "outcome": runs[0]}
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"PASS: {len(SCENARIOS)} fee-payment scenarios, {len(ERRORS)} rejections, {len(SCENARIOS)} confirmed controls per run; two identical fresh runs. Report: {destination}")


if __name__ == "__main__":
    main()
