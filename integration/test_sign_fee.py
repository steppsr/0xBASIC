"""Approval ordering and publication boundaries without private keys or BLS runtime."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import sign_fee
from testnet_probe import ProbeError


class SignerBoundaryTests(unittest.TestCase):
    def test_review_never_loads_key(self):
        with patch.object(sign_fee, "revalidate_preparation", return_value=(b"review", {"full": "preparation"})), \
                patch.object(sign_fee, "load_owner") as load:
            r = sign_fee.review(None, None, None, None, None, 20)
        self.assertEqual(r["preparation_sha256"], sign_fee.digest(b"review"))
        self.assertEqual(r["preparation"], {"full": "preparation"})
        self.assertFalse(r["signature_created"])
        load.assert_not_called()

    def test_digest_rejected_before_key_and_stale_success_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            out = root / "response.json"
            for approval in (None, "bad", "00" * 32):
                out.write_text("old success")
                with patch.object(sign_fee, "_platform"), patch.object(sign_fee, "revalidate_preparation", return_value=(b"review", {})), \
                        patch.object(sign_fee, "load_owner") as load:
                    with self.assertRaises(ProbeError):
                        sign_fee.sign(root / "binary", root / "artifact/manifest.json", root / "obs", root / "solution", root / "prep",
                                      root / "vault/owner.key", out, approval, 20)
                    load.assert_not_called()
                self.assertFalse(out.exists())

    def test_invalid_preparation_never_opens_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(sign_fee, "_platform"), patch.object(sign_fee, "revalidate_preparation", side_effect=ProbeError("bad")), \
                    patch.object(sign_fee, "load_owner") as load:
                with self.assertRaises(ProbeError):
                    sign_fee.sign(root / "bin", root / "manifest.json", root / "obs", root / "sol", root / "prep",
                                  root / "vault/key.key", root / "out", "00" * 32, 20)
                load.assert_not_called()

    def test_output_aliases_and_key_directory_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.write_text("keep")
            for out in (source, root / "vault/report.json"):
                with self.assertRaises(ProbeError):
                    sign_fee._output(out, root / "vault/key.key", [source])
            alias = root / "hardlink"
            os.link(source, alias)
            with self.assertRaises(ProbeError):
                sign_fee._output(alias, root / "vault/key.key", [source])
            self.assertEqual(source.read_text(), "keep")

    def test_platform_refusal_before_side_effects(self):
        with patch.object(sign_fee, "_platform", side_effect=ValueError("unsupported")), patch.object(sign_fee, "_output") as output:
            with self.assertRaises(ValueError):
                sign_fee.sign(None, None, None, None, None, None, None, None, 20)
            output.assert_not_called()

    def test_cli_requires_explicit_mode_and_approval(self):
        common = ["sign_fee", "--binary", "bin", "--manifest", "manifest.json", "--observation", "obs",
                  "--solution", "sol", "--preparation", "prep", "--max-fee", "20"]
        for extra in ([], ["--review-only", "--key-file", "key"], ["--review-only", "--approve-preparation-sha256", "00" * 32]):
            with patch.object(sys, "argv", common + extra), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(sign_fee, "review") as review, patch.object(sign_fee, "sign") as sign:
                with self.assertRaises(SystemExit) as caught:
                    sign_fee.main()
                self.assertEqual(caught.exception.code, 2)
                review.assert_not_called()
                sign.assert_not_called()


if __name__ == "__main__":
    unittest.main()
