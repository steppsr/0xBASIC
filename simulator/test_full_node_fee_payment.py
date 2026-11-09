"""Fail-closed fee evidence checks, without importing Chia."""
import unittest

from full_node_fee_payment import audit


def evidence():
    result = {"rejections": [], "confirmations": [],
              "rejected_coin_unspent_after_controls": True, "funding_change_unchanged": True,
              "active_mempool_empty": True, "all_confirmed_outputs_unspent": True}
    for name, error in [("missing-signature", "BAD_AGGREGATE_SIGNATURE"),
                        ("changed-fee-stale-signature", "BAD_AGGREGATE_SIGNATURE"),
                        ("wrong-coin-amount", "ASSERT_MY_AMOUNT_FAILED"),
                        ("additive-fee-offset", "RESERVE_FEE_CONDITION_FAILED")]:
        result["rejections"].append({"scenario": name, "error": error, "status": "FAILED",
            "after_farm_block": {"fee": "0"}, "state_unchanged_after_farm": True,
            "funding_change_unchanged": True, "active_mempool_empty": True})
    result["rejections"][-1]["accounting"] = {
        "removal_amount": "2100", "addition_amount": "2080", "net_fee": "20", "reserved_fee": "30"}
    for name, removed, added, fee, inputs, outputs, contracts in [
            ("partial", 1000, 989, 11, 1, 2, 1), ("exact", 1000, 990, 10, 1, 1, 1),
            ("additive-aggregate", 2100, 2070, 30, 3, 5, 2)]:
        result["confirmations"].append({"scenario": name, "status": "SUCCESS",
            "accounting": {"removal_amount": str(removed), "addition_amount": str(added),
                           "net_fee": str(fee), "reserved_fee": str(fee)},
            "inclusion_block": {"fee": str(fee)}, "input_count": inputs, "child_count": outputs,
            "input_records": [{}] * inputs, "output_records": [{}] * outputs,
            "contract_spends": [{}] * contracts, "exact_block_coins": True, "all_outputs_unspent": True,
            "unaffected_inputs_unchanged": True, "funding_change_unchanged": True, "active_mempool_empty": True})
    return result


class FullNodeFeeTests(unittest.TestCase):
    def test_complete_evidence(self):
        audit(evidence())

    def test_incomplete_or_incorrect_evidence(self):
        mutations = [
            lambda r: r["rejections"].pop(),
            lambda r: r["rejections"].append(r["rejections"][0]),
            lambda r: r["rejections"][3].update(error="BAD_AGGREGATE_SIGNATURE"),
            lambda r: r["rejections"][3]["accounting"].update(reserved_fee="20"),
            lambda r: r["rejections"][0]["after_farm_block"].update(fee="1"),
            lambda r: r["rejections"][0].update(state_unchanged_after_farm=False),
            lambda r: r["confirmations"].pop(),
            lambda r: r["confirmations"][2]["accounting"].update(net_fee="20"),
            lambda r: r["confirmations"][0]["inclusion_block"].update(fee="10"),
            lambda r: r["confirmations"][1].update(child_count=2),
            lambda r: r["confirmations"][2]["input_records"].pop(),
            lambda r: r["confirmations"][2]["output_records"].pop(),
            lambda r: r["confirmations"][2]["contract_spends"].pop(),
            lambda r: r["confirmations"][0].update(exact_block_coins=False),
            lambda r: r["confirmations"][1].update(unaffected_inputs_unchanged=False),
            lambda r: r.update(funding_change_unchanged=False),
            lambda r: r.update(rejected_coin_unspent_after_controls=False),
            lambda r: r.update(all_confirmed_outputs_unspent=False),
            lambda r: r.update(active_mempool_empty=False),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(fault=index):
                result = evidence()
                mutate(result)
                with self.assertRaises(RuntimeError):
                    audit(result)


if __name__ == "__main__":
    unittest.main()
