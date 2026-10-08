"""Fetch public upstream references for M0; no packages are installed or executed."""

import hashlib
import io
import json
import tarfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".work" / "m0-upstream"
CHIA_COMMIT = "98aba3d176b24b5814e84a33f9d1c11af67a9cdc"
CHIA_RS_COMMIT = "e11b3c8aa97af8f5d0915d72d4ac7b3c3da00cc2"
SOURCES = {
    "clvmr-metadata.json": "https://crates.io/api/v1/crates/clvmr",
    "chia-pyproject.toml": "https://raw.githubusercontent.com/Chia-Network/chia-blockchain/2.7.4/pyproject.toml",
    "chia-default-constants.py": "https://raw.githubusercontent.com/Chia-Network/chia-blockchain/2.7.4/chia/consensus/default_constants.py",
    "chia-spend-sim.py": "https://raw.githubusercontent.com/Chia-Network/chia-blockchain/2.7.4/chia/_tests/util/spend_sim.py",
    "chia-mempool-manager.py": "https://raw.githubusercontent.com/Chia-Network/chia-blockchain/2.7.4/chia/full_node/mempool_manager.py",
    "chia-commit.json": "https://api.github.com/repos/Chia-Network/chia-blockchain/commits/2.7.4",
    "chia-rs-commit.json": "https://api.github.com/repos/Chia-Network/chia_rs/commits/0.48.0",
    "chia-rs-tree.json": "https://api.github.com/repos/Chia-Network/chia_rs/git/trees/0.48.0?recursive=1",
    "clvmr-0.19.0.crate": "https://static.crates.io/crates/clvmr/clvmr-0.19.0.crate",
    "chia-rs-Cargo.toml": f"https://raw.githubusercontent.com/Chia-Network/chia_rs/{CHIA_RS_COMMIT}/Cargo.toml",
    "chia-rs-conditions.rs": f"https://raw.githubusercontent.com/Chia-Network/chia_rs/{CHIA_RS_COMMIT}/crates/chia-consensus/src/conditions.rs",
    "chia-rs-flags.rs": f"https://raw.githubusercontent.com/Chia-Network/chia_rs/{CHIA_RS_COMMIT}/crates/chia-consensus/src/flags.rs",
    "chia-rs-coin.rs": f"https://raw.githubusercontent.com/Chia-Network/chia_rs/{CHIA_RS_COMMIT}/crates/chia-protocol/src/coin.rs",
    "chia-rs-public-key.rs": f"https://raw.githubusercontent.com/Chia-Network/chia_rs/{CHIA_RS_COMMIT}/crates/chia-bls/src/public_key.rs",
    "chia-rs-time-locks.rs": f"https://raw.githubusercontent.com/Chia-Network/chia_rs/{CHIA_RS_COMMIT}/crates/chia-consensus/src/check_time_locks.rs",
    "chia-rs-spend-validation.rs": f"https://raw.githubusercontent.com/Chia-Network/chia_rs/{CHIA_RS_COMMIT}/crates/chia-consensus/src/spendbundle_validation.rs",
}
SOURCES = {name: url.replace("/chia-blockchain/2.7.4/", f"/chia-blockchain/{CHIA_COMMIT}/") for name, url in SOURCES.items()}


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, url in SOURCES.items():
        if (CACHE / name).exists() and name not in {"chia-pyproject.toml", "chia-default-constants.py", "chia-spend-sim.py", "chia-mempool-manager.py"}:
            body = (CACHE / name).read_bytes()
            manifest.append({"file": name, "url": url, "sha256": hashlib.sha256(body).hexdigest()})
            continue
        request = Request(url, headers={"User-Agent": "0xBASIC-M0-research/0.1"})
        try:
            with urlopen(request, timeout=25) as response:
                body = response.read()
            (CACHE / name).write_bytes(body)
            manifest.append({"file": name, "url": url, "sha256": hashlib.sha256(body).hexdigest()})
            print(f"Fetched {name}: {len(body)} bytes", flush=True)
            if name == "clvmr-metadata.json":
                metadata = json.loads(body)
                print(json.dumps([{"version": v["num"], "rust_version": v.get("rust_version"), "yanked": v["yanked"]} for v in metadata["versions"][:5]]), flush=True)
            if name == "clvmr-0.19.0.crate":
                metadata = json.loads((CACHE / "clvmr-metadata.json").read_bytes())
                version = next(v for v in metadata["versions"] if v["num"] == "0.19.0")
                if hashlib.sha256(body).hexdigest() != version["checksum"]:
                    raise ValueError("Crate checksum mismatch")
                with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as archive:
                    for relative in ("Cargo.toml", "src/chia_dialect.rs", "src/allocator.rs", "src/bls_ops.rs", "src/more_ops.rs", "src/op_utils.rs", "src/serde/mod.rs", "src/serde/ser.rs", ".cargo_vcs_info.json"):
                        member = archive.extractfile("clvmr-0.19.0/" + relative)
                        if member is not None:
                            (CACHE / ("clvmr-" + relative.replace("/", "-"))).write_bytes(member.read())
        except Exception as error:
            manifest.append({"file": name, "url": url, "error": str(error)})
            print(f"Failed {name}: {error}", flush=True)
    (CACHE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if any("error" in item for item in manifest):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
