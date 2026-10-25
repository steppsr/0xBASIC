"""Assemble notices and complete vendored application sources for redistribution."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib

from verify_package import require

ROOT = Path(__file__).resolve().parents[1]
SUPPLEMENTS = {"blst": "blst", "chia-bls": "chia_rs", "chia-sha2": "chia_rs",
               "chia-traits": "chia_rs", "chia_streamable_macro": "chia_rs",
               "malachite-base": "malachite", "malachite-bigint": "malachite", "malachite-nz": "malachite"}


def assemble(staging):
    source = staging / "source-tree"
    source.mkdir()
    vendor = source / "vendor"
    print("Vendoring complete locked source dependencies", flush=True)
    process = subprocess.run(["cargo", "vendor", "--locked", str(vendor)], cwd=ROOT,
                             capture_output=True, text=True, check=True)
    (staging / "vendor.log").write_text(process.stderr, encoding="utf-8")
    (source / ".cargo").mkdir()
    (source / ".cargo/config.toml").write_text(
        '[source.crates-io]\nreplace-with = "vendored-sources"\n\n[source.vendored-sources]\ndirectory = "vendor"\n', encoding="utf-8")
    for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml", "LICENSE"):
        shutil.copyfile(ROOT / name, source / name)
    for name in ("crates", "examples", "docs/spec", "tools", "distribution"):
        for path in sorted((ROOT / name).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                destination = source / path.relative_to(ROOT)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
    provenance_root = ROOT / "distribution/upstream-notices"
    provenance = json.loads((provenance_root / "sources.json").read_text(encoding="utf-8"))
    for item in provenance:
        require(hashlib.sha256((provenance_root / item["path"]).read_bytes()).hexdigest() == item["sha256"],
                f"Supplemental license changed: {item['path']}")
    sections = ["0xBASIC third-party notices\n\nThe project is Apache-2.0 licensed. Dependencies retain their stated licenses.\n"
                "The complete source bundle accompanies this binary. It includes library and application sources, build files,\n"
                "and instructions to rebuild with modified libraries. Modification and reverse engineering for debugging\n"
                "such modifications are permitted; no additional package restriction overrides those rights.\n"
                "This inventory includes all locked crates, including build-only and other-platform sources.\n"]
    packages = []
    for directory in sorted(vendor.iterdir()):
        package = tomllib.loads((directory / "Cargo.toml").read_text(encoding="utf-8"))["package"]
        notices = {p.relative_to(directory).as_posix(): p.read_bytes() for p in sorted(directory.rglob("*"))
                   if p.is_file() and p.name.lower().startswith(("license", "licence", "copying", "notice", "authors", "copyright"))}
        extra = []
        if package["name"] in SUPPLEMENTS:
            group = SUPPLEMENTS[package["name"]]
            vcs = json.loads((directory / ".cargo_vcs_info.json").read_text(encoding="utf-8"))["git"]["sha1"]
            extra = [item for item in provenance if item["path"].startswith(group + "/")]
            require(extra and all(item["commit"] == vcs for item in extra), f"License/source revision mismatch: {package['name']}")
            for item in extra:
                notices["upstream/" + item["path"]] = (provenance_root / item["path"]).read_bytes()
        require(notices, f"No notices found: {package['name']}")
        declared = package.get("license") or package.get("license-file")
        require(declared, f"No license metadata: {package['name']}")
        heading = f"{package['name']} {package['version']}\nDeclared license: {declared}\n"
        if package["name"] == "r-efi":
            heading += "Distribution uses the MIT alternative; the upstream AUTHORS terms and credits follow.\n"
        sections.append("\n" + "=" * 72 + "\n" + heading)
        for name, data in notices.items():
            sections.append(f"\n--- {name} ---\n" + data.decode("utf-8") + "\n")
        packages.append({"name": package["name"], "version": package["version"], "declared_license": declared,
                         "notice_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in notices.items()}})
    notice = "".join(sections).encode("utf-8")
    (source / "THIRD-PARTY-NOTICES.txt").write_bytes(notice)
    rebuild = (ROOT / "distribution/REBUILD.md").read_bytes()
    (source / "REBUILD.md").write_bytes(rebuild)
    (source / "DEPENDENCIES.json").write_text(json.dumps(packages, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths = sorted(p for p in source.rglob("*") if p.is_file())
    index = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (source / "SOURCE-MANIFEST.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    archive = staging / "source.tar.gz"
    with archive.open("wb") as output, gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as handle:
            for path in sorted(p for p in source.rglob("*") if p.is_file()):
                data = path.read_bytes()
                entry = tarfile.TarInfo(path.relative_to(source).as_posix())
                entry.size = len(data)
                entry.mode = 0o755 if path.suffix in {".sh", ".py", ".pl"} else 0o644
                handle.addfile(entry, io.BytesIO(data))
    print(f"Assembled {len(packages)} locked crates, {len(index)} source files and complete notices", flush=True)
    return {"source.tar.gz": archive.read_bytes(), "THIRD-PARTY-NOTICES.txt": notice, "REBUILD.md": rebuild}
