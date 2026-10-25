"""Execute the payment tutorial's actual command blocks in an isolated directory."""
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

from verify_m3_payments import expected_tree

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs/spec/payment-tutorial.md"
STEPS = ["version", "check", "ast", "ir", "clvm", "build", "run", "cost-failure", "overwrite-failure"]


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def snapshot(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    work = ROOT / ".work/m5"
    work.mkdir(parents=True, exist_ok=True)
    report = work / ("tutorial-windows.json" if os.name == "nt" else "tutorial-linux.json")
    report.unlink(missing_ok=True)
    require(binary.is_file(), "Build the CLI first or pass --binary")
    blocks = re.findall(r"<!-- tutorial:([a-z-]+) -->\s*```text\s*\n(.*?)\n```",
                        DOCUMENT.read_text(encoding="utf-8"), re.S)
    require([name for name, _ in blocks] == STEPS, "Missing, duplicate or reordered tutorial commands")
    run = work / ("tutorial-" + uuid.uuid4().hex)
    examples = run / "examples"
    examples.mkdir(parents=True)
    for name in ["height-locked-payment.bas", "height-locked-payment.bindings.json"]:
        shutil.copyfile(ROOT / "examples" / name, examples / name)
    print(f"Tutorial working directory: {run}", flush=True)
    results = {}
    artifact = run / "payment-tutorial-build"
    before = None
    for name, command in blocks:
        tokens = shlex.split(command)
        require(tokens and tokens[0] == "0xbasic" and "\n" not in command.strip(), f"Unsupported command block: {name}")
        process = subprocess.run([str(binary), *tokens[1:]], cwd=run, capture_output=True, timeout=20)
        (run / f"{name}.stdout").write_bytes(process.stdout)
        (run / f"{name}.stderr").write_bytes(process.stderr)
        status = {"cost-failure": 3, "overwrite-failure": 4}.get(name, 0)
        require(process.returncode == status and not process.stderr, f"{name}: unexpected status/stderr; inspect {run}")
        value = json.loads(process.stdout)
        if name == "version":
            require(value == {"compiler": "0.1.0-m3.8b", "language": "0.1", "abi": 1,
                              "target_profile": "chia-clvm-0.19-strict-v1"}, "Tutorial version identifiers changed")
        else:
            require(value["schema_version"] == 1 and value["ok"] == (status == 0), f"{name}: envelope")
            if status:
                code = "E0501" if name == "cost-failure" else "E0600"
                require(value["result"] is None and value["diagnostics"][0]["code"] == code, f"{name}: diagnostic")
            else:
                require(value["diagnostics"] == [], f"{name}: unexpected diagnostic")
        results[name] = value
        if name in {"version", "check", "ast", "ir", "clvm"}:
            require(not artifact.exists(), f"{name}: unexpected artifacts")
        if name == "build":
            before = snapshot(artifact)
        if name in {"run", "cost-failure", "overwrite-failure"}:
            require(snapshot(artifact) == before, f"{name}: modified published artifacts")
        print(f"PASS: tutorial {name}", flush=True)
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
    require(set(before) == {"manifest.json", "template.clvm", "template.hex", "puzzle.clvm", "puzzle.hex"}, "Artifact list")
    view = results["clvm"]["result"]["representation"]
    for role in ("template", "puzzle"):
        require(bytes.fromhex(view[role]["hex"]) == before[f"{role}.clvm"], "Explain/build bytes differ")
        require(view[role]["tree_hash"] == manifest[role]["tree_hash"], "Explain/build hash differs")
    for name in ("ast", "ir"):
        require(results[name]["result"]["stage"] == name and
                results[name]["result"]["source"]["sha256"] == manifest["source"]["sha256"], "Inspection source differs")
    vector = json.loads((ROOT / "docs/spec/vectors.json").read_text(encoding="utf-8"))["payment"]
    conditions = [[73, int(vector["amount"])], [83, int(vector["earliest_height"])],
                  [50, vector["owner_hex"], vector["application_message_hex"]],
                  [51, vector["recipient_hex"], int(vector["amount"])]]
    execution = results["run"]["result"]
    require(execution["validation"] == "clvm-execution-only" and execution["cost"] == "1487727"
            and execution["tree"] == expected_tree(conditions), "Tutorial payment result differs from original vector")
    evidence = {"schema_version": 1, "steps": STEPS, "commands": dict(blocks),
                "document_sha256": hashlib.sha256(DOCUMENT.read_bytes()).hexdigest(),
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
                "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "puzzle_tree_hash": manifest["puzzle"]["tree_hash"], "local_cost": execution["cost"]}
    temporary = run / "success.json"
    temporary.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report)
    print(f"PASS: all 9 documented payment commands and expected results verified. Report: {report}")


if __name__ == "__main__":
    main()
