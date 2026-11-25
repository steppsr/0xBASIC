"""Internal read-only SSH confirmation adapter; caller must verify signed inputs.

No CLI, signature verification, polling, submission, or automatic recovery.
"""
from confirmation import coin, name, spend
from network_identity import PUBLIC_TESTNET
from ssh_probe import _exchange
from testnet_probe import hex32, require, uint


def read_confirmation(target, packet, duration):
    expected = spend(packet["spend"])
    input_id = name(expected["coin"])
    depth = packet["depth"]
    require(type(depth) is int and 1 <= depth <= 10000, "Invalid confirmation depth")
    require(type(packet["children"]) is list and 1 <= len(packet["children"]) <= 2,
            "Expected one or two children")
    children = [coin(child) for child in packet["children"]]
    require(all(child["parent_coin_info"] == input_id and child["amount"] > 0 for child in children)
            and len({name(child) for child in children}) == len(children)
            and sum(child["amount"] for child in children) <= expected["coin"]["amount"],
            "Invalid expected outputs")
    anchor = packet.get("anchor")
    if anchor is not None:
        require(type(anchor) is dict and set(anchor) == {"input_id", "height", "header_hash"}
                and hex32(anchor["input_id"]) == input_id, "Wrong prior anchor")
        anchor = {"input_id": input_id, "height": uint(anchor["height"], 32),
                  "header_hash": hex32(anchor["header_hash"])}
    reply = _exchange(target, packet["endpoint"], packet["ca"], packet["cert"], packet["key"],
                      duration, packet["socket_timeout"], "confirmation",
                      {"spend": expected, "children": children, "depth": depth, "anchor": anchor})
    observed = reply["observation"]
    require(type(observed) is dict and observed.get("validation") == "rpc-confirmation-observation-only"
            and observed.get("network") == PUBLIC_TESTNET.network()
            and observed.get("node_version") == PUBLIC_TESTNET.version
            and observed.get("input_id") == input_id and type(observed.get("required_depth")) is int
            and observed["required_depth"] == depth
            and observed.get("status") in {"unspent", "confirming", "confirmed", "reorged", "conflicting-spend"}
            and observed.get("chain_proof") is False and observed.get("atomic_snapshot") is False
            and type(observed.get("transactions_submitted")) is int and observed["transactions_submitted"] == 0,
            "Unexpected SSH confirmation observation")
    require(observed.get("previous_anchor") == anchor, "Confirmation reply changed prior anchor")
    return observed
