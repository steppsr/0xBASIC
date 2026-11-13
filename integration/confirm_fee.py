"""One read-only confirmation observation after independent detached-spend verification."""
import argparse
import http.client
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile

from confirmation import observe_confirmation, name, spend
from confirmation_transport import ConfirmationTransport
from prepare_fee import FILES, SOURCE
from testnet_probe import ProbeError, require, uint, hex32
from verify_signed_fee import verify_signed


def confirm(call, binary, manifest, observation, solution, preparation, response, max_fee, depth,
            max_age=300, previous_height=None, previous_hash=None):
    require(type(depth) is int and 1 <= depth <= 10000, "Confirmation depth must be 1..10000")
    require((previous_height is None) == (previous_hash is None), "Prior height and hash must be supplied together")
    if previous_height is not None:
        previous_height, previous_hash = uint(previous_height, 32), hex32(previous_hash)
    # Never accept a saved report's signature_verified flag as authority.
    verified = verify_signed(binary, manifest, observation, solution, preparation, response, max_fee, max_age)
    require(len(verified["spend_bundle"]["coin_spends"]) == 1, "Expected one independently verified spend")
    expected = spend(verified["spend_bundle"]["coin_spends"][0])
    children = [{"parent_coin_info": c["parent_coin_info"], "puzzle_hash": c["puzzle_hash"], "amount": int(c["amount"])}
                for c in verified["preparation"]["expected_outputs"]]
    anchor = None if previous_height is None else {"input_id": name(expected["coin"]), "height": previous_height, "header_hash": previous_hash}
    observed = observe_confirmation(call, expected, children, depth, anchor)
    return {"schema_version": 1, "validation": "verified-spend-rpc-observation-only",
            "expected_bundle_id": verified["bundle_id"], "preparation_sha256": verified["preparation_sha256"],
            "signature_response_sha256": verified["signature_response_sha256"], "signature_verified_offline": True,
            "observation": observed, "chain_proof": False, "transactions_submitted": 0}


def _report_path(report, protected):
    report = Path(report)
    require(not report.is_symlink(), "Report is a symlink")
    for path in protected:
        path = Path(path)
        require(report.resolve() != path.resolve() and not (report.exists() and path.exists() and report.samefile(path)),
                "Report overlaps input or credentials")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("binary", "manifest", "observation", "solution", "preparation", "signature-response",
                   "ca-cert", "client-cert", "client-key", "report"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--max-fee", type=int, required=True)
    parser.add_argument("--depth", type=int, required=True)
    parser.add_argument("--max-observation-age", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--previous-height", type=int)
    parser.add_argument("--previous-header-hash")
    args = parser.parse_args()
    temporary = None
    try:
        protected = [args.binary, args.observation, args.solution, args.preparation, args.signature_response,
                     args.ca_cert, args.client_cert, args.client_key, SOURCE, *[args.manifest.parent / n for n in FILES]]
        report = _report_path(args.report, protected)
        report.unlink(missing_ok=True)
        client = ConfirmationTransport(args.endpoint, args.ca_cert, args.client_cert, args.client_key, args.timeout)
        result = confirm(client.call, args.binary, args.manifest, args.observation, args.solution, args.preparation,
                         args.signature_response, args.max_fee, args.depth, args.max_observation_age,
                         args.previous_height, args.previous_header_hash)
        report.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=report.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, sort_keys=True, indent=2)
            handle.write("\n")
        temporary.replace(report)
        status = result["observation"]["status"]
        print(f"OBSERVED: {status}; authenticated RPC observation, not chain proof; no submission")
        return 0 if status == "confirmed" else 3
    except (ProbeError, OSError, ssl.SSLError, http.client.HTTPException, ValueError, RuntimeError,
            KeyError, TypeError, ImportError, subprocess.SubprocessError):
        print("FAIL: signed-input verification or confirmation observation failed", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
