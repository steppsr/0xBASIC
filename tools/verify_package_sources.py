"""Validate and optionally rebuild the embedded application/library source archive."""
import hashlib
import io
import json
import os
from pathlib import PurePosixPath
import shutil
import subprocess
import tarfile

from verify_package import require


def verify_sources(data, root, metadata, rebuild=False):
    source = root / "source-rebuild"
    source.mkdir()
    files = {}
    size = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for item in archive:
            path = PurePosixPath(item.name)
            require(item.isfile() and not path.is_absolute() and ".." not in path.parts
                    and "\\" not in item.name and ":" not in item.name, "Unsafe source entry")
            require(item.name not in files and len(files) < 40000 and item.size < 64 * 1024 * 1024,
                    "Invalid source inventory")
            size += item.size
            require(size < 1024 * 1024 * 1024, "Source archive too large")
            blob = archive.extractfile(item).read()
            files[item.name] = hashlib.sha256(blob).hexdigest()
            target = source.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            if os.name != "nt":
                target.chmod(item.mode & 0o777)
    index = json.loads((source / "SOURCE-MANIFEST.json").read_text(encoding="utf-8"))
    require(set(files) == set(index) | {"SOURCE-MANIFEST.json"}, "Source inventory mismatch")
    require(all(files[name] == digest for name, digest in index.items()), "Source hash mismatch")
    for name, digest in metadata["source_hashes"].items():
        require(index.get(name) == digest, f"Binary/source provenance differs: {name}")
    require(files["Cargo.lock"] == metadata["cargo_lock_sha256"], "Source lock mismatch")
    require((source / ".cargo/config.toml").is_file() and (source / "vendor/malachite-bigint/src/lib.rs").is_file(),
            "Missing rebuild inputs")
    for name in ("REBUILD.md", "THIRD-PARTY-NOTICES.txt"):
        require(files[name] == metadata["files"][name], f"Source/binary notice mismatch: {name}")
    if not rebuild:
        return {"source_files_verified": len(index), "offline_rebuilds": 0}
    env = os.environ.copy()
    env.update(CARGO_HOME=str(root / "empty-cargo-home"), CARGO_TARGET_DIR=str(root / "source-target"),
               CARGO_NET_OFFLINE="true", RUSTUP_TOOLCHAIN="1.95.0")

    def build(label, locked):
        command = ["cargo", "build", "--release", "--offline", "-p", "oxbasic-cli"]
        if locked:
            command.append("--locked")
        print(f"Verifying {label} from extracted sources with an empty Cargo cache", flush=True)
        process = subprocess.run(command, cwd=source, env=env, capture_output=True, timeout=600)
        require(process.returncode == 0, f"{label} failed: {process.stderr.decode(errors='replace')}")
        executable = root / "source-target/release" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")

        def invoke(args):
            result = subprocess.run([str(executable), *args, "--json"], cwd=source, env=env,
                                    capture_output=True, timeout=20)
            require(result.returncode == 0 and not result.stderr, f"{label}: rebuilt CLI failure")
            return json.loads(result.stdout)["result"]

        invoke(["build", "examples/height-locked-payment.bas", "--bindings",
                "examples/height-locked-payment.bindings.json", "--out", label])
        result = invoke(["run", f"{label}/manifest.json"])
        manifest = json.loads((source / label / "manifest.json").read_text(encoding="utf-8"))
        require(manifest["puzzle"]["tree_hash"] == metadata["payment_tree_hash"]
                and result["tree"] == metadata["payment_result"] and result["cost"] == "1487727",
                f"{label}: rebuilt payment differs")

    build("original-source", True)
    modified = source / "modified-libraries/malachite-bigint"
    shutil.copytree(source / "vendor/malachite-bigint", modified)
    with (modified / "src/lib.rs").open("a", encoding="utf-8") as handle:
        handle.write('\npub const OXBASIC_RELINK_PROBE: &str = "local source modification";\n')
    with (source / "Cargo.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[patch.crates-io]\nmalachite-bigint = { path = "modified-libraries/malachite-bigint" }\n')
    build("modified-library", False)
    resolved = json.loads(subprocess.check_output(["cargo", "metadata", "--offline", "--format-version", "1"], cwd=source, env=env))
    package = next(p for p in resolved["packages"] if p["name"] == "malachite-bigint")
    require(package["source"] is None and "modified-libraries" in package["manifest_path"], "Local library override not used")
    return {"source_files_verified": len(index), "offline_rebuilds": 2, "modified_library": "malachite-bigint 0.9.2"}
