"""Check an experimental archive and exercise only its extracted executable/files."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
import zipfile


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def verify(archive, rebuild_source=False):
    archive = archive.resolve()
    checksum = archive.with_name(archive.name + ".sha256").read_text(encoding="ascii").strip()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    require(checksum == f"{digest}  {archive.name}", "Archive checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="0xbasic extracted package ") as temporary:
        root = Path(temporary)
        entries = {}
        modes = {}
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as handle:
                for item in handle.infolist():
                    require(not item.is_dir() and item.file_size < 64 * 1024 * 1024, "Invalid archive entry")
                    require(item.filename not in entries, "Duplicate archive entry")
                    entries[item.filename] = handle.read(item)
                    modes[item.filename] = (item.external_attr >> 16) & 0o777
        else:
            with tarfile.open(archive, "r:gz") as handle:
                for item in handle:
                    require(item.isfile() and item.size < 64 * 1024 * 1024, "Invalid tar entry")
                    require(item.name not in entries, "Duplicate archive entry")
                    entries[item.name] = handle.extractfile(item).read()
                    modes[item.name] = item.mode & 0o777
        require(0 < len(entries) < 100, "Unexpected package file count")
        for name, data in entries.items():
            path = PurePosixPath(name)
            require(not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name,
                    "Unsafe package path")
            target = root.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if os.name != "nt":
                target.chmod(modes[name])
        metadata = json.loads(entries["package.json"])
        require(metadata["schema_version"] == 1 and metadata["experimental"] is True, "Invalid metadata")
        require(set(entries) == set(metadata["files"]) | {"package.json"}, "Package inventory mismatch")
        for name, expected in metadata["files"].items():
            require(hashlib.sha256(entries[name]).hexdigest() == expected, f"File hash mismatch: {name}")
        require({"source.tar.gz", "THIRD-PARTY-NOTICES.txt", "REBUILD.md"} <= set(entries), "Missing source or notice materials")
        from verify_package_sources import verify_sources
        source_evidence = verify_sources(entries["source.tar.gz"], root, metadata, rebuild_source)
        binary_name = "bin/0xbasic.exe" if os.name == "nt" else "bin/0xbasic"
        binary = root / binary_name
        require(binary_name in metadata["files"], "Wrong package platform")
        if os.name != "nt":
            require(modes[binary_name] & 0o111, "Archived binary is not executable")
        env = os.environ.copy()
        env.update(PATH="", CARGO_HOME=str(root / "unavailable-cargo"), RUSTUP_HOME=str(root / "unavailable-rustup"))
        calls = 0

        def call(args, status=0, json_mode=True):
            nonlocal calls
            calls += 1
            output = subprocess.run([str(binary), *args, *(["--json"] if json_mode else [])],
                                    cwd=root, env=env, capture_output=True, timeout=20)
            require(output.returncode == status and not output.stderr, f"Package command failed: {args}: {output}")
            result = json.loads(output.stdout)
            if json_mode:
                require(result["schema_version"] == 1 and result["ok"] == (status == 0), "CLI envelope mismatch")
            return result

        version = call(["--version"], json_mode=False)
        require(version["compiler"] == metadata["compiler"] and version["abi"] == 1, "Package version mismatch")
        require("usage" in call(["--help"], json_mode=False), "Missing package help")
        source = "examples/height-locked-payment.bas"
        bindings = "examples/height-locked-payment.bindings.json"
        call(["check", source])
        view = call(["explain", source, "--stage", "clvm", "--bindings", bindings])["result"]["representation"]
        call(["build", source, "--bindings", bindings, "--out", "payment-build"])
        manifest = json.loads((root / "payment-build/manifest.json").read_text(encoding="utf-8"))
        require(manifest["puzzle"]["tree_hash"] == view["puzzle"]["tree_hash"], "Package inspection hash mismatch")
        require(manifest["compiler"]["cargo_lock_sha256"] == metadata["cargo_lock_sha256"], "Build lock mismatch")
        require(manifest["compiler"]["rust_version"] == metadata["rust_version"], "Build toolchain mismatch")
        execution = call(["run", "payment-build/manifest.json"])["result"]
        require(execution["validation"] == "clvm-execution-only" and execution["cost"] == "1487727", "Package execution mismatch")
        require(manifest["puzzle"]["tree_hash"] == metadata["payment_tree_hash"]
                and execution["tree"] == metadata["payment_result"], "Frozen payment baseline mismatch")
        require(call(["run", "payment-build/manifest.json", "--max-cost", "1"], 3)["diagnostics"][0]["code"] == "E0501", "Cost gate mismatch")
        before = {p.name: p.read_bytes() for p in (root / "payment-build").iterdir()}
        require(call(["build", source, "--bindings", bindings, "--out", "payment-build"], 4)["diagnostics"][0]["code"] == "E0600", "Overwrite gate mismatch")
        require(before == {p.name: p.read_bytes() for p in (root / "payment-build").iterdir()}, "Package overwrote artifacts")
    return {"schema_version": 1, "archive": archive.name, "archive_sha256": digest,
            "compiler": metadata["compiler"], "target": metadata["target"], "commands_passed": calls,
            "path_empty": True, "outside_checkout": True, "resources_closed": True, **source_evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--rebuild-source", action="store_true", help="Also build original sources and a locally modified library offline")
    args = parser.parse_args()
    args.report.unlink(missing_ok=True)
    report = verify(args.archive, args.rebuild_source)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PASS: extracted package verified; 8 CLI commands passed with empty PATH. Report: {args.report}")


if __name__ == "__main__":
    main()
