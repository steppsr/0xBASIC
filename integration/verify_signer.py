"""Approved offline signer matrix using public fixtures only; no live node or user keys."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

import sign_fee
import signer_keyfile as storage
from owner_keys import no_network
from prepare_fee import ROOT, cli, digest, prepare
from testnet_probe import GENESIS, ProbeError, coin_id, require
from verify_signed_fee import verify_signed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    binary = parser.parse_args().binary.resolve()
    work = ROOT / ".work/testnet"
    work.mkdir(parents=True, exist_ok=True)
    native = sys.platform == "linux"
    destination = work / ("signer-linux.json" if native else "signer-windows.json")
    destination.unlink(missing_ok=True)
    sys.addaudithook(no_network)
    sys.path.insert(0, str(ROOT / "simulator"))
    from smoke import preflight
    preflight()
    from chia_rs import PrivateKey
    if native:
        import pwd
        temporary_parent = Path(pwd.getpwuid(os.getuid()).pw_dir)
    else:
        temporary_parent = work
    positives, negatives = [], []
    with ExitStack() as stack:
        base = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix=".0xbasic-signer-fixture-", dir=temporary_parent)))
        vault = base / ".local/share/0xbasic-signer"
        vault.mkdir(parents=True, mode=0o700)
        keyfile = vault / "fixture.key"
        material = [(1).to_bytes(32, "big")]
        if native:
            for directory in (base, base / ".local", vault.parent, vault):
                directory.chmod(0o700)
            stack.enter_context(patch.object(storage, "_home", return_value=base))
        else:
            stack.enter_context(patch.object(sign_fee, "_platform"))
        artifact = base / "artifact"
        cli(binary, "build", ROOT / "examples/payment-fee.bas", "--bindings", ROOT / "examples/payment-fee.bindings.json", "--out", artifact)
        manifest = artifact / "manifest.json"
        ph = json.loads(manifest.read_text())["puzzle"]["tree_hash"]
        peak = {"height": 3924000, "header_hash": "46" * 32, "synced": True, "sync_mode": False}
        parent = "45" * 32
        obs = {"schema_version": 1, "validation": "rpc-observation-only", "node_version": "2.7.5", "compiler_profile": "chia-clvm-0.19-strict-v2",
               "network": {"name": "testnet11", "prefix": "txch", "genesis_challenge": GENESIS},
               "before": peak, "after": dict(peak), "coin": {"name": coin_id(parent, ph, 1000), "parent_coin_info": parent,
               "puzzle_hash": ph, "amount": "1000", "confirmed_block_index": 1, "spent_block_index": 0, "spent": False,
               "coinbase": False, "timestamp": 1}, "atomic_snapshot": False, "spend_validated": False, "transactions_submitted": 0}
        op, sp, pp = [base / (name + ".json") for name in ("observation", "solution", "preparation")]
        output = base / "outputs/response.json"
        output.parent.mkdir()
        loaded = []
        real_loader = sign_fee.load_owner
        def loader(path, expected):
            loaded.append(expected)
            if native:
                return real_loader(path, expected)
            key = PrivateKey.from_bytes(material[0])
            require(bytes(key.get_g1()).hex() == expected, "Wrong fixture owner")
            return key
        stack.enter_context(patch.object(sign_fee, "load_owner", side_effect=loader))
        def reset(payment=600, fee=10):
            material[0] = (1).to_bytes(32, "big")
            if native:
                keyfile.write_bytes(storage.HEADER + material[0].hex().encode() + b"\n")
                keyfile.chmod(0o600)
            obs["observed_at"] = datetime.now(timezone.utc).isoformat()
            op.write_text(json.dumps(obs), encoding="utf-8")
            sp.write_text(json.dumps({"paymentAmount": str(payment), "feeAmount": str(fee)}), encoding="utf-8")
            pp.write_text(json.dumps(prepare(binary, manifest, op, sp, 20), sort_keys=True, indent=2), encoding="utf-8")
            loaded.clear()
            return digest(pp.read_bytes())
        def sign(approved):
            return sign_fee.sign(binary, manifest, op, sp, pp, keyfile, output, approved, 20)
        for label, payment, fee in (("partial", 600, 10), ("exact", 990, 10), ("zero-fee", 1000, 0)):
            approved = reset(payment, fee)
            reviewed = sign_fee.review(binary, manifest, op, sp, pp, 20)
            assert reviewed["preparation_sha256"] == approved and not loaded
            sign(approved)
            verified = verify_signed(binary, manifest, op, sp, pp, output, 20)
            assert verified["signature_verified"] and verified["transactions_submitted"] == 0 and len(loaded) == 1
            positives.append(label)
        def reject(label, action, before_key=True):
            output.write_text("stale success", encoding="utf-8")
            try:
                action()
            except (ProbeError, ValueError, RuntimeError, OSError):
                pass
            else:
                raise RuntimeError("Signer negative accepted: " + label)
            assert not output.exists() and not list(output.parent.iterdir()), label
            if before_key:
                assert not loaded, label
            negatives.append(label)
        approved = reset()
        reject("wrong-approval", lambda: sign("00" * 32))
        reset()
        reject("missing-approval", lambda: sign(None))
        approved = reset()
        pp.write_bytes(pp.read_bytes() + b"\n")
        reject("changed-preparation-bytes", lambda: sign(approved))
        approved = reset()
        sp.write_text(json.dumps({"paymentAmount": "600", "feeAmount": "11"}))
        reject("changed-solution", lambda: sign(approved))
        reset()
        changed = json.loads(pp.read_text()); changed["accounting"]["fee"] = "11"
        pp.write_text(json.dumps(changed))
        reject("approved-tampered-preparation", lambda: sign(digest(pp.read_bytes())))
        approved = reset()
        changed = json.loads(op.read_text()); changed["observed_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        op.write_text(json.dumps(changed))
        reject("stale-observation", lambda: sign(approved))
        approved = reset()
        changed = json.loads(op.read_text()); changed["network"]["genesis_challenge"] = "00" * 32
        op.write_text(json.dumps(changed))
        reject("wrong-domain", lambda: sign(approved))
        approved = reset()
        material[0] = (2).to_bytes(32, "big")
        if native:
            keyfile.write_bytes(storage.HEADER + material[0].hex().encode() + b"\n")
        reject("wrong-owner", lambda: sign(approved), False)
        approved = reset()
        with patch.object(sign_fee, "verify_signed", side_effect=ProbeError("fixture verification failure")):
            reject("independent-verifier-failure", lambda: sign(approved), False)
        approved = reset()
        def changed_after_load(path, expected):
            key = loader(path, expected)
            pp.write_bytes(pp.read_bytes() + b"\n")
            return key
        with patch.object(sign_fee, "load_owner", side_effect=changed_after_load):
            reject("preparation-changed-after-key-load", lambda: sign(approved), False)
        reset()
        command = [sys.executable, str(ROOT / "integration/sign_fee.py"), "--binary", str(binary), "--manifest", str(manifest),
                   "--observation", str(op), "--solution", str(sp), "--preparation", str(pp), "--max-fee", "20", "--review-only"]
        result = subprocess.run(command, capture_output=True, check=True, timeout=60)
        assert json.loads(result.stdout)["preparation_sha256"] == digest(pp.read_bytes())
        positives.append("review-cli")
    assert len(positives) == 4 and len(negatives) == 10
    report = {"schema_version": 1, "validation": "public-fixture-approved-offline-signing", "positive_cases": positives,
              "negative_cases": negatives, "native_key_loading": native, "user_keys_accessed": False,
              "transactions_submitted": 0, "resources_closed": True, "binary_sha256": digest(binary.read_bytes()),
              "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p.read_bytes()) for p in
                 (Path(__file__), ROOT / "integration/sign_fee.py", ROOT / "integration/verify_signed_fee.py",
                  ROOT / "integration/owner_keys.py", ROOT / "integration/signer_keyfile.py", ROOT / "integration/prepare_fee.py")}}
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PASS: 4 positive / 10 negative approved-signer cases; native key loading={native}; public fixtures only. Report: {destination}")


if __name__ == "__main__":
    main()
