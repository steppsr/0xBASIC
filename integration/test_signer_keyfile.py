"""Public disposable bytes only. Native Linux tests enforce actual filesystem rules."""
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import signer_keyfile as keys

RAW = keys.HEADER + b"01" * 32 + b"\n"


class KeyPolicyTests(unittest.TestCase):
    def test_canonical_encoding(self):
        self.assertEqual(keys._decode(RAW), b"\x01" * 32)
        for raw in (RAW[:-1], RAW + b"\n", RAW.replace(b"\n", b"\r\n"), keys.HEADER + b"AB" * 32 + b"\n",
                    keys.HEADER + b"00" * 32 + b"\n", b"other" + RAW, keys.HEADER + b"gg" * 32 + b"\n"):
            with self.subTest(size=len(raw)), self.assertRaises(keys.KeyFileError):
                keys._decode(raw)

    def test_file_metadata_rejects_unsafe_modes_owners_and_types(self):
        good = dict(st_mode=stat.S_IFREG | 0o600, st_uid=1001, st_nlink=1, st_size=keys.SIZE)
        keys._file(SimpleNamespace(**good), 1001)
        for changes in ({"st_mode": stat.S_IFREG | 0o644}, {"st_mode": stat.S_IFREG | 0o400},
                        {"st_mode": stat.S_IFIFO | 0o600}, {"st_mode": stat.S_IFREG | 0o4600},
                        {"st_uid": 0}, {"st_nlink": 2}, {"st_size": keys.SIZE + 1}):
            with self.subTest(changes=changes), self.assertRaises(keys.KeyFileError):
                keys._file(SimpleNamespace(**{**good, **changes}), 1001)

    def test_directory_policy(self):
        keys._directory(SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0), 1001)
        keys._directory(SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1001), 1001, vault=True)
        for mode, uid, vault in [(0o777, 0, False), (0o1777, 0, False), (0o700, 999, False),
                                 (0o755, 1001, True), (0o700, 0, True)]:
            with self.assertRaises(keys.KeyFileError):
                keys._directory(SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=uid), 1001, vault=vault)

    def test_unsupported_platform_fails_before_io(self):
        for platform in ("win32", "darwin"):
            with patch.object(keys.sys, "platform", platform), patch.object(keys.os, "open") as opened:
                with self.assertRaises(keys.KeyFileError):
                    keys.read_test_owner("unused.key")
                opened.assert_not_called()


@unittest.skipUnless(sys.platform == "linux", "Requires actual Linux descriptor/permission semantics")
class NativeKeyFileTests(unittest.TestCase):
    def setUp(self):
        import pwd
        # A private disposable tree in the real native home avoids world-writable /tmp.
        self.temp = tempfile.TemporaryDirectory(prefix=".0xbasic-key-test-", dir=pwd.getpwuid(os.getuid()).pw_dir)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.vault = self.home / ".local/share/0xbasic-signer"
        self.vault.mkdir(parents=True, mode=0o700)
        for directory in (self.home, self.home / ".local", self.vault.parent, self.vault):
            directory.chmod(0o700)
        self.path = self.vault / "fixture.key"
        self.path.write_bytes(RAW)
        self.path.chmod(0o600)
        self.home_patch = patch.object(keys, "_home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)

    def test_read_and_descriptor_cleanup(self):
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(10):
            self.assertEqual(keys.read_test_owner(self.path), b"\x01" * 32)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_file_permissions_and_failure_cleanup(self):
        before = len(os.listdir("/proc/self/fd"))
        for mode in (0o644, 0o660, 0o400, 0o777):
            self.path.chmod(mode)
            with self.assertRaises(keys.KeyFileError):
                keys.read_test_owner(self.path)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_vault_and_ancestor_permissions(self):
        for directory, bad_mode, restore in [(self.vault, 0o755, 0o700), (self.vault.parent, 0o777, 0o700)]:
            directory.chmod(bad_mode)
            with self.assertRaises(keys.KeyFileError):
                keys.read_test_owner(self.path)
            directory.chmod(restore)

    def test_leaf_symlink_and_hardlink(self):
        alias = self.vault / "alias.key"
        alias.symlink_to(self.path)
        with self.assertRaises(keys.KeyFileError):
            keys.read_test_owner(alias)
        alias.unlink()
        os.link(self.path, alias)
        with self.assertRaises(keys.KeyFileError):
            keys.read_test_owner(self.path)

    def test_directory_symlink(self):
        moved = self.vault.with_name("moved")
        self.vault.rename(moved)
        self.vault.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(keys.KeyFileError):
            keys.read_test_owner(self.path)

    def test_fifo_rejected_without_blocking(self):
        self.path.unlink()
        os.mkfifo(self.path, 0o600)
        with self.assertRaises(keys.KeyFileError):
            keys.read_test_owner(self.path)

    def test_wrong_location_and_traversal(self):
        for path in (Path("fixture.key"), self.home / "fixture.key", self.vault / ".." / "0xbasic-signer" / "fixture.key"):
            with self.assertRaises(keys.KeyFileError):
                keys.read_test_owner(path)

    def test_home_environment_does_not_select_vault(self):
        with patch.dict(os.environ, {"HOME": "/tmp", "XDG_DATA_HOME": "/tmp"}):
            self.assertEqual(keys.read_test_owner(self.path), b"\x01" * 32)

    def test_bad_content_is_sanitized(self):
        self.path.write_bytes(keys.HEADER + b"zz" * 32 + b"\n")
        with self.assertRaises(keys.KeyFileError) as caught:
            keys.read_test_owner(self.path)
        self.assertNotIn("zz", str(caught.exception))
        self.assertNotIn(str(self.path), str(caught.exception))

    def test_reject_root(self):
        with patch.object(keys.os, "getuid", return_value=0):
            with self.assertRaises(keys.KeyFileError):
                keys.read_test_owner(self.path)

    def test_permission_change_during_read(self):
        real_read = os.read
        def changed(fd, size):
            block = real_read(fd, size)
            self.path.chmod(0o644)
            return block
        with patch.object(keys.os, "read", side_effect=changed), self.assertRaises(keys.KeyFileError):
            keys.read_test_owner(self.path)

    def test_short_reads_are_completed(self):
        real_read = os.read
        with patch.object(keys.os, "read", side_effect=lambda fd, size: real_read(fd, min(size, 7))):
            self.assertEqual(keys.read_test_owner(self.path), b"\x01" * 32)


if __name__ == "__main__":
    unittest.main()
