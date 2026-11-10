"""TN-3a synthetic detached-signature matrix, with public test keys only and no network."""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from prepare_fee import ROOT, cli, digest, prepare
from testnet_probe import GENESIS, ProbeError, coin_id
from verify_preparation import no_network
from verify_signed_fee import verify_signed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    binary = parser.parse_args().binary.resolve()
    work = ROOT / ".work/testnet"
    work.mkdir(parents=True, exist_ok=True)
    destination = work / ("signing-windows.json" if os.name == "nt" else "signing-linux.json")
    destination.unlink(missing_ok=True)
    sys.addaudithook(no_network)
    sys.path.insert(0, str(ROOT / "simulator"))
    from smoke import preflight
    preflight()
    from chia_rs import AugSchemeMPL, PrivateKey, G2Element, SpendBundle
    key = PrivateKey.from_bytes((1).to_bytes(32, "big"))  # Public fixture scalar, never user key material.
    other_key = PrivateKey.from_bytes((2).to_bytes(32, "big"))
    positives, negatives = [], []
    with tempfile.TemporaryDirectory(prefix="signing-", dir=work) as temporary:
        base = Path(temporary)
        artifact = base / "artifact"
        cli(binary, "build", ROOT / "examples/payment-fee.bas", "--bindings", ROOT / "examples/payment-fee.bindings.json", "--out", artifact)
        manifest = artifact / "manifest.json"
        ph = json.loads(manifest.read_text())["puzzle"]["tree_hash"]
        parent = "45" * 32
        peak = {"height": 3924000, "header_hash": "46" * 32, "synced": True, "sync_mode": False}
        obs = {"schema_version": 1, "validation": "rpc-observation-only", "node_version": "2.7.5", "compiler_profile": "chia-clvm-0.19-strict-v2",
               "network": {"name": "testnet11", "prefix": "txch", "genesis_challenge": GENESIS}, "observed_at": datetime.now(timezone.utc).isoformat(),
               "before": peak, "after": dict(peak), "coin": {"name": coin_id(parent, ph, 1000), "parent_coin_info": parent,
               "puzzle_hash": ph, "amount": "1000", "confirmed_block_index": 1, "spent_block_index": 0, "spent": False,
               "coinbase": False, "timestamp": 1}, "atomic_snapshot": False, "spend_validated": False, "transactions_submitted": 0}
        op, sp, pp, rp = [base / (n + ".json") for n in ("observation", "solution", "preparation", "response")]
        def build_preparation(payment=600, fee=10, observation=None, artifact_manifest=None):
            op.write_text(json.dumps(obs if observation is None else observation), encoding="utf-8")
            sp.write_text(json.dumps({"paymentAmount": str(payment), "feeAmount": str(fee)}), encoding="utf-8")
            return prepare(binary, artifact_manifest or manifest, op, sp, 20)
        def response_for(prepared, signature=None):
            pp.write_text(json.dumps(prepared, indent=2, sort_keys=True), encoding="utf-8")
            message = prepared["signing_request"]["message"]
            return {"schema_version": 1, "scheme": "AugSchemeMPL", "preparation_sha256": digest(pp.read_bytes()),
                    "public_key": prepared["signing_request"]["public_key"], "message": message,
                    "signature": bytes(signature if signature is not None else AugSchemeMPL.sign(key, bytes.fromhex(message))).hex()}
        def check(prepared, response=None, artifact_manifest=None):
            reply = response_for(prepared) if response is None else response
            rp.write_text(json.dumps(reply), encoding="utf-8")
            return verify_signed(binary, artifact_manifest or manifest, op, sp, pp, rp, 20)
        def reject(label, action):
            try:
                action()
            except (ProbeError, RuntimeError, ValueError, KeyError, TypeError):
                negatives.append(label)
            else:
                raise AssertionError("Invalid signing accepted: " + label)
        def confirm(label, prepared, artifact_manifest=None):
            result = check(prepared, artifact_manifest=artifact_manifest)
            bundle = SpendBundle.from_json_dict(result["spend_bundle"])
            assert bundle.name().hex() == result["bundle_id"] and digest(bytes(bundle)) == result["bundle_sha256"]
            assert len(bundle.coin_spends) == 1
            assert AugSchemeMPL.verify(key.get_g1(), bytes.fromhex(prepared["signing_request"]["message"]), bundle.aggregated_signature)
            assert result["signature_verified"] and not result["mempool_validated"] and result["transactions_submitted"] == 0
            assert result["preparation"]["expected_outputs"] == prepared["expected_outputs"]
            positives.append({"scenario": label, "result": result})
        for label, payment, fee in [("partial", 600, 10), ("exact", 990, 10), ("zero", 1000, 0)]:
            confirm(label, build_preparation(payment, fee))
        original = build_preparation()
        original_response = response_for(original)
        mutations = {
            "prepared-message": lambda p: p["signing_request"].update(message="00" * 96),
            "prepared-key": lambda p: p["signing_request"].update(public_key=bytes(other_key.get_g1()).hex()),
            "prepared-domain": lambda p: p["signing_request"].update(additional_data="aa" * 32),
            "prepared-output": lambda p: p["expected_outputs"][0].update(amount="601"),
            "prepared-fee": lambda p: p["accounting"].update(fee="9"),
            "prepared-coin": lambda p: p["unsigned_coin_spend"]["coin"].update(amount="1001"),
            "prepared-flags": lambda p: p["runtime"].update(flags=0),
            "prepared-binding": lambda p: p["bindings"]["recipient"].update(hex="66" * 32),
            "prepared-solution": lambda p: p["solution_values"].update(paymentAmount="601"),
            "prepared-scope-type": lambda p: p.update(signature_verified=0),
        }
        for label, mutate in mutations.items():
            changed = copy.deepcopy(original)
            mutate(changed)
            reply = response_for(changed)  # Even correctly signed tampered requests must fail revalidation.
            reject(label, lambda: check(changed, reply))
        response_mutations = {
            "response-hash": lambda r: r.update(preparation_sha256="00" * 32),
            "response-key": lambda r: r.update(public_key=bytes(other_key.get_g1()).hex()),
            "response-message": lambda r: r.update(message="00" * 96),
            "response-scheme": lambda r: r.update(scheme="BasicSchemeMPL"),
            "response-extra": lambda r: r.update(extra=True),
            "short-signature": lambda r: r.update(signature="00"),
            "malformed-signature": lambda r: r.update(signature="00" * 96),
            "empty-signature": lambda r: r.update(signature=bytes(G2Element()).hex()),
            "wrong-owner": lambda r: r.update(signature=bytes(AugSchemeMPL.sign(other_key, bytes.fromhex(r["message"]))).hex()),
            "wrong-domain": lambda r: r.update(signature=bytes(AugSchemeMPL.sign(key, bytes.fromhex(r["message"][:-64] + "aa" * 32))).hex()),
            "application-only": lambda r: r.update(signature=bytes(AugSchemeMPL.sign(key, bytes.fromhex(original["signing_request"]["application_message"]))).hex()),
        }
        for label, mutate in response_mutations.items():
            reply = response_for(original)
            mutate(reply)
            reject(label, lambda: check(original, reply))
        stale_signature = AugSchemeMPL.sign(key, bytes.fromhex(original["signing_request"]["message"]))
        for label, payment, fee in [("changed-payment", 601, 10), ("changed-fee", 600, 11)]:
            changed = build_preparation(payment, fee)
            reply = response_for(changed, stale_signature)
            reject(label, lambda: check(changed, reply))
            confirm(label + "-resigned", changed)
        other_obs = copy.deepcopy(obs)
        other_obs["coin"]["parent_coin_info"] = "55" * 32
        other_obs["coin"]["name"] = coin_id("55" * 32, ph, 1000)
        changed = build_preparation(observation=other_obs)
        reply = response_for(changed, stale_signature)
        reject("changed-coin", lambda: check(changed, reply))
        confirm("changed-coin-resigned", changed)
        bindings = json.loads((ROOT / "examples/payment-fee.bindings.json").read_text())
        bindings["recipient"]["hex"] = "66" * 32
        bp = base / "bindings.json";bp.write_text(json.dumps(bindings))
        other_artifact = base / "destination"
        cli(binary, "build", ROOT / "examples/payment-fee.bas", "--bindings", bp, "--out", other_artifact)
        other_manifest = other_artifact / "manifest.json"
        other_ph = json.loads(other_manifest.read_text())["puzzle"]["tree_hash"]
        other_obs = copy.deepcopy(obs)
        other_obs["coin"]["puzzle_hash"] = other_ph
        other_obs["coin"]["name"] = coin_id(parent, other_ph, 1000)
        changed = build_preparation(observation=other_obs, artifact_manifest=other_manifest)
        reply = response_for(changed, stale_signature)
        reject("changed-destination", lambda: check(changed, reply, other_manifest))
        confirm("changed-destination-resigned", changed, other_manifest)
        original = build_preparation()
        reply = response_for(original)
        rp.write_text(json.dumps(reply))
        out = base / "signed.json"
        command = [sys.executable, str(ROOT / "integration/verify_signed_fee.py"), "--binary", str(binary), "--manifest", str(manifest),
                   "--observation", str(op), "--solution", str(sp), "--preparation", str(pp), "--signature-response", str(rp),
                   "--max-fee", "20", "--out", str(out)]
        proc = subprocess.run(command, capture_output=True, timeout=60)
        assert proc.returncode == 0 and out.is_file(), proc.stderr
        reply["signature"] = bytes(G2Element()).hex();rp.write_text(json.dumps(reply))
        proc = subprocess.run(command, capture_output=True, timeout=60)
        assert proc.returncode == 1 and not out.exists(), proc.stderr
        negatives.append("cli-stale-success-invalidation")
    assert len(positives) == 7 and len(negatives) == 26
    evidence = {"schema_version": 1, "positive_count": len(positives), "negative_count": len(negatives),
                "positives": positives, "negatives": negatives, "resources_closed": True,
                "validation": "synthetic-offline-detached-signature", "live_node_contacted": False,
                "input_sha256": {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p.read_bytes()) for p in
                    [Path(__file__), ROOT / "integration/verify_signed_fee.py", ROOT / "integration/prepare_fee.py", ROOT / "integration/testnet_probe.py",
                     ROOT / "integration/verify_preparation.py", ROOT / "simulator/smoke.py"]},
                "binary_sha256": digest(binary.read_bytes())}
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PASS: 7 positive / 26 negative detached-signature cases; no user keys or live node. Report: {destination}")


if __name__ == "__main__":
    main()
