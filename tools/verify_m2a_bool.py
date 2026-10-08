"""Verify BOOLEAN/comparison/ASSERT CLI behavior; optionally compare Python CLVM.

Uses the standard library unless --with-upstream selects installed clvm/clvm_tools.
Does not install dependencies or connect to a node.
"""
import argparse
import io
import os
from pathlib import Path
import tempfile

from verify_m2b import invoke

ROOT = Path(__file__).resolve().parents[1]


def cases():
    for left, right in [(-2, -1), (0, 0), (128, 127), (2**128, 2**128 - 1), (-2**128, -2**128 + 1)]:
        l, r = f"(q . {left})", f"(q . {right})"
        for symbol, clvm, expected in [
            ("=", f"(= {l} {r})", left == right),
            ("<>", f"(not (= {l} {r}))", left != right),
            ("<", f"(> {r} {l})", left < right),
            ("<=", f"(not (> {l} {r}))", left <= right),
            (">", f"(> {l} {r})", left > right),
            (">=", f"(not (> {r} {l}))", left >= right),
        ]:
            yield f"{left} {symbol} {right}", clvm, expected
    yield "NOT FALSE", "(not (q . ()))", True
    yield "NOT TRUE", "(not (q . 1))", False
    yield "TRUE = FALSE", "(= (q . 1) (q . ()))", False
    yield "FALSE <> TRUE", "(not (= (q . ()) (q . 1)))", True
    yield "NOT 1 = 2", "(not (= (q . 1) (q . 2)))", True
    yield "(1 < 2) = TRUE", "(= (> (q . 2) (q . 1)) (q . 1))", True


def short_cases():
    def lazy(left, right, is_and):
        yes, no = (right, "(q . ())") if is_and else ("(q . 1)", right)
        return f"(a (i {left} (q . {yes}) (q . {no})) 1)"

    for a in [False, True]:
        for b in [False, True]:
            for is_and in [False, True]:
                op = "AND" if is_and else "OR"
                reference = lazy(f"(q . {int(a)})", f"(q . {int(b)})", is_and)
                yield f"{str(a).upper()} {op} {str(b).upper()}", reference, (a and b) if is_and else (a or b)
    t, f = "(q . 1)", "(q . ())"
    yield "TRUE OR FALSE AND FALSE", lazy(t, lazy(f, f, True), False), True
    yield "FALSE AND (TRUE OR FALSE)", lazy(f, lazy(t, f, False), True), False
    yield "(TRUE OR FALSE) AND (FALSE OR TRUE)", lazy(lazy(t, f, False), lazy(f, t, False), True), True
    yield "FALSE OR (TRUE AND FALSE)", lazy(f, lazy(t, f, True), False), False


def cost_cases(binary, directory, with_upstream):
    expensive = " * ".join(["9" * 500] * 8)
    for index, (left, op, skipped) in enumerate([("FALSE", "AND", True), ("TRUE", "OR", True), ("TRUE", "AND", False), ("FALSE", "OR", False)]):
        source = directory / "cost.bas"
        source.write_text(f"CONTRACT CostCheck()\nDIM unused = {left} {op} ({expensive} > 0)\nEND CONTRACT\n", encoding="utf-8")
        out = directory / f"cost-{index}"
        invoke(binary, ["build", source, "--out", out])
        result = invoke(binary, ["run", out / "manifest.json", "--max-cost", "10000"], 0 if skipped else 3)
        if skipped:
            assert result["result"]["tree"] == {"atom": ""}
        else:
            assert result["diagnostics"][0]["code"] == "E0501"
        if with_upstream:
            from clvm import SExp, run_program
            from clvm.EvalError import EvalError
            from clvm.operators import OPERATOR_LOOKUP
            from clvm.serialize import sexp_from_stream
            program = sexp_from_stream(io.BytesIO((out / "puzzle.clvm").read_bytes()), SExp.to)
            try:
                cost, output = run_program(program, SExp.to([]), OPERATOR_LOOKUP, max_cost=10000)
            except EvalError:
                assert not skipped
            else:
                assert skipped and output.as_bin() == b"\x80"
                assert str(cost) == result["result"]["cost"]


def upstream(puzzle, reference, expected, result):
    from clvm import SExp, run_program
    from clvm.EvalError import EvalError
    from clvm.operators import OPERATOR_LOOKUP
    from clvm.serialize import sexp_from_stream
    from clvm_tools.binutils import assemble

    _, comparison = run_program(assemble(reference), SExp.to([]), OPERATOR_LOOKUP)
    assert comparison.as_bin() == (b"\x01" if expected else b"\x80")
    # Independent lazy assertion, returning no conditions when true.
    assertion = assemble(f"(a (i {reference} (q . (q . ())) (q . (x))) 1)")
    generated = sexp_from_stream(io.BytesIO(puzzle), SExp.to)
    for program in [assertion, generated]:
        try:
            cost, output = run_program(program, SExp.to([]), OPERATOR_LOOKUP)
        except EvalError:
            assert not expected
        else:
            assert expected
            assert output.as_bin() == b"\x80"
            if program is generated:
                assert str(cost) == result["result"]["cost"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    parser.add_argument("--short-circuit", action="store_true", help="Check AND/OR truth tables, nesting, and execution budgets")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file():
        parser.error("Build the CLI first or supply --binary PATH")
    count = 0
    with tempfile.TemporaryDirectory(prefix="0xbasic booleans ") as directory:
        directory = Path(directory)
        source = directory / "boolean.bas"
        for expression, reference, expected in (short_cases() if args.short_circuit else cases()):
            for declaration in ["DIM", "CONST"]:
                body = f"{declaration} value AS BOOLEAN = {expression}\nDIM saved = VALUE\nDIM mutable = saved\nmutable = NOT mutable\nASSERT saved"
                source.write_text(f"CONTRACT BooleanChecks()\n{body}\nEND CONTRACT\n", encoding="utf-8", newline="\n")
                out = directory / str(count)
                invoke(binary, ["check", source])
                invoke(binary, ["build", source, "--out", out])
                result = invoke(binary, ["run", out / "manifest.json"], 0 if expected else 3)
                if expected:
                    assert result["result"]["tree"] == {"atom": ""}
                else:
                    assert result["diagnostics"][0]["code"] == "E0500"
                    assert result["result"] is None
                if args.with_upstream:
                    upstream((out / "puzzle.clvm").read_bytes(), reference, expected, result)
                count += 1
        if args.short_circuit:
            cost_cases(binary, directory, args.with_upstream)
            print("4 short-circuit execution-budget cases passed.")
    print(f"{count} BOOLEAN/comparison/assertion cases passed" + (" with independent Python CLVM results, failures, and cost comparisons." if args.with_upstream else "."))


if __name__ == "__main__":
    main()
