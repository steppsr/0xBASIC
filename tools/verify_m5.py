"""Bounded deterministic CLI mutation checks and frozen size/cost regressions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

from verify_m3_payments import expected_tree

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs/spec/m5-regression-baseline.json"
SEED = 0x0B451503


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


class Generator:
    def __init__(self):
        self.state = SEED

    def next(self, limit):
        self.state ^= (self.state << 13) & 0xffffffff
        self.state ^= self.state >> 17
        self.state ^= (self.state << 5) & 0xffffffff
        self.state &= 0xffffffff
        return self.state % limit


def atom(data):
    if len(data) == 1 and data[0] < 128:
        return data
    require(len(data) < 64, "Small test atom required")
    return bytes([128 + len(data)]) + data


def integer(value):
    if value == 0:
        return b"\x80"
    data = value.to_bytes((value.bit_length() + 8) // 8, "big", signed=True)
    return atom(data)


def sequence(items):
    return b"".join(b"\xff" + item for item in items) + b"\x80"


class Runner:
    def __init__(self, binary, directory):
        self.binary, self.directory = binary, directory
        self.case = "setup"
        self.calls = 0

    def call(self, args, statuses=(0,), code=None):
        self.calls += 1
        command = [str(self.binary), *map(str, args), "--json"]
        # Persist the exact active command before launching: a crash/timeout remains reproducible.
        (self.directory / "active-case.json").write_text(json.dumps({"case": self.case, "command": command}), encoding="utf-8")
        result = subprocess.run(command, capture_output=True, timeout=10)
        (self.directory / "last-stdout.txt").write_bytes(result.stdout)
        (self.directory / "last-stderr.txt").write_bytes(result.stderr)
        require(result.returncode in statuses, f"{self.case}: exit {result.returncode}; expected {statuses}")
        require(not result.stderr, f"{self.case}: unexpected stderr")
        value = json.loads(result.stdout)
        require(value["schema_version"] == 1 and value["ok"] == (result.returncode == 0), f"{self.case}: envelope")
        if result.returncode:
            require(value["result"] is None and len(value["diagnostics"]) == 1, f"{self.case}: diagnostics")
            observed = value["diagnostics"][0]["code"]
            require(observed != "E9000" and (code is None or observed == code), f"{self.case}: code {observed}")
        else:
            require(value["diagnostics"] == [] and value["result"] is not None, f"{self.case}: success")
        return value

    def build(self, source, name, bindings=None):
        out = self.directory / name
        args = ["build", source, "--out", out]
        if bindings:
            args += ["--bindings", bindings]
        self.call(args)
        return out / "manifest.json"


def generated(runner):
    rng = Generator()
    root = runner.directory
    source = root / "mutated.bas"
    original = b"CONTRACT Demo()\nDIM n = 17\nEMIT ASSERT_HEIGHT_ABSOLUTE(n + 3)\nEND CONTRACT\n"
    # Byte-oriented mutation intentionally includes invalid UTF-8, NUL and delimiters.
    for index in range(128):
        runner.case = f"source-{index}"
        data = bytearray(original)
        for _ in range(1 + rng.next(4)):
            offset = rng.next(len(data))
            operation = rng.next(3)
            if operation == 0:
                del data[offset]
            elif operation == 1:
                data[offset] = rng.next(256)
            else:
                data[offset:offset] = bytes([rng.next(256)])
        source.write_bytes(data)
        checked = runner.call(["check", source], (0, 1))
        out = root / f"mutant-{index}"
        built = runner.call(["build", source, "--out", out], (0,) if checked["ok"] else (1,))
        require(checked["diagnostics"] == built["diagnostics"], f"{runner.case}: check/build disagreement")
        require(out.exists() == checked["ok"], f"{runner.case}: publication mismatch")
    print("PASS: 128 source mutations (check/build parity, no crash or timeout)", flush=True)

    for index in range(32):
        runner.case = f"arithmetic-{index}"
        left, right = rng.next(1000), rng.next(1000)
        source.write_text(f"CONTRACT Demo()\nEMIT ASSERT_HEIGHT_ABSOLUTE({left} + {right} * 3)\nEND CONTRACT\n", encoding="utf-8")
        manifest = runner.build(source, f"arithmetic-{index}")
        result = runner.call(["run", manifest])["result"]
        require(result["tree"] == expected_tree([[83, left + right * 3]]), f"{runner.case}: arithmetic oracle")
    print("PASS: 32 generated arithmetic controls", flush=True)

    source.write_text("CONTRACT Boundary()\nSOLUTION n AS INTEGER\nSOLUTION flag AS BOOLEAN\nEMIT ASSERT_HEIGHT_ABSOLUTE(n)\nEND CONTRACT\n", encoding="utf-8")
    manifest = runner.build(source, "boundary")
    solution = root / "solution.json"
    raw = root / "solution.hex"
    for index in range(64):
        runner.case = f"boundary-{index}"
        n = rng.next(10000)
        solution.write_text(json.dumps({"n": str(n), "flag": bool(index % 2)}), encoding="utf-8")
        good = runner.call(["run", manifest, "--solution", solution])["result"]
        require(good["tree"] == expected_tree([[83, n]]), f"{runner.case}: boundary oracle")
        raw.write_text(sequence([integer(n), b"\x01" if index % 2 else b"\x80"]).hex(), encoding="utf-8")
        require(runner.call(["run", manifest, "--solution-hex", raw])["result"] == good, f"{runner.case}: JSON/raw parity")
        invalid = [f'{{"n":"{n}","flag":true,"FLAG":false}}',
                   f'{{"n":{n},"flag":true}}', f'{{"n":"+{n}","flag":true}}',
                   f'{{"n":"{n}","flag":1}}', f'{{"n":"{n}"}}',
                   f'{{"n":"{n}","flag":true,"extra":0}}', '{"n":',
                   f'{{"n":"{n}","flag":true,"n":"0"}}'][index % 8]
        solution.write_text(invalid, encoding="utf-8")
        runner.call(["run", manifest, "--solution", solution], (1,), "E0300")
        # All trees serialize correctly but violate raw ABI guards, including unused BOOLEAN.
        malformed = [sequence([integer(n), b"\x02"]), sequence([atom(b"\x00"), b"\x80"]),
                     sequence([integer(n)]), sequence([integer(n), b"\x80", b"\x80"]),
                     b"\xff" + integer(n) + b"\x01",
                     sequence([integer(n), sequence([b"\x01"])])][index % 6]
        raw.write_text(malformed.hex(), encoding="utf-8")
        runner.call(["run", manifest, "--solution-hex", raw], (3,), "E0500")
    print("PASS: 64 JSON/raw positive pairs, 64 JSON and 64 raw ABI rejections", flush=True)

    pristine = manifest.read_bytes()
    for index in range(64):
        runner.case = f"artifact-{index}"
        value = json.loads(pristine)
        kind = index % 8
        if kind == 0:
            value["schema_version"] = 2 + index
        elif kind == 1:
            value["compiler"]["version"] = f"unsupported-{index}"
        elif kind == 2:
            value["puzzle"]["binary"] = f"../escape-{index}.clvm"
        elif kind == 3:
            value["puzzle"]["tree_hash"] = hashlib.sha256(str(index).encode()).hexdigest()
        elif kind == 4:
            value["source"]["sha256"] = "INVALID"
        elif kind == 5:
            value["unknown_field"] = index
        elif kind == 6:
            del value["inputs"]
        encoded = json.dumps(value)
        if kind == 7:
            encoded = '{"schema_version":1,' + encoded[1:]
        manifest.write_text(encoded, encoding="utf-8")
        status, code = (2, "E0400") if kind < 2 else (4, "E0600")
        runner.call(["run", manifest], (status,), code)
    manifest.write_bytes(pristine)
    print("PASS: 64 damaged manifests rejected", flush=True)


def measure(runner, case):
    source = ROOT / case["source"]
    bindings = ROOT / case["bindings"] if case.get("bindings") else None
    manifest = runner.build(source, case["id"], bindings)
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    result = runner.call(["run", manifest])["result"]
    # Git stores these text fixtures as LF; rsync may preserve a Windows CRLF copy.
    # Normalize only regression input fingerprints, never compiler artifact bytes.
    return {"source_sha256": hashlib.sha256(source.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            "bindings_sha256": hashlib.sha256(bindings.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if bindings else None,
            "template_bytes": (manifest.parent / "template.clvm").stat().st_size,
            "puzzle_bytes": (manifest.parent / "puzzle.clvm").stat().st_size,
            "puzzle_sha256": metadata["puzzle"]["program_sha256"],
            "puzzle_tree_hash": metadata["puzzle"]["tree_hash"],
            "cost": result["cost"], "tree": result["tree"]}


def regressions(runner):
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    require(len(baseline["cases"]) == 3, "Regression coverage changed")
    for case in baseline["cases"]:
        runner.case = case["id"]
        measured = measure(runner, case)
        differences = {key: {"expected": case["expected"].get(key), "actual": value}
                       for key, value in measured.items() if case["expected"].get(key) != value}
        require(measured == case["expected"], f"{runner.case}: frozen regression changed: {differences}")
        manifest = runner.directory / case["id"] / "manifest.json"
        cost = int(measured["cost"])
        runner.call(["run", manifest, "--max-cost", cost])
        runner.call(["run", manifest, "--max-cost", cost - 1], (3,), "E0501")
    print("PASS: 3 frozen size/hash/cost/output baselines and exact cost limits", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    work = ROOT / ".work/m5"
    work.mkdir(parents=True, exist_ok=True)
    report = work / ("generated-windows.json" if os.name == "nt" else "generated-linux.json")
    report.unlink(missing_ok=True)
    require(binary.is_file(), "Build CLI first or pass --binary")
    run = work / ("generated-" + uuid.uuid4().hex)
    run.mkdir()
    runner = Runner(binary, run)
    print(f"Seed {SEED:#x}; retained inputs and diagnostics: {run}", flush=True)
    try:
        generated(runner)
        regressions(runner)
    except Exception as error:
        raise RuntimeError(f"FAILED {runner.case}; inspect {run}") from error
    evidence = {"schema_version": 1, "seed": SEED, "cli_calls": runner.calls,
                "source_mutations": 128, "arithmetic_controls": 32, "boundary_pairs": 64,
                "json_rejections": 64, "raw_rejections": 64, "artifact_rejections": 64, "regressions": 3,
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "baseline_sha256": hashlib.sha256(BASELINE.read_bytes()).hexdigest()}
    temporary = run / "success.json"
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report)
    print(f"PASS: M5 generated-input and regression checks ({runner.calls} CLI calls). Report: {report}")


if __name__ == "__main__":
    main()
