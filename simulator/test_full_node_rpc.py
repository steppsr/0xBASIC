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
        c["bundle_id"] = f"{index:064x}"
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
    from network_identity import ISOLATED_REHEARSAL
    c = fee["confirmations"][0]["bundle"]["coin_spends"][0]["coin"]
    identity = coin_id(c["parent_coin_info"], c["puzzle_hash"], c["amount"])
    def shared(expected, depth):
        anchor = None if expected["status"] == "reorged" else expected.get("anchor") or {"height": expected["height"], "header_hash": expected["block_hash"]}
        return {"validation": "isolated-rpc-confirmation-observation-only", "network": ISOLATED_REHEARSAL.network(),
                "node_version": ISOLATED_REHEARSAL.version, "input_id": identity, "status": expected["status"],
                "confirmations": expected["confirmations"], "required_depth": depth, "chain_proof": False,
                "transactions_submitted": 0, "confirmation_anchor": None if anchor is None else {"input_id": identity, **anchor}}
    reorg["shared_observations"] = {k: shared(reorg[k], reorg["required_depth"]) for k in ("before", "deeper", "after")}
    result["reconfirmation"]["shared_confirmed"] = shared(result["reconfirmation"]["confirmed"]["last_observation"], 2)
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
    from offline_bridge import NEGATIVES
    result["offline_pipeline"] = []
    for confirmation in fee["confirmations"][:2]:
        confirmation["contract_spends"][0]["final_signing_message"] = "ab"
        prepared = {"validation": "isolated-offline-unsigned-fee-preparation", "network": ISOLATED_REHEARSAL.network(),
                    "node_baseline": ISOLATED_REHEARSAL.version, "transactions_submitted": 0,
                    "runtime": {"consensus_constants_sha256": "ab" * 32}, "signing_request": {"message": "ab"},
                    "expected_outputs": [copy.deepcopy(r["coin"]) for r in confirmation["output_records"]]}
        verified = {"validation": "isolated-offline-signature-verified-fee-bundle", "network": ISOLATED_REHEARSAL.network(),
                    "preparation": prepared, "signature_verified": True, "mempool_validated": False, "transactions_submitted": 0,
                    "spend_bundle": copy.deepcopy(confirmation["bundle"]), "bundle_id": confirmation["bundle_id"]}
        result["offline_pipeline"].append({"scenario": confirmation["scenario"], "node_constants_sha256": "ab" * 32,
            "node_environment_unchanged": True, "bridge": {"verified": verified, "negative_cases": list(NEGATIVES),
            "original_bundle_equal": True, "private_keys_loaded": False, "sockets_allowed": False}})
    from submission_attempt import _document
    result["verified_dispatch"] = []
    for pipeline, confirmation in zip(result["offline_pipeline"], fee["confirmations"]):
        verified = pipeline["bridge"]["verified"]
        verified.update(bundle_sha256="11" * 32, preparation_sha256="22" * 32, signature_response_sha256="33" * 32)
        coin = confirmation["bundle"]["coin_spends"][0]["coin"]
        context = {"bundle_id": verified["bundle_id"], "bundle_sha256": verified["bundle_sha256"],
                   "input_id": coin_id(coin["parent_coin_info"], coin["puzzle_hash"], coin["amount"]),
                   "preparation_sha256": verified["preparation_sha256"], "signature_response_sha256": verified["signature_response_sha256"]}
        loss = confirmation["scenario"] == "exact"
        saved = {**_document(context, "unknown" if loss else "reply-success", ISOLATED_REHEARSAL),
                 "fresh_chain_validation_required": True, "dispatch_may_have_occurred": True}
        result["verified_dispatch"].append({"scenario": confirmation["scenario"], "attempt": saved,
            "worker_calls": 1, "reply_loss_injected": loss, "automatic_retry_performed": False,
            "node_environment_unchanged": True, "mempool_bundle": copy.deepcopy(confirmation["bundle"])})
    return result


class RpcEvidenceTests(unittest.TestCase):
    def test_dispatch_evidence_mutations_fail(self):
        changes = [lambda r: r["verified_dispatch"].pop(),
                   lambda r: r["verified_dispatch"][0].update(worker_calls=2),
                   lambda r: r["verified_dispatch"][1].update(reply_loss_injected=False),
                   lambda r: r["verified_dispatch"][0].update(automatic_retry_performed=True),
                   lambda r: r["verified_dispatch"][0].update(node_environment_unchanged=False),
                   lambda r: r["verified_dispatch"][1]["attempt"].update(outcome="reply-success"),
                   lambda r: r["verified_dispatch"][0]["attempt"]["context"].update(bundle_id="ff" * 32),
                   lambda r: r["verified_dispatch"][0]["attempt"].update(confirmation_established=True),
                   lambda r: r["verified_dispatch"][0]["mempool_bundle"].update(aggregated_signature="00" * 96)]
        for change in changes:
            r = evidence()
            change(r)
            with self.assertRaises(RuntimeError):
                audit(r)

    def test_offline_pipeline_mutations_fail(self):
        changes = [lambda r: r["offline_pipeline"].pop(),
            lambda r: r["offline_pipeline"][0].update(node_environment_unchanged=False),
            lambda r: r["offline_pipeline"][0]["bridge"]["negative_cases"].pop(),
            lambda r: r["offline_pipeline"][0]["bridge"].update(private_keys_loaded=True),
            lambda r: r["offline_pipeline"][0]["bridge"]["verified"].update(bundle_id="wrong"),
            lambda r: r["offline_pipeline"][0]["bridge"]["verified"].update(transactions_submitted=1),
            lambda r: r["offline_pipeline"][0]["bridge"]["verified"]["preparation"]["runtime"].update(consensus_constants_sha256="00" * 32),
            lambda r: r["offline_pipeline"][0]["bridge"]["verified"]["preparation"]["expected_outputs"].pop()]
        for change in changes:
            r = evidence()
            change(r)
            with self.assertRaises(RuntimeError):
                audit(r)

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
            lambda r: r["journal"].update(automatic_resume_allowed=True),
            lambda r: r["reorg"]["shared_observations"]["after"].update(status="confirmed"),
            lambda r: r["reconfirmation"]["shared_confirmed"].update(input_id="ff" * 32)]
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
