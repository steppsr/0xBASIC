"""Reject damaged archives before running an executable."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from verify_package import has_loops, has_fees, verify
from verify_package_sources import verify_sources


def archive(root, files, kind="zip"):
    path = root / ("candidate.zip" if kind == "zip" else "candidate.tar.gz")
    if kind == "zip":
        with zipfile.ZipFile(path, "w") as handle:
            for name, content in files.items():
                handle.writestr(name, content)
    else:
        with tarfile.open(path, "w:gz") as handle:
            for name, content in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                handle.addfile(entry, io.BytesIO(content))
    path.with_name(path.name + ".sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="ascii")
    return path


class PackageRejectionTests(unittest.TestCase):
    def test_fee_candidate_retains_loop_package_checks(self):
        self.assertTrue(has_loops({"compiler": "0.3.0-alpha.1"}))
        self.assertTrue(has_loops({"compiler": "0.2.0-alpha.1"}))
        self.assertFalse(has_loops({"compiler": "0.1.0-m3.8b"}))

    def test_fee_checks_preserve_older_package_support(self):
        self.assertTrue(has_fees({"compiler": "0.3.0-alpha.1"}))
        for version in ("0.2.0-alpha.1", "0.1.0-m3.8b"):
            self.assertFalse(has_fees({"compiler": version}))

    def test_fee_candidate_requires_fee_materials(self):
        with tempfile.TemporaryDirectory() as temp:
            files = {name: b"fixture" for name in ("source.tar.gz", "THIRD-PARTY-NOTICES.txt",
                     "REBUILD.md", "examples/counted-heights.bas", "LOOPS.md")}
            metadata = {"schema_version": 1, "experimental": True, "compiler": "0.3.0-alpha.1",
                        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
            files["package.json"] = json.dumps(metadata).encode()
            with self.assertRaisesRegex(RuntimeError, "Missing fee package inputs"):
                verify(archive(Path(temp), files))

    def test_changed_archive_fails_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            path = archive(Path(temp), {"file": b"original"})
            path.write_bytes(path.read_bytes() + b"changed")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                verify(path)

    def test_traversal_rejected_for_both_formats(self):
        with tempfile.TemporaryDirectory() as temp:
            for kind in ("zip", "tar"):
                path = archive(Path(temp), {"../escape": b"bad"}, kind)
                with self.assertRaisesRegex(RuntimeError, "Unsafe package path"):
                    verify(path)
            self.assertFalse((Path(temp) / "escape").exists())

    def test_changed_payload_fails_internal_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            metadata = {"schema_version": 1, "experimental": True, "files": {"file": "0" * 64}}
            path = archive(Path(temp), {"file": b"changed", "package.json": json.dumps(metadata).encode()})
            with self.assertRaisesRegex(RuntimeError, "File hash mismatch"):
                verify(path)

    def test_binary_only_package_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            metadata = {"schema_version": 1, "experimental": True, "files": {}}
            path = archive(Path(temp), {"package.json": json.dumps(metadata).encode()})
            with self.assertRaisesRegex(RuntimeError, "Missing source or notice"):
                verify(path)

    def test_current_package_requires_loop_materials(self):
        with tempfile.TemporaryDirectory() as temp:
            files = {name: b"fixture" for name in ("source.tar.gz", "THIRD-PARTY-NOTICES.txt", "REBUILD.md")}
            metadata = {"schema_version": 1, "experimental": True, "compiler": "0.2.0-alpha.1",
                        "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
            files["package.json"] = json.dumps(metadata).encode()
            with self.assertRaisesRegex(RuntimeError, "Missing loop package inputs"):
                verify(archive(Path(temp), files))

    def test_source_inventory_requires_loop_implementation(self):
        files = {name: b"fixture" for name in ("Cargo.lock", ".cargo/config.toml",
                 "vendor/malachite-bigint/src/lib.rs", "REBUILD.md", "THIRD-PARTY-NOTICES.txt")}
        index = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        metadata = {"compiler": "0.2.0-alpha.1", "source_hashes": {}, "cargo_lock_sha256": index["Cargo.lock"],
                    "files": index}
        files["SOURCE-MANIFEST.json"] = json.dumps(index).encode()
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as handle:
            for name, content in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                handle.addfile(entry, io.BytesIO(content))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "Missing loop source inputs"):
                verify_sources(data.getvalue(), Path(temp), metadata)


if __name__ == "__main__":
    unittest.main()
