"""Actual isolated full-node RPC rehearsal, using the pinned simulator identity."""
import asyncio
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sys

from smoke import ROOT, BASE, require

sys.path.insert(0, str(ROOT / "integration"))
from confirmation_transport import ConfirmationTransport
from testnet_probe import ProbeError, observe, hex32, state, coin_id


class RehearsalTransport(ConfirmationTransport):
    """Harness-only additions. Never exposed by the public read-only clients."""
    def validate_request(self, route, request):
        if route == "push_tx":
            require(type(request) is dict and set(request) == {"spend_bundle"}, "Invalid submission request")
            from chia_rs import SpendBundle
            SpendBundle.from_json_dict(request["spend_bundle"])
        elif route == "get_mempool_item_by_tx_id":
            require(type(request) is dict and set(request) == {"tx_id"}, "Invalid mempool request")
            hex32(request["tx_id"])
        else:
            super().validate_request(route, request)


def audit(result):
    from full_node_fee_payment import audit as audit_fees
    audit_fees(result["fee_payment"])
    require(result["node_version"] == "2.7.4" and result["network"]["network_name"] == "0xbasic-simulator", "Wrong rehearsal identity")
    require(result["public_testnet_probe_rejected"] and result["rpc_closed"] and result["no_peer_or_daemon_connections"], "Incomplete RPC isolation evidence")
    require(not result["fee_payment"]["offline_sync_readiness_bypassed"], "RPC used test submission bypass")
    receipts = result["submissions"]
    require(len(receipts) == 13 and sum(r["accepted"] for r in receipts) == 9, "Incomplete RPC submission coverage")
    require(all(r["duplicate_success"] and r["mempool_bundle_matched"] for r in receipts if r["accepted"]), "Missing duplicate/mempool checks")
    require(len(result["confirmed_rpc_spends"]) == 5 and all(r["exact_spend_and_children"] for r in result["confirmed_rpc_spends"]), "Missing RPC confirmation checks")
    observed = {r["coin_id"]: r for r in result["confirmed_rpc_spends"]}
    require(len(observed) == 5, "Duplicate RPC spend evidence")
    for confirmation in result["fee_payment"]["confirmations"]:
        for expected in confirmation["bundle"]["coin_spends"]:
            c = expected["coin"]
            identity = coin_id(c["parent_coin_info"], c["puzzle_hash"], c["amount"])
            r = observed[identity]
            height = confirmation["inclusion_block"]["height"]
            expected_children = [{**child, "spent": child["spent_block_index"] > 0}
                for child in confirmation["output_records"] if hex32(child["coin"]["parent_coin_info"]) == identity]
            require(r["coin_solution"] == expected and r["children"] == expected_children
                    and r["height"] == height and r["block_hash"] == confirmation["inclusion_block"]["header_hash"]
                    and r["confirmations"] == result["confirmation_peak"]["height"] - height + 1 and r["confirmations"] >= 1,
                    "RPC evidence differs from exact block/store evidence")
    require(result["all_submitted_bundles_absent_before_reorg"] and result["public_network_contacted"] is False, "Incomplete final RPC state")
    from rpc_reorg import audit as audit_reorg
    audit_reorg(result["reorg"])
    reorg = result["reorg"]
    first = result["fee_payment"]["confirmations"][0]["inclusion_block"]
    require(all(reorg["before"]["peak"][key] == result["confirmation_peak"][key] for key in ("height", "header_hash"))
            and reorg["before"]["anchor"] == {"height": first["height"], "header_hash": first["header_hash"]}, "Reorg targets wrong checkpoint")
    expected_inputs = [r for c in result["fee_payment"]["confirmations"] for r in c["input_records"]]
    for old, restored in zip(expected_inputs, reorg["after"]["restored_inputs"]):
        require(restored["coin"] == old["coin"] and restored["confirmed_block_index"] == old["confirmed_block_index"], "Wrong restored input")
    expected_missing = set()
    for c in result["fee_payment"]["confirmations"]:
        for r in c["output_records"]:
            coin = r["coin"]
            expected_missing.add(coin_id(coin["parent_coin_info"], coin["puzzle_hash"], coin["amount"]))
    require(set(reorg["after"]["missing_outputs"]) == expected_missing, "Wrong removed output IDs")
    from rpc_reconfirm import audit as audit_reconfirm
    audit_reconfirm(result["reconfirmation"], result["fee_payment"], reorg)
    audit_journal(result)


