"""INTEGER SOLUTION source/JSON/raw conformance and optional independent Python CLVM."""
import argparse
import io
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m2_branches import expected_tree

ROOT = Path(__file__).resolve().parents[1]


def upstream(program_bytes, solution_bytes, expected, result, reference):
    from clvm import SExp, run_program
    from clvm.EvalError import EvalError
    from clvm.operators import OPERATOR_LOOKUP
    from clvm.serialize import sexp_from_stream
    from clvm_tools.binutils import assemble
    program = sexp_from_stream(io.BytesIO(program_bytes), SExp.to)
    solution = sexp_from_stream(io.BytesIO(solution_bytes), SExp.to)
    try:
        cost, output = run_program(program, solution, OPERATOR_LOOKUP, max_cost=10000000)
    except EvalError:
        assert expected is None
    else:
        assert expected is not None
        assert output.as_bin() == SExp.to([[83,h] for h in expected]).as_bin()
        assert str(cost) == result["result"]["cost"]
    try:
        _, output = run_program(assemble(reference), solution, OPERATOR_LOOKUP)
    except EvalError:
        assert expected is None
    else:
        assert expected is not None
        assert output.as_bin() == SExp.to([[83,h] for h in expected]).as_bin()


def integer_list(values):
    # Independent canonical integer/list serialization, no compiler encoder.
    output = bytearray()
    for n in values:
        if n == 0:
            atom = b""
        else:
            width = 1
            while not -(1 << (8*width-1)) <= n < (1 << (8*width-1)):
                width += 1
            atom = n.to_bytes(width,"big",signed=True)
        assert len(atom) < 64
        output.append(255)
        output.extend(atom if len(atom)==1 and atom[0]<128 else bytes([128+len(atom)])+atom)
    output.append(128)
    return bytes(output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary",type=Path)
    parser.add_argument("--with-upstream",action="store_true")
    args=parser.parse_args()
    target=Path(os.environ.get("CARGO_TARGET_DIR") or ROOT/"target")
    binary=(args.binary or target/"debug"/("0xbasic.exe" if os.name=="nt" else "0xbasic")).resolve()
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary PATH")
    cases=json.loads((ROOT/"docs/spec/m3-boundary-cases.json").read_text(encoding="utf-8"))["cases"]
    original=json.loads((ROOT/"docs/spec/source-cases.json").read_text(encoding="utf-8"))["cases"]
    for identifier in ["input-shape","condition-input"]:
        c=next(c for c in original if c["id"]==identifier)
        cases.append({"id":"m0-"+identifier,"source":c["source"],"route":"json-solution" if c["accept"] else "source", "solution_json_text":json.dumps(c.get("solution",{})), "diagnostic":c.get("diagnostic"),"execution":{"conditions":[]}})
    cases.append({"id":"example","source":(ROOT/"examples/m3-integer-inputs.bas").read_text(encoding="utf-8"),"route":"json-solution","solution_json_text":'{"height":"7"}',"execution":{"conditions":[[83,7]]}})
    assert len(cases)==26
    with tempfile.TemporaryDirectory(prefix="0xbasic inputs ") as temp:
        root=Path(temp)
        for c in cases:
            source=root/(c["id"]+".bas")
            source.write_text(c["source"],encoding="utf-8",newline="\n")
            out=root/c["id"]
            if c["route"]=="source":
                for command in [["check",source],["build",source,"--out",out]]:
                    result=invoke(binary,command,1)
                    assert result["diagnostics"][0]["code"]==c["diagnostic"],c["id"]
                assert not out.exists()
                continue
            invoke(binary,["check",source])
            invoke(binary,["build",source,"--out",out])
            duplicate=root/(c["id"]+"-repeat")
            invoke(binary,["build",source,"--out",duplicate])
            assert {f.name:f.read_bytes() for f in out.iterdir()}=={f.name:f.read_bytes() for f in duplicate.iterdir()}
            manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
            error=c["execution"].get("diagnostic")
            if c["route"]=="raw-solution":
                path=root/"solution.hex";path.write_text(c["solution_hex"],encoding="ascii")
                option="--solution-hex"; solution=bytes.fromhex(c["solution_hex"])
            else:
                path=root/"solution.json";path.write_text(c["solution_json_text"],encoding="utf-8")
                option="--solution"
                if error != "E0300":
                    values={k.lower():int(v) for k,v in json.loads(c["solution_json_text"]).items()}
                    solution=integer_list([values[f["name"]] for f in manifest["inputs"]])
            result=invoke(binary,["run",out/"manifest.json",option,path],1 if error=="E0300" else 3 if error else 0)
            if error: assert result["diagnostics"][0]["code"]==error,c["id"]
            else: assert result["result"]["tree"]==expected_tree([v[1] for v in c["execution"]["conditions"]]),c["id"]
            if args.with_upstream and error != "E0300":
                expected=None if error else [v[1] for v in c["execution"]["conditions"]]
                reference="(x)" if error else "(q . ())"
                if c["id"] in ["example","declaration-order"]:
                    height="(f 1)" if c["id"]=="example" else "(- (f 1) (f (r 1)))"
                    reference=f"(c (c (q . 83) (c {height} (q . ()))) (q . ()))"
                upstream((out/"puzzle.clvm").read_bytes(),solution,expected,result,reference)
    print("26 INTEGER SOLUTION cases passed; repeated artifacts identical." + (" Python CLVM results, references and successful generated costs matched." if args.with_upstream else ""))


if __name__=="__main__": main()
