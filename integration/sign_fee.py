"""Review a public-testnet preparation, then explicitly approve its digest for offline signing."""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import subprocess

from prepare_fee import FILES, SOURCE, digest
from testnet_probe import require, ProbeError
from verify_signed_fee import revalidate_preparation, verify_signed
from owner_keys import load_owner, no_network
from signer_keyfile import _platform


def review(binary, manifest, observation, solution, preparation, max_fee, max_age=300):
    raw, prepared = revalidate_preparation(binary, manifest, observation, solution, preparation, max_fee, max_age)
    return {"schema_version": 1, "validation": "offline-signing-review-only", "preparation_sha256": digest(raw),
            "preparation": prepared, "signature_created": False, "transactions_submitted": 0}


def _output(out, key_file, protected):
    out, key_file = Path(out), Path(key_file)
    require(not out.is_symlink() and not out.resolve().is_relative_to(key_file.parent.resolve()), "Output overlaps key directory")
    for path in [key_file, *protected]:
        path = Path(path)
        require(out.resolve() != path.resolve() and not (out.exists() and path.exists() and out.samefile(path)), "Output overlaps input")
    return out


def sign(binary, manifest, observation, solution, preparation, key_file, out, approved, max_fee, max_age=300):
    _platform()
    protected = [binary, observation, solution, preparation, SOURCE, *[Path(manifest).parent / name for name in FILES]]
    out = _output(out, key_file, protected)
    out.unlink(missing_ok=True)
    temporary = None
    try:
        require(type(approved) is str and re.fullmatch("[0-9a-f]{64}", approved) is not None, "Explicit preparation digest required")
        raw, prepared = revalidate_preparation(binary, manifest, observation, solution, preparation, max_fee, max_age)
        require(digest(raw) == approved, "Approved preparation changed")
        request = prepared["signing_request"]
        # Nothing opens a key until the complete preparation and digest pass.
        key = load_owner(key_file, request["public_key"])
        from chia_rs import AugSchemeMPL
        signature = AugSchemeMPL.sign(key, bytes.fromhex(request["message"]))
        response = {"schema_version": 1, "scheme": "AugSchemeMPL", "preparation_sha256": approved,
                    "public_key": request["public_key"], "message": request["message"], "signature": bytes(signature).hex()}
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(response, handle, sort_keys=True, indent=2)
            handle.write("\n")
        verified = verify_signed(binary, manifest, observation, solution, preparation, temporary, max_fee, max_age)
        require(verified["preparation_sha256"] == approved and verified["signature_verified"] is True, "Independent verification failed")
        temporary.replace(out)
        return response
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "manifest", "observation", "solution", "preparation"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--max-fee", type=int, required=True)
    parser.add_argument("--max-observation-age", type=int, default=300)
    parser.add_argument("--review-only", action="store_true")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--approve-preparation-sha256")
    args = parser.parse_args()
    if args.review_only:
        if any(x is not None for x in (args.key_file, args.out, args.approve_preparation_sha256)):
            parser.error("Review mode accepts no key, output or approval arguments")
    elif any(x is None for x in (args.key_file, args.out, args.approve_preparation_sha256)):
        parser.error("Signing requires explicit key-file, out and approve-preparation-sha256")
    sys.addaudithook(no_network)
    try:
        inputs = (args.binary, args.manifest, args.observation, args.solution, args.preparation)
        if args.review_only:
            print(json.dumps(review(*inputs, args.max_fee, args.max_observation_age), indent=2, sort_keys=True))
        else:
            sign(*inputs, args.key_file, args.out, args.approve_preparation_sha256, args.max_fee, args.max_observation_age)
            print("PASS: approved preparation signed and independently verified offline; no submission")
        return 0
    except (ProbeError, RuntimeError, OSError, ValueError, KeyError, TypeError, ImportError, subprocess.SubprocessError):
        print("FAIL: preparation review or approved offline signing failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
