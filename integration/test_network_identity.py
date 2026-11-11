"""Public defaults cannot inherit the isolated rehearsal's network identity."""
import copy
from dataclasses import FrozenInstanceError, replace
import unittest

from network_identity import PUBLIC_TESTNET, ISOLATED_REHEARSAL, validate
from testnet_probe import GENESIS, ProbeError, observe, _observe_for_identity
from confirmation import observe_confirmation, _confirm_for_identity, name
from prepare_fee import observation
from test_confirmation import Fixture


def isolated():
    f = Fixture()
    f.override["get_version"] = {"success": True, "version": ISOLATED_REHEARSAL.version}
    f.override["get_network_info"] = {"success": True, "network_name": ISOLATED_REHEARSAL.name,
        "network_prefix": ISOLATED_REHEARSAL.prefix, "genesis_challenge": ISOLATED_REHEARSAL.genesis}
    return f


class IdentityTests(unittest.TestCase):
    def test_only_reviewed_immutable_objects(self):
        self.assertEqual(PUBLIC_TESTNET.genesis, GENESIS)
        for identity in (PUBLIC_TESTNET, ISOLATED_REHEARSAL):
            validate(identity)
            with self.assertRaises(FrozenInstanceError):
                identity.version = "other"
            with self.assertRaises(ValueError):
                validate(replace(identity))
        with self.assertRaises(ValueError):
            validate({"network": "0xbasic-simulator"})

    def test_public_default_rejects_isolated_and_reverse(self):
        f = isolated()
        with self.assertRaises(ProbeError):
            observe(f.call)
        r = _observe_for_identity(f.call, ISOLATED_REHEARSAL)
        self.assertEqual(r["validation"], "isolated-rpc-observation-only")
        self.assertEqual(r["network"], ISOLATED_REHEARSAL.network())
        with self.assertRaises(ProbeError):
            _observe_for_identity(Fixture().call, ISOLATED_REHEARSAL)
        self.assertEqual(observe(Fixture().call)["validation"], "rpc-observation-only")

    def test_mixed_network_version_domain_prefix_rejected(self):
        for route, key, value in [("get_version", "version", "2.7.5"),
                ("get_network_info", "network_name", "testnet11"),
                ("get_network_info", "network_prefix", "xch"),
                ("get_network_info", "genesis_challenge", PUBLIC_TESTNET.genesis)]:
            f = isolated()
            f.override[route][key] = value
            with self.subTest(key=key), self.assertRaises(ProbeError):
                _observe_for_identity(f.call, ISOLATED_REHEARSAL)

    def test_same_confirmation_checks_separate_scope(self):
        f = isolated()
        with self.assertRaises(ProbeError):
            observe_confirmation(f.call, f.spend, f.children, 3)
        r = _confirm_for_identity(f.call, ISOLATED_REHEARSAL, f.spend, f.children, 3)
        self.assertEqual((r["status"], r["validation"]), ("confirmed", "isolated-rpc-confirmation-observation-only"))
        self.assertFalse(r["chain_proof"])
        self.assertEqual(r["transactions_submitted"], 0)
        f.records[name(f.children[0])]["confirmed_block_index"] = 99
        with self.assertRaises(ProbeError):
            _confirm_for_identity(f.call, ISOLATED_REHEARSAL, f.spend, f.children, 3)

    def test_public_preparation_rejects_isolated_observation(self):
        f = isolated()
        f.records[name(f.input)] = f.record(f.input, 90, 0)
        r = _observe_for_identity(f.call, ISOLATED_REHEARSAL, name(f.input))
        with self.assertRaises(ProbeError):
            observation(r)
        renamed = copy.deepcopy(r)
        renamed["validation"] = "rpc-observation-only"
        with self.assertRaises(ProbeError):
            observation(renamed)


if __name__ == "__main__":
    unittest.main()
