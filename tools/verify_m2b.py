"""Check integer arithmetic through the CLI; optionally compare Python CLVM.

Default uses only the Python standard library and the built debug CLI.
--with-upstream uses installed clvm/clvm_tools; it installs nothing.
"""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
# BASIC input, separately written CLVM arithmetic, mathematically expected value.
CASES = [
    ("2 + 3 * 4", "(+ (q . 2) (* (q . 3) (q . 4)))", 14),
    ("(2 + 3) * 4", "(* (+ (q . 2) (q . 3)) (q . 4))", 20),
    ("20 - 5 - 2", "(- (- (q . 20) (q . 5)) (q . 2))", 13),
    ("-(-128)", "(- (q . 0) (- (q . 0) (q . 128)))", 128),
    ("-0", "(- (q . 0) (q . 0))", 0),
    ("18446744073709551616 - 18446744073709551615", "(- (q . 18446744073709551616) (q . 18446744073709551615))", 1),
    ("18446744073709551616 * 18446744073709551616 - 340282366920938463463374607431768211455", "(- (* (q . 18446744073709551616) (q . 18446744073709551616)) (q . 340282366920938463463374607431768211455))", 1),
    ("&HFFFFFFFF + 1 - 1", "(- (+ (q . 4294967295) (q . 1)) (q . 1))", 4294967295),
    ("-1", "(- (q . 0) (q . 1))", -1),
    ("4294967296", "(q . 4294967296)", 4294967296),
    ("1 - 2", "(- (q . 1) (q . 2))", -1),
]


def invoke(binary, args, status=0):
    run = subprocess.run([str(binary), *map(str, args), "--json"], capture_output=True, text=True)
    assert run.returncode == status, (args, run.returncode, run.stdout, run.stderr)
    assert not run.stderr, run.stderr
    value = json.loads(run.stdout)
    assert value["ok"] == (status == 0)
    return value


def check_upstream(puzzle, expression, expected, result, valid):
    from clvm import SExp, run_program
    from clvm.operators import OPERATOR_LOOKUP
    from clvm.serialize import sexp_from_stream
    from clvm_tools.binutils import assemble
    from clvm.EvalError import EvalError

    _, arithmetic = run_program(assemble(expression), SExp.to([]), OPERATOR_LOOKUP)
    assert arithmetic.as_int() == expected
    program = sexp_from_stream(io.BytesIO(puzzle), SExp.to)
    if valid:
        cost, output = run_program(program, SExp.to([]), OPERATOR_LOOKUP)
        assert output.as_bin() == SExp.to([[83, expected]]).as_bin()
        assert str(cost) == result["result"]["cost"]
    else:
        try:
            run_program(program, SExp.to([]), OPERATOR_LOOKUP)
        except EvalError:
            pass
        else:
            raise AssertionError("Python CLVM accepted invalid height")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    parser.add_argument("--locals", action="store_true", help="Exercise DIM initialization and case-insensitive aliases")
    parser.add_argument("--assignments", action="store_true", help="Exercise assignment to an existing INTEGER local")
    parser.add_argument("--constants", action="store_true", help="Exercise compile-time INTEGER constants and immutable aliases")
    parser.add_argument("--conditions", action="store_true", help="Exercise CONDITION locals, alias snapshots, and typed EMIT")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file():
        parser.error("Build the CLI first or supply --binary PATH")
    with tempfile.TemporaryDirectory(prefix="0xbasic arithmetic ") as directory:
        directory = Path(directory)
        source = directory / "arithmetic.bas"
        for index, (basic, reference, expected) in enumerate(CASES):
            body = f" DIM value AS INTEGER = {basic}\n DIM alias = VALUE\n EMIT ASSERT_HEIGHT_ABSOLUTE(ALIAS)" if args.locals else f" EMIT ASSERT_HEIGHT_ABSOLUTE({basic})"
            if args.assignments:
                body = f" DIM value AS INTEGER = 123\n VALUE = {basic}\n DIM alias = value\n value = 0\n EMIT ASSERT_HEIGHT_ABSOLUTE(ALIAS)"
            if args.constants:
                body = f" CONST value AS INTEGER = {basic}\n CONST alias = VALUE + 0\n DIM mutable = alias\n mutable = 0\n EMIT ASSERT_HEIGHT_ABSOLUTE(ALIAS)"
            if args.conditions:
                body = f" DIM pending AS CONDITION = ASSERT_HEIGHT_ABSOLUTE({basic})\n DIM alias = PENDING\n pending = ASSERT_HEIGHT_ABSOLUTE(123)\n EMIT (ALIAS)"
            source.write_text(f"CONTRACT Arithmetic()\n{body}\nEND CONTRACT\n", encoding="utf-8", newline="\n")
            out = directory / str(index)
            invoke(binary, ["check", source])
            invoke(binary, ["build", source, "--out", out])
            valid = 0 <= expected <= 4294967295
            result = invoke(binary, ["run", out / "manifest.json"], 0 if valid else 3)
            if valid:
                atom = "" if expected == 0 else expected.to_bytes((expected.bit_length() + 8) // 8, "big").hex()
                tree = {"pair": [{"pair": [{"atom": "53"}, {"pair": [{"atom": atom}, {"atom": ""}]}]}, {"atom": ""}]}
                assert result["result"]["tree"] == tree
            else:
                assert result["diagnostics"][0]["code"] == "E0500"
                assert result["result"] is None
            if args.with_upstream:
                check_upstream((out / "puzzle.clvm").read_bytes(), reference, expected, result, valid)
    print(f"{len(CASES)} integer/range cases passed (locals={args.locals}, assignments={args.assignments}, constants={args.constants}, conditions={args.conditions})" + (" with independent Python CLVM arithmetic, execution, and cost comparisons." if args.with_upstream else "."))


if __name__ == "__main__":
    main()
