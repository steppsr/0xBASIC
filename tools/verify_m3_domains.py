"""AMOUNT/PUZZLEHASH boundary CLI checks with optional independent Python CLVM execution."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m3_inputs import upstream

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file():
        parser.error("Build the CLI first or supply --binary PATH")
    count = 0
    with tempfile.TemporaryDirectory(prefix="0xbasic domains ") as temp:
        root = Path(temp)
        for ty, cases in [
            ("AMOUNT", [('"0"', 'ff8080'), ('"128"', 'ff82008080'), ('"18446744073709551615"', 'ff8900ffffffffffffffff80'), ('"-1"', None), ('"18446744073709551616"', None), ('"-0"', None), ('"01"', None), ('1', None)]),
            ("PUZZLEHASH", [(json.dumps({"hex":"Af"*32}), 'ffa0'+'af'*32+'80'), (json.dumps({"hex":"00"*32}), 'ffa0'+'00'*32+'80'), (json.dumps({"hex":"00"*31}), None), (json.dumps({"hex":"00"*33}), None), ('{"hex":"","hex":""}', None)]),
        ]:
            for fixed in [False, True]:
                source = root / "scalar.bas"
                source.write_text(f"CONTRACT Demo(value AS {ty})\nEND CONTRACT\n" if fixed else f"CONTRACT Demo()\nSOLUTION value AS {ty}\nEND CONTRACT\n", encoding="utf-8")
                for index, (value, raw) in enumerate(cases):
                    count += 1
                    out = root / f"{ty}-{fixed}-{index}"
                    values = root / "values.json"
                    values.write_text('{"VALUE":' + value + '}', encoding="utf-8")
                    build = ["build", source, "--out", out]
                    if fixed:
                        build += ["--bindings", values]
                    result = invoke(binary, build, 1 if fixed and raw is None else 0)
                    if fixed and raw is None:
                        assert result["diagnostics"][0]["code"] == "E0301"
                        assert not out.exists()
                        continue
                    run = ["run", out / "manifest.json"]
                    if not fixed:
                        run += ["--solution", values]
                    result = invoke(binary, run, 1 if raw is None else 0)
                    if raw is None:
                        assert result["diagnostics"][0]["code"] == "E0300"
                        continue
                    assert result["result"]["tree"] == {"atom": ""}
                    if fixed:
                        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
                        expected = json.loads(value)
                        if ty == "PUZZLEHASH": expected["hex"] = expected["hex"].lower()
                        assert manifest["bindings"] == {"value": expected}
                    if args.with_upstream:
                        upstream((out / "puzzle.clvm").read_bytes(), bytes.fromhex("80" if fixed else raw), [], result, "(q . ())")
                if not fixed:
                    out = root / f"{ty}-raw"
                    invoke(binary, ["build", source, "--out", out])
                    for raw, amount_ok, hash_ok in [('ff8080', True, False), ('ff0180', True, False), ('ff0080', False, False), ('ff82000180', False, False), ('ff81ff80', False, False), ('ff8900ffffffffffffffff80', True, False), ('ff8901000000000000000080', False, False), ('ffa0'+'00'*32+'80', False, True), ('ff9f'+'00'*31+'80', False, False), ('ffa1'+'00'*33+'80', False, False), ('ffff018080', False, False), ('ff0102', False, False), ('80', False, False)]:
                        count += 1
                        valid = amount_ok if ty == "AMOUNT" else hash_ok
                        rawfile = root / "raw.hex"
                        rawfile.write_text(raw, encoding="utf-8")
                        result = invoke(binary, ["run", out / "manifest.json", "--solution-hex", rawfile], 0 if valid else 3)
                        if not valid: assert result["diagnostics"][0]["code"] == "E0500"
                        if args.with_upstream:
                            upstream((out / "puzzle.clvm").read_bytes(), bytes.fromhex(raw), [] if valid else None, result, "(q . ())" if valid else "(x)")
        for index, (expression, valid) in enumerate([
            ("AS_AMOUNT(0)", True), ("AS_AMOUNT(18446744073709551615)", True),
            ("AS_AMOUNT(-1)", False), ("AS_AMOUNT(18446744073709551616)", False),
            ("AS_PUZZLEHASH(0x" + "00"*32 + ")", True), ("AS_PUZZLEHASH(0x)", False),
        ]):
            count += 1
            source = root / "conversion.bas"
            source.write_text(f"CONTRACT Demo()\nDIM unused = {expression}\nEND CONTRACT\n", encoding="utf-8")
            out = root / f"conversion-{index}"
            invoke(binary, ["build", source, "--out", out])
            result = invoke(binary, ["run", out / "manifest.json"], 0 if valid else 3)
            if args.with_upstream:
                upstream((out / "puzzle.clvm").read_bytes(), b"\x80", [] if valid else None, result, "(q . ())" if valid else "(x)")
    print(f"{count} AMOUNT/PUZZLEHASH host and raw boundary cases passed." + (" Python CLVM results and successful costs matched." if args.with_upstream else ""))


if __name__ == "__main__":
    main()
