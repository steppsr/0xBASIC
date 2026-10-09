"""PUBLICKEY host/raw/conversion checks; optional independent Python CLVM."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m3_inputs import upstream

ROOT = Path(__file__).resolve().parents[1]


def raw_key(value):
    data = bytes.fromhex(value)
    assert len(data) < 64
    atom = data if len(data) == 1 and data[0] < 128 else bytes([128 + len(data)]) + data
    return b"\xff" + atom + b"\x80"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file():
        parser.error("Build the CLI first or supply --binary PATH")
    cases = json.loads((ROOT / "docs/spec/m3-publickey-cases.json").read_text(encoding="utf-8"))["cases"]
    count = 0
    with tempfile.TemporaryDirectory(prefix="0xbasic publickeys ") as temp:
        root = Path(temp)
        for fixed in [False, True]:
            source = root / "key.bas"
            source.write_text("CONTRACT Demo(value AS PUBLICKEY)\nEND CONTRACT\n" if fixed else "CONTRACT Demo()\nSOLUTION value AS PUBLICKEY\nEND CONTRACT\n", encoding="utf-8")
            for case in cases:
                count += 1
                out = root / f"{fixed}-{case['id']}"
                values = root / "values.json"
                values.write_text(json.dumps({"VALUE": {"hex": case["hex"].upper()}}), encoding="utf-8")
                build = ["build", source, "--out", out]
                if fixed:
                    build += ["--bindings", values]
                result = invoke(binary, build, 1 if fixed and not case["valid"] else 0)
                if fixed and not case["valid"]:
                    assert result["diagnostics"][0]["code"] == "E0301"
                    assert not out.exists()
                    continue
                run = ["run", out / "manifest.json"]
                if not fixed:
                    run += ["--solution", values]
                result = invoke(binary, run, 0 if case["valid"] else 1)
                if not case["valid"]:
                    assert result["diagnostics"][0]["code"] == "E0300"
                    continue
                assert result["result"]["tree"] == {"atom": ""}
                if fixed:
                    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                    assert manifest["bindings"] == {"value": {"hex": case["hex"]}}
                if args.with_upstream:
                    upstream((out / "puzzle.clvm").read_bytes(), b"\x80" if fixed else raw_key(case["hex"]), [], result, "(q . ())")
        # Run every hostile key directly, bypassing host conversion.
        source.write_text("CONTRACT Demo()\nSOLUTION value AS PUBLICKEY\nEND CONTRACT\n", encoding="utf-8")
        out = root / "raw"
        invoke(binary, ["build", source, "--out", out])
        for case in cases + [{"hex": None, "raw": r, "valid": False} for r in ["80", "ffff018080", "ff0102"]]:
            count += 1
            raw = raw_key(case["hex"]) if case["hex"] is not None else bytes.fromhex(case["raw"])
            rawfile = root / "raw.hex"
            rawfile.write_text(raw.hex(), encoding="utf-8")
            result = invoke(binary, ["run", out / "manifest.json", "--solution-hex", rawfile], 0 if case["valid"] else 3)
            if not case["valid"]:
                assert result["diagnostics"][0]["code"] == "E0500"
            if args.with_upstream:
                upstream((out / "puzzle.clvm").read_bytes(), raw, [] if case["valid"] else None, result, "(q . ())" if case["valid"] else "(x)")
        for case in cases:
            count += 1
            source.write_text(f"CONTRACT Demo()\nDIM key = AS_PUBLICKEY(0x{case['hex']})\nASSERT KEY_BYTES(key) = 0x{case['hex']}\nEND CONTRACT\n", encoding="utf-8")
            out = root / ("conversion-" + case["id"])
            invoke(binary, ["build", source, "--out", out])
            result = invoke(binary, ["run", out / "manifest.json"], 0 if case["valid"] else 3)
            if args.with_upstream:
                upstream((out / "puzzle.clvm").read_bytes(), b"\x80", [] if case["valid"] else None, result, "(q . ())" if case["valid"] else "(x)")
    print(f"{count} PUBLICKEY host/raw/conversion cases passed." + (" Independent Python CLVM results and successful costs matched." if args.with_upstream else ""))


if __name__ == "__main__":
    main()
