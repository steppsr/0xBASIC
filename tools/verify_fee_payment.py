"""FP-2 local fee-payment oracle and boundary checks; no signing or spend claim."""
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
SOURCE = ROOT / "examples/payment-fee.bas"
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


def raw_solution(payment, fee):
    result = b""
    for value in (payment, fee):
        atom = integer_bytes(value)
        encoded = atom if len(atom) == 1 and atom[0] < 128 else bytes([128 + len(atom)]) + atom
        result += b"\xff" + encoded
    return result + b"\x80"


def oracle(bindings, payment, fee):
    owner = bytes.fromhex(bindings["owner"]["hex"])
    recipient = bytes.fromhex(bindings["recipient"]["hex"])
    change_recipient = bytes.fromhex(bindings["changeRecipient"]["hex"])
    total = int(bindings["inputAmount"])
    message = hashlib.sha256(b"0xBASIC/payment-fee/v1\x00" + owner + recipient + change_recipient
                             + total.to_bytes(8, "big") + payment.to_bytes(8, "big") + fee.to_bytes(8, "big")).digest()
    conditions = [[73, total], [50, owner, message], [52, fee], [51, recipient, payment]]
    if total > payment + fee:
        conditions.append([51, change_recipient, total - payment - fee])
    return tree(conditions), message.hex()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    work = ROOT / ".work/payment-fee"
    work.mkdir(parents=True, exist_ok=True)
    destination = work / ("local-windows.json" if os.name == "nt" else "local-linux.json")
    destination.unlink(missing_ok=True)
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    require(binary.is_file(), "Build CLI first or pass --binary")
    fixtures = [SOURCE, ROOT / "examples/payment-fee.bindings.json",
                ROOT / "examples/payment-fee.partial.json", ROOT / "examples/payment-fee.exact.json",
                ROOT / "examples/payment-fee.zero-fee.json", ROOT / "docs/spec/m3-publickey-cases.json"]
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
        require(set(snapshot) == {"manifest.json", "template.clvm", "template.hex", "puzzle.clvm", "puzzle.hex"}, "Unexpected artifact inventory")
        require(snapshot == {p.name: p.read_bytes() for p in repeated.iterdir()}, "Repeated artifacts differ")
        view = call(["explain", SOURCE, "--bindings", binding_file, "--stage", "clvm"])["representation"]
        manifest = json.loads(snapshot["manifest.json"])
        require(manifest["compiler"]["version"] == version, "Stale compiler identity")
        require(manifest["language_version"] == "0.3" and manifest["abi_version"] == 1
                and manifest["target_profile"] == "chia-clvm-0.19-strict-v2", "Unexpected language/ABI/profile identity")
        require([x["name"] for x in manifest["fixed_parameters"]] == ["owner", "recipient", "changerecipient", "inputamount"]
                and [x["name"] for x in manifest["inputs"]] == ["paymentamount", "feeamount"], "Unexpected ABI field order")
        for role in ("template", "puzzle"):
            require(view[role]["tree_hash"] == manifest[role]["tree_hash"]
                    and view[role]["program_sha256"] == manifest[role]["program_sha256"]
                    == hashlib.sha256(snapshot[f"{role}.clvm"]).hexdigest(), "Inspection identity mismatch")
            require(bytes.fromhex(view[role]["hex"]) == bytes.fromhex(snapshot[f"{role}.hex"].decode())
                    == snapshot[f"{role}.clvm"], "Inspection/artifact bytes differ")
        call(["build", SOURCE, "--bindings", binding_file, "--out", baseline], 4, "E0600")
        require(snapshot == {p.name: p.read_bytes() for p in baseline.iterdir()}, "Overwrite protection failed")

        valid = [("partial", 1000, 600, 10), ("exact", 1000, 990, 10),
                 ("zero-fee-partial", 1000, 600, 0), ("zero-fee", 1000, 1000, 0),
                 ("changed-fee", 1000, 600, 11), ("minimum-payment", 1000, 1, 1),
                 ("sign-bit", 1000, 128, 128), ("minimum-change", 1000, 989, 10),
                 ("one-mojo", 1, 1, 0), ("maximum-input", MAX_AMOUNT, 1, 1),
                 ("maximum-fee", MAX_AMOUNT, 1, MAX_AMOUNT - 1), ("maximum-exact", MAX_AMOUNT, MAX_AMOUNT, 0)]
        artifacts = {1000: baseline}
        for name, total, payment, fee in valid:
            bindings = {**base, "inputAmount": str(total)}
            if total not in artifacts:
                artifacts[total] = build(name, bindings)
            out = artifacts[total]
            if name in {"partial", "exact", "zero-fee"}:
                solution = ROOT / f"examples/payment-fee.{name}.json"
                require(json.loads(solution.read_text()) == {"paymentAmount": str(payment), "feeAmount": str(fee)}, "Example fixture differs")
            else:
                solution_file.write_text(json.dumps({"paymentAmount": str(payment), "feeAmount": str(fee)}), encoding="utf-8")
                solution = solution_file
            result = call(["run", out / "manifest.json", "--solution", solution])
            expected, message = oracle(bindings, payment, fee)
            require(result["tree"] == expected and result["validation"] == "clvm-execution-only", f"{name}: oracle mismatch")
            raw_file.write_text(raw_solution(payment, fee).hex(), encoding="ascii")
            require(call(["run", out / "manifest.json", "--solution-hex", raw_file]) == result, "Host/raw parity failed")
            cost = int(result["cost"])
            require(call(["run", out / "manifest.json", "--solution", solution, "--max-cost", str(cost)]) == result,
                    "Exact cost failed")
            call(["run", out / "manifest.json", "--solution", solution, "--max-cost", str(cost - 1)], 3, "E0501")
            m = json.loads((out / "manifest.json").read_text())
            successes.append({"case": name, "input_amount": str(total), "payment_amount": str(payment),
                              "fee_amount": str(fee), "change_amount": str(total - payment - fee), "conditions": expected, "application_message": message,
                              "cost": result["cost"], "puzzle_tree_hash": m["puzzle"]["tree_hash"],
                              "puzzle_sha256": hashlib.sha256((out / "puzzle.clvm").read_bytes()).hexdigest()})
        require(successes[0]["application_message"] != successes[1]["application_message"], "Payment not committed by message")
        require(successes[0]["puzzle_sha256"] == successes[1]["puzzle_sha256"], "Solution changed fixed puzzle")

        require(successes[0]["application_message"] != successes[4]["application_message"], "Fee not committed by message")
        require(successes[0]["puzzle_sha256"] == successes[4]["puzzle_sha256"], "Fee solution changed fixed puzzle")
        double_key = next(c["hex"] for c in json.loads(fixtures[-1].read_text())["cases"] if c["id"] == "double-generator")
        for name, change in [("changed-owner", {"owner": {"hex": double_key}}),
                             ("changed-recipient", {"recipient": {"hex": "33" * 32}}),
                             ("changed-change-recipient", {"changeRecipient": {"hex": "44" * 32}}),
                             ("changed-input", {"inputAmount": "1001"})]:
            bindings = {**base, **change}
            out = build(name, bindings)
            result = call(["run", out / "manifest.json", "--solution", fixtures[2]])
            expected, message = oracle(bindings, 600, 10)
            require(result["tree"] == expected and result["validation"] == "clvm-execution-only", "Fixed-term oracle mismatch")
            require(message != successes[0]["application_message"], "Fixed term absent from message")
            m = json.loads((out / "manifest.json").read_text())
            require(m["puzzle"]["tree_hash"] != successes[0]["puzzle_tree_hash"], "Fixed term absent from puzzle")
            successes.append({"case": name, "conditions": expected, "application_message": message,
                              "cost": result["cost"], "puzzle_tree_hash": m["puzzle"]["tree_hash"]})

        for name, bindings, payment, fee in [("zero-payment", base, 0, 10), ("overspend", base, 1001, 0),
                ("fee-overruns-exact-payment", base, 1000, 1), ("fee-exhausts-input", base, 1, 1000),
                ("sum-exceeds-u64", {**base, "inputAmount": str(MAX_AMOUNT)}, MAX_AMOUNT, MAX_AMOUNT),
                ("zero-input", {**base, "inputAmount": "0"}, 1, 0),
                ("same-destination", {**base, "changeRecipient": base["recipient"]}, 600, 10)]:
            out = baseline if bindings == base else build(name, bindings)
            solution_file.write_text(json.dumps({"paymentAmount": str(payment), "feeAmount": str(fee)}), encoding="utf-8")
            call(["run", out / "manifest.json", "--solution", solution_file], 3, "E0500")
            raw_file.write_text(raw_solution(payment, fee).hex(), encoding="ascii")
            call(["run", out / "manifest.json", "--solution-hex", raw_file], 3, "E0500")
            failures.append({"case": name, "layer": "contract", "diagnostic": "E0500"})

        bad_solutions = ['{}', '{"paymentAmount":"1"}', '{"feeAmount":"0"}',
                         '{"paymentAmount":"1","feeAmount":"0","extra":"2"}',
                         '{"paymentAmount":"1","feeAmount":"0","feeAmount":"1"}',
                         '{"paymentAmount":"1","feeAmount":"0","FEEAMOUNT":"1"}']
        for field in ("paymentAmount", "feeAmount"):
            for invalid in [1, "-1", str(MAX_AMOUNT + 1), "01", "-0", [], None]:
                bad_solutions.append(json.dumps({"paymentAmount": "600", "feeAmount": "10", field: invalid}))
        for index, value in enumerate(bad_solutions):
            solution_file.write_text(value, encoding="utf-8")
            call(["run", baseline / "manifest.json", "--solution", solution_file], 1, "E0300")
            failures.append({"case": f"host-solution-{index}", "layer": "host", "diagnostic": "E0300"})
        malformed = ["80", "ff0180", "ff01ff80ff0180", "ff01ff8002"]
        for atom in ["00", "820001", "81ff", "89010000000000000000", "ff0180"]:
            malformed.extend(["ff" + atom + "ff8080", "ff01ff" + atom + "80"])
        for index, value in enumerate(malformed):
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
    report = {"schema_version": 1, "validation": "fee-payment-local-clvm-only", "compiler": version,
              "platform": sys.platform, "binary_sha256": binary_hash, "input_sha256": hashes,
              "cli_calls": calls, "positive_cases": successes, "negative_cases": failures,
              "signatures_verified": False, "spends_submitted": False}
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"PASS: {len(successes)} fee-payment positives, {len(failures)} negatives, {calls} CLI calls; local execution only. Report: {destination}")


if __name__ == "__main__":
    main()
