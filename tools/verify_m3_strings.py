"""STRING boundary CLI conformance, optionally checked with independent Python CLVM."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m3_inputs import upstream

ROOT = Path(__file__).resolve().parents[1]


def atom_list(data):
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
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary PATH")
    cases = json.loads((ROOT / "docs/spec/m3-string-cases.json").read_text(encoding="utf-8"))["cases"]
    count = 0
    with tempfile.TemporaryDirectory(prefix="0xbasic strings ") as temp:
        root = Path(temp)
        for fixed in [False, True]:
            source = root / "text.bas"
            source.write_text("CONTRACT Demo(value AS STRING)\nEND CONTRACT\n" if fixed else "CONTRACT Demo()\nSOLUTION value AS STRING\nEND CONTRACT\n", encoding="utf-8")
            host = [(json.dumps(bytes.fromhex(c["hex"]).decode("utf-8")), bytes.fromhex(c["hex"])) for c in cases if c["valid"]]
            host += [(v, None) for v in ['"\\ud800"', '"\\udc00"', '"\\ud800x"', 'null', '1', 'false', '{"hex":"61"}', '[]']]
            for index, (json_value, data) in enumerate(host):
                count += 1
                out = root / f"host-{fixed}-{index}"
                values = root / "values.json"
                values.write_text('{"VALUE":' + json_value + '}', encoding="utf-8")
                build = ["build", source, "--out", out] + (["--bindings", values] if fixed else [])
                result = invoke(binary, build, 1 if fixed and data is None else 0)
                if fixed and data is None:
                    assert result["diagnostics"][0]["code"] == "E0301"
                    assert not out.exists()
                    continue
                result = invoke(binary, ["run", out / "manifest.json"] + ([] if fixed else ["--solution", values]), 1 if data is None else 0)
                if data is None:
                    assert result["diagnostics"][0]["code"] == "E0300"
                    continue
                assert result["result"]["tree"] == {"atom": ""}
                if fixed:
                    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                    assert manifest["bindings"] == {"value": data.decode("utf-8")}
                if args.with_upstream:
                    upstream((out / "puzzle.clvm").read_bytes(), b"\x80" if fixed else atom_list(data), [], result, "(q . ())")
            if not fixed:
                out = root / "raw"
                invoke(binary, ["build", source, "--out", out])
                raw_cases = [(atom_list(bytes.fromhex(c["hex"])), c["valid"]) for c in cases]
                raw_cases += [(bytes.fromhex(raw), False) for raw in ['ffff018080', '80', 'ff6101', 'ff61ff6280']]
                for raw, valid in raw_cases:
                    count += 1
                    path = root / "solution.hex"
                    path.write_text(raw.hex(), encoding="utf-8")
                    result = invoke(binary, ["run", out / "manifest.json", "--solution-hex", path], 0 if valid else 3)
                    if not valid: assert result["diagnostics"][0]["code"] == "E0500"
                    if args.with_upstream:
                        upstream((out / "puzzle.clvm").read_bytes(), raw, [] if valid else None, result, "(q . ())" if valid else "(x)")
    print(f"{count} STRING host/raw cases passed." + (" Independent Python CLVM results and successful costs matched." if args.with_upstream else ""))


if __name__ == "__main__":
    main()
