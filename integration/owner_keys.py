"""Explicit offline test-owner key creation; public-key output only, no signing."""
import argparse
import json
import os
from pathlib import Path
import sys

import signer_keyfile as storage


def _runtime():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "simulator"))
    from smoke import preflight
    preflight()
    from chia_rs import AugSchemeMPL, PrivateKey, G1Element
    return AugSchemeMPL, PrivateKey, G1Element


def _validated(material, runtime):
    _, PrivateKey, G1Element = runtime
    storage.require(type(material) is bytes and len(material) == 32 and any(material))
    try:
        key = PrivateKey.from_bytes(material)
        storage.require(bytes(key) == material and key.get_g1() != G1Element())
        return key
    except (ValueError, RuntimeError):
        raise storage.KeyFileError("Invalid test-owner scalar") from None


def load_owner(path, expected_public_key):
    """Require an explicit canonical owner before returning any signing key."""
    storage._platform()
    import re
    storage.require(type(expected_public_key) is str and re.fullmatch("[0-9a-f]{96}", expected_public_key) is not None)
    runtime = _runtime()
    key = _validated(storage.read_test_owner(path), runtime)
    storage.require(bytes(key.get_g1()).hex() == expected_public_key)
    return key


def create_owner(path):
    storage._platform()
    runtime = _runtime()
    # No seed/key import or deterministic generation option is exposed.
    key = _validated(bytes(runtime[0].key_gen(os.urandom(32))), runtime)
    storage._create_test_owner(path, bytes(key))
    return {"schema_version": 1, "purpose": "test-only-contract-owner", "scheme": "AugSchemeMPL",
            "public_key": bytes(key.get_g1()).hex()}


def no_network(event, args):
    if event in {"socket.connect", "socket.bind"}:
        raise RuntimeError("Offline key tool cannot use sockets")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    sys.addaudithook(no_network)
    try:
        result = create_owner(args.key_file)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, KeyError, TypeError, AttributeError):
        print("FAIL: owner key creation failed; any existing file is preserved. Inspect before retrying.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
