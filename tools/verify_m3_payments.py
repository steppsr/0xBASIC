"""Verify payment-condition trees, diagnostics, reproducibility and optional Python CLVM."""
import argparse
import io
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke

ROOT = Path(__file__).resolve().parents[1]


def expected_tree(value):
    if isinstance(value, list):
        tail = {"atom": ""}
        for item in reversed(value):
            tail = {"pair": [expected_tree(item), tail]}
        return tail
    if isinstance(value, int):
        return {"atom": "" if value == 0 else value.to_bytes((value.bit_length()+8)//8, "big").hex()}
    return {"atom": value}


def independent(program, case, result):
    from clvm import SExp, run_program
    from clvm.EvalError import EvalError
    from clvm.operators import OPERATOR_LOOKUP
    from clvm.serialize import sexp_from_stream
    p = sexp_from_stream(io.BytesIO(program), SExp.to)
    try:
        cost, output = run_program(p, SExp.to([]), OPERATOR_LOOKUP, max_cost=10000000)
    except EvalError:
        assert case.get("runtime_diagnostic") == "E0500"
        return
    assert "runtime_diagnostic" not in case
    assert output.as_bin().hex() == case["expected_hex"]
    assert str(cost) == result["result"]["cost"]
    expected = [[bytes.fromhex(x) if isinstance(x,str) else x for x in c] for c in case["conditions"]]
    # Build the quoted reference solely from independent specification data.
    _, reference = run_program(SExp.to((1, expected)), SExp.to([]), OPERATOR_LOOKUP)
    assert reference.as_bin() == output.as_bin()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary")
    cases = json.loads((ROOT / "docs/spec/m3-payment-condition-cases.json").read_text(encoding="utf-8"))["cases"]
    original = json.loads((ROOT / "docs/spec/source-cases.json").read_text(encoding="utf-8"))["cases"]
    old = next(c for c in original if c["id"] == "emission-order")
    active = next(c for c in cases if c["id"] == "m0-emission-order")
    assert active["source"] == old["source"] and active["conditions"] == old["expected_conditions"]
    with tempfile.TemporaryDirectory(prefix="0xbasic payments ") as temp:
        root = Path(temp)
        for case in cases:
            source = root / (case["id"] + ".bas")
            source.write_text(case["source"], encoding="utf-8")
            out = root / case["id"]
            rejected = "check_diagnostic" in case
            result = invoke(binary, ["check", source], 1 if rejected else 0)
            if rejected: assert result["diagnostics"][0]["code"] == case["check_diagnostic"]
            result = invoke(binary, ["build", source, "--out", out], 1 if rejected else 0)
            if rejected:
                assert result["diagnostics"][0]["code"] == case["check_diagnostic"]
                assert not out.exists()
                continue
            repeated = root / (case["id"] + "-repeat")
            invoke(binary, ["build", source, "--out", repeated])
            assert {p.name:p.read_bytes() for p in out.iterdir()} == {p.name:p.read_bytes() for p in repeated.iterdir()}
            failed = "runtime_diagnostic" in case
            result = invoke(binary, ["run", out / "manifest.json"], 3 if failed else 0)
            if failed: assert result["diagnostics"][0]["code"] == case["runtime_diagnostic"]
            else:
                assert result["result"]["tree"] == expected_tree(case["conditions"])
                assert result["result"]["validation"] == "clvm-execution-only"
            if args.with_upstream: independent((out / "puzzle.clvm").read_bytes(), case, result)
    print(f"{len(cases)} payment-condition cases passed; original M0 emission-order activated and artifacts reproducible." + (" Independent Python CLVM results and costs matched." if args.with_upstream else ""))


if __name__ == "__main__":
    main()
