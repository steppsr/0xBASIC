"""FP-1 CLI, boundary, compatibility and frozen legacy checks; optional upstream CLVM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from verify_payment_change import require, tree, raw_solution

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    work = ROOT / ".work/fp1"
    work.mkdir(parents=True, exist_ok=True)
    report = work / ("reserve-fee-windows.json" if os.name == "nt" else "reserve-fee-linux.json")
    report.unlink(missing_ok=True)
    require(binary.is_file(), "Build CLI first or pass --binary")
    run = work / ("verify-" + uuid.uuid4().hex)
    run.mkdir()
    calls = 0

    def call(argv, status=0, code=None):
        nonlocal calls
        calls += 1
        p = subprocess.run([str(binary), *map(str, argv), "--json"], capture_output=True, timeout=30)
        require(p.returncode == status and not p.stderr, f"Unexpected status/stderr: {argv}: {p.stdout!r} {p.stderr!r}")
        value = json.loads(p.stdout)
        require(value["ok"] == (status == 0), "Invalid envelope")
        if code:
            require(value["diagnostics"][0]["code"] == code, "Unexpected diagnostic")
        return value["result"]

    version = json.loads(subprocess.check_output([str(binary), "--version"]))
    require(version == {"compiler": "0.3.0-alpha.1", "language": "0.3", "abi": 1,
                        "target_profile": "chia-clvm-0.19-strict-v2"}, "Wrong activation identity")
    source = run / "fees.bas"
    source.write_text("CONTRACT Fees()\nSOLUTION fee AS AMOUNT\nEMIT RESERVE_FEE(fee)\nEND CONTRACT\n", encoding="utf-8")
    out = run / "artifact"
    call(["build", source, "--out", out])
    view = call(["explain", source, "--stage", "clvm"])["representation"]
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for role in ("template", "puzzle"):
        require(view[role]["hex"] == (out / f"{role}.clvm").read_bytes().hex(), "Inspection/build mismatch")
    solution = run / "solution.json"
    raw = run / "raw.hex"
    costs = {}

    def upstream(blob, expected, cost=None):
        if not args.with_upstream:
            return
        from chia.types.blockchain_format.program import Program
        puzzle = Program.from_bytes((out / "puzzle.clvm").read_bytes())
        try:
            actual_cost, result = puzzle.run_with_cost(10000000, Program.from_bytes(blob))
        except ValueError:
            require(expected is None, "Upstream unexpectedly rejected")
        else:
            require(expected is not None and bytes(result) == bytes(Program.to(expected)), "Upstream condition mismatch")
            require(actual_cost == int(cost), "Upstream cost mismatch")

    for amount in (0, 1, 127, 128, 255, 256, 2**64-1):
        solution.write_text(json.dumps({"fee": str(amount)}), encoding="utf-8")
        blob = raw_solution(amount)
        raw.write_text(blob.hex(), encoding="ascii")
        result = call(["run", manifest_path, "--solution", solution])
        require(result["tree"] == tree([[52, amount]]) and result["validation"] == "clvm-execution-only", "Fee condition mismatch")
        require(call(["run", manifest_path, "--solution-hex", raw]) == result, "Host/raw mismatch")
        require(call(["run", manifest_path, "--solution", solution, "--max-cost", result["cost"]]) == result, "Exact cost mismatch")
        call(["run", manifest_path, "--solution", solution, "--max-cost", str(int(result["cost"])-1)], 3, "E0501")
        upstream(blob, [[52, amount]], result["cost"])
        costs[str(amount)] = result["cost"]
    for value in ({}, {"fee": "-1"}, {"fee": str(2**64)}, {"fee": "01"}, {"fee": 1}, {"fee": "0", "extra": "1"}):
        solution.write_text(json.dumps(value), encoding="utf-8")
        call(["run", manifest_path, "--solution", solution], 1, "E0300")
    for blob in map(bytes.fromhex, ["80", "ff0080", "ff82000180", "ff81ff80", "ff8901000000000000000080", "ffff018080", "ff0102"]):
        raw.write_text(blob.hex(), encoding="ascii")
        call(["run", manifest_path, "--solution-hex", raw], 3, "E0500")
        upstream(blob, None)
    for field, value in [("compiler", "0.2.0-alpha.1"), ("language_version", "0.2"),
                         ("target_profile", "chia-clvm-0.19-strict-v1")]:
        changed = json.loads(json.dumps(manifest))
        if field == "compiler":
            changed[field]["version"] = value
        else:
            changed[field] = value
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        call(["run", manifest_path], 2, "E0400")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    source.write_text("CONTRACT Fees(fee AS AMOUNT)\nEMIT RESERVE_FEE(fee)\nEND CONTRACT\n", encoding="utf-8")
    for index, value in enumerate(("0", str(2**64-1), "-1", str(2**64))):
        solution.write_text(json.dumps({"fee": value}), encoding="utf-8")
        fixed_out = run / f"fixed-{index}"
        valid = index < 2
        call(["build", source, "--bindings", solution, "--out", fixed_out], 0 if valid else 1, None if valid else "E0301")
        if valid:
            require(call(["run", fixed_out / "manifest.json"])["tree"] == tree([[52, int(value)]]), "Fixed fee mismatch")
        else:
            require(not fixed_out.exists(), "Invalid binding published artifacts")
    baseline_file = ROOT / "docs/spec/fee-legacy-baselines.json"
    for case in json.loads(baseline_file.read_text(encoding="utf-8"))["cases"]:
        old_out = run / case["name"]
        source_bytes = (ROOT / "examples" / (case["name"] + ".bas")).read_bytes().replace(b"\r\n", b"\n")
        legacy_source = run / (case["name"] + ".bas")
        legacy_source.write_bytes(source_bytes)
        argv = ["build", legacy_source, "--out", old_out]
        if case["bindings"]:
            argv += ["--bindings", ROOT / "examples" / case["bindings"]]
        call(argv)
        m = json.loads((old_out / "manifest.json").read_text(encoding="utf-8"))
        require(m["source"]["sha256"] == hashlib.sha256(source_bytes).hexdigest(), "Manifest source mismatch")
        require(hashlib.sha256(source_bytes).hexdigest() == case["source_sha256_lf"], "Legacy source changed")
        require(all(m[role] == case[role] for role in ("template", "puzzle")), "Legacy program bytes/hash changed")
        argv = ["run", old_out / "manifest.json"]
        if case["solution"]:
            argv += ["--solution", ROOT / "examples" / case["solution"]]
        require(call(argv) == case["execution"], "Legacy conditions/cost changed")
    evidence = {"version": version, "cli_calls": calls, "upstream": args.with_upstream, "local_costs": costs,
                "legacy_cases": 3, "validation": "clvm-execution-only", "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in [Path(__file__).resolve(), baseline_file, ROOT / "Cargo.lock"]}}
    temporary = run / "success.json"
    temporary.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    temporary.replace(report)
    print(f"PASS: RESERVE_FEE boundaries, compatibility and 3 frozen legacy cases; {calls} CLI calls; upstream={args.with_upstream}. Report: {report}")


if __name__ == "__main__":
    main()
