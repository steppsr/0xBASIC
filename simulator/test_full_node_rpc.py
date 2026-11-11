"""RPC evidence must agree with independently checked block/store records."""
import copy
import unittest

from full_node_rpc import audit, RehearsalTransport
from test_full_node_fee_payment import evidence as fee_evidence
from testnet_probe import ProbeError, coin_id


def evidence():
    from test_rpc_reorg import evidence as reorg_evidence
    fee = fee_evidence()
    fee["offline_sync_readiness_bypassed"] = False
    result = {"fee_payment": fee, "node_version": "2.7.4", "network": {"network_name": "0xbasic-simulator"},
              "reorg": reorg_evidence(),
              "public_testnet_probe_rejected": True, "rpc_closed": True, "no_peer_or_daemon_connections": True,
              "public_network_contacted": False, "all_submitted_bundles_absent_before_reorg": True,
              "confirmation_peak": {"height": 12, "header_hash": "55" * 32, "synced": True, "sync_mode": False}, "confirmed_rpc_spends": [],
              "submissions": [{"accepted": i < 9, "duplicate_success": True, "mempool_bundle_matched": True} for i in range(13)]}
    index = 0
    for c in fee["confirmations"]:
        c["bundle_id"] = str(index)
        c["bundle"] = {"coin_spends": []}
        c["inclusion_block"].update(height=10, header_hash="ab" * 32)
        c["output_records"] = []
        c["input_records"] = []
        for j in range(c["input_count"]):
            index += 1
            coin = {"parent_coin_info": f"{index:064x}", "puzzle_hash": "cd" * 32, "amount": 1000}
            identity = coin_id(coin["parent_coin_info"], coin["puzzle_hash"], 1000)
            spend = {"coin": coin, "puzzle_reveal": "01", "solution": "80"}
            c["input_records"].append({"coin": copy.deepcopy(coin), "confirmed_block_index": 5})
            c["bundle"]["coin_spends"].append(spend)
            # Only test report consistency here; fee audit retains its own fixture counts.
            output_count = c["child_count"] if j == 0 else 0
            children = [{"coin": {"parent_coin_info": identity, "puzzle_hash": f"{k:064x}", "amount": 1},
                         "spent_block_index": 0} for k in range(output_count)]
            c["output_records"].extend(children)
            result["confirmed_rpc_spends"].append({"coin_id": identity, "coin_solution": copy.deepcopy(spend),
                "height": 10, "block_hash": "ab" * 32, "confirmations": 3, "exact_spend_and_children": True,
                "children": [{**copy.deepcopy(child), "spent": False} for child in children]})
    reorg = result["reorg"]
    reorg["before"]["peak"] = {"height": 12, "header_hash": "55" * 32}
    reorg["before"]["confirmations"] = 3
    reorg["deeper"]["peak"] = {"height": 13}
    reorg["deeper"]["confirmations"] = reorg["required_depth"] = 4
    reorg["after"]["restored_inputs"] = [{**copy.deepcopy(r), "spent": False, "spent_block_index": 0}
        for c in fee["confirmations"] for r in c["input_records"]]
    reorg["after"]["missing_outputs"] = [coin_id(r["coin"]["parent_coin_info"], r["coin"]["puzzle_hash"], r["coin"]["amount"])
        for c in fee["confirmations"] for r in c["output_records"]]
    from test_rpc_reconfirm import evidence as reconfirm_evidence
    result["reconfirmation"] = reconfirm_evidence([c["bundle_id"] for c in fee["confirmations"]], reorg["after"]["peak"]["height"])
    result["initial_peak"] = {"height": 1}
    from observation_journal import STAGES, digest, encoded, decode_history
    context = {"node_version": result["node_version"], "network": result["network"]}
    observations = [result["initial_peak"], {"bundle_ids": [c["bundle_id"] for c in fee["confirmations"]]},
                    reorg["before"], reorg["deeper"], reorg["after"], result["reconfirmation"]["pending"],
                    result["reconfirmation"]["confirming"], result["reconfirmation"]["confirmed"], {"rpc_closed": True}]
    records, previous = [], digest(context)
    for index, (stage, observation) in enumerate(zip(STAGES, observations)):
        body = {"sequence": index + 1, "stage": stage, "observation": copy.deepcopy(observation), "previous": previous}
        previous = digest(body)
        records.append({**body, "sha256": previous})
    result["journal"] = decode_history(encoded({"schema_version": 1, "context": context, "records": records}) + b"\n")
    return result


class RpcEvidenceTests(unittest.TestCase):
    def test_consistent_evidence(self):
        audit(evidence())

    def test_mutated_evidence_fails(self):
        changes = [lambda r: r.update(rpc_closed=False), lambda r: r.update(public_network_contacted=True),
            lambda r: r.update(node_version="2.7.5"), lambda r: r["network"].update(network_name="testnet11"),
            lambda r: r["submissions"].pop(), lambda r: r["submissions"][0].update(duplicate_success=False),
            lambda r: r["submissions"][0].update(mempool_bundle_matched=False),
            lambda r: r["confirmed_rpc_spends"].pop(), lambda r: r["confirmed_rpc_spends"][0].update(confirmations=0),
            lambda r: r["confirmed_rpc_spends"][0].update(block_hash="ef" * 32),
            lambda r: r["confirmed_rpc_spends"][0]["coin_solution"].update(solution="01"),
            lambda r: r["confirmed_rpc_spends"][0]["children"].pop(),
            lambda r: r["fee_payment"].update(offline_sync_readiness_bypassed=True),
            lambda r: r["reorg"]["after"]["restored_inputs"][0]["coin"].update(amount=999),
            lambda r: r["reorg"]["after"]["missing_outputs"].__setitem__(0, "ef" * 32),
            lambda r: r["journal"]["records"].pop(),
            lambda r: r["journal"]["records"][0]["observation"].update(height=999),
            lambda r: r["journal"].update(automatic_resume_allowed=True)]
        for index, change in enumerate(changes):
            r = evidence()
            change(r)
            with self.subTest(case=index), self.assertRaises((RuntimeError, KeyError)):
                audit(r)

    def test_harness_routes_reject_invalid_requests_before_io(self):
        client = object.__new__(RehearsalTransport)
        for route, request in [("get_private_key", {}), ("send_transaction", {}),
                               ("push_tx", {}), ("get_mempool_item_by_tx_id", {"tx_id": "bad"})]:
            with self.subTest(route=route), self.assertRaises((ProbeError, RuntimeError)):
                client.call(route, request)


if __name__ == "__main__":
    unittest.main()
