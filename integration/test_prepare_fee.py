"""Offline preparation input/publication checks without importing Chia."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import prepare_fee as prep
from testnet_probe import ProbeError


class PreparationInputTests(unittest.TestCase):
    def test_canonical_amounts_and_json(self):
        for value in [True, 10, "01", "+1", "-1", "1.0", str(2**64)]:
            with self.subTest(value=value), self.assertRaises(ProbeError):
                prep.amount(value)
        self.assertEqual(prep.amount(str(2**64-1)), 2**64-1)
        for data in [b'{"a":1,"a":2}', b'{"a":NaN}', b'null', b'[]', b'\xff']:
            with self.assertRaises(ProbeError):
                prep.read_json(data)

    def test_observation_schema_and_freshness(self):
        now = datetime.now(timezone.utc)
        peak = {"height": 10, "header_hash": "33"*32, "synced": True, "sync_mode": False}
        coin = {"name": prep.coin_id("11"*32, "22"*32, 1000), "parent_coin_info": "11"*32, "puzzle_hash": "22"*32,
                "amount": "1000", "spent": False, "spent_block_index": 0, "confirmed_block_index": 1,
                "coinbase": False, "timestamp": 1}
        value = {"schema_version": 1, "validation": "rpc-observation-only", "node_version": "2.7.5",
                 "compiler_profile": prep.PROFILE, "atomic_snapshot": False, "spend_validated": False,
                 "transactions_submitted": 0, "network": {"name": "testnet11", "prefix": "txch", "genesis_challenge": prep.GENESIS},
                 "observed_at": now.isoformat(), "before": peak, "after": peak.copy(), "coin": coin}
        self.assertEqual(prep.observation(value, now=now), (coin, 10))
        for field, wrong in [("schema_version", True), ("transactions_submitted", False),
                             ("observed_at", (now-timedelta(seconds=301)).isoformat()),
                             ("observed_at", (now+timedelta(seconds=1)).isoformat())]:
            with self.subTest(field=field), self.assertRaises(ProbeError):
                prep.observation({**value, field: wrong}, now=now)

    def test_output_cannot_replace_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            solution = Path(directory) / "solution.json"
            solution.write_text("keep")
            args = ["prepare", "--binary", "binary", "--manifest", "manifest.json", "--observation", "observation.json",
                    "--solution", str(solution), "--max-fee", "10", "--out", str(solution)]
            with patch.object(sys, "argv", args), patch.object(sys, "stderr"):
                self.assertEqual(prep.main(), 1)
            self.assertEqual(solution.read_text(), "keep")

    def test_failed_runtime_invalidates_previous_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "prepared.json"
            out.write_text('{"old":true}')
            args = ["prepare", "--binary", "binary", "--manifest", "manifest.json", "--observation", "observation.json",
                    "--solution", "solution.json", "--max-fee", "10", "--out", str(out)]
            with patch.object(sys, "argv", args), patch.object(prep, "prepare", side_effect=RuntimeError("failure")), patch.object(sys, "stderr"):
                self.assertEqual(prep.main(), 1)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
