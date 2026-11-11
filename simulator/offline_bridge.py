"""Private offline rehearsal worker: no key loading, node or socket operations."""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile

from isolated_preparation import prepare_isolated, verify_isolated
from prepare_fee import prepare, read_json, digest
from verify_signed_fee import verify_signed
from testnet_probe import ProbeError, require, GENESIS

NEGATIVES = ["public-preparation", "public-signature-verifier", "changed-response-message", "missing-signature",
             "fee-budget", "wrong-observation-domain", "changed-constants-evidence"]


def no_network(event, args):
    if event in {"socket.connect", "socket.bind"}:
        raise RuntimeError("Offline bridge cannot use sockets")


def run(binary, manifest, work):
    op, sp = work / "observation.json", work / "solution.json"
    pp, rp = work / "preparation.json", work / "signature-response.json"
    prepared = prepare_isolated(binary, manifest, op, sp, 20)
    from chia_rs import SpendBundle, G2Element
    bundle = SpendBundle.from_json_dict(read_json((work / "original-bundle.json").read_bytes()))
    require(len(bundle.coin_spends) == 1, "Bridge requires a single-input fee control")
    pp.write_text(json.dumps(prepared, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    original_preparation = pp.read_bytes()
    request = prepared["signing_request"]
    response = {"schema_version": 1, "scheme": "AugSchemeMPL", "preparation_sha256": digest(original_preparation),
                "public_key": request["public_key"], "message": request["message"], "signature": bytes(bundle.aggregated_signature).hex()}
    rp.write_text(json.dumps(response), encoding="utf-8")
    original_response, original_observation = rp.read_bytes(), op.read_bytes()
    rejected = []
    def reject(name, operation):
        try:
            operation()
        except ProbeError:
            rejected.append(name)
        else:
            raise RuntimeError("Bridge negative unexpectedly accepted: " + name)
    def verify():
        return verify_isolated(binary, manifest, op, sp, pp, rp, 20)
    reject("public-preparation", lambda: prepare(binary, manifest, op, sp, 20))
    reject("public-signature-verifier", lambda: verify_signed(binary, manifest, op, sp, pp, rp, 20))
    changed = {**response, "message": response["message"] + "00"}
    rp.write_text(json.dumps(changed), encoding="utf-8")
    reject("changed-response-message", verify)
    rp.write_text(json.dumps({**response, "signature": bytes(G2Element()).hex()}), encoding="utf-8")
    reject("missing-signature", verify)
    rp.write_bytes(original_response)
    reject("fee-budget", lambda: prepare_isolated(binary, manifest, op, sp, int(prepared["accounting"]["fee"]) - 1))
    changed = read_json(original_observation)
    changed["network"]["genesis_challenge"] = GENESIS
    op.write_text(json.dumps(changed), encoding="utf-8")
    reject("wrong-observation-domain", verify)
    op.write_bytes(original_observation)
    changed = copy.deepcopy(prepared)
    changed["runtime"]["consensus_constants_sha256"] = "00" * 32
    pp.write_text(json.dumps(changed), encoding="utf-8")
    reject("changed-constants-evidence", verify)
    pp.write_bytes(original_preparation)
    verified = verify()
    require(SpendBundle.from_json_dict(verified["spend_bundle"]) == bundle, "Shared verifier changed the original bundle")
    require(rejected == NEGATIVES, "Missing offline bridge controls")
    return {"verified": verified, "negative_cases": rejected, "original_bundle_equal": True,
            "private_keys_loaded": False, "sockets_allowed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("binary", "manifest", "work"):
        parser.add_argument("--" + arg, required=True, type=Path)
    args = parser.parse_args()
    from full_node_smoke import contained
    work = contained(args.work)
    output = work / "bridge-result.json"
    require(not output.is_symlink() and output.resolve() not in (args.binary.resolve(), args.manifest.resolve()), "Bridge output alias")
    output.unlink(missing_ok=True)
    sys.addaudithook(no_network)
    result = run(args.binary.resolve(), args.manifest.resolve(), work)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=work, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, sort_keys=True, indent=2)
            handle.write("\n")
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
