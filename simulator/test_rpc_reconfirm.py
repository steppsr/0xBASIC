"""Reconfirmation evidence cannot replace original bundles or claim early success."""
import copy
import unittest
from rpc_reconfirm import audit


def evidence(ids, reorg_height):
    height = reorg_height + 1
    confirming = {"status": "confirming", "confirmations": 1, "height": height, "block_hash": "aa" * 32,
                  "peak": {"height": height}, "exact_spends": 5, "exact_outputs": 8}
    confirmed = {**confirming, "status": "confirmed", "confirmations": 2, "peak": {"height": height + 1}}
    return {"bundle_ids": ids, "transactions_submitted": 3, "signatures_created": 0, "unchanged_bundles": True,
            "required_depth": 2, "pending": {"status": "timed-out", "reason": "attempt-limit", "attempts": 2,
                "last_observation": {"status": "unspent"}}, "confirming": confirming,
            "confirmed": {"status": "confirmed", "last_observation": confirmed, "transactions_submitted": 0},
            "block_fee": "51", "mempool_empty_after": True, "funding_change_preserved": True}


class ReconfirmationTests(unittest.TestCase):
    def test_complete_evidence(self):
        fee = {"confirmations": [{"bundle_id": str(i)} for i in range(3)]}
        audit(evidence([str(i) for i in range(3)], 20), fee, {"after": {"peak": {"height": 20}}})

    def test_replacements_and_stale_success_rejected(self):
        fee = {"confirmations": [{"bundle_id": str(i)} for i in range(3)]}
        changes = [lambda r: r["bundle_ids"].__setitem__(0, "replacement"), lambda r: r.update(signatures_created=1),
            lambda r: r["pending"].update(status="confirmed"), lambda r: r["confirming"].update(confirmations=2),
            lambda r: r["confirmed"]["last_observation"].update(height=20),
            lambda r: r["confirmed"]["last_observation"].update(block_hash="bb" * 32),
            lambda r: r.update(block_fee="50"), lambda r: r.update(funding_change_preserved=False)]
        for index, change in enumerate(changes):
            r = copy.deepcopy(evidence([str(i) for i in range(3)], 20))
            change(r)
            with self.subTest(case=index), self.assertRaises(RuntimeError):
                audit(r, fee, {"after": {"peak": {"height": 20}}})


if __name__ == "__main__":
    unittest.main()
