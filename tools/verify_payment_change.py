"""PC-1 local payment/change oracle and boundary checks; no signing or spend claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/payment-change.bas"
MAX_AMOUNT = (1 << 64) - 1


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def integer_bytes(value):
    return b"" if value == 0 else value.to_bytes((value.bit_length() + 8) // 8, "big", signed=True)


def tree(value):
    if isinstance(value, list):
        result = {"atom": ""}
        for item in reversed(value):
            result = {"pair": [tree(item), result]}
        return result
    return {"atom": (integer_bytes(value) if isinstance(value, int) else value).hex()}


def raw_solution(value):
    atom = integer_bytes(value)
    encoded = atom if len(atom) == 1 and atom[0] < 128 else bytes([128 + len(atom)]) + atom
    return b"\xff" + encoded + b"\x80"


def oracle(bindings, payment):
    owner = bytes.fromhex(bindings["owner"]["hex"])
    recipient = bytes.fromhex(bindings["recipient"]["hex"])
    change_recipient = bytes.fromhex(bindings["changeRecipient"]["hex"])
    total = int(bindings["inputAmount"])
    message = hashlib.sha256(b"0xBASIC/payment-change/v1\x00" + owner + recipient + change_recipient
                             + total.to_bytes(8, "big") + payment.to_bytes(8, "big")).digest()
    conditions = [[73, total], [50, owner, message], [51, recipient, payment]]
    if total > payment:
        conditions.append([51, change_recipient, total - payment])
    return tree(conditions), message.hex()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    work = ROOT / ".work/payment-change"
    work.mkdir(parents=True, exist_ok=True)
    destination = work / ("local-windows.json" if os.name == "nt" else "local-linux.json")
    destination.unlink(missing_ok=True)
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    require(binary.is_file(), "Build CLI first or pass --binary")
    fixtures = [SOURCE, ROOT / "examples/payment-change.bindings.json",
                ROOT / "examples/payment-change.partial.json", ROOT / "examples/payment-change.exact.json"]
    inputs = [*fixtures, Path(__file__).resolve(), ROOT / "Cargo.toml", ROOT / "Cargo.lock"]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    binary_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    base = json.loads(fixtures[1].read_text(encoding="utf-8"))
    calls = 0
    successes, failures = [], []

    def call(arguments, status=0, diagnostic=None):
        nonlocal calls
        calls += 1
        p = subprocess.run([str(binary), *map(str, arguments), "--json"], capture_output=True, timeout=20)
        require(p.returncode == status and not p.stderr, f"CLI mismatch: {arguments}: {p.stdout!r} {p.stderr!r}")
        envelope = json.loads(p.stdout)
        require(envelope["schema_version"] == 1 and envelope["ok"] == (status == 0), "Wrong CLI envelope")
        if diagnostic:
            require(envelope["diagnostics"][0]["code"] == diagnostic, f"Expected {diagnostic}: {envelope}")
        return envelope.get("result")

    with tempfile.TemporaryDirectory(prefix="local-", dir=work) as temporary:
        root = Path(temporary)
        binding_file, solution_file, raw_file = [root / name for name in ("bindings.json", "solution.json", "solution.hex")]

        def build(name, bindings):
            binding_file.write_text(json.dumps(bindings), encoding="utf-8")
            out = root / name
            call(["build", SOURCE, "--bindings", binding_file, "--out", out])
            return out

        call(["check", SOURCE])
        for stage in ("ast", "ir"):
            call(["explain", SOURCE, "--stage", stage])
        baseline = build("baseline", base)
        repeated = build("repeated", base)
        snapshot = {p.name: p.read_bytes() for p in baseline.iterdir()}
        require(snapshot == {p.name: p.read_bytes() for p in repeated.iterdir()}, "Repeated artifacts differ")
        view = call(["explain", SOURCE, "--bindings", binding_file, "--stage", "clvm"])["representation"]
        manifest = json.loads(snapshot["manifest.json"])
        require(manifest["compiler"]["version"] == version, "Stale compiler identity")
        require([x["name"] for x in manifest["fixed_parameters"]] == ["owner", "recipient", "changerecipient", "inputamount"]
                and [x["name"] for x in manifest["inputs"]] == ["paymentamount"], "Unexpected ABI field order")
        require(view["puzzle"]["tree_hash"] == manifest["puzzle"]["tree_hash"]
                and view["puzzle"]["program_sha256"] == hashlib.sha256(snapshot["puzzle.clvm"]).hexdigest(), "Inspection mismatch")
        call(["build", SOURCE, "--bindings", binding_file, "--out", baseline], 4, "E0600")
        require(snapshot == {p.name: p.read_bytes() for p in baseline.iterdir()}, "Overwrite protection failed")

        valid = [("partial", 1000, 600), ("exact", 1000, 1000), ("minimum-payment", 1000, 1),
                 ("sign-bit", 1000, 128), ("minimum-change", 1000, 999), ("one-mojo", 1, 1),
                 ("maximum-input", MAX_AMOUNT, 1), ("maximum-exact", MAX_AMOUNT, MAX_AMOUNT)]
        artifacts = {1000: baseline}
        for name, total, payment in valid:
            bindings = {**base, "inputAmount": str(total)}
            if total not in artifacts:
                artifacts[total] = build(name, bindings)
            out = artifacts[total]
            if name in {"partial", "exact"}:
                solution = ROOT / f"examples/payment-change.{name}.json"
                require(json.loads(solution.read_text())["paymentAmount"] == str(payment), "Example fixture differs")
            else:
                solution_file.write_text(json.dumps({"paymentAmount": str(payment)}), encoding="utf-8")
                solution = solution_file
            result = call(["run", out / "manifest.json", "--solution", solution])
            expected, message = oracle(bindings, payment)
            require(result["tree"] == expected and result["validation"] == "clvm-execution-only", f"{name}: oracle mismatch")
            raw_file.write_text(raw_solution(payment).hex(), encoding="ascii")
            require(call(["run", out / "manifest.json", "--solution-hex", raw_file]) == result, "Host/raw parity failed")
            cost = int(result["cost"])
            require(call(["run", out / "manifest.json", "--solution", solution, "--max-cost", str(cost)]) == result,
                    "Exact cost failed")
            call(["run", out / "manifest.json", "--solution", solution, "--max-cost", str(cost - 1)], 3, "E0501")
            m = json.loads((out / "manifest.json").read_text())
            successes.append({"case": name, "input_amount": str(total), "payment_amount": str(payment),
                              "change_amount": str(total - payment), "conditions": expected, "application_message": message,
                              "cost": result["cost"], "puzzle_tree_hash": m["puzzle"]["tree_hash"],
                              "puzzle_sha256": hashlib.sha256((out / "puzzle.clvm").read_bytes()).hexdigest()})
        require(successes[0]["application_message"] != successes[1]["application_message"], "Payment not committed by message")
        require(successes[0]["puzzle_sha256"] == successes[1]["puzzle_sha256"], "Solution changed fixed puzzle")

        for name, bindings, payment in [("zero-payment", base, 0), ("overspend", base, 1001),
                ("zero-input", {**base, "inputAmount": "0"}, 1),
                ("same-destination", {**base, "changeRecipient": base["recipient"]}, 600)]:
            out = baseline if bindings == base else build(name, bindings)
            solution_file.write_text(json.dumps({"paymentAmount": str(payment)}), encoding="utf-8")
            call(["run", out / "manifest.json", "--solution", solution_file], 3, "E0500")
            raw_file.write_text(raw_solution(payment).hex(), encoding="ascii")
            call(["run", out / "manifest.json", "--solution-hex", raw_file], 3, "E0500")
            failures.append({"case": name, "layer": "contract", "diagnostic": "E0500"})

        bad_solutions = ['{}', '{"paymentAmount":"1","extra":"2"}', '{"paymentAmount":1}',
                         '{"paymentAmount":"-1"}', '{"paymentAmount":"18446744073709551616"}',
                         '{"paymentAmount":"01"}', '{"paymentAmount":"-0"}',
                         '{"paymentAmount":[]}', '{"paymentAmount":"1","paymentAmount":"2"}']
        for index, value in enumerate(bad_solutions):
            solution_file.write_text(value, encoding="utf-8")
            call(["run", baseline / "manifest.json", "--solution", solution_file], 1, "E0300")
            failures.append({"case": f"host-solution-{index}", "layer": "host", "diagnostic": "E0300"})
        for index, value in enumerate(["80", "ff01ff0280", "ff0102", "ffff018080", "ff0080", "ff82000180",
                                       "ff81ff80", "ff8901000000000000000080"]):
            raw_file.write_text(value, encoding="ascii")
            call(["run", baseline / "manifest.json", "--solution-hex", raw_file], 3, "E0500")
            failures.append({"case": f"raw-solution-{index}", "raw_hex": value, "layer": "puzzle", "diagnostic": "E0500"})
        for index, change in enumerate([{"inputAmount": "-1"}, {"inputAmount": str(MAX_AMOUNT + 1)},
                                       {"recipient": {"hex": "11" * 31}}, {"owner": {"hex": "00" * 48}}]):
            binding_file.write_text(json.dumps({**base, **change}), encoding="utf-8")
            out = root / f"bad-binding-{index}"
            call(["build", SOURCE, "--bindings", binding_file, "--out", out], 1, "E0301")
            require(not out.exists(), "Invalid bindings created artifacts")
            failures.append({"case": f"host-binding-{index}", "layer": "host", "diagnostic": "E0301"})

    require(hashlib.sha256(binary.read_bytes()).hexdigest() == binary_hash and all(
        hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items()), "Inputs changed during verification")
    report = {"schema_version": 1, "validation": "payment-change-local-clvm-only", "compiler": version,
              "platform": sys.platform, "binary_sha256": binary_hash, "input_sha256": hashes,
              "cli_calls": calls, "positive_cases": successes, "negative_cases": failures,
              "signatures_verified": False, "spends_submitted": False}
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"PASS: {len(successes)} payment/change positives, {len(failures)} negatives, {calls} CLI calls; local execution only. Report: {destination}")


if __name__ == "__main__":
    main()
