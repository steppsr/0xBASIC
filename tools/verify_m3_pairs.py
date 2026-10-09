"""PAIR boundary CLI cases and optional independent Python CLVM execution."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m3_inputs import upstream

ROOT = Path(__file__).resolve().parents[1]


def atom(data):
    assert len(data) < 64
    return data if len(data) == 1 and data[0] < 128 else bytes([128 + len(data)]) + data


def raw_value(value):
    if isinstance(value, bool): return atom(b"\x01" if value else b"")
    if isinstance(value, str): return atom(value.encode("utf-8"))
    if "hex" in value: return atom(bytes.fromhex(value["hex"]))
    return b"\xff" + raw_value(value["first"]) + raw_value(value["rest"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary PATH")
    cases = json.loads((ROOT / "docs/spec/m3-pair-cases.json").read_text(encoding="utf-8"))
    count = 0
    with tempfile.TemporaryDirectory(prefix="0xbasic pairs ") as temp:
        root = Path(temp)
        for fixed in [False, True]:
            source = root / "pair.bas"
            ty = cases["type"]
            source.write_text(f"CONTRACT Demo(value AS {ty})\nEND CONTRACT\n" if fixed else f"CONTRACT Demo()\nSOLUTION value AS {ty}\nEND CONTRACT\n", encoding="utf-8")
            for c in cases["cases"]:
                count += 1
                values = root / "values.json"
                values.write_text(c["json"], encoding="utf-8")
                out = root / f"{fixed}-{c['id']}"
                build = ["build", source, "--out", out] + (["--bindings", values] if fixed else [])
                result = invoke(binary, build, 1 if fixed and not c["valid"] else 0)
                if fixed and not c["valid"]:
                    assert result["diagnostics"][0]["code"] == "E0301"
                    assert not out.exists()
                    continue
                result = invoke(binary, ["run", out / "manifest.json"] + ([] if fixed else ["--solution", values]), 0 if c["valid"] else 1)
                if not c["valid"]:
                    assert result["diagnostics"][0]["code"] == "E0300"
                    continue
                assert result["result"]["tree"] == {"atom": ""}
                value = next(iter(json.loads(c["json"]).values()))
                if fixed:
                    value["rest"]["rest"]["hex"] = value["rest"]["rest"]["hex"].lower()
                    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                    assert manifest["bindings"] == {"value": value}
                if args.with_upstream:
                    raw = b"\x80" if fixed else b"\xff" + raw_value(value) + b"\x80"
                    upstream((out / "puzzle.clvm").read_bytes(), raw, [], result, "(q . ())")
        source.write_text("CONTRACT Demo()\nSOLUTION value AS PAIR OF (INTEGER, PAIR OF (BOOLEAN, STRING))\nEND CONTRACT\n", encoding="utf-8")
        out = root / "raw"
        invoke(binary, ["build", source, "--out", out])
        for raw, valid in [('ffff07ff016180', True), ('ffff80ff808080', True), ('ffff00ff016180', False), ('ffff07ff026180', False), ('ffff07ff0181ff80', False), ('ff0780', False), ('ffff078080', False), ('ffff07ff01ff618080', False), ('80', False), ('ffff07ff016101', False)]:
            count += 1
            path = root / "raw.hex"
            path.write_text(raw, encoding="utf-8")
            result = invoke(binary, ["run", out / "manifest.json", "--solution-hex", path], 0 if valid else 3)
            if not valid: assert result["diagnostics"][0]["code"] == "E0500"
            if args.with_upstream:
                upstream((out / "puzzle.clvm").read_bytes(), bytes.fromhex(raw), [] if valid else None, result, "(q . ())" if valid else "(x)")
    print(f"{count} PAIR host/raw cases passed." + (" Independent Python CLVM results and successful costs matched." if args.with_upstream else ""))


if __name__ == "__main__":
    main()
