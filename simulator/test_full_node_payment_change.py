"""Full-node payment/change evidence coverage without importing Chia."""
import unittest

from full_node_payment_change import audit


def evidence():
    return {"rejections": [{"scenario": name, "status": "FAILED", "error": error, "state_unchanged_after_farm": True}
            for name, error in [("missing-signature", "BAD_AGGREGATE_SIGNATURE"),
                                ("changed-payment-stale-signature", "BAD_AGGREGATE_SIGNATURE"),
                                ("wrong-coin-amount", "ASSERT_MY_AMOUNT_FAILED")]],
            "confirmations": [{"scenario": name, "status": "SUCCESS", "child_count": count,
                               "input_spent": True, "exact_block_coins": True, "all_outputs_unspent": True}
                              for name, count in [("partial", 2), ("exact", 1)]],
            "rejected_coin_unspent_after_controls": True, "funding_change_unchanged": True, "active_mempool_empty": True}


class FullNodePaymentChangeTests(unittest.TestCase):
    def test_complete_evidence(self):
        audit(evidence())

    def test_missing_or_incorrect_evidence_rejected(self):
        for fault in ("missing-rejection", "wrong-error", "missing-control", "extra-child", "partial-count", "state", "funding", "block"):
            with self.subTest(fault=fault):
                result = evidence()
                if fault == "missing-rejection":
                    result["rejections"].pop()
                elif fault == "wrong-error":
                    result["rejections"][2]["error"] = "BAD_AGGREGATE_SIGNATURE"
                elif fault == "missing-control":
                    result["confirmations"].pop()
                elif fault == "extra-child":
                    result["confirmations"][1]["child_count"] = 2
                elif fault == "partial-count":
                    result["confirmations"][0]["child_count"] = 1
                elif fault == "state":
                    result["rejected_coin_unspent_after_controls"] = False
                elif fault == "funding":
                    result["funding_change_unchanged"] = False
                else:
                    result["confirmations"][0]["exact_block_coins"] = False
                with self.assertRaises(RuntimeError):
                    audit(result)


if __name__ == "__main__":
    unittest.main()
