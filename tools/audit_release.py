"""Inventory locked release dependencies and available notices; not a license clearance."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu")


def main():
    platforms = {}
    for target in TARGETS:
        metadata = json.loads(subprocess.check_output(
            ["cargo", "metadata", "--format-version", "1", "--locked", "--offline", "--filter-platform", target],
            cwd=ROOT))
        packages = {p["id"]: p for p in metadata["packages"]}
        nodes = {n["id"]: n for n in metadata["resolve"]["nodes"]}
        root = next(p["id"] for p in metadata["packages"] if p["name"] == "oxbasic-cli" and p["source"] is None)
        paths = {root: ["oxbasic-cli"]}
        pending = [root]
        while pending:
            current = pending.pop(0)
            for dep in nodes[current]["deps"]:
                if not any(kind["kind"] != "dev" for kind in dep["dep_kinds"]):
                    continue
                child = dep["pkg"]
                if child not in paths:
                    paths[child] = paths[current] + [packages[child]["name"]]
                    pending.append(child)
        inventory = []
        for identity in sorted(paths, key=lambda key: (packages[key]["name"], packages[key]["version"])):
            package = packages[identity]
            if package["source"] is None:
                continue
            directory = Path(package["manifest_path"]).parent
            notices = {}
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.name.lower().startswith(("license", "licence", "copying", "notice")):
                    notices[path.relative_to(directory).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
            inventory.append({"name": package["name"], "version": package["version"],
                              "declared_license": package["license"], "license_file": package["license_file"],
                              "repository": package["repository"], "dependency_path": paths[identity],
                              "available_notice_sha256": notices})
        platforms[target] = inventory
        flagged = [p["name"] for p in inventory if "LGPL" in (p["declared_license"] or "")]
        missing = [p["name"] for p in inventory if not p["available_notice_sha256"]]
        print(f"{target}: {len(inventory)} normal/build dependencies; LGPL metadata: {flagged}; no bundled notice found: {missing}")
    evidence = {"schema_version": 1, "scope": "normal/build dependency graph; includes build-only crates; not a linked-symbol or legal-compliance determination",
                "cargo_lock_sha256": hashlib.sha256((ROOT / "Cargo.lock").read_bytes()).hexdigest(),
                "platforms": platforms}
    destination = ROOT / "docs/spec/dependency-license-inventory.json"
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {destination}; distribution review remains open.")


if __name__ == "__main__":
    main()