def audit_journal(result):
    from observation_journal import STAGES, decode_history, encoded
    journal = result["journal"]
    raw = {key: journal[key] for key in ("schema_version", "context", "records")}
    require(decode_history(encoded(raw) + b"\n") == journal, "Embedded journal altered")
    require([r["stage"] for r in journal["records"]] == list(STAGES), "Incomplete journal")
    require(journal["context"]["node_version"] == result["node_version"]
            and journal["context"]["network"] == result["network"], "Wrong journal identity")
    expected = [result["initial_peak"], {"bundle_ids": [c["bundle_id"] for c in result["fee_payment"]["confirmations"]]},
                result["reorg"]["before"], result["reorg"]["deeper"], result["reorg"]["after"],
                result["reconfirmation"]["pending"], result["reconfirmation"]["confirming"], result["reconfirmation"]["confirmed"],
                {"rpc_closed": True}]
    require([r["observation"] for r in journal["records"]] == expected, "Journal differs from validated lifecycle")


async def rehearse(node, api, binary, run, bt):
    from chia.full_node.full_node_rpc_api import FullNodeRpcApi
    from chia.rpc.rpc_server import start_rpc_server
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia.util.errors import Err
    from chia_rs import SpendBundle
    from chia_rs.sized_ints import uint16
    from full_node_fee_payment import fee_payment
    from full_node_smoke import contained

    sources = json.loads((BASE / "rpc_sources.json").read_text())
    distribution = metadata.distribution("chia-blockchain")
    for relative, digest in sources["source_hashes"].items():
        require(hashlib.sha256(Path(distribution.locate_file(relative)).read_bytes()).hexdigest() == digest, "RPC source drift")
    require(metadata.version("chia-blockchain") == "2.7.4", "Unexpected rehearsal runtime")
    require("simulator" in node.config["selected_network"], "Expected isolated simulator network")
    require(await node.synced(), "Simulator readiness failed")
    rpc = await start_rpc_server(FullNodeRpcApi(node), "127.0.0.1", uint16(0), uint16(0), lambda: None,
                                 bt.root_path, bt.config, node.config, connect_to_daemon=False)
    result = {"submissions": [], "confirmed_rpc_spends": [], "rpc_source_hashes": sources["source_hashes"],
              "public_network_contacted": False, "rpc_closed": False}
    try:
        ca = contained(bt.root_path / bt.config["private_ssl_ca"]["crt"], run)
        cert = contained(bt.root_path / bt.config["daemon_ssl"]["private_crt"], run)
        key = contained(bt.root_path / bt.config["daemon_ssl"]["private_key"], run)
        transport = RehearsalTransport(f"https://127.0.0.1:{rpc.listen_port}", ca, cert, key)

        async def call(route, request=None):
            return await asyncio.to_thread(transport.call, route, {} if request is None else request)

        async def success(route, request=None):
            reply = await call(route, request)
            require(reply["success"] is True, "RPC read failed")
            return reply

        result["node_version"] = (await success("get_version"))["version"]
        result["network"] = await success("get_network_info")
        require(result["node_version"] == "2.7.4" and result["network"]["network_name"] == node.config["selected_network"]
                and hex32(result["network"]["genesis_challenge"]) == node.constants.GENESIS_CHALLENGE.hex(), "RPC identity disagrees with node")
        try:
            await asyncio.to_thread(observe, transport.call)
        except ProbeError:
            result["public_testnet_probe_rejected"] = True
        else:
            raise RuntimeError("Public-testnet probe accepted isolated simulator")
        result["initial_peak"] = await asyncio.to_thread(state, transport.call)
        from observation_journal import Journal, read_history
        journal_path = run / "observations.json"
        journal = Journal(journal_path, {"node_version": result["node_version"], "network": result["network"],
                                        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                                        "rpc_source_hashes": sources["source_hashes"]})
        journal.record("ready", result["initial_peak"])

        async def submit(bundle):
            reply = await call("push_tx", {"spend_bundle": bundle.to_json_dict()})
            receipt = {"bundle_id": bundle.name().hex(), "accepted": reply["success"] is True, "response": reply}
            result["submissions"].append(receipt)
            if not reply["success"]:
                structured = reply.get("structuredError", {})
                require(structured.get("code") == "TRANSACTION_FAILED", "Unexpected RPC submission error")
                error = structured["data"]["error"]
                return MempoolInclusionStatus.FAILED, Err[error]
            require(reply.get("status") == "SUCCESS", "Unexpected pending RPC result")
            item = (await success("get_mempool_item_by_tx_id", {"tx_id": bundle.name().hex()}))["mempool_item"]
            require(SpendBundle.from_json_dict(item["spend_bundle"]) == bundle, "RPC mempool bundle mismatch")
            receipt["mempool_bundle_matched"] = True
            duplicate = await call("push_tx", {"spend_bundle": bundle.to_json_dict()})
            require(duplicate["success"] and duplicate.get("status") == "SUCCESS", "Duplicate RPC submission not idempotent")
            receipt["duplicate_success"] = True
            return MempoolInclusionStatus.SUCCESS, None

        directory = run / "rpc-fees"
        directory.mkdir()
        from chia.types.blockchain_format.program import Program
        from chia.simulator.simulator_protocol import FarmNewBlockProtocol
        # Seed the dedicated anyone-can-spend funding puzzle with local rewards.
        for _ in range(2):
            await api.farm_new_transaction_block(FarmNewBlockProtocol(Program.to(1).get_tree_hash()))
        result["fee_payment"] = await fee_payment(node, api, binary, directory, submitter=submit)
        journal.record("fees-confirmed", {"bundle_ids": [c["bundle_id"] for c in result["fee_payment"]["confirmations"]]})
        # Compare RPC records against independently asserted block/store evidence.
        before = await asyncio.to_thread(state, transport.call)
        for confirmed in result["fee_payment"]["confirmations"]:
            bundle = SpendBundle.from_json_dict(confirmed["bundle"])
            height = confirmed["inclusion_block"]["height"]
            block = (await success("get_block_record_by_height", {"height": height}))["block_record"]
            require(block["height"] == height and hex32(block["header_hash"]) == confirmed["inclusion_block"]["header_hash"], "RPC confirmation block differs")
            for spend in bundle.coin_spends:
                actual = (await success("get_puzzle_and_solution", {"coin_id": spend.coin.name().hex(), "height": height}))["coin_solution"]
                from chia.types.coin_spend import CoinSpend
                require(CoinSpend.from_json_dict(actual) == spend, "RPC on-chain puzzle/solution mismatch")
                expected_input = next(r for r in confirmed["input_records"] if r["coin"] == spend.coin.to_json_dict())
                actual_input = (await success("get_coin_record_by_name", {"name": spend.coin.name().hex()}))["coin_record"]
                require(actual_input == {**expected_input, "spent": expected_input["spent_block_index"] > 0}, "RPC input record mismatch")
                children = []
                from chia_rs import Coin
                for child_record in confirmed["output_records"]:
                    child = Coin.from_json_dict(child_record["coin"])
                    if child.parent_coin_info != spend.coin.name():
                        continue
                    observed = (await success("get_coin_record_by_name", {"name": child.name().hex()}))["coin_record"]
                    require(observed == {**child_record, "spent": child_record["spent_block_index"] > 0}, "RPC child record mismatch")
                    children.append(observed)
                result["confirmed_rpc_spends"].append({"coin_id": spend.coin.name().hex(), "height": height,
                    "block_hash": hex32(block["header_hash"]), "coin_solution": actual, "children": children,
                    "confirmations": before["height"] - height + 1, "exact_spend_and_children": True})
        after = await asyncio.to_thread(state, transport.call)
        require(before == after, "Peak changed during RPC confirmation checks")
        result["confirmation_peak"] = after
        for receipt in result["submissions"]:
            reply = await call("get_mempool_item_by_tx_id", {"tx_id": receipt["bundle_id"]})
            require(reply["success"] is False and reply.get("structuredError", {}).get("code") == "TX_NOT_IN_MEMPOOL", "Unexpected final RPC mempool state")
        result["all_submitted_bundles_absent_before_reorg"] = True
        # Above fee/peak/mempool evidence is the pre-reorg checkpoint. Preserve it
        # as historical evidence; subsequent chain state is reported separately.
        from rpc_reorg import exercise
        result["reorg"] = await exercise(call, node, api, result["fee_payment"], record=journal.record)
        from rpc_reconfirm import exercise as reconfirm
        result["reconfirmation"] = await reconfirm(call, node, api, result["fee_payment"], result["reorg"], record=journal.record)
        require(not node.server.all_connections and node.server.webserver is None
                and rpc.daemon_connection_task is None and rpc.websocket is None, "Unexpected peer/daemon connection")
        result["no_peer_or_daemon_connections"] = True
    finally:
        rpc.close()
        await rpc.await_closed()
        result["rpc_closed"] = True
    journal.record("rpc-closed", {"rpc_closed": True})
    result["journal"] = read_history(journal_path)
    audit(result)
    return result
