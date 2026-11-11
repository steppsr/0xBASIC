"""Reconfirm unchanged fixture bundles after actual rollback, with bounded reads."""
from smoke import require
from rpc_poll import poll


def audit(result, fee, reorg):
    expected_ids = [c["bundle_id"] for c in fee["confirmations"]]
    require(result["bundle_ids"] == expected_ids and result["transactions_submitted"] == 3
            and result["signatures_created"] == 0 and result["unchanged_bundles"], "Reconfirmation replaced original bundles")
    pending, confirming, done = result["pending"], result["confirming"], result["confirmed"]
    require(pending["status"] == "timed-out" and pending["reason"] == "attempt-limit" and pending["attempts"] == 2
            and pending["last_observation"]["status"] == "unspent", "Mempool acceptance incorrectly confirmed")
    require(confirming["status"] == "confirming" and confirming["confirmations"] == 1, "Missing depth-one observation")
    require(done["status"] == "confirmed" and done["last_observation"]["status"] == "confirmed"
            and done["transactions_submitted"] == 0, "Missing bounded reconfirmation")
    observed = done["last_observation"]
    require(observed["confirmations"] == result["required_depth"] == 2
            and observed["height"] > reorg["after"]["peak"]["height"]
            and observed["height"] == confirming["height"] and observed["block_hash"] == confirming["block_hash"]
            and observed["peak"]["height"] == observed["height"] + 1, "Wrong new inclusion/depth")
    require(observed["exact_spends"] == 5 and observed["exact_outputs"] == 8
            and result["block_fee"] == "51" and result["mempool_empty_after"] and result["funding_change_preserved"], "Incomplete reconfirmation accounting")


