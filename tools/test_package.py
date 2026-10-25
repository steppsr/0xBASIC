"""Reject damaged archives before running an executable."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from verify_package import verify


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


if __name__ == "__main__":
    unittest.main()
