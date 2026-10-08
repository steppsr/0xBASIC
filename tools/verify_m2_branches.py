"""Check IF/ELSE results and skipped work, optionally against installed Python CLVM."""
import argparse
import io
import os
from pathlib import Path
import tempfile

from verify_m2b import invoke

ROOT = Path(__file__).resolve().parents[1]


def quoted(heights):
    return "(q . (" + " ".join(f"(83 {h})" for h in heights) + "))"


def choose(predicate, yes, no):
    return f"(a (i (q . {int(predicate)}) (q . {yes}) (q . {no})) 1)"


def cases():
    for flag in [False, True]:
        basic = str(flag).upper()
        body = f"DIM h = 10\nEMIT ASSERT_HEIGHT_ABSOLUTE(1)\nIF {basic} THEN\nDIM extra = 10\nh = h + extra\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nELSE\nDIM extra = 20\nh = h + extra\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n"
        yield body, choose(flag, quoted([1, 20, 20]), quoted([1, 30, 30])), [1, 20, 20] if flag else [1, 30, 30]
        body = f"IF {basic} THEN\nDIM unused = ASSERT_HEIGHT_ABSOLUTE(-1)\nELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(7)\nEND IF\n"
        yield body, choose(flag, "(x)", quoted([7])), None if flag else [7]
        body = f"IF {basic} THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(8)\nELSE\nASSERT FALSE\nEND IF\n"
        yield body, choose(flag, quoted([8]), "(x)"), [8] if flag else None
        yield f"IF {basic} THEN\nELSE\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(9)\n", choose(flag, quoted([9]), quoted([9])), [9]
        for inner in [False, True]:
            body = f"EMIT ASSERT_HEIGHT_ABSOLUTE(1)\nIF {basic} THEN\nIF {str(inner).upper()} THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(2)\nELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(3)\nEND IF\nELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(7)\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(9)\n"
            reference = choose(flag, choose(inner, quoted([1, 2, 9]), quoted([1, 3, 9])), quoted([1, 7, 9]))
            yield body, reference, [1, (2 if inner else 3) if flag else 7, 9]


def elseif_cases():
    for a in [False, True]:
        for b in [False, True]:
            for c in [False, True]:
                selected = 1 if a else 2 if b else 3 if c else 4
                body = "DIM h = 0\nEMIT ASSERT_HEIGHT_ABSOLUTE(9)\n"
                for index, predicate in enumerate([a, b, c]):
                    body += f"{'IF' if index == 0 else 'ELSEIF'} {str(predicate).upper()} THEN\nDIM local = {index + 1}\nh = local\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n"
                body += "ELSE\nh = 4\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n"
                reference = choose(a, quoted([9, 1, 1]), choose(b, quoted([9, 2, 2]), choose(c, quoted([9, 3, 3]), quoted([9, 4, 4]))))
                yield body, reference, [9, selected, selected]
    for flag in [False, True]:
        body = f"IF {str(flag).upper()} THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(1)\nELSEIF TRUE THEN\nDIM unused = ASSERT_HEIGHT_ABSOLUTE(-1)\nEND IF\n"
        yield body, choose(flag, quoted([1]), choose(True, "(x)", quoted([]))), [1] if flag else None
        body = f"EMIT ASSERT_HEIGHT_ABSOLUTE(9)\nIF FALSE THEN\nASSERT FALSE\nELSEIF {str(flag).upper()} THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(2)\nEND IF\n"
        yield body, choose(False, "(x)", choose(flag, quoted([9, 2]), quoted([9]))), [9, 2] if flag else [9]


def expected_tree(heights):
    tree = {"atom": ""}
    for height in reversed(heights):
        atom = "" if height == 0 else height.to_bytes((height.bit_length() + 8) // 8, "big").hex()
        tree = {"pair": [{"pair": [{"atom": "53"}, {"pair": [{"atom": atom}, {"atom": ""}]}]}, tree]}
    return tree


def upstream(puzzle, reference, expected, result):
    from clvm import SExp, run_program
    from clvm.EvalError import EvalError
    from clvm.operators import OPERATOR_LOOKUP
    from clvm.serialize import sexp_from_stream
    from clvm_tools.binutils import assemble

    generated = sexp_from_stream(io.BytesIO(puzzle), SExp.to)
    for program in [assemble(reference), generated]:
        try:
            cost, output = run_program(program, SExp.to([]), OPERATOR_LOOKUP)
        except EvalError:
            assert expected is None
        else:
            assert expected is not None
            assert output.as_bin() == SExp.to([[83, h] for h in expected]).as_bin()
            if program is generated:
                assert str(cost) == result["result"]["cost"]


def cost_cases(binary, directory, with_upstream, elseif=False):
    work = " * ".join(["9" * 500] * 8)
    for index, (predicate, expensive_yes) in enumerate([(False, True), (True, False), (True, True), (False, False)]):
        expensive = f"DIM unused = {work}\n"
        yes, no = (expensive, "") if expensive_yes else ("", expensive)
        body = f"IF {str(predicate).upper()} THEN\n{yes}ELSE\n{no}END IF\n"
        skipped = predicate != expensive_yes
        if elseif:
            skipped = index < 2
            prefix = ["IF TRUE THEN\n", "IF FALSE THEN\nELSEIF TRUE THEN\n", "IF FALSE THEN\n", "IF FALSE THEN\nELSEIF FALSE THEN\n"][index]
            body = prefix + f"ELSEIF {work} > 0 THEN\nEND IF\n"
        source = directory / "cost.bas"
        source.write_text(f"CONTRACT CostFixture()\n{body}END CONTRACT\n", encoding="utf-8")
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    parser.add_argument("--elseif", action="store_true", help="Check first-match chains and skipped later predicates")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file():
        parser.error("Build the CLI first or supply --binary PATH")
    count = 0
    with tempfile.TemporaryDirectory(prefix="0xbasic branches ") as directory:
        directory = Path(directory)
        for count, (body, reference, expected) in enumerate(elseif_cases() if args.elseif else cases(), start=1):
            source = directory / "branch.bas"
            source.write_text(f"CONTRACT BranchFixture()\n{body}END CONTRACT\n", encoding="utf-8", newline="\n")
            out = directory / str(count)
            invoke(binary, ["check", source])
            invoke(binary, ["build", source, "--out", out])
            result = invoke(binary, ["run", out / "manifest.json"], 3 if expected is None else 0)
            if expected is None:
                assert result["diagnostics"][0]["code"] == "E0500" and result["result"] is None
            else:
                assert result["result"]["tree"] == expected_tree(expected)
            if args.with_upstream:
                upstream((out / "puzzle.clvm").read_bytes(), reference, expected, result)
        cost_cases(binary, directory, args.with_upstream, args.elseif)
    mode = "IF/ELSEIF/ELSE" if args.elseif else "IF/ELSE"
    print(f"{count} {mode} cases and 4 execution-budget cases passed" + (" with independent Python CLVM checks." if args.with_upstream else "."))


if __name__ == "__main__":
    main()
