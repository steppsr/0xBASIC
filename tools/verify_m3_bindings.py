"""INTEGER fixed-binding artifacts and independent CLVM execution checks."""
import argparse
import json
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke
from verify_m2_branches import expected_tree
from verify_m3_inputs import upstream, integer_list
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary",type=Path)
    parser.add_argument("--with-upstream",action="store_true")
    args=parser.parse_args()
    target=Path(os.environ.get("CARGO_TARGET_DIR") or ROOT/"target")
    binary=(args.binary or target/"debug"/("0xbasic.exe" if os.name=="nt" else "0xbasic")).resolve()
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary PATH")
    data=json.loads((ROOT/"docs/spec/m3-binding-cases.json").read_text(encoding="utf-8"))
    assert len(data["cases"])==16
    with tempfile.TemporaryDirectory(prefix="0xbasic fixed ") as temp:
        root=Path(temp); source=root/"fixed source.bas";source.write_text(data["source"],encoding="utf-8",newline="\n")
        invoke(binary,["check",source]);invoke(binary,["build",source,"--out",root/"template","--template-only"])
        template=(root/"template/template.clvm").read_bytes()
        meta=json.loads((root/"template/manifest.json").read_text(encoding="utf-8"));assert meta["bindings"] is None and meta["puzzle"] is None
        invoke(binary,["run",root/"template/manifest.json"],2)
        solution=root/"solution.json";solution.write_text(json.dumps(data["solution"]),encoding="utf-8")
        for c in data["cases"]:
            bindings=root/"bindings.json";bindings.write_text(c["bindings_json"],encoding="utf-8")
            out=root/c["id"]
            result=invoke(binary,["build",source,"--out",out,"--bindings",bindings],1 if "diagnostic" in c else 0)
            if "diagnostic" in c:
                assert result["diagnostics"][0]["code"]==c["diagnostic"]
                assert not out.exists()
                continue
            assert (out/"template.clvm").read_bytes()==template
            repeated=root/(c["id"]+"-repeat")
            invoke(binary,["build",source,"--out",repeated,"--bindings",bindings])
            assert {f.name:f.read_bytes() for f in out.iterdir()}=={f.name:f.read_bytes() for f in repeated.iterdir()}
            manifest=json.loads((out/"manifest.json").read_text(encoding="utf-8"))
            values={k.lower():v for k,v in json.loads(c["bindings_json"]).items()}
            assert manifest["bindings"]==values
            assert [f["name"] for f in manifest["fixed_parameters"]]==["base","stride"]
            assert [f["name"] for f in manifest["inputs"]]==["offset"]
            failed="diagnostic" in c["execution"]
            result=invoke(binary,["run",out/"manifest.json","--solution",solution],3 if failed else 0)
            expected=None if failed else [v[1] for v in c["execution"]["conditions"]]
            if failed: assert result["diagnostics"][0]["code"]=="E0500"
            else: assert result["result"]["tree"]==expected_tree(expected)
            if args.with_upstream:
                height=f"(+ (q . {values['base']}) (q . {values['stride']}) (f 1))"
                reference="(x)" if failed else f"(c (c (q . 83) (c {height} (q . ()))) (q . ()))"
                upstream((out/"puzzle.clvm").read_bytes(),integer_list([7]),expected,result,reference)
        assert (root/"normal/puzzle.clvm").read_bytes()==(root/"case-and-order/puzzle.clvm").read_bytes()
        assert (root/"normal/puzzle.clvm").read_bytes()!=(root/"changed/puzzle.clvm").read_bytes()
    print("16 fixed-binding cases passed; template identity and repeated artifacts verified."+(" Python CLVM results, references and successful costs matched." if args.with_upstream else ""))


if __name__=="__main__": main()
