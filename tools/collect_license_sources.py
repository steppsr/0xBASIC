"""Fetch exact upstream notices omitted from registry crate archives."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [
    ("malachite", "mhogrefe/malachite", "78c822c126a0627ecc8b9b89d0058cec8116e1b2", ["LICENSE", "COPYING", "COPYING.LESSER"]),
    ("chia_rs", "Chia-Network/chia_rs", "da47ae281f1f8801542a743263db84fff3612de1", ["LICENSE"]),
    ("blst", "supranational/blst", "54e6e55674722fc2797ebb4bbb71b26d881eb4b8", ["LICENSE"]),
]


def main():
    destination = ROOT / "distribution/upstream-notices"
    evidence = []
    for name, repository, commit, files in SOURCES:
        for filename in files:
            url = f"https://raw.githubusercontent.com/{repository}/{commit}/{filename}"
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
            path = destination / name / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            evidence.append({"path": path.relative_to(destination).as_posix(), "url": url,
                             "commit": commit, "sha256": hashlib.sha256(data).hexdigest()})
            print(f"Collected {name}/{filename}")
    (destination / "sources.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
