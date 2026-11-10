"""RPC-shaped synthetic confirmation fixtures; no sockets, keys or Chia runtime."""
import copy
import unittest

from confirmation import name, observe_confirmation
from testnet_probe import GENESIS, ProbeError


class Fixture:
    def __init__(self):
        self.input = {"parent_coin_info": "11" * 32, "puzzle_hash": "22" * 32, "amount": 1000}
        self.spend = {"coin": self.input, "puzzle_reveal": "01", "solution": "80"}
        self.children = [{"parent_coin_info": name(self.input), "puzzle_hash": p * 32, "amount": n}
                         for p, n in [("33", 600), ("44", 390)]]
        self.peak = {"height": 102, "header_hash": "aa" * 32}
        self.block = {"height": 100, "header_hash": "bb" * 32}
        self.records = {name(self.input): self.record(self.input, 90, 100),
                        **{name(c): self.record(c, 100, 0) for c in self.children}}
        self.calls = []
        self.override = {}

    @staticmethod
    def record(c, created, used):
        return {"coin": c, "confirmed_block_index": created, "spent_block_index": used,
                "spent": bool(used), "coinbase": False, "timestamp": 1000}

    def call(self, route, request):
        self.calls.append((route, request))
        if route in self.override:
            return copy.deepcopy(self.override[route])
        if route == "get_version":
            return {"success": True, "version": "2.7.5"}
        if route == "get_network_info":
            return {"success": True, "network_name": "testnet11", "network_prefix": "txch", "genesis_challenge": GENESIS}
        if route == "get_blockchain_state":
            return {"success": True, "blockchain_state": {"sync": {"synced": True, "sync_mode": False}, "peak": copy.deepcopy(self.peak)}}
        if route == "get_coin_record_by_name":
            return {"success": True, "coin_record": copy.deepcopy(self.records[request["name"][2:]])}
        if route == "get_puzzle_and_solution":
            assert request == {"coin_id": "0x" + name(self.input), "height": 100}
            return {"success": True, "coin_solution": copy.deepcopy(self.spend)}
        if route == "get_block_record_by_height":
            assert request == {"height": 100}
            return {"success": True, "block_record": copy.deepcopy(self.block)}
        raise AssertionError("Unapproved route: " + route)

    def run(self, depth=3, anchor=None):
        return observe_confirmation(self.call, self.spend, self.children, depth, anchor)


