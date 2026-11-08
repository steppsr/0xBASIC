"""Execute the payment/change tutorial's command blocks and verify their results."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import uuid

from verify_payment_change import oracle, require

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs/spec/payment-change-tutorial.md"
STEPS = ["check", "clvm", "build", "partial", "exact"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    work = ROOT / ".work/payment-change"
    work.mkdir(parents=True, exist_ok=True)
    report = work / ("tutorial-windows.json" if os.name == "nt" else "tutorial-linux.json")
    report.unlink(missing_ok=True)
    require(binary.is_file(), "Build the CLI first or pass --binary")
    blocks = re.findall(r"<!-- payment-change:([a-z-]+) -->\s*```text\s*\n(.*?)\n```",
                        DOCUMENT.read_text(encoding="utf-8"), re.S)
    require([name for name, _ in blocks] == STEPS, "Missing, duplicate or reordered tutorial commands")
    run = work / ("tutorial-" + uuid.uuid4().hex)
    (run / "examples").mkdir(parents=True)
    sources = [ROOT / "examples" / name for name in ["payment-change.bas", "payment-change.bindings.json",
               "payment-change.partial.json", "payment-change.exact.json"]]
    for source in sources:
        shutil.copyfile(source, run / "examples" / source.name)
    artifact = run / "payment-change-tutorial-build"
    results = {}
    snapshot = None
    for name, command in blocks:
        tokens = shlex.split(command)
        require(tokens and tokens[0] == "0xbasic" and "\n" not in command.strip(), "Unsupported tutorial command")
        process = subprocess.run([str(binary), *tokens[1:]], cwd=run, capture_output=True, timeout=20)
        (run / f"{name}.stdout").write_bytes(process.stdout)
        (run / f"{name}.stderr").write_bytes(process.stderr)
        require(process.returncode == 0 and not process.stderr, f"{name}: failed; inspect {run}")
        value = json.loads(process.stdout)
        require(value["schema_version"] == 1 and value["ok"] and not value["diagnostics"], f"{name}: envelope")
        results[name] = value["result"]
        if name in {"check", "clvm"}:
            require(not artifact.exists(), "Inspection wrote artifacts")
        elif name == "build":
            snapshot = {p.name: p.read_bytes() for p in artifact.iterdir()}
        else:
            require({p.name: p.read_bytes() for p in artifact.iterdir()} == snapshot, "Execution changed artifacts")
    require(set(snapshot) == {"manifest.json", "template.clvm", "template.hex", "puzzle.clvm", "puzzle.hex"}, "Artifact inventory")
    manifest = json.loads(snapshot["manifest.json"])
    require(manifest["compiler"]["version"] == "0.3.0-alpha.1", "Tutorial compiler identity differs")
    view = results["clvm"]["representation"]
    for role in ("template", "puzzle"):
        require(bytes.fromhex(view[role]["hex"]) == snapshot[f"{role}.clvm"], "Inspection/build bytes differ")
        require(bytes.fromhex(snapshot[f"{role}.hex"].decode()) == snapshot[f"{role}.clvm"], "Artifact hex differs")
        require(view[role]["tree_hash"] == manifest[role]["tree_hash"], "Inspection/build hash differs")
        require(hashlib.sha256(snapshot[f"{role}.clvm"]).hexdigest() == manifest[role]["program_sha256"], "Byte hash differs")
    bindings = json.loads(sources[1].read_text(encoding="utf-8"))
    messages = {}
    for name, amount in [("partial", 600), ("exact", 1000)]:
        expected, messages[name] = oracle(bindings, amount)
        require(results[name]["tree"] == expected and results[name]["validation"] == "clvm-execution-only"
                and int(results[name]["cost"]) > 0, f"{name}: unexpected execution result")
    require(messages["partial"] != messages["exact"], "Payment must change the application message")
    evidence = {"schema_version": 1, "commands": dict(blocks), "steps": STEPS,
                "input_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [DOCUMENT, Path(__file__).resolve(), ROOT / "tools/verify_payment_change.py", *sources]},
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "puzzle_tree_hash": manifest["puzzle"]["tree_hash"], "application_messages": messages,
                "local_costs": {name: results[name]["cost"] for name in ("partial", "exact")},
                "validation": "clvm-execution-only", "spends_submitted": False}
    temporary = run / "success.json"
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report)
    print(f"PASS: all 5 documented payment/change commands and expected results verified. Report: {report}")


if __name__ == "__main__":
    main()
