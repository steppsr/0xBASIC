"""TN-4a read-only confirmation observations through an injected RPC callable.

No transport or command-line entry point: expected spends/children must come from
the independent preparation/signature verifier, not an unvalidated report file.
"""
import re

from testnet_probe import coin_id, fetch, hex32, observe, require, state, uint


def coin(value):
    require(type(value) is dict, "Missing coin")
    return {"parent_coin_info": hex32(value.get("parent_coin_info")),
            "puzzle_hash": hex32(value.get("puzzle_hash")), "amount": uint(value.get("amount"))}


def name(value):
    return coin_id(value["parent_coin_info"], value["puzzle_hash"], value["amount"])


def program(value):
    require(type(value) is str, "Missing serialized program")
    value = value.removeprefix("0x")
    require(0 < len(value) <= 2 * 1024 * 1024 and len(value) % 2 == 0
            and re.fullmatch("[0-9a-fA-F]+", value) is not None, "Invalid serialized program")
    return value.lower()


def spend(value):
    require(type(value) is dict, "Missing coin spend")
    return {"coin": coin(value.get("coin")), "puzzle_reveal": program(value.get("puzzle_reveal")),
            "solution": program(value.get("solution"))}


def record(call, expected, peak):
    value = fetch(call, "get_coin_record_by_name", {"name": "0x" + name(expected)}).get("coin_record")
    require(type(value) is dict and coin(value.get("coin")) == expected, "Coin record mismatch")
    created, used = uint(value.get("confirmed_block_index"), 32), uint(value.get("spent_block_index"), 32)
    require(type(value.get("spent")) is bool and value["spent"] == (used != 0), "Inconsistent spent record")
    require(created <= peak and (used == 0 or created <= used <= peak), "Coin height outside observed chain")
    require(type(value.get("coinbase")) is bool, "Invalid coinbase flag")
    uint(value.get("timestamp"))
    return {"coin": expected, "coin_id": name(expected), "created_height": created,
            "spent_height": used, "spent": value["spent"], "coinbase": value["coinbase"]}


def block(call, height):
    value = fetch(call, "get_block_record_by_height", {"height": height}).get("block_record")
    require(type(value) is dict and uint(value.get("height"), 32) == height, "Wrong block height")
    return {"height": height, "header_hash": hex32(value.get("header_hash"))}


def observe_confirmation(call, expected_spend, expected_children, depth, previous_anchor=None):
    """Observe exact spend and children, with inclusive confirmation depth.

    The callable must implement authenticated, bounded RPC reads. A changed peak
    invalidates the whole observation. Even an unchanged peak is not an atomic
    snapshot or independent chain proof. No bundle/signature identity is inferred
    from a block: only exact input/puzzle/solution and expected child records.
    """
    require(type(depth) is int and 1 <= depth <= 10000, "Confirmation depth must be 1..10000")
    expected = spend(expected_spend)
    input_id = name(expected["coin"])
    require(type(expected_children) is list and 1 <= len(expected_children) <= 2, "Expected one or two fee-payment children")
    children = [coin(c) for c in expected_children]
    require(all(c["parent_coin_info"] == input_id and c["amount"] > 0 for c in children), "Wrong child parent or amount")
    require(len({name(c) for c in children}) == len(children), "Duplicate expected child")
    require(sum(c["amount"] for c in children) <= expected["coin"]["amount"], "Outputs exceed input")
    if previous_anchor is not None:
        require(type(previous_anchor) is dict and set(previous_anchor) == {"input_id", "height", "header_hash"}
                and hex32(previous_anchor["input_id"]) == input_id, "Wrong prior confirmation anchor")
        previous_anchor = {"input_id": input_id, "height": uint(previous_anchor["height"], 32),
                           "header_hash": hex32(previous_anchor["header_hash"])}
    initial = observe(call)
    before = initial["after"]
    result = {"schema_version": 1, "validation": "rpc-confirmation-observation-only",
              "network": initial["network"], "node_version": initial["node_version"], "observed_at": initial["observed_at"],
              "before": before, "required_depth": depth, "input_id": input_id,
              "atomic_snapshot": False, "chain_proof": False, "transactions_submitted": 0,
              "confirmation_anchor": None, "confirmations": 0, "children": []}

    def finish(status):
        after = state(call)
        require(after == before, "Peak changed during confirmation observation")
        result.update(status=status, after=after)
        return result

    # A prior anchor is an observation supplied by the caller, not trusted proof.
    if previous_anchor is not None:
        result["previous_anchor"] = previous_anchor
        if before["height"] < previous_anchor["height"]:
            return finish("reorged")
        current = block(call, previous_anchor["height"])
        if current["header_hash"] != previous_anchor["header_hash"]:
            return finish("reorged")
    actual = record(call, expected["coin"], before["height"])
    result["input"] = actual
    if not actual["spent"]:
        require(previous_anchor is None, "Unspent input contradicts unchanged prior anchor")
        return finish("unspent")
    height = actual["spent_height"]
    if previous_anchor is not None:
        require(height == previous_anchor["height"], "Spend height contradicts unchanged prior anchor")
    actual_spend = spend(fetch(call, "get_puzzle_and_solution", {"coin_id": "0x" + input_id, "height": height}).get("coin_solution"))
    require(actual_spend["coin"] == expected["coin"], "Returned spend coin mismatch")
    if actual_spend != expected:
        require(previous_anchor is None, "Spend contradicts unchanged prior anchor")
        return finish("conflicting-spend")
    anchor = block(call, height)
    if previous_anchor is not None:
        require(anchor["header_hash"] == previous_anchor["header_hash"], "Anchor changed during observation")
    observed_children = [record(call, child, before["height"]) for child in children]
    require(all(c["created_height"] == height and not c["coinbase"] for c in observed_children), "Child confirmation mismatch")
    result["children"] = observed_children
    result["confirmation_anchor"] = {"input_id": input_id, **anchor}
    result["confirmations"] = before["height"] - height + 1
    return finish("confirmed" if result["confirmations"] >= depth else "confirming")
