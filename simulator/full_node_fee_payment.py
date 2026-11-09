"""FP-4: fee-payment funding, rejection and inclusion through a real isolated full node."""
import hashlib
import json
import tomllib

from payment import MAX_COST, coin_json, condition_tree_json, invoke
from smoke import ROOT, require


def audit(result):
    expected_errors = [("missing-signature", "BAD_AGGREGATE_SIGNATURE"),
                       ("changed-fee-stale-signature", "BAD_AGGREGATE_SIGNATURE"),
                       ("wrong-coin-amount", "ASSERT_MY_AMOUNT_FAILED"),
                       ("additive-fee-offset", "RESERVE_FEE_CONDITION_FAILED")]
    require([(r["scenario"], r["error"]) for r in result["rejections"]] == expected_errors,
            "Incomplete fee rejection coverage")
    for record in result["rejections"]:
        require(record["status"] == "FAILED" and record["after_farm_block"]["fee"] == "0"
                and all(record[k] for k in ("state_unchanged_after_farm", "funding_change_unchanged", "active_mempool_empty")),
                "Incomplete fee rejection state")
    require(result["rejections"][-1]["accounting"] == {
        "removal_amount": "2100", "addition_amount": "2080", "net_fee": "20", "reserved_fee": "30"},
        "Incorrect rejected aggregate accounting")
    expected = [("partial", 1000, 989, 11, 1, 2, 1), ("exact", 1000, 990, 10, 1, 1, 1),
                ("additive-aggregate", 2100, 2070, 30, 3, 5, 2)]
    require([r["scenario"] for r in result["confirmations"]] == [e[0] for e in expected],
            "Incomplete fee confirmation coverage")
    for record, (_, removed, added, fee, inputs, children, contracts) in zip(result["confirmations"], expected):
        require(record["accounting"] == {"removal_amount": str(removed), "addition_amount": str(added),
                "net_fee": str(fee), "reserved_fee": str(fee)} and record["inclusion_block"]["fee"] == str(fee),
                "Incorrect confirmed fee accounting")
        require(record["input_count"] == len(record["input_records"]) == inputs
                and record["child_count"] == len(record["output_records"]) == children
                and len(record["contract_spends"]) == contracts, "Incorrect fee coin counts")
        require(record["status"] == "SUCCESS" and all(record[k] for k in
                ("exact_block_coins", "all_outputs_unspent", "unaffected_inputs_unchanged", "funding_change_unchanged", "active_mempool_empty")),
                "Incomplete fee confirmation state")
    require(all(result[k] for k in ("rejected_coin_unspent_after_controls", "funding_change_unchanged",
                                   "active_mempool_empty", "all_confirmed_outputs_unspent")), "Incomplete final fee state")


