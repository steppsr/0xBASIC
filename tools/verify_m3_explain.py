"""Verify read-only AST/IR inspection without CLVM execution."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
from verify_m2b import invoke

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file(): parser.error("Build the CLI first or supply --binary")
    with tempfile.TemporaryDirectory(prefix="0xbasic explain ") as temp:
        root = Path(temp)
        source = root / "inspect.bas"
        for example in ["height-locked-payment.bas", "m2-early-return.bas"]:
            data = (ROOT / "examples" / example).read_bytes()
            source.write_bytes(data)
            for stage in ["ast", "ir"]:
                command = ["explain", source, "--stage", stage]
                result = invoke(binary, command)
                assert result == invoke(binary, command)
                view = result["result"]
                assert view["stage"] == stage
                assert view["source"] == {"name": source.name, "sha256": hashlib.sha256(data).hexdigest()}
                assert view["compiler_version"] and view["representation"]
                if stage == "ast":
                    assert any(n["kind"] == "Return" for n in view["representation"]["nodes"])
        source.write_text("CONTRACT Demo(n AS INTEGER)\nASSERT FALSE\nEND CONTRACT\n", encoding="utf-8")
        for stage in ["ast", "ir"]: invoke(binary, ["explain", source, "--stage", stage])
        source.write_text("CONTRACT Demo()\nEMIT unknown\nEND CONTRACT\n", encoding="utf-8")
        invoke(binary, ["explain", source, "--stage", "ast"])
        assert invoke(binary, ["explain", source, "--stage", "ir"], 1)["diagnostics"] == invoke(binary, ["check", source], 1)["diagnostics"]
        for stage in ["CLVM", "unknown"]:
            assert invoke(binary, ["explain", source, "--stage", stage], 2)["diagnostics"][0]["code"] == "E0400"
        assert list(root.iterdir()) == [source]
        source.write_bytes((ROOT / "examples/height-locked-payment.bas").read_bytes())
        for template_only in [False, True]:
            flags = ["--template-only"] if template_only else ["--bindings", ROOT / "examples/height-locked-payment.bindings.json"]
            before = set(root.iterdir())
            command = ["explain", source, "--stage", "clvm", *flags]
            explained = invoke(binary, command)
            assert explained == invoke(binary, command)
            assert set(root.iterdir()) == before
            r = explained["result"]["representation"]
            out = root / ("template" if template_only else "bound")
            invoke(binary, ["build", source, "--out", out, *flags])
            import json
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            assert r["bindings"] == manifest["bindings"]
            for name in ["template", "puzzle"]:
                if template_only and name == "puzzle":
                    assert r[name] is None
                    continue
                program = r[name]
                assert bytes.fromhex(program["hex"]) == (out / (name + ".clvm")).read_bytes()
                assert program["program_sha256"] == manifest[name]["program_sha256"]
                hashes = [None] * len(program["nodes"])
                for i in reversed(range(len(hashes))):
                    node = program["nodes"][i]
                    payload = b"\x01" + bytes.fromhex(node["atom"]) if "atom" in node else b"\x02" + b"".join(hashes[j] for j in node["pair"])
                    hashes[i] = hashlib.sha256(payload).digest()
                assert hashes[program["root"]].hex() == program["tree_hash"] == manifest[name]["tree_hash"]

    print("M3 AST/IR/CLVM views, source digests, diagnostics, reproducibility and read-only behavior verified.")

if __name__ == "__main__":
    main()
