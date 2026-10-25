"""Compare installed full-node integration sources with the pinned Chia commit."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "98aba3d176b24b5814e84a33f9d1c11af67a9cdc"
FILES = [
    "chia/simulator/block_tools.py", "chia/simulator/full_node_simulator.py",
    "chia/simulator/start_simulator.py", "chia/simulator/keyring.py",
    "chia/full_node/full_node.py", "chia/server/start_service.py",
    "chia/server/server.py", "chia/util/default_root.py",
]


def main():
    import importlib.metadata as metadata
    distribution = metadata.distribution("chia-blockchain")
    assert distribution.version == "2.7.4"
    hashes = {}
    for name in FILES:
        with urllib.request.urlopen(
            f"https://raw.githubusercontent.com/Chia-Network/chia-blockchain/{COMMIT}/{name}", timeout=30
        ) as response:
            upstream = response.read()
        installed = Path(distribution.locate_file(name)).read_bytes()
        if installed != upstream:
            raise RuntimeError(f"Pinned source mismatch: {name}")
        hashes[name] = hashlib.sha256(upstream).hexdigest()
        print(f"MATCH: {name}")
    profile = {"schema_version": 1, "chia_commit": COMMIT, "source_hashes": hashes}
    (ROOT / "simulator/full_node_sources.json").write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
