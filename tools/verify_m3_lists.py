"""LIST boundary CLI cases and optional independent Python CLVM execution."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m3_inputs import upstream
from verify_m3_pairs import raw_value

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary PATH")
    cases = json.loads((ROOT / "docs/spec/m3-list-boundary-cases.json").read_text(encoding="utf-8"))
    count = 0
    with tempfile.TemporaryDirectory(prefix="0xbasic lists ") as temp:
        root = Path(temp)
        for fixed in [False, True]:
            source = root / "list.bas"
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
                value = json.loads(c["json"])["value"]
                if fixed:
                    for item in value: item["rest"]["hex"] = item["rest"]["hex"].lower()
                    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                    assert manifest["bindings"] == {"value": value}
                if args.with_upstream:
                    raw = b"\x80" if fixed else b"\xff" + b"".join(b"\xff" + raw_value(item) for item in value) + b"\x80\x80"
                    upstream((out / "puzzle.clvm").read_bytes(), raw, [], result, "(q . ())")
        source.write_text("CONTRACT Demo()\nSOLUTION value AS LIST OF BOOLEAN\nEND CONTRACT\n", encoding="utf-8")
        out = root / "raw"
        invoke(binary, ["build", source, "--out", out])
        for raw, valid in [('ff8080', True), ('ffff01ff808080', True), ('ff0180', False), ('ffff028080', False), ('ffff01ff028080', False), ('ffff01ff008080', False), ('ffff01ff8200018080', False), ('ffffff01808080', False), ('ffff010180', False), ('ffff010080', False), ('80', False), ('ff80ff8080', False)]:
            count += 1
            path = root / "raw.hex"
            path.write_text(raw, encoding="utf-8")
            result = invoke(binary, ["run", out / "manifest.json", "--solution-hex", path], 0 if valid else 3)
            if not valid: assert result["diagnostics"][0]["code"] == "E0500"
            if args.with_upstream:
                upstream((out / "puzzle.clvm").read_bytes(), bytes.fromhex(raw), [] if valid else None, result, "(q . ())" if valid else "(x)")
    print(f"{count} LIST host/raw cases passed." + (" Independent Python CLVM results and successful costs matched." if args.with_upstream else ""))


if __name__ == "__main__":
    main()