async def fee_payment(node, api, binary, directory):
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.simulator.simulator_protocol import FarmNewBlockProtocol
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia_rs import AugSchemeMPL, Coin, G2Element, SpendBundle, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_ints import uint64

    key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/full-node-fee-payment/public-test-key/v1").digest())
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
    invoke(binary, "build", ROOT / "examples/payment-fee.bas", "--bindings", binding_file, "--out", out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    require(manifest["compiler"]["version"] == version, "Stale fee-payment compiler")
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
        actual_fee = sum(int(c.amount) for c in removals) - sum(int(c.amount) for c in additions)
        require(block.transactions_info is not None and int(block.transactions_info.fees) == actual_fee,
                "Full-block transaction fee differs from exact coin accounting")
        return {"height": int(block.height), "header_hash": block.header_hash.hex(), "fee": str(actual_fee)}

    # Use only unspent rewards: never consume earlier fixtures' change or child coins.
    changes = []
    async def fund(amount, reveal=None):
        reveal = puzzle if reveal is None else reveal
        rewards = await node.coin_store.get_coin_records_by_puzzle_hash(False, funding.get_tree_hash())
        parent = min((r.coin for r in rewards if r.coinbase and r.coin.amount > amount), key=lambda c: (c.amount, c.name()))
        coin = Coin(parent.name(), reveal.get_tree_hash(), uint64(amount))
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
    aggregate_first, aggregate_second = await fund(1000), await fund(1000)
    companion = await fund(100, funding)
    tracked = [partial, exact, wrong, aggregate_first, aggregate_second, companion]
    before = {c.name(): await get(c) for c in (*tracked, *changes)}

    def application_message(amount, fee):
        return hashlib.sha256(b"0xBASIC/payment-fee/v1\x00" + bytes(owner) + bytes(recipient) + bytes(change_hash)
                              + (1000).to_bytes(8, "big") + amount.to_bytes(8, "big") + fee.to_bytes(8, "big")).digest()

    def final_message(coin, amount, fee):
        result = application_message(amount, fee) + bytes(coin.name()) + bytes(node.constants.AGG_SIG_ME_ADDITIONAL_DATA)
        require(pkm_pairs_for_conditions_dict(conditions_dict_for_solution(puzzle, Program.to([amount, fee]), MAX_COST),
                coin, node.constants.AGG_SIG_ME_ADDITIONAL_DATA) == [(owner, result)], "Independent signing context differs")
        return result

    def sign(coin, amount, fee):
        message = final_message(coin, amount, fee)
        sig = AugSchemeMPL.sign(key, message)
        require(AugSchemeMPL.verify(owner, message, sig), "Positive signature invalid")
        return sig

    def context():
        flags = int(get_flags_for_height_and_constants(node.mempool_manager.peak.height, node.constants)) | int(MEMPOOL_MODE)
        require(not flags & int(DONT_VALIDATE_SIGNATURE), "Signature validation bypass")
        return {"peak_height": int(node.blockchain.get_peak().height), "mempool_height": int(node.mempool_manager.peak.height),
                "previous_transaction_block_height": int(node.blockchain.get_peak().prev_transaction_block_height), "flags": flags}

    async def unchanged(coins):
        for coin in coins:
            require(await get(coin) == before[coin.name()] and not await children(coin), "Unspent coin/children changed")
        for coin in changes:
            require(await get(coin) == before[coin.name()], "Funding change modified")

    async def reject(name, bundle, error_name, accounting=None):
        await unchanged(tracked)
        ctx = context()
        status, error = await submit(bundle)
        require(status == MempoolInclusionStatus.FAILED and error is not None and error.name == error_name,
                f"{name}: unexpected rejection {status} {error}")
        await unchanged(tracked)
        require(not node.mempool_manager.mempool.all_item_ids(), "Rejected bundle entered mempool")
        block = await farm([], [])
        await unchanged(tracked)
        require(not node.mempool_manager.mempool.all_item_ids(), "Rejected bundle entered mempool after farm")
        records["rejections"].append({"scenario": name, "status": status.name, "error": error.name,
            "bundle": bundle.to_json_dict(), "bundle_id": bundle.name().hex(), "context": ctx,
            "accounting": accounting, "after_farm_block": block,
            "inputs_before": [before[c.name()].to_json_dict() for c in tracked],
            "state_unchanged_after_farm": True, "funding_change_unchanged": True, "active_mempool_empty": True})

    def build_bundle(specs, companion_output=None):
        spends, signatures, outputs, details = [], [], [], []
        for coin, amount, fee in specs:
            conditions = [[73, 1000], [50, bytes(owner), application_message(amount, fee)], [52, fee], [51, recipient, amount]]
            children_expected = [Coin(coin.name(), recipient, uint64(amount))]
            change = 1000 - amount - fee
            if change:
                conditions.append([51, change_hash, change])
                children_expected.append(Coin(coin.name(), change_hash, uint64(change)))
            solution = Program.to([amount, fee])
            vm_cost, actual = puzzle.run_with_cost(MAX_COST, solution)
            require(bytes(actual) == bytes(Program.to(conditions)), "Independent fee condition oracle differs")
            values = directory / "solution.json"
            values.write_text(json.dumps({"paymentAmount": str(amount), "feeAmount": str(fee)}), encoding="utf-8")
            local = invoke(binary, "run", out / "manifest.json", "--solution", values)
            require(local["tree"] == condition_tree_json(Program.to(conditions)) and int(local["cost"]) == vm_cost
                    and local["validation"] == "clvm-execution-only", "Local/upstream execution mismatch")
            spends.append(make_spend(coin, puzzle, solution))
            signatures.append(sign(coin, amount, fee))
            outputs.extend(children_expected)
            details.append({"coin": coin_json(coin), "payment_amount": str(amount), "fee_amount": str(fee), "change_amount": str(change),
                            "application_message": application_message(amount, fee).hex(),
                            "final_signing_message": final_message(coin, amount, fee).hex(),
                            "conditions_hex": bytes(actual).hex(), "local_vm_cost": str(vm_cost)})
        if companion_output is not None:
            spends.append(make_spend(companion, funding, Program.to([[51, recipient, companion_output]])))
            outputs.append(Coin(companion.name(), recipient, uint64(companion_output)))
        inputs = [s.coin for s in spends]
        removals, additions = sum(int(c.amount) for c in inputs), sum(int(c.amount) for c in outputs)
        accounting = {"removal_amount": str(removals), "addition_amount": str(additions),
                      "net_fee": str(removals-additions), "reserved_fee": str(sum(f for _, _, f in specs))}
        return SpendBundle(spends, AugSchemeMPL.aggregate(signatures)), inputs, outputs, details, accounting

    missing = G2Element()
    require(not AugSchemeMPL.verify(owner, final_message(partial, 600, 11), missing), "Missing signature is valid")
    await reject("missing-signature", SpendBundle([make_spend(partial, puzzle, Program.to([600, 11]))], missing), "BAD_AGGREGATE_SIGNATURE")
    stale = sign(partial, 600, 10)
    require(not AugSchemeMPL.verify(owner, final_message(partial, 600, 11), stale), "Stale fee signature is valid")
    await reject("changed-fee-stale-signature", SpendBundle([make_spend(partial, puzzle, Program.to([600, 11]))], stale), "BAD_AGGREGATE_SIGNATURE")
    await reject("wrong-coin-amount", SpendBundle([make_spend(wrong, puzzle, Program.to([600, 10]))], sign(wrong, 600, 10)), "ASSERT_MY_AMOUNT_FAILED")
    aggregate_specs = [(aggregate_first, 600, 10), (aggregate_second, 600, 20)]
    bundle, _, _, _, accounting = build_bundle(aggregate_specs, 110)
    await reject("additive-fee-offset", bundle, "RESERVE_FEE_CONDITION_FAILED", accounting)

    spent, created = [], []
    async def confirm(name, specs, companion_output=None):
        bundle, inputs, outputs, details, accounting = build_bundle(specs, companion_output)
        await unchanged([c for c in tracked if c not in spent])
        ctx = context()
        status, error = await submit(bundle)
        require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Positive fee payment failed: {status} {error}")
        item = node.mempool_manager.get_mempool_item(bundle.name())
        require(item is not None, "Fee payment absent from mempool")
        require(int(item.fee) == int(accounting["net_fee"]) and int(item.conds.reserve_fee) == int(accounting["reserved_fee"])
                and int(item.conds.removal_amount) == int(accounting["removal_amount"])
                and int(item.conds.addition_amount) == int(accounting["addition_amount"]), "Mempool fee accounting mismatch")
        cost = int(item.cost)
        block = await farm(outputs, inputs)
        require(block["fee"] == accounting["net_fee"], "Full block fee differs from mempool fee")
        for coin in inputs:
            child_records = await children(coin)
            expected = [c for c in outputs if c.parent_coin_info == coin.name()]
            require(len(child_records) == len(expected) and {r.coin for r in child_records} == set(expected), "Wrong child records")
        spent.extend(inputs)
        created.extend(outputs)
        await unchanged([c for c in tracked if c not in spent])
        require(not node.mempool_manager.mempool.all_item_ids(), "Post-payment mempool not empty")
        records["confirmations"].append({"scenario": name, "status": status.name, "bundle": bundle.to_json_dict(),
            "bundle_id": bundle.name().hex(), "context": ctx, "contract_spends": details, "accounting": accounting,
            "input_count": len(inputs), "child_count": len(outputs), "inclusion_block": block,
            "input_records": [(await get(c)).to_json_dict() for c in inputs],
            "output_records": [(await get(c)).to_json_dict() for c in outputs], "full_node_mempool_cost": str(cost),
            "exact_block_coins": True, "all_outputs_unspent": True, "unaffected_inputs_unchanged": True,
            "funding_change_unchanged": True, "active_mempool_empty": True})

    await confirm("partial", [(partial, 600, 11)])
    await confirm("exact", [(exact, 990, 10)])
    await confirm("additive-aggregate", aggregate_specs, 100)
    await unchanged([wrong])
    for coin in created:
        require(not (await get(coin)).spent, "Later control spent an earlier output")
    records.update(rejected_coin_unspent_after_controls=True, funding_change_unchanged=True, active_mempool_empty=True,
                   all_confirmed_outputs_unspent=True)
    audit(records)
    return records
