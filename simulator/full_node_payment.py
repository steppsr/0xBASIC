"""Compiled signed payment through the isolated real full node (M5-1b)."""
import hashlib
import json
import tomllib

from payment import AMOUNT, HEIGHT, MAX_COST, invoke, condition_tree_json, coin_json
from smoke import ROOT, require


async def payment(node, api, binary, directory):
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.simulator.simulator_protocol import FarmNewBlockProtocol
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia.util.errors import Err
    from chia_rs import AugSchemeMPL, Coin, G2Element, SpendBundle, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_ints import uint64

    constants = node.constants
    key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/M5/public-test-key/v1").digest())
    owner = key.get_g1()
    funding = Program.to(1)
    recipient = Program.to((1, []))
    bindings = {"owner": {"hex": bytes(owner).hex()}, "recipient": {"hex": recipient.get_tree_hash().hex()},
                "paymentAmount": str(AMOUNT), "earliestHeight": str(HEIGHT)}
    binding_file = directory / "bindings.json"
    binding_file.write_text(json.dumps(bindings), encoding="utf-8")
    out = directory / "payment"
    invoke(binary, "build", ROOT / "examples/height-locked-payment.bas", "--bindings", binding_file, "--out", out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    require(manifest["compiler"]["version"] == version, "Stale compiler; rebuild CLI")
    for name in ("template", "puzzle"):
        blob = (out / f"{name}.clvm").read_bytes()
        require(hashlib.sha256(blob).hexdigest() == manifest[name]["program_sha256"], "Artifact digest mismatch")
        require(Program.from_bytes(blob).get_tree_hash().hex() == manifest[name]["tree_hash"], "Artifact tree hash mismatch")
    puzzle = Program.from_bytes((out / "puzzle.clvm").read_bytes())
    solution = Program.to([])
    message = hashlib.sha256(b"0xBASIC/payment/v1\x00" + bytes(owner) + bytes(recipient.get_tree_hash())
                             + AMOUNT.to_bytes(8, "big") + HEIGHT.to_bytes(4, "big")).digest()
    expected = Program.to([[73, AMOUNT], [83, HEIGHT], [50, bytes(owner), message],
                           [51, recipient.get_tree_hash(), AMOUNT]])
    vm_cost, conditions = puzzle.run_with_cost(MAX_COST, solution)
    require(bytes(conditions) == bytes(expected), "Independent payment conditions mismatch")
    local = invoke(binary, "run", out / "manifest.json")
    require(local["validation"] == "clvm-execution-only" and local["tree"] == condition_tree_json(expected),
            "CLI condition mismatch")

    async def farm():
        block = await api.farm_new_transaction_block(FarmNewBlockProtocol(funding.get_tree_hash()))
        require(node.blockchain.get_peak().header_hash == block.header_hash, "Block not accepted as peak")
        require(await node.block_store.get_full_block(block.header_hash) == block, "Full block absent")
        return block

    async def submit(bundle):
        # Upstream test=True skips only wall-clock/peer sync readiness for this offline
        # historical chain. It still pre-validates signatures/conditions and adds via mempool.
        return await node.add_transaction(bundle, bundle.name(), test=True)

    async def state(coin):
        record = await node.coin_store.get_coin_record(coin.name())
        require(record is not None, "Expected coin record")
        return record

    async def check_inclusion(block, additions, removals):
        require(block.transactions_generator is not None, "No transaction generator in block")
        added = await node.coin_store.get_coins_added_at_height(block.height)
        removed = await node.coin_store.get_coins_removed_at_height(block.height)
        require({r.coin for r in added if not r.coinbase} == set(additions), "Unexpected non-reward block additions")
        require({r.coin for r in removed} == set(removals), "Unexpected block removals")
        for coin in additions:
            record = await state(coin)
            require(record.coin == coin and not record.spent and record.confirmed_block_index == block.height,
                    "Output not confirmed at inclusion height")
        for coin in removals:
            require((await state(coin)).spent_block_index == block.height, "Input not removed at inclusion height")

    await farm()
    await farm()
    rewards = await node.coin_store.get_coin_records_by_puzzle_hash(False, funding.get_tree_hash())
    funding_coin = min((r.coin for r in rewards if r.coin.amount > AMOUNT), key=lambda c: (c.amount, c.name()))
    contract = Coin(funding_coin.name(), puzzle.get_tree_hash(), uint64(AMOUNT))
    change = Coin(funding_coin.name(), funding.get_tree_hash(), uint64(funding_coin.amount - AMOUNT))
    funding_bundle = SpendBundle([make_spend(funding_coin, funding, Program.to([
        [51, puzzle.get_tree_hash(), AMOUNT], [51, funding.get_tree_hash(), funding_coin.amount - AMOUNT]
    ]))], G2Element())
    status, error = await submit(funding_bundle)
    require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Funding failed: {status} {error}")
    funding_block = await farm()
    await check_inclusion(funding_block, [contract, change], [funding_coin])
    before = await state(contract)
    while node.mempool_manager.peak.height < HEIGHT:
        await farm()
    context = {"peak_height": int(node.blockchain.get_peak().height),
               "mempool_peak_height": int(node.mempool_manager.peak.height),
               "previous_transaction_block_height": int(node.blockchain.get_peak().prev_transaction_block_height)}
    require(context["mempool_peak_height"] >= HEIGHT, "Signature negative is height-invalid")
    flags = int(get_flags_for_height_and_constants(node.mempool_manager.peak.height, constants)) | int(MEMPOOL_MODE)
    require(not flags & int(DONT_VALIDATE_SIGNATURE), "Signature bypass flag")
    final_message = message + bytes(contract.name()) + bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA)
    pairs = pkm_pairs_for_conditions_dict(conditions_dict_for_solution(puzzle, solution, MAX_COST),
                                        contract, constants.AGG_SIG_ME_ADDITIONAL_DATA)
    require(pairs == [(owner, final_message)], "Independent signing message differs from upstream")
    signature = AugSchemeMPL.sign(key, final_message)
    require(AugSchemeMPL.verify(owner, final_message, signature), "Positive signature invalid")
    expected_child = Coin(contract.name(), recipient.get_tree_hash(), uint64(AMOUNT))
    spend = make_spend(contract, puzzle, solution)
    rejected = SpendBundle([spend], G2Element())
    status, error = await submit(rejected)
    require(status == MempoolInclusionStatus.FAILED and error == Err.BAD_AGGREGATE_SIGNATURE,
            f"Missing-signature rejection differs: {status} {error}")

    async def unchanged():
        require(await state(contract) == before and not before.spent, "Rejected attempt changed input")
        require(await node.coin_store.get_coin_record(expected_child.name()) is None, "Rejected attempt created recipient")
        require(not await node.coin_store.get_coin_records_by_parent_ids(True, [contract.name()]),
                "Rejected attempt created children")
        require(not node.mempool_manager.mempool.all_item_ids(), "Rejected attempt entered mempool")
        require(not (await state(change)).spent, "Change consumed")

    await unchanged()
    rejection_block = await farm()
    await unchanged()
    rejection = {"status": status.name, "error": error.name, "bundle_id": rejected.name().hex(),
                 "context": context, "flags": flags, "state_unchanged_after_farm": True,
                 "after_farm_height": int(rejection_block.height), "input_record": before.to_json_dict()}
    bundle = SpendBundle([spend], signature)
    acceptance_height = int(node.mempool_manager.peak.height)
    status, error = await submit(bundle)
    require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Valid payment rejected: {status} {error}")
    item = node.mempool_manager.get_mempool_item(bundle.name())
    require(item is not None, "Payment not in mempool")
    consensus_cost = int(item.cost)
    payment_block = await farm()
    await check_inclusion(payment_block, [expected_child], [contract])
    after, child = await state(contract), await state(expected_child)
    children = await node.coin_store.get_coin_records_by_parent_ids(True, [contract.name()])
    require(len(children) == 1 and children[0].coin == expected_child, "Unexpected payment children")
    require(not (await state(change)).spent and not node.mempool_manager.mempool.all_item_ids(),
            "Change or post-payment mempool mismatch")
    return {"manifest": manifest, "bindings": bindings, "application_message": message.hex(),
            "final_signing_message": final_message.hex(), "signature": bytes(signature).hex(),
            "signature_domain": constants.AGG_SIG_ME_ADDITIONAL_DATA.hex(), "conditions_hex": bytes(conditions).hex(),
            "funding_coin": coin_json(funding_coin), "contract_coin": coin_json(contract),
            "change_coin": coin_json(change), "recipient_coin": coin_json(expected_child),
            "funding_height": int(funding_block.height), "funding_block_hash": funding_block.header_hash.hex(),
            "rejection": rejection, "acceptance_mempool_height": acceptance_height,
            "payment_height": int(payment_block.height), "payment_block_hash": payment_block.header_hash.hex(),
            "bundle_id": bundle.name().hex(), "payment_status": status.name,
            "input_before": before.to_json_dict(), "input_after": after.to_json_dict(),
            "recipient_record": child.to_json_dict(), "exactly_one_child": True, "change_unspent": True,
            "local_cli_vm_cost": local["cost"], "upstream_program_vm_cost": str(vm_cost),
            "full_node_mempool_cost": str(consensus_cost), "offline_sync_readiness_bypassed": True}