class ConfirmationTests(unittest.TestCase):
    def test_confirmed_exact_spend_children_depth_and_read_only_routes(self):
        f = Fixture()
        result = f.run()
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["confirmations"], 3)
        self.assertEqual(result["confirmation_anchor"], {"input_id": name(f.input), **f.block})
        self.assertEqual(len(result["children"]), 2)
        self.assertFalse(result["chain_proof"])
        self.assertFalse(result["atomic_snapshot"])
        self.assertEqual(result["transactions_submitted"], 0)
        self.assertTrue(all(r.startswith("get_") for r, _ in f.calls))

    def test_inclusive_depth_boundary_and_exact_payment_single_child(self):
        f = Fixture()
        self.assertEqual(f.run(4)["status"], "confirming")
        f.peak["height"] = 103
        self.assertEqual(f.run(4)["status"], "confirmed")
        f.children = [f.children[0]]
        self.assertEqual(len(f.run()["children"]), 1)
        for depth in (0, True, 1.0, 10001):
            with self.subTest(depth=depth), self.assertRaises(ProbeError):
                f.run(depth)

    def test_unspent_never_implies_mempool_or_confirmation(self):
        f = Fixture()
        f.records[name(f.input)] = f.record(f.input, 90, 0)
        r = f.run()
        self.assertEqual(r["status"], "unspent")
        self.assertEqual(r["confirmations"], 0)
        self.assertIsNone(r["confirmation_anchor"])
        self.assertNotIn("get_puzzle_and_solution", [route for route, _ in f.calls])

    def test_wrong_solution_or_puzzle_is_conflicting_spend(self):
        for field in ("puzzle_reveal", "solution"):
            f = Fixture()
            changed = copy.deepcopy(f.spend)
            changed[field] = "02"
            f.override["get_puzzle_and_solution"] = {"success": True, "coin_solution": changed}
            self.assertEqual(f.run()["status"], "conflicting-spend")

    def test_reorg_replaced_anchor_or_shorter_chain(self):
        for short in (False, True):
            f = Fixture()
            anchor = f.run()["confirmation_anchor"]
            if short:
                f.peak["height"] = 99
            else:
                f.block["header_hash"] = "cc" * 32
            r = f.run(anchor=anchor)
            self.assertEqual(r["status"], "reorged")
            self.assertIsNone(r["confirmation_anchor"])
            self.assertEqual(r["confirmations"], 0)
            self.assertEqual(r["previous_anchor"], anchor)

    def test_prior_anchor_continuity_and_contradictions(self):
        f = Fixture()
        anchor = f.run()["confirmation_anchor"]
        self.assertEqual(f.run(anchor=anchor)["status"], "confirmed")
        f.records[name(f.input)] = f.record(f.input, 90, 0)
        with self.assertRaises(ProbeError):
            f.run(anchor=anchor)
        anchor["input_id"] = "ff" * 32
        with self.assertRaises(ProbeError):
            f.run(anchor=anchor)

    def test_changed_peak_invalidates_observation_even_after_valid_records(self):
        f = Fixture()
        def changing(route, request):
            reply = f.call(route, request)
            if route == "get_block_record_by_height":
                f.peak["header_hash"] = "dd" * 32
            return reply
        with self.assertRaises(ProbeError):
            observe_confirmation(changing, f.spend, f.children, 3)

    def test_wrong_network_version_and_unsynced_fail_before_coin_reads(self):
        cases = [("get_version", {"success": True, "version": "2.7.4"}),
                 ("get_network_info", {"success": True, "network_name": "mainnet", "network_prefix": "xch", "genesis_challenge": GENESIS}),
                 ("get_blockchain_state", {"success": True, "blockchain_state": {"sync": {"synced": False}, "peak": None}})]
        for route, value in cases:
            f = Fixture()
            f.override[route] = value
            with self.subTest(route=route), self.assertRaises(ProbeError):
                f.run()
            self.assertNotIn("get_coin_record_by_name", [r for r, _ in f.calls])

    def test_input_record_identity_types_and_heights(self):
        cases = [("spent", 1), ("spent_block_index", 0), ("spent_block_index", 103),
                 ("confirmed_block_index", 101), ("coinbase", 0), ("timestamp", -1),
                 ("coin", {"parent_coin_info": "ee" * 32, "puzzle_hash": "22" * 32, "amount": 1000})]
        for field, value in cases:
            f = Fixture()
            f.records[name(f.input)][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ProbeError):
                f.run()

    def test_children_must_match_identity_creation_height_and_not_rewards(self):
        for field, value in [("confirmed_block_index", 99), ("coinbase", True), ("coin", None)]:
            f = Fixture()
            f.records[name(f.children[0])][field] = value
            with self.subTest(field=field), self.assertRaises(ProbeError):
                f.run()
        # Subsequent spending of a child does not undo creation confirmation.
        f = Fixture()
        f.records[name(f.children[0])].update(spent=True, spent_block_index=101)
        result = f.run()
        self.assertEqual(result["status"], "confirmed")
        self.assertTrue(result["children"][0]["spent"])

    def test_missing_records_errors_malformed_spends_and_blocks_fail(self):
        cases = [("get_coin_record_by_name", {"success": True, "coin_record": None}),
                 ("get_coin_record_by_name", {"success": False, "structuredError": {"code": "COIN_RECORD_NOT_FOUND"}}),
                 ("get_puzzle_and_solution", {"success": True, "coin_solution": None}),
                 ("get_block_record_by_height", {"success": True, "block_record": {"height": 99, "header_hash": "bb" * 32}}),
                 ("get_block_record_by_height", {"success": False})]
        for route, value in cases:
            f = Fixture()
            f.override[route] = value
            with self.subTest(route=route, value=value), self.assertRaises(ProbeError):
                f.run()

    def test_expected_children_and_programs_fail_before_rpc(self):
        for variant in ("parent", "duplicate", "empty", "overspend", "program", "bool"):
            f = Fixture()
            if variant == "parent":
                f.children[0]["parent_coin_info"] = "ee" * 32
            elif variant == "duplicate":
                f.children = [f.children[0], f.children[0]]
            elif variant == "empty":
                f.children = []
            elif variant == "overspend":
                f.children[0]["amount"] = 1001
            elif variant == "program":
                f.spend["solution"] = "not hex"
            else:
                f.input["amount"] = True
            with self.subTest(variant=variant), self.assertRaises(ProbeError):
                f.run()
            self.assertEqual(f.calls, [])

    def test_rpc_hex_prefixes_normalize_without_changing_expected_bytes(self):
        f = Fixture()
        reply = copy.deepcopy(f.spend)
        reply["coin"]["parent_coin_info"] = "0x" + reply["coin"]["parent_coin_info"].upper()
        reply["puzzle_reveal"] = "0x01"
        reply["solution"] = "0x80"
        f.override["get_puzzle_and_solution"] = {"success": True, "coin_solution": reply}
        self.assertEqual(f.run()["status"], "confirmed")
        reply["coin"]["amount"] = 999
        with self.assertRaises(ProbeError):
            f.run()

    def test_transport_timeout_never_returns_confirmation(self):
        f = Fixture()
        def failing(route, request):
            if route == "get_block_record_by_height":
                raise TimeoutError("fixture timeout")
            return f.call(route, request)
        with self.assertRaises(TimeoutError):
            observe_confirmation(failing, f.spend, f.children, 3)


if __name__ == "__main__":
    unittest.main()