async def exercise(call, node, api, fee, reorg, record=None, confirm=None):
    from chia_rs import SpendBundle, Coin
    from chia.types.coin_spend import CoinSpend
    from chia.types.blockchain_format.program import Program
    from chia.simulator.simulator_protocol import FarmNewBlockProtocol

    async def read(route, request=None):
        reply = await call(route, request)
        require(reply["success"] is True, "Reconfirmation RPC read failed")
        return reply

    bundles = [SpendBundle.from_json_dict(c["bundle"]) for c in fee["confirmations"]]
    inputs = [s for b in bundles for s in b.coin_spends]
    outputs = [Coin.from_json_dict(r["coin"]) for c in fee["confirmations"] for r in c["output_records"]]
    require([b.name().hex() for b in bundles] == [c["bundle_id"] for c in fee["confirmations"]], "Original bundle ID mismatch")
    for bundle in bundles:
        reply = await read("push_tx", {"spend_bundle": bundle.to_json_dict()})
        require(reply.get("status") == "SUCCESS", "Reconfirmation submission not accepted")
        item = (await read("get_mempool_item_by_tx_id", {"tx_id": bundle.name().hex()}))["mempool_item"]
        require(SpendBundle.from_json_dict(item["spend_bundle"]) == bundle, "Mempool replaced unchanged bundle")

    async def peak():
        v = (await read("get_blockchain_state"))["blockchain_state"]
        require(v["sync"]["synced"] is True and v["sync"]["sync_mode"] is False, "Node not ready")
        return {"height": v["peak"]["height"], "header_hash": v["peak"]["header_hash"].removeprefix("0x")}

    async def observation():
        before = await peak()
        records = [(await read("get_coin_record_by_name", {"name": s.coin.name().hex()}))["coin_record"] for s in inputs]
        for s, record in zip(inputs, records):
            require(record["coin"] == s.coin.to_json_dict(), "Reconfirmation input changed")
        if all(r["spent"] is False and r["spent_block_index"] == 0 for r in records):
            require(await peak() == before, "Peak changed during pending observation")
            return {"status": "unspent", "peak": before, "confirmations": 0}
        heights = {r["spent_block_index"] for r in records}
        require(all(r["spent"] is True for r in records) and len(heights) == 1, "Partial or inconsistent fixture inclusion")
        height = heights.pop()
        require(reorg["after"]["peak"]["height"] < height <= before["height"], "Old or future spend height")
        block = (await read("get_block_record_by_height", {"height": height}))["block_record"]
        require(block["height"] == height, "Wrong reconfirmation block")
        for spend in inputs:
            actual = (await read("get_puzzle_and_solution", {"coin_id": spend.coin.name().hex(), "height": height}))["coin_solution"]
            require(CoinSpend.from_json_dict(actual) == spend, "Reconfirmed spend differs")
            stored = await node.coin_store.get_coin_record(spend.coin.name())
            require(stored.spent and stored.spent_block_index == height, "RPC inclusion disagrees with store")
        for child in outputs:
            r = (await read("get_coin_record_by_name", {"name": child.name().hex()}))["coin_record"]
            require(r["coin"] == child.to_json_dict() and r["confirmed_block_index"] == height
                    and r["spent"] is False and not r["coinbase"], "Recreated output mismatch")
            stored = await node.coin_store.get_coin_record(child.name())
            require(stored.coin == child and stored.confirmed_block_index == height and not stored.spent, "RPC child differs from store")
        require(await peak() == before, "Peak changed during reconfirmation")
        depth = before["height"] - height + 1
        return {"status": "confirmed" if depth >= 2 else "confirming", "confirmations": depth, "height": height,
                "block_hash": block["header_hash"].removeprefix("0x"), "peak": before, "exact_spends": 5, "exact_outputs": 8}

    pending = await poll(observation, timeout=30, interval=0.02, max_attempts=2)
    require(pending["status"] == "timed-out" and pending["last_observation"]["status"] == "unspent", "Unexpected pending observation")
    if record is not None:
        record("pending-timeout", pending)
    funding_hash = Program.to(1).get_tree_hash()
    block = await api.farm_new_transaction_block(FarmNewBlockProtocol(funding_hash))
    require(block.transactions_info is not None and block.transactions_info.fees == 51, "Reconfirmed block fee differs")
    added = await node.coin_store.get_coins_added_at_height(block.height)
    removed = await node.coin_store.get_coins_removed_at_height(block.height)
    require({r.coin for r in added if not r.coinbase} == set(outputs) and len([r for r in added if not r.coinbase]) == 8
            and {r.coin for r in removed} == {s.coin for s in inputs} and len(removed) == 5, "Reconfirmation block coins differ")
    confirming = await observation()
    require(confirming["status"] == "confirming", "Missing depth-one observation")
    if record is not None:
        record("reconfirming", confirming)
    await api.farm_new_transaction_block(FarmNewBlockProtocol(funding_hash))
    confirmed = await poll(observation, timeout=30, interval=0.02, max_attempts=2)
    for bundle in bundles:
        reply = await call("get_mempool_item_by_tx_id", {"tx_id": bundle.name().hex()})
        require(reply["success"] is False and reply.get("structuredError", {}).get("code") == "TX_NOT_IN_MEMPOOL", "Reconfirmed bundle remains in mempool")
    require(not node.mempool_manager.mempool.all_item_ids(), "Other active mempool entries remain")
    for funding in fee["funding"]:
        old = funding["change"]
        r = (await read("get_coin_record_by_name", {"name": old["id"]}))["coin_record"]
        require(r["coin"]["amount"] == int(old["amount"])
                and r["coin"]["parent_coin_info"].removeprefix("0x") == old["parent"]
                and r["coin"]["puzzle_hash"].removeprefix("0x") == old["puzzle_hash"] and r["spent"] is False
                and r["confirmed_block_index"] == funding["block"]["height"], "Funding change changed")
    result = {"bundle_ids": [b.name().hex() for b in bundles], "transactions_submitted": 3, "signatures_created": 0,
              "unchanged_bundles": True, "required_depth": 2, "pending": pending, "confirming": confirming,
              "confirmed": confirmed, "block_fee": "51", "mempool_empty_after": True, "funding_change_preserved": True}
    audit(result, fee, reorg)
    if confirm is not None:
        result["shared_confirmed"] = await confirm(2)
        require(result["shared_confirmed"]["status"] == "confirmed", "Shared observer missed reconfirmation")
    if record is not None:
        record("reconfirmed", confirmed)
    return result
