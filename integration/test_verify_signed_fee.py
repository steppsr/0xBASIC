"""Detached response and publication checks without a signing runtime."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import verify_signed_fee as signed
from testnet_probe import ProbeError


class DetachedSignatureInputTests(unittest.TestCase):
    def test_response_contract(self):
        r = {"schema_version": 1, "scheme": "AugSchemeMPL", "preparation_sha256": "ab"*32,
             "public_key": "cd"*48, "message": "ef"*96, "signature": "ab"*96}
        self.assertEqual(signed.response_fields(r, "ab"*32, "cd"*48, "ef"*96), bytes.fromhex("ab"*96))
        for field, value in [("schema_version", True), ("scheme", "BasicSchemeMPL"), ("preparation_sha256", "00"*32),
                             ("public_key", "00"*48), ("message", "00"*96), ("signature", "AB"*96),
                             ("signature", "0x"+"ab"*96), ("signature", "ab")]:
            with self.subTest(field=field), self.assertRaises(ProbeError):
                signed.response_fields({**r, field: value}, "ab"*32, "cd"*48, "ef"*96)
        with self.assertRaises(ProbeError):
            signed.response_fields({**r, "extra": 0}, "ab"*32, "cd"*48, "ef"*96)

    def test_comparison_is_type_exact(self):
        self.assertNotEqual(signed.canonical({"value": False}), signed.canonical({"value": 0}))
        self.assertNotEqual(signed.canonical({"value": 1}), signed.canonical({"value": 1.0}))
        self.assertEqual(signed.canonical({"a": 1, "b": 2}), signed.canonical({"b": 2, "a": 1}))

    def arguments(self, out, prep="preparation.json"):
        return ["signed", "--binary", "binary", "--manifest", "manifest.json", "--observation", "observation.json",
                "--solution", "solution.json", "--preparation", str(prep), "--signature-response", "response.json",
                "--max-fee", "20", "--out", str(out)]

    def test_failed_signature_invalidates_old_success(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "signed.json"
            out.write_text('{"old_success":true}')
            with patch.object(sys, "argv", self.arguments(out)), patch.object(signed, "verify_signed", side_effect=ProbeError("bad signature")), patch.object(sys, "stderr"):
                self.assertEqual(signed.main(), 1)
            self.assertFalse(out.exists())

    def test_output_does_not_replace_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "preparation.json"
            out.write_text("original")
            with patch.object(sys, "argv", self.arguments(out, out)), patch.object(sys, "stderr"):
                self.assertEqual(signed.main(), 1)
            self.assertEqual(out.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
