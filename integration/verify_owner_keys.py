"""Pinned-runtime owner-key matrix; deterministic PUBLIC fixtures, no user keys."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import owner_keys
import signer_keyfile as storage

ROOT = Path(__file__).resolve().parents[1]


def main():
    work = ROOT / ".work/testnet"
    work.mkdir(parents=True, exist_ok=True)
    destination = work / ("owner-keys-windows.json" if sys.platform == "win32" else "owner-keys-linux.json")
    destination.unlink(missing_ok=True)
    sys.addaudithook(owner_keys.no_network)
    runtime = owner_keys._runtime()
    AugSchemeMPL, PrivateKey, _ = runtime
    material = (1).to_bytes(32, "big")
    public = bytes(PrivateKey.from_bytes(material).get_g1()).hex()
    rejected = []
    for label, raw in (("zero", bytes(32)), ("out-of-range", b"\xff" * 32), ("short", b"\x01"), ("long", b"\x01" * 33)):
        try:
            owner_keys._validated(raw, runtime)
        except storage.KeyFileError:
            rejected.append(label)
        else:
            raise RuntimeError("Invalid scalar accepted")
    # Portable crypto layer only; actual Linux filesystem tests remain separate.
    with patch.object(storage, "_platform"), patch.object(owner_keys, "_runtime", return_value=runtime), \
            patch.object(storage, "read_test_owner", return_value=material):
        loaded = owner_keys.load_owner(Path("fixture.key"), public)
        assert bytes(loaded) == material
        message = b"0xbasic public owner-key fixture"
        assert AugSchemeMPL.verify(loaded.get_g1(), message, AugSchemeMPL.sign(loaded, message))
        for label, expected in (("wrong-owner", bytes(PrivateKey.from_bytes((2).to_bytes(32, "big")).get_g1()).hex()),
                                 ("noncanonical-owner", public.upper())):
            try:
                owner_keys.load_owner(Path("fixture.key"), expected)
            except storage.KeyFileError:
                rejected.append(label)
            else:
                raise RuntimeError("Invalid owner accepted")
    # Test key_gen invocation with public deterministic seed, never real entropy.
    with patch.object(storage, "_platform"), patch.object(owner_keys, "_runtime", return_value=runtime), \
            patch.object(owner_keys.os, "urandom", return_value=b"public fixture seed for keygen!!".ljust(32, b"!")) as entropy, \
            patch.object(storage, "_create_test_owner") as created:
        result = owner_keys.create_owner(Path("fixture.key"))
        entropy.assert_called_once_with(32)
        saved = created.call_args.args[1]
        assert result == {"schema_version": 1, "purpose": "test-only-contract-owner", "scheme": "AugSchemeMPL",
                          "public_key": bytes(PrivateKey.from_bytes(saved).get_g1()).hex()}
        assert saved.hex() not in json.dumps(result)
    native = False
    if sys.platform == "linux":
        import pwd
        with tempfile.TemporaryDirectory(prefix=".0xbasic-owner-fixture-", dir=pwd.getpwuid(os.getuid()).pw_dir) as temporary:
            home = Path(temporary)
            vault = home / ".local/share/0xbasic-signer"
            vault.mkdir(parents=True, mode=0o700)
            for directory in (home, home / ".local", vault.parent, vault):
                directory.chmod(0o700)
            target = vault / "public-fixture.key"
            with patch.object(storage, "_home", return_value=home), patch.object(owner_keys.os, "urandom", return_value=b"\x01" * 32):
                result = owner_keys.create_owner(target)
                key = owner_keys.load_owner(target, result["public_key"])
                assert bytes(key) == storage.read_test_owner(target)
            native = True
    assert len(rejected) == 6
    report = {"schema_version": 1, "validation": "public-fixture-owner-key-validation", "negative_cases": rejected,
              "native_storage_roundtrip": native, "user_keys_accessed": False, "resources_closed": True,
              "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (Path(__file__), ROOT / "integration/owner_keys.py", ROOT / "integration/signer_keyfile.py", ROOT / "simulator/smoke.py")}}
    destination.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: owner scalar/creation matrix, 6 rejections; native storage roundtrip={native}; public fixtures only. Report: {destination}")


if __name__ == "__main__":
    main()
