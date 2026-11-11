"""Real isolated-chain depth and rollback observations; no signing or resubmission."""
from smoke import require


def audit(result):
    require(result["validation"] == "isolated-rpc-reorg-observation" and result["transactions_submitted"] == 0, "Wrong reorg scope")
    before, deeper, after = result["before"], result["deeper"], result["after"]
    require(before["status"] == "confirming" and deeper["status"] == "confirmed"
            and before["confirmations"] + 1 == deeper["confirmations"] == result["required_depth"], "Invalid depth transition")
    require(before["anchor"] == deeper["anchor"] and deeper["peak"]["height"] == before["peak"]["height"] + 1, "Depth anchor changed")
    require(before["confirmations"] == before["peak"]["height"] - before["anchor"]["height"] + 1
            and before["confirmations"] > 0, "Depth does not match chain height")
    require(after["status"] == "reorged" and after["confirmations"] == 0
            and after["old_anchor"] == before["anchor"] and after["replacement_hash"] != before["anchor"]["header_hash"]
            and after["peak"]["height"] > deeper["peak"]["height"], "Missing canonical reorg evidence")
    require(len(after["restored_inputs"]) == 5 and len(after["missing_outputs"]) == 8
            and len(set(after["missing_outputs"])) == 8, "Missing rollback evidence")
    require(all(r["spent"] is False and r["spent_block_index"] == 0 for r in after["restored_inputs"]), "Inputs remain spent")
    require(result["funding_preserved"] and result["surrounding_peak_unchanged"], "Inconsistent rollback observation")


async def exercise(call, node, api, fee, record=None, confirm=None):
    from chia.simulator.simulator_protocol import FarmNewBlockProtocol, ReorgProtocol
    from chia.types.blockchain_format.program import Program
    from chia_rs import Coin
    from chia_rs.sized_bytes import bytes32
    from chia_rs.sized_ints import uint32

    async def read(route, request=None):
        reply = await call(route, request)
        require(reply["success"] is True, "Reorg RPC read failed")
        return reply

    async def peak():
        value = (await read("get_blockchain_state"))["blockchain_state"]
        require(value["sync"]["synced"] is True and value["sync"]["sync_mode"] is False, "Reorg node not ready")
        return {"height": value["peak"]["height"], "header_hash": value["peak"]["header_hash"].removeprefix("0x")}

    first = fee["confirmations"][0]
    height = first["inclusion_block"]["height"]
    anchor = {"height": height, "header_hash": first["inclusion_block"]["header_hash"]}
    async def canonical():
        b = (await read("get_block_record_by_height", {"height": height}))["block_record"]
        require(b["height"] == height, "Wrong canonical height")
        return b["header_hash"].removeprefix("0x")

    start = await peak()
    require(await canonical() == anchor["header_hash"], "Initial anchor missing")
    depth = start["height"] - height + 1
    require(depth > 0, "Invalid initial depth")
    required = depth + 1
    before = {"status": "confirming", "confirmations": depth, "peak": start, "anchor": anchor}
    shared = {}
    if confirm is not None:
        shared["before"] = await confirm(required)
        require(shared["before"]["status"] == "confirming", "Shared observer missed pending depth")
    if record is not None:
        record("depth-pending", before)
    funding_hash = Program.to(1).get_tree_hash()
    await api.farm_new_transaction_block(FarmNewBlockProtocol(funding_hash))
    advanced = await peak()
    require(await canonical() == anchor["header_hash"] and advanced["height"] == start["height"] + 1, "Unexpected depth extension")
    deeper = {"status": "confirmed", "confirmations": advanced["height"] - height + 1, "peak": advanced, "anchor": anchor}
    if confirm is not None:
        shared["deeper"] = await confirm(required, shared["before"]["confirmation_anchor"])
        require(shared["deeper"]["status"] == "confirmed", "Shared observer missed confirmation")
    if record is not None:
        record("depth-confirmed", deeper)

    # Replace every fee-control block, preserving all earlier funding/rejection blocks.
    await api.reorg_from_index_to_new_index(ReorgProtocol(uint32(height - 1), uint32(advanced["height"] + 3),
                                                        funding_hash, bytes32(bytes.fromhex("71" * 32))))
    current = await peak()
    replacement = await canonical()
    require(replacement != anchor["header_hash"] and current["height"] > advanced["height"], "Reorg did not replace anchor")
    restored, missing = [], []
    for confirmation in fee["confirmations"]:
        for old in confirmation["input_records"]:
            coin = Coin.from_json_dict(old["coin"])
            r = (await read("get_coin_record_by_name", {"name": coin.name().hex()}))["coin_record"]
            require(r["coin"] == old["coin"] and r["confirmed_block_index"] == old["confirmed_block_index"]
                    and r["spent"] is False and r["spent_block_index"] == 0, "Input not restored after reorg")
            stored = await node.coin_store.get_coin_record(coin.name())
            require(stored is not None and not stored.spent and stored.coin == coin, "RPC rollback disagrees with store")
            restored.append(r)
        for old in confirmation["output_records"]:
            coin = Coin.from_json_dict(old["coin"])
            reply = await call("get_coin_record_by_name", {"name": coin.name().hex()})
            require(reply["success"] is False and reply.get("structuredError", {}).get("code") == "COIN_RECORD_NOT_FOUND",
                    "Rolled-back child still exists")
            require(await node.coin_store.get_coin_record(coin.name()) is None, "Rolled-back child remains in store")
            missing.append(coin.name().hex())
    for funding in fee["funding"]:
        for field in ("coin", "change"):
            # Fee oracle coin_json uses the upstream coin fields plus its own ID.
            value = funding[field]
            coin = Coin(bytes32.from_hexstr(value["parent"]), bytes32.from_hexstr(value["puzzle_hash"]), int(value["amount"]))
            r = (await read("get_coin_record_by_name", {"name": coin.name().hex()}))["coin_record"]
            require(r["coin"] == coin.to_json_dict() and r["spent"] is False
                    and r["confirmed_block_index"] == funding["block"]["height"], "Funding not preserved")
    require(await peak() == current, "Peak changed during rollback observation")
    if confirm is not None:
        shared["after"] = await confirm(required, shared["deeper"]["confirmation_anchor"])
        require(shared["after"]["status"] == "reorged", "Shared observer missed reorg")
    result = {"validation": "isolated-rpc-reorg-observation", "required_depth": required, "before": before, "deeper": deeper,
              "after": {"status": "reorged", "confirmations": 0, "old_anchor": anchor, "replacement_hash": replacement,
                        "peak": current, "restored_inputs": restored, "missing_outputs": missing},
              "transactions_submitted": 0, "funding_preserved": True, "surrounding_peak_unchanged": True}
    audit(result)
    result["shared_observations"] = shared
    if record is not None:
        record("reorged", result["after"])
    return result
