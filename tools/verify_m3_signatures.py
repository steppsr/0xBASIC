"""Verify signature-condition trees, diagnostics, reproducibility and optional Python CLVM."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m3_payments import expected_tree, independent

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary")
    cases = json.loads((ROOT / "docs/spec/m3-signature-condition-cases.json").read_text(encoding="utf-8"))["cases"]
    with tempfile.TemporaryDirectory(prefix="0xbasic signatures ") as temp:
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
        out = root / "full-payment"
        invoke(binary, ["build", ROOT / "examples/height-locked-payment.bas", "--bindings", ROOT / "examples/height-locked-payment.bindings.json", "--out", out])
        result = invoke(binary, ["run", out / "manifest.json"])
        v = json.loads((ROOT / "docs/spec/vectors.json").read_text(encoding="utf-8"))["payment"]
        conditions = [[73,int(v["amount"])],[83,int(v["earliest_height"])],[50,v["owner_hex"],v["application_message_hex"]],[51,v["recipient_hex"],int(v["amount"])]]
        assert result["result"]["tree"] == expected_tree(conditions)
        assert result["result"]["validation"] == "clvm-execution-only"
        if args.with_upstream:
            independent((out / "puzzle.clvm").read_bytes(), {"conditions":conditions,"expected_hex":v["conditions_serialized_hex"]}, result)
    print(f"{len(cases) + 1} signature-condition cases passed; artifacts reproducible." + (" Independent Python CLVM results and costs matched." if args.with_upstream else ""))


if __name__ == "__main__":
    main()
