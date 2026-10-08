"""Collection fixture conformance, deterministic CLI artifacts and optional Python CLVM.

Uses the standard library unless --with-upstream is selected. Installs nothing.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile

from verify_m2b import invoke
from verify_m2_branches import expected_tree, upstream

ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    data = json.loads((ROOT / "docs/spec/m2-collections-cases.json").read_text(encoding="utf-8"))
    active = [case for case in data["cases"] if "superseded_by" not in case]
    original = json.loads((ROOT / "docs/spec/source-cases.json").read_text(encoding="utf-8"))
    for identifier in ["short-circuit", "pair-and-list", "empty-list-inference", "contract-return"]:
        case = next(case for case in original["cases"] if case["id"] == identifier)
        if not case["accept"]:
            active.append({"id": "m0-" + identifier, "source": case["source"], "check": "reject", "diagnostic": case["diagnostic"]})
            continue
        active.append({"id": "m0-" + identifier, "source": case["source"], "check": "accept", "execution": {"conditions": case["expected_conditions"]}})
    assert len(active) == 35
    assert len({case["id"] for case in active}) == len(active)
    return active


def main(case_loader=fixtures, label="collection"):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file():
        parser.error("Build the CLI first or supply --binary PATH")
    cases = case_loader()
    accepted = rejected = failures = 0
    with tempfile.TemporaryDirectory(prefix="0xbasic collections ") as temp:
        root = Path(temp)
        for case in cases:
            source = root / (case["id"] + ".bas")
            source.write_text(case["source"], encoding="utf-8", newline="\n")
            output = root / case["id"]
            if case["check"] == "reject":
                for command in [["check", source], ["build", source, "--out", output]]:
                    result = invoke(binary, command, 1)
                    assert result["diagnostics"][0]["code"] == case["diagnostic"], case["id"]
                assert not output.exists()
                rejected += 1
                continue
            accepted += 1
            invoke(binary, ["check", source])
            invoke(binary, ["build", source, "--out", output])
            repeated = root / (case["id"] + "-repeat")
            invoke(binary, ["build", source, "--out", repeated])
            original_files = {p.name: p.read_bytes() for p in output.iterdir()}
            assert original_files == {p.name: p.read_bytes() for p in repeated.iterdir()}, case["id"]
            execution = case["execution"]
            failed = "diagnostic" in execution
            result = invoke(binary, ["run", output / "manifest.json"], 3 if failed else 0)
            if failed:
                failures += 1
                assert result["diagnostics"][0]["code"] == execution["diagnostic"]
                expected = None
                reference = "(x)"
            else:
                conditions = execution["conditions"]
                assert all(c[0] == 83 and len(c) == 2 for c in conditions)
                expected = [c[1] for c in conditions]
                assert result["result"]["tree"] == expected_tree(expected), case["id"]
                # Expected condition trees come from specification fixtures, never compiler output.
                reference = "(q . (" + " ".join(f"(83 {height})" for height in expected) + "))"
            if args.with_upstream:
                upstream((output / "puzzle.clvm").read_bytes(), reference, expected, result)
    print(f"{len(cases)} {label} cases passed: {accepted} accepted ({failures} expected runtime failures), {rejected} rejected; repeated artifacts identical."
          + (" Python CLVM results and successful generated-program costs matched." if args.with_upstream else ""))


if __name__ == "__main__":
    main()
