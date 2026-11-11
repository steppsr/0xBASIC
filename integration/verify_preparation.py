"""TN-2 independent runtime and failure matrix; uses only synthetic offline observations."""
import argparse
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from prepare_fee import ROOT, prepare, cli, digest
from testnet_probe import GENESIS, coin_id


def no_network(event, args):
    if event in {"socket.connect", "socket.bind"}:
        raise RuntimeError("Offline verifier forbids network I/O")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    work = ROOT / ".work/testnet"
    work.mkdir(parents=True, exist_ok=True)
    destination = work / ("preparation-windows.json" if os.name == "nt" else "preparation-linux.json")
    destination.unlink(missing_ok=True)
    sys.addaudithook(no_network)
    positives, failures = [], []
    with tempfile.TemporaryDirectory(prefix="preparation-", dir=work) as temporary:
        base = Path(temporary)
        artifact = base / "artifact"
        cli(binary, "build", ROOT / "examples/payment-fee.bas", "--bindings", ROOT / "examples/payment-fee.bindings.json", "--out", artifact)
        manifest_path = artifact / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        bindings = manifest["bindings"]
        ph = manifest["puzzle"]["tree_hash"]
        parent = "45" * 32
        name = coin_id(parent, ph, 1000)
        peak = {"height": 3924000, "header_hash": "46" * 32, "synced": True, "sync_mode": False}
        obs = {"schema_version": 1, "validation": "rpc-observation-only", "node_version": "2.7.5",
               "compiler_profile": "chia-clvm-0.19-strict-v2", "network": {"name": "testnet11", "prefix": "txch", "genesis_challenge": GENESIS},
               "observed_at": datetime.now(timezone.utc).isoformat(), "before": peak, "after": dict(peak),
               "coin": {"name": name, "parent_coin_info": parent, "puzzle_hash": ph, "amount": "1000",
                        "confirmed_block_index": 1, "spent_block_index": 0, "spent": False, "coinbase": False, "timestamp": 1},
               "atomic_snapshot": False, "spend_validated": False, "transactions_submitted": 0}
        op, sp = base / "observation.json", base / "solution.json"
        def write(observation, payment=600, fee=10):
            op.write_text(json.dumps(observation), encoding="utf-8")
            sp.write_text(json.dumps({"paymentAmount": str(payment), "feeAmount": str(fee)}), encoding="utf-8")
        for height in (3754999, 3755000, 3924000):
            for label, payment, fee, change in [("partial", 600, 10, 390), ("exact", 990, 10, 0), ("zero", 1000, 0, 0)]:
                value = copy.deepcopy(obs)
                value["before"]["height"] = value["after"]["height"] = height
                write(value, payment, fee)
                r = prepare(binary, manifest_path, op, sp, 20)
                message = hashlib.sha256(b"0xBASIC/payment-fee/v1\x00" + bytes.fromhex(bindings["owner"]["hex"])
                    + bytes.fromhex(bindings["recipient"]["hex"] + bindings["changerecipient"]["hex"])
                    + b"".join(n.to_bytes(8, "big") for n in (1000, payment, fee))).hexdigest()
                assert r["signing_request"]["application_message"] == message
                assert r["signing_request"]["message"] == message + name + GENESIS
                assert r["runtime"]["flags"] == (50987607 if height >= 3924000 else 34210327)
                assert r["accounting"]["change"] == str(change)
                assert [x["amount"] for x in r["expected_outputs"]] == ([str(payment), str(change)] if change else [str(payment)])
                assert all(x["parent_coin_info"] == name for x in r["expected_outputs"])
                assert sum(int(x["amount"]) for x in r["expected_outputs"]) + fee == 1000
                assert not r["signature_verified"] and not r["mempool_validated"] and r["transactions_submitted"] == 0
                positives.append({"scenario": label, "height": height, "flags": r["runtime"]["flags"], "costs": r["runtime"], "message": message})
        write(obs, 600, 11)
        changed = prepare(binary, manifest_path, op, sp, 20)
        assert changed["signing_request"]["message"] != positives[6]["message"] + name + GENESIS
        positives.append({"scenario": "changed-fee", "message": changed["signing_request"]["message"]})
        faults = {
            "wrong-network": lambda o: o["network"].update(name="mainnet"),
            "wrong-domain": lambda o: o["network"].update(genesis_challenge="aa" * 32),
            "wrong-version": lambda o: o.update(node_version="2.7.4"),
            "stale": lambda o: o.update(observed_at=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()),
            "future": lambda o: o.update(observed_at=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()),
            "no-timezone": lambda o: o.update(observed_at="2026-11-09T00:00:00"),
            "spent": lambda o: o["coin"].update(spent=True),
            "missing-coin": lambda o: o.update(coin=None),
            "coin-id": lambda o: o["coin"].update(name="55" * 32),
            "amount": lambda o: o["coin"].update(amount="1001"),
            "peak-change": lambda o: o["after"].update(header_hash="55" * 32),
            "unsynced": lambda o: o["before"].update(synced=False),
            "claimed-validation": lambda o: o.update(spend_validated=True),
        }
        from testnet_probe import ProbeError
        def reject(label, action):
            try:
                action()
            except (ProbeError, RuntimeError, ValueError, KeyError, TypeError) as error:
                failures.append({"scenario": label, "error_type": type(error).__name__})
            else:
                raise AssertionError("Accepted invalid preparation: " + label)
        for label, mutate in faults.items():
            value = copy.deepcopy(obs)
            mutate(value)
            write(value)
            reject(label, lambda: prepare(binary, manifest_path, op, sp, 20))
        for label, payment, fee, budget in [("zero-payment", 0, 10, 20), ("overspend", 1000, 1, 20), ("fee-budget", 600, 11, 10)]:
            write(obs, payment, fee)
            reject(label, lambda: prepare(binary, manifest_path, op, sp, budget))
        write(obs)
        sp.write_text('{"paymentAmount":"600","feeAmount":"10","feeAmount":"0"}')
        reject("duplicate-solution", lambda: prepare(binary, manifest_path, op, sp, 20))
        write(obs)
        changed_manifest = json.loads(manifest_bytes)
        changed_manifest["compiler"]["version"] = "0.2.0-alpha.1"
        manifest_path.write_text(json.dumps(changed_manifest))
        reject("old-artifact", lambda: prepare(binary, manifest_path, op, sp, 20))
        manifest_path.write_bytes(manifest_bytes)
        puzzle_path = artifact / "puzzle.clvm"
        puzzle_bytes = puzzle_path.read_bytes()
        puzzle_path.write_bytes(b"\x80")
        reject("corrupt-artifact", lambda: prepare(binary, manifest_path, op, sp, 20))
        puzzle_path.write_bytes(puzzle_bytes)
        # A valid unrelated compiled artifact is rejected even when coin and bindings can be made consistent.
        other_source = base / "other.bas"
        other_source.write_text((ROOT / "examples/payment-fee.bas").read_text().replace("    EMIT RESERVE_FEE(feeAmount)\n", ""))
        other = base / "other"
        cli(binary, "build", other_source, "--bindings", ROOT / "examples/payment-fee.bindings.json", "--out", other)
        other_manifest = json.loads((other / "manifest.json").read_text())
        value = copy.deepcopy(obs)
        value["coin"]["puzzle_hash"] = other_manifest["puzzle"]["tree_hash"]
        value["coin"]["name"] = coin_id(parent, value["coin"]["puzzle_hash"], 1000)
        write(value)
        reject("unreserved-contract", lambda: prepare(binary, other / "manifest.json", op, sp, 20))
        write(obs)
        out = base / "prepared.json"
        command = [sys.executable, str(ROOT / "integration/prepare_fee.py"), "--binary", str(binary), "--manifest", str(manifest_path),
                   "--observation", str(op), "--solution", str(sp), "--max-fee", "20", "--out", str(out)]
        p = subprocess.run(command, capture_output=True, timeout=60)
        assert p.returncode == 0 and out.is_file(), p.stderr
        value = copy.deepcopy(obs);value["coin"]["spent"] = True;write(value)
        p = subprocess.run(command, capture_output=True, timeout=60)
        assert p.returncode == 1 and not out.exists(), p.stderr
        failures.append({"scenario": "cli-stale-success-invalidation"})
    result = {"schema_version": 1, "positive_cases": positives, "negative_cases": failures,
              "positive_count": len(positives), "negative_count": len(failures), "resources_closed": True,
              "validation": "synthetic-offline-preparation", "live_node_contacted": False,
              "input_sha256": {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p.read_bytes()) for p in
                               [Path(__file__), ROOT / "integration/prepare_fee.py", ROOT / "integration/network_identity.py", ROOT / "integration/testnet_probe.py", ROOT / "examples/payment-fee.bas"]},
              "binary_sha256": digest(binary.read_bytes())}
    assert len(positives) == 10 and len(failures) == 21
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PASS: 10 positive / 21 negative offline preparation cases; no live node. Report: {destination}")


if __name__ == "__main__":
    main()
