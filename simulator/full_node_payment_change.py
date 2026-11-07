"""PC-3: payment/change funding, rejection and inclusion through a real isolated full node."""
import hashlib
import json
import tomllib

from payment import MAX_COST, coin_json, condition_tree_json, invoke
from smoke import ROOT, require


def audit(result):
    require([r["scenario"] for r in result["rejections"]] == [
        "missing-signature", "changed-payment-stale-signature", "wrong-coin-amount"], "Incomplete full-node rejection coverage")
    for r in result["rejections"]:
        expected = "ASSERT_MY_AMOUNT_FAILED" if r["scenario"] == "wrong-coin-amount" else "BAD_AGGREGATE_SIGNATURE"
        require(r["status"] == "FAILED" and r["error"] == expected and r["state_unchanged_after_farm"],
                "Incomplete full-node rejection evidence")
    require([r["scenario"] for r in result["confirmations"]] == ["partial", "exact"], "Incomplete full-node controls")
    for r, count in zip(result["confirmations"], [2, 1]):
        require(r["status"] == "SUCCESS" and r["child_count"] == count and r["input_spent"]
                and r["exact_block_coins"] and r["all_outputs_unspent"], "Incomplete full-node confirmation evidence")
    require(result["rejected_coin_unspent_after_controls"] and result["funding_change_unchanged"]
            and result["active_mempool_empty"], "Incomplete final full-node state")


