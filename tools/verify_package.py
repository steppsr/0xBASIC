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


def has_loops(metadata):
    return metadata["compiler"] in {"0.2.0-alpha.1", "0.3.0-alpha.1"}


def has_fees(metadata):
    return metadata["compiler"] == "0.3.0-alpha.1"


FEE_FILES = {f"examples/payment-fee{suffix}" for suffix in
             (".bas", ".bindings.json", ".partial.json", ".exact.json", ".zero-fee.json")}


def verify_fee(call, root, label):
    """Independent fee oracle for extracted binaries and both offline rebuilds."""
    source, bindings_path = "examples/payment-fee.bas", "examples/payment-fee.bindings.json"
    call(["check", source])
    view = call(["explain", source, "--bindings", bindings_path, "--stage", "clvm"])["result"]["representation"]
    call(["build", source, "--bindings", bindings_path, "--out", label])
    manifest_path = f"{label}/manifest.json"
    snapshot = {p.name: p.read_bytes() for p in (root / label).iterdir()}
    require(set(snapshot) == {"manifest.json", "template.clvm", "template.hex", "puzzle.clvm", "puzzle.hex"}, "Fee artifact inventory")
    manifest = json.loads(snapshot["manifest.json"])
    require(manifest["compiler"]["version"] == "0.3.0-alpha.1", "Fee compiler identity mismatch")
    for role in ("template", "puzzle"):
        require(bytes.fromhex(view[role]["hex"]) == snapshot[f"{role}.clvm"]
                and bytes.fromhex(snapshot[f"{role}.hex"].decode()) == snapshot[f"{role}.clvm"]
                and view[role]["tree_hash"] == manifest[role]["tree_hash"]
                and hashlib.sha256(snapshot[f"{role}.clvm"]).hexdigest() == manifest[role]["program_sha256"],
                "Fee inspection/build mismatch")
    bindings = json.loads((root / bindings_path).read_text(encoding="utf-8"))
    owner, recipient, change = [bytes.fromhex(bindings[k]["hex"]) for k in ("owner", "recipient", "changeRecipient")]
    total = int(bindings["inputAmount"])

    def tree(value):
        if isinstance(value, list):
            result = {"atom": ""}
            for item in reversed(value):
                result = {"pair": [tree(item), result]}
            return result
        if isinstance(value, int):
            value = b"" if value == 0 else value.to_bytes((value.bit_length() + 8) // 8, "big", signed=True)
        return {"atom": value.hex()}

    results = {}
    for name, payment, fee in [("partial", 600, 10), ("exact", 990, 10), ("zero-fee", 1000, 0)]:
        solution = f"examples/payment-fee.{name}.json"
        require(json.loads((root / solution).read_text(encoding="utf-8")) == {
            "paymentAmount": str(payment), "feeAmount": str(fee)}, "Fee solution fixture mismatch")
        message = hashlib.sha256(b"0xBASIC/payment-fee/v1\x00" + owner + recipient + change
                    + b"".join(n.to_bytes(8, "big") for n in (total, payment, fee))).digest()
        expected = [[73, total], [50, owner, message], [52, fee], [51, recipient, payment]]
        if total > payment + fee:
            expected.append([51, change, total - payment - fee])
        args = ["run", manifest_path, "--solution", solution]
        execution = call(args)["result"]
        require(execution["tree"] == tree(expected) and execution["validation"] == "clvm-execution-only", "Fee execution mismatch")
        cost = int(execution["cost"])
        require(cost > 0 and call([*args, "--max-cost", str(cost)])["result"] == execution, "Fee exact cost mismatch")
        require(call([*args, "--max-cost", str(cost-1)], 3)["diagnostics"][0]["code"] == "E0501", "Fee short budget mismatch")
        results[name] = {"tree": execution["tree"], "cost": execution["cost"]}
    require(call(["build", source, "--bindings", bindings_path, "--out", label], 4)["diagnostics"][0]["code"] == "E0600", "Fee overwrite gate mismatch")
    require(snapshot == {p.name: p.read_bytes() for p in (root / label).iterdir()}, "Fee artifacts modified")
    return {"tree_hash": manifest["puzzle"]["tree_hash"], "program_sha256": manifest["puzzle"]["program_sha256"], "cases": results}


def verify_loop(call, root, label):
    """Exercise the tutorial with an independent expected condition tree."""
    source = "examples/counted-heights.bas"
    call(["check", source])
    for stage in ("ast", "ir"):
        call(["explain", source, "--stage", stage])
    view = call(["explain", source, "--stage", "clvm"])["result"]["representation"]
    call(["build", source, "--out", label])
    manifest_path = f"{label}/manifest.json"
    manifest = json.loads((root / manifest_path).read_text(encoding="utf-8"))
    blob = (root / label / "puzzle.clvm").read_bytes()
    require(manifest["puzzle"]["tree_hash"] == view["puzzle"]["tree_hash"]
            and hashlib.sha256(blob).hexdigest() == view["puzzle"]["program_sha256"], "Loop inspection mismatch")
    execution = call(["run", manifest_path])["result"]

    def tree(value):
        if isinstance(value, int):
            return {"atom": bytes([value]).hex()}
        result = {"atom": ""}
        for item in reversed(value):
            result = {"pair": [tree(item), result]}
        return result

    require(execution["tree"] == tree([[83, 5], [83, 3], [83, 1]])
            and execution["validation"] == "clvm-execution-only", "Loop tutorial result mismatch")
    cost = int(execution["cost"])
    require(cost > 0, "Missing loop cost")
    require(call(["run", manifest_path, "--max-cost", str(cost)])["result"] == execution, "Loop exact cost mismatch")
    require(call(["run", manifest_path, "--max-cost", str(cost - 1)], 3)["diagnostics"][0]["code"] == "E0501",
            "Loop cost-minus-one gate mismatch")
    before = {p.name: p.read_bytes() for p in (root / label).iterdir()}
    require(call(["build", source, "--out", label], 4)["diagnostics"][0]["code"] == "E0600", "Loop overwrite gate mismatch")
    require(before == {p.name: p.read_bytes() for p in (root / label).iterdir()}, "Loop artifacts overwritten")
    return {"program_sha256": hashlib.sha256(blob).hexdigest(), "tree_hash": manifest["puzzle"]["tree_hash"],
            "cost": execution["cost"], "tree": execution["tree"]}


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
        if has_loops(metadata):
            require({"examples/counted-heights.bas", "LOOPS.md"} <= set(entries), "Missing loop package inputs")
        if has_fees(metadata):
            require(FEE_FILES | {"FEES.md"} <= set(entries), "Missing fee package inputs")
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
        if has_loops(metadata):
            loop = verify_loop(call, root, "loop-build")
            require(all(result == loop for result in source_evidence.get("rebuilt_loops", [])), "Rebuilt loop differs from packaged binary")
            source_evidence["packaged_loop"] = loop
        if has_fees(metadata):
            fee = verify_fee(call, root, "fee-build")
            require(all(result == fee for result in source_evidence.get("rebuilt_fees", [])), "Rebuilt fee differs from packaged binary")
            source_evidence["packaged_fee"] = fee
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
    print(f"PASS: extracted package verified; {report['commands_passed']} CLI commands passed with empty PATH. Report: {args.report}")


if __name__ == "__main__":
    main()
