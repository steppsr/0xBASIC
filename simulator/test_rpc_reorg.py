"""Reject inconsistent real-reorg lifecycle reports without importing Chia."""
import copy
import unittest

from rpc_reorg import audit


def evidence():
    anchor = {"height": 10, "header_hash": "ab" * 32}
    return {"validation": "isolated-rpc-reorg-observation", "transactions_submitted": 0, "required_depth": 3,
            "before": {"status": "confirming", "confirmations": 2, "anchor": anchor, "peak": {"height": 11}},
            "deeper": {"status": "confirmed", "confirmations": 3, "anchor": copy.deepcopy(anchor), "peak": {"height": 12}},
            "after": {"status": "reorged", "confirmations": 0, "old_anchor": copy.deepcopy(anchor),
                      "replacement_hash": "cd" * 32, "peak": {"height": 15},
                      "restored_inputs": [{"spent": False, "spent_block_index": 0} for _ in range(5)],
                      "missing_outputs": [f"{i:064x}" for i in range(8)]},
            "funding_preserved": True, "surrounding_peak_unchanged": True}


class ReorgEvidenceTests(unittest.TestCase):
    def test_complete_transition(self):
        audit(evidence())

    def test_stale_confirmed_or_incomplete_rollback_rejected(self):
        mutations = [lambda r: r.update(transactions_submitted=1), lambda r: r.update(required_depth=4),
            lambda r: r["deeper"]["anchor"].update(header_hash="ef" * 32),
            lambda r: r["after"].update(status="confirmed"), lambda r: r["after"].update(confirmations=3),
            lambda r: r["after"].update(replacement_hash="ab" * 32),
            lambda r: r["after"]["peak"].update(height=12),
            lambda r: r["after"]["restored_inputs"][0].update(spent=True),
            lambda r: r["after"]["missing_outputs"].pop(),
            lambda r: r.update(funding_preserved=False), lambda r: r.update(surrounding_peak_unchanged=False)]
        for index, mutate in enumerate(mutations):
            data = evidence()
            mutate(data)
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                audit(data)


if __name__ == "__main__":
    unittest.main()