async def payment_change(node, api, binary, directory):
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.simulator.simulator_protocol import FarmNewBlockProtocol
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia_rs import AugSchemeMPL, Coin, G2Element, SpendBundle, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_ints import uint64

    key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/full-node-payment-change/public-test-key/v1").digest())
    owner = key.get_g1()
    funding = Program.to(1)
    recipient = Program.to((1, [])).get_tree_hash()
    change_hash = Program.to((1, [[83, 0]])).get_tree_hash()
    require(recipient != change_hash, "Payment and change destinations coincide")
    bindings = {"owner": {"hex": bytes(owner).hex()}, "recipient": {"hex": recipient.hex()},
                "changeRecipient": {"hex": change_hash.hex()}, "inputAmount": "1000"}
    binding_file = directory / "bindings.json"
    binding_file.write_text(json.dumps(bindings), encoding="utf-8")
    out = directory / "artifact"
    invoke(binary, "build", ROOT / "examples/payment-change.bas", "--bindings", binding_file, "--out", out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    require(manifest["compiler"]["version"] == version, "Stale payment/change compiler")
    for part in ("template", "puzzle"):
        blob = (out / f"{part}.clvm").read_bytes()
        require(hashlib.sha256(blob).hexdigest() == manifest[part]["program_sha256"]
                and Program.from_bytes(blob).get_tree_hash().hex() == manifest[part]["tree_hash"], "Artifact identity mismatch")
    puzzle = Program.from_bytes((out / "puzzle.clvm").read_bytes())
    records = {"manifest": manifest, "bindings": bindings, "funding": [], "rejections": [], "confirmations": [],
               "signature_domain": node.constants.AGG_SIG_ME_ADDITIONAL_DATA.hex(), "offline_sync_readiness_bypassed": True}

    async def get(coin):
        record = await node.coin_store.get_coin_record(coin.name())
        require(record is not None and record.coin == coin, "Missing/mismatched full-node coin")
        return record

    async def children(coin):
        return await node.coin_store.get_coin_records_by_parent_ids(True, [coin.name()])

    async def submit(bundle):
        # Skip only offline wall-clock/peer readiness, as in the existing full-node gate.
        return await node.add_transaction(bundle, bundle.name(), test=True)

    async def farm(additions, removals):
        block = await api.farm_new_transaction_block(FarmNewBlockProtocol(funding.get_tree_hash()))
        require(node.blockchain.get_peak().header_hash == block.header_hash, "Block not accepted as peak")
        require(await node.block_store.get_full_block(block.header_hash) == block, "Full block absent from store")
        require(block.is_transaction_block(), "Expected transaction block")
        added = await node.coin_store.get_coins_added_at_height(block.height)
        removed = await node.coin_store.get_coins_removed_at_height(block.height)
        actual = [r.coin for r in added if not r.coinbase]
        require(len(actual) == len(additions) and set(actual) == set(additions)
                and len(removed) == len(removals) and {r.coin for r in removed} == set(removals), "Wrong block additions/removals")
        if removals:
            require(block.transactions_generator is not None, "Missing payment transaction generator")
        for coin in additions:
            r = await get(coin)
            require(not r.spent and r.confirmed_block_index == block.height, "Output not confirmed at inclusion height")
        for coin in removals:
            r = await get(coin)
            require(r.spent and r.spent_block_index == block.height, "Input not spent at inclusion height")
        return {"height": int(block.height), "header_hash": block.header_hash.hex()}

    # Use only unspent rewards: never consume earlier fixtures' change or child coins.
    changes = []
    async def fund(amount):
        rewards = await node.coin_store.get_coin_records_by_puzzle_hash(False, funding.get_tree_hash())
        parent = min((r.coin for r in rewards if r.coinbase and r.coin.amount > amount), key=lambda c: (c.amount, c.name()))
        coin = Coin(parent.name(), puzzle.get_tree_hash(), uint64(amount))
        change = Coin(parent.name(), funding.get_tree_hash(), uint64(parent.amount - amount))
        bundle = SpendBundle([make_spend(parent, funding, Program.to([
            [51, coin.puzzle_hash, amount], [51, change.puzzle_hash, change.amount]
        ]))], G2Element())
        status, error = await submit(bundle)
        require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Funding failed: {status} {error}")
        block = await farm([coin, change], [parent])
        changes.append(change)
        records["funding"].append({"parent": coin_json(parent), "coin": coin_json(coin), "change": coin_json(change), "block": block})
        return coin

    partial, exact, wrong = await fund(1000), await fund(1000), await fund(1001)
    before = {c.name(): await get(c) for c in (partial, exact, wrong, *changes)}

    def application_message(amount):
        return hashlib.sha256(b"0xBASIC/payment-change/v1\x00" + bytes(owner) + bytes(recipient) + bytes(change_hash)
                              + (1000).to_bytes(8, "big") + amount.to_bytes(8, "big")).digest()

    def final_message(coin, amount):
        result = application_message(amount) + bytes(coin.name()) + bytes(node.constants.AGG_SIG_ME_ADDITIONAL_DATA)
        require(pkm_pairs_for_conditions_dict(conditions_dict_for_solution(puzzle, Program.to([amount]), MAX_COST),
                coin, node.constants.AGG_SIG_ME_ADDITIONAL_DATA) == [(owner, result)], "Independent signing context differs")
        return result

    def sign(coin, amount):
        message = final_message(coin, amount)
        sig = AugSchemeMPL.sign(key, message)
        require(AugSchemeMPL.verify(owner, message, sig), "Positive signature invalid")
        return sig

    def context():
        flags = int(get_flags_for_height_and_constants(node.mempool_manager.peak.height, node.constants)) | int(MEMPOOL_MODE)
        require(not flags & int(DONT_VALIDATE_SIGNATURE), "Signature validation bypass")
        return {"peak_height": int(node.blockchain.get_peak().height), "mempool_height": int(node.mempool_manager.peak.height),
                "previous_transaction_block_height": int(node.blockchain.get_peak().prev_transaction_block_height), "flags": flags}

    async def changes_unchanged():
        require(all([await get(c) == before[c.name()] for c in changes]), "Funding change was modified")

    async def rejected(name, coin, amount, sig, expected):
        solution = Program.to([amount])
        bundle = SpendBundle([make_spend(coin, puzzle, solution)], sig)
        ctx = context()
        if expected == "BAD_AGGREGATE_SIGNATURE":
            require(not AugSchemeMPL.verify(owner, final_message(coin, amount), sig), "Negative signature is valid")
        status, error = await submit(bundle)
        require(status == MempoolInclusionStatus.FAILED and error is not None and error.name == expected,
                f"{name}: unexpected rejection {status} {error}")
        async def unchanged():
            for c in (partial, exact, wrong):
                require(await get(c) == before[c.name()] and not await children(c), "Rejected attempt changed contract state")
            await changes_unchanged()
            require(not node.mempool_manager.mempool.all_item_ids(), "Rejected attempt entered mempool")
        await unchanged()
        block = await farm([], [])
        await unchanged()
        records["rejections"].append({"scenario": name, "status": status.name, "error": error.name,
            "coin": coin_json(coin), "bundle_id": bundle.name().hex(), "solution_hex": bytes(solution).hex(),
            "signature": bytes(sig).hex(), "context": ctx, "after_farm_block": block,
            "input_before": before[coin.name()].to_json_dict(), "state_unchanged_after_farm": True})

    await rejected("missing-signature", partial, 600, G2Element(), "BAD_AGGREGATE_SIGNATURE")
    await rejected("changed-payment-stale-signature", partial, 700, sign(partial, 600), "BAD_AGGREGATE_SIGNATURE")
    await rejected("wrong-coin-amount", wrong, 600, sign(wrong, 600), "ASSERT_MY_AMOUNT_FAILED")

    async def confirm(name, coin, amount):
        conditions = [[73, 1000], [50, bytes(owner), application_message(amount)], [51, recipient, amount]]
        outputs = [Coin(coin.name(), recipient, uint64(amount))]
        if amount < 1000:
            conditions.append([51, change_hash, 1000 - amount])
            outputs.append(Coin(coin.name(), change_hash, uint64(1000 - amount)))
        solution = Program.to([amount])
        vm_cost, actual = puzzle.run_with_cost(MAX_COST, solution)
        require(bytes(actual) == bytes(Program.to(conditions)), "Independent condition oracle differs")
        values = directory / f"{name}.json"
        values.write_text(json.dumps({"paymentAmount": str(amount)}), encoding="utf-8")
        local = invoke(binary, "run", out / "manifest.json", "--solution", values)
        require(local["tree"] == condition_tree_json(Program.to(conditions)) and int(local["cost"]) == vm_cost
                and local["validation"] == "clvm-execution-only", "Local/upstream execution mismatch")
        require(await get(coin) == before[coin.name()] and not await children(coin), "Positive input was modified")
        sig = sign(coin, amount)
        bundle = SpendBundle([make_spend(coin, puzzle, solution)], sig)
        ctx = context()
        status, error = await submit(bundle)
        require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Positive payment failed: {status} {error}")
        item = node.mempool_manager.get_mempool_item(bundle.name())
        require(item is not None, "Positive payment absent from mempool")
        cost = int(item.cost)
        block = await farm(outputs, [coin])
        child_records = await children(coin)
        require(len(child_records) == len(outputs) and {r.coin for r in child_records} == set(outputs)
                and all(not r.spent for r in child_records), "Unexpected payment/change children")
        require(sum(c.amount for c in outputs) == coin.amount, "Payment value not fully allocated")
        await changes_unchanged()
        require(not node.mempool_manager.mempool.all_item_ids(), "Post-payment mempool not empty")
        records["confirmations"].append({"scenario": name, "status": status.name, "coin": coin_json(coin),
            "children": [coin_json(c) for c in outputs], "child_count": len(outputs), "input_spent": (await get(coin)).spent,
            "input_before": before[coin.name()].to_json_dict(), "input_after": (await get(coin)).to_json_dict(),
            "output_records": [(await get(c)).to_json_dict() for c in outputs], "exact_block_coins": True,
            "all_outputs_unspent": True, "inclusion_block": block, "context": ctx, "bundle_id": bundle.name().hex(),
            "application_message": application_message(amount).hex(), "final_signing_message": final_message(coin, amount).hex(),
            "signature": bytes(sig).hex(), "conditions_hex": bytes(actual).hex(), "local_vm_cost": str(vm_cost),
            "full_node_mempool_cost": str(cost)})

    await confirm("partial", partial, 600)
    await confirm("exact", exact, 1000)
    require(await get(wrong) == before[wrong.name()] and not await children(wrong), "Positive controls changed rejected coin")
    await changes_unchanged()
    records.update(rejected_coin_unspent_after_controls=True, funding_change_unchanged=True, active_mempool_empty=True)
    audit(records)
    return records
