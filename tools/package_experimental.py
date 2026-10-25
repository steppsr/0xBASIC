"""Build, archive and verify a native experimental CLI package; never publish a release."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tomllib
import uuid
import zipfile

from verify_package import require, verify
from package_sources import assemble

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / ".work/packages"
    out.mkdir(parents=True, exist_ok=True)
    report = out / ("package-windows.json" if os.name == "nt" else "package-linux.json")
    report.unlink(missing_ok=True)
    staging = out / ("candidate-" + uuid.uuid4().hex)
    staging.mkdir()
    toolchain = subprocess.check_output(["rustc", "-vV"], cwd=ROOT, text=True)
    rust = dict(line.split(": ", 1) for line in toolchain.splitlines() if ": " in line)
    host = rust["host"]
    require(host in {"x86_64-pc-windows-msvc", "x86_64-unknown-linux-gnu"}, "Only native x86_64 Windows/Linux packages are supported")
    require(rust["release"] == "1.95.0", "Use pinned Rust 1.95.0")
    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    subprocess.run(["cargo", "build", "--release", "--locked", "-p", "oxbasic-cli", "--target", host], cwd=ROOT, check=True)
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    if not target.is_absolute():
        target = ROOT / target
    executable = "0xbasic.exe" if os.name == "nt" else "0xbasic"
    binary = target / host / "release" / executable
    payload = {f"bin/{executable}": binary.read_bytes(), "LICENSE": (ROOT / "LICENSE").read_bytes(),
               "PACKAGE.md": (ROOT / "docs/spec/package-usage.md").read_bytes()}
    for name in ("height-locked-payment.bas", "height-locked-payment.bindings.json"):
        payload[f"examples/{name}"] = (ROOT / "examples" / name).read_bytes()
    payload.update(assemble(staging))
    sources = [ROOT / name for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml")]
    sources += sorted(path for path in (ROOT / "crates").rglob("*") if path.suffix in {".rs", ".toml"})
    baseline = json.loads((ROOT / "docs/spec/m5-regression-baseline.json").read_text(encoding="utf-8"))
    payment = next(case["expected"] for case in baseline["cases"] if case["id"] == "payment")
    metadata = {"schema_version": 1, "experimental": True, "compiler": version, "target": host,
                "rust_version": rust["release"], "cargo_lock_sha256": hashlib.sha256((ROOT / "Cargo.lock").read_bytes()).hexdigest(),
                "build_os": platform.system(), "build_libc": list(platform.libc_ver()),
                "source_hashes": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()},
                "payment_tree_hash": payment["puzzle_tree_hash"], "payment_result": payment["tree"]}
    payload["package.json"] = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
    name = f"0xbasic-{version}-experimental-{host}"
    archive = staging / (name + (".zip" if os.name == "nt" else ".tar.gz"))
    if os.name == "nt":
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for name, data in sorted(payload.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o755 if name.startswith("bin/") else 0o644) << 16
                handle.writestr(info, data)
    else:
        with archive.open("wb") as output, gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as handle:
                for name, data in sorted(payload.items()):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(data), 0o755 if name.startswith("bin/") else 0o644
                    handle.addfile(info, io.BytesIO(data))
    checksum = archive.with_name(archive.name + ".sha256")
    checksum.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="ascii")
    evidence = verify(archive, rebuild_source=True)
    archive.replace(out / archive.name)
    checksum.replace(out / checksum.name)
    report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PASS: experimental package built and verified; 8 extracted CLI commands passed. Archive: {out / archive.name}")
    print(f"Evidence: {report}")


if __name__ == "__main__":
    main()
