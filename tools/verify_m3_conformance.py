"""Execute all original source cases through M3 artifacts; no spend validation."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m3_payments import expected_tree

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary")
    spec = ROOT / "docs/spec"
    cases = json.loads((spec / "source-cases.json").read_text(encoding="utf-8"))["cases"]
    assert len(cases) == len({c["id"] for c in cases}) == 29
    v = json.loads((spec / "vectors.json").read_text(encoding="utf-8"))["payment"]
    with tempfile.TemporaryDirectory(prefix="0xbasic conformance ") as temp:
        root = Path(temp)
        for case in cases:
            source = root / (case["id"] + ".bas")
            data = case["source"].encode("utf-8") if "source" in case else (spec / case["source_file"]).read_bytes()
            source.write_bytes(data)
            out = root / case["id"]
            rejected = not case["accept"]
            checked = invoke(binary, ["check", source], 1 if rejected else 0)
            flags = ["--bindings", ROOT / "examples/height-locked-payment.bindings.json"] if case["id"] == "full-payment" else []
            built = invoke(binary, ["build", source, "--out", out, *flags], 1 if rejected else 0)
            if rejected:
                assert checked["diagnostics"][0]["code"] == built["diagnostics"][0]["code"] == case["diagnostic"]
                assert not out.exists()
                continue
            repeated = root / (case["id"] + "-repeat")
            invoke(binary, ["build", source, "--out", repeated, *flags])
            assert {p.name:p.read_bytes() for p in out.iterdir()} == {p.name:p.read_bytes() for p in repeated.iterdir()}
            view = invoke(binary, ["explain", source, "--stage", "clvm", *flags])["result"]["representation"]
            for name in ["template", "puzzle"]:
                assert bytes.fromhex(view[name]["hex"]) == (out / (name + ".clvm")).read_bytes()
                assert view[name]["tree_hash"] == built["result"][name]["tree_hash"]
            solution = root / "solution.json"
            solution.write_text(json.dumps(case.get("solution", {})), encoding="utf-8")
            command = ["run", out / "manifest.json", "--solution", solution]
            result = invoke(binary, command)
            conditions = case.get("expected_conditions")
            if case["id"] == "full-payment":
                conditions = [[73,int(v["amount"])],[83,int(v["earliest_height"])],[50,v["owner_hex"],v["application_message_hex"]],[51,v["recipient_hex"],int(v["amount"])]]
            assert result["result"]["tree"] == expected_tree(conditions)
            assert result["result"]["validation"] == "clvm-execution-only"
            cost = int(result["result"]["cost"])
            assert invoke(binary, [*command,"--max-cost",str(cost)]) == result
            assert invoke(binary, [*command,"--max-cost",str(cost-1)],3)["diagnostics"][0]["code"] == "E0501"
    print("All 29 original source cases active: diagnostics, reproducible artifacts, explain parity, conditions and exact cost boundaries passed. Signing/lifecycle proof remains M4.")


if __name__ == "__main__":
    main()
