"""Verify the M1 CLI against a separately assembled CLVM reference.

Default requires only Python's standard library and a built debug CLI.
--with-upstream additionally needs installed clvm and clvm_tools.
--write-vectors --with-upstream regenerates the reviewed golden file.
No network, wallet, or node access.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "crates/compiler/tests/fixtures/m1-height.json"
# Explicit, independently assembled ABI checks. Quote branch programs because
# CLVM evaluates arguments eagerly; apply only the selected branch.
TEMPLATE = """
(a (i (l 1)
      (q . (a (i (= 2 (q . ()))
                 (q . (a (i (= 3 (q . ()))
                            (q . (q . ((83 100))))
                            (q . (x))) 1))
                 (q . (x))) 1))
      (q . (x))) 1)
"""


def upstream_vector():
    from clvm_tools.binutils import assemble
    from clvm import SExp, run_program
    from clvm.operators import OPERATOR_LOOKUP

    def tree_hash(node):
        if node.pair is None:
            return hashlib.sha256(b"\x01" + node.atom).digest()
        left, right = node.pair
        return hashlib.sha256(b"\x02" + tree_hash(SExp.to(left)) + tree_hash(SExp.to(right))).digest()

    template = assemble(TEMPLATE)
    puzzle = assemble(f"(a (q . {TEMPLATE}) (c (q . ()) 1))")
    cost, result = run_program(puzzle, SExp.to([]), OPERATOR_LOOKUP)
    assert result.as_bin().hex() == "ffff53ff648080"
    for bad in [1, [1], (b"", 1)]:
        try:
            run_program(puzzle, SExp.to(bad), OPERATOR_LOOKUP)
        except Exception:
            pass
        else:
            raise AssertionError(f"reference accepted malformed solution {bad!r}")
    return {
        "source": "CONTRACT HeightFixture()\n    EMIT ASSERT_HEIGHT_ABSOLUTE(100)\nEND CONTRACT\n",
        "template_hex": template.as_bin().hex(),
        "puzzle_hex": puzzle.as_bin().hex(),
        "template_tree_hash": tree_hash(template).hex(),
        "puzzle_tree_hash": tree_hash(puzzle).hex(),
        "result_hex": result.as_bin().hex(),
        "cost": str(cost),
    }


def invoke(binary, *args):
    result = subprocess.run([str(binary), *map(str, args), "--json"], capture_output=True, text=True, check=True)
    assert not result.stderr, result.stderr
    value = json.loads(result.stdout)
    assert value["ok"], value
    return value["result"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-upstream", action="store_true")
    parser.add_argument("--write-vectors", action="store_true")
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    if args.write_vectors and not args.with_upstream:
        parser.error("--write-vectors requires --with-upstream")
    if args.with_upstream:
        reference = upstream_vector()
        print("Reference versions:", {p: importlib.metadata.version(p) for p in ["clvm", "clvm_tools"]})
        if args.write_vectors:
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(json.dumps(reference, indent=2) + "\n", encoding="utf-8", newline="\n")
    vector = json.loads(GOLDEN.read_text(encoding="utf-8"))
    if args.with_upstream:
        assert vector == reference
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    executable = "0xbasic.exe" if os.name == "nt" else "0xbasic"
    binary = (args.binary or target / "debug" / executable).resolve()
    if not binary.is_file():
        parser.error(f"CLI not found at {binary}. Run cargo build --workspace --locked, or supply --binary PATH for a custom Cargo output layout.")
    with tempfile.TemporaryDirectory(prefix="0xbasic reference ") as directory:
        directory = Path(directory)
        source = directory / "height fixture.bas"
        source.write_text(vector["source"], encoding="utf-8", newline="\n")
        out = directory / "output with spaces"
        invoke(binary, "build", source, "--out", out)
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        for stem in ["template", "puzzle"]:
            assert (out / f"{stem}.clvm").read_bytes().hex() == vector[f"{stem}_hex"]
            assert manifest[stem]["tree_hash"] == vector[f"{stem}_tree_hash"]
        result = invoke(binary, "run", out / "manifest.json")
        assert result["cost"] == vector["cost"]
        assert result["validation"] == "clvm-execution-only"
    print("M1 golden bytes, tree hashes, CLI execution, and cost verified.")


if __name__ == "__main__":
    main()
