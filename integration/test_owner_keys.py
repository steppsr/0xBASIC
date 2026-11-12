"""Creation failure boundaries using disposable public bytes, never real owner keys."""
import contextlib
import io
import os
from pathlib import Path
import stat
import sys
import unittest
from unittest.mock import patch

import owner_keys
import signer_keyfile as storage
import test_signer_keyfile as fixture


class OwnerPlatformTests(unittest.TestCase):
    def test_unsupported_platform_never_generates_or_loads(self):
        with patch.object(storage.sys, "platform", "win32"), patch.object(owner_keys, "_runtime") as runtime, \
                patch.object(owner_keys.os, "urandom") as entropy:
            for action in (lambda: owner_keys.create_owner(Path("unused.key")),
                           lambda: owner_keys.load_owner(Path("unused.key"), "01" * 48)):
                with self.assertRaises(storage.KeyFileError):
                    action()
            runtime.assert_not_called()
            entropy.assert_not_called()

    def test_cli_failure_has_no_public_success_or_secret_path(self):
        output, error = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["owner_keys", "--key-file", "private-location.key"]), \
                patch.object(owner_keys, "create_owner", side_effect=storage.KeyFileError("sensitive")), \
                patch.object(sys, "addaudithook"), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            self.assertEqual(owner_keys.main(), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertNotIn("sensitive", error.getvalue())
        self.assertNotIn("private-location", error.getvalue())

    def test_network_hook(self):
        for event in ("socket.connect", "socket.bind"):
            with self.assertRaises(RuntimeError):
                owner_keys.no_network(event, ())


@unittest.skipUnless(sys.platform == "linux", "Requires actual Linux exclusive creation and fsync")
class NativeCreationTests(unittest.TestCase):
    setUp = fixture.NativeKeyFileTests.setUp

    def test_exclusive_creation_permissions_and_sync_order(self):
        target = self.vault / "new.key"
        calls, real_sync = [], os.fsync
        def synced(fd):
            calls.append(stat.S_ISDIR(os.fstat(fd).st_mode))
            real_sync(fd)
        old_mask = os.umask(0)
        try:
            with patch.object(storage.os, "fsync", side_effect=synced):
                storage._create_test_owner(target, b"\x01" * 32)
        finally:
            os.umask(old_mask)
        self.assertEqual(calls, [False, True])
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(storage.read_test_owner(target), b"\x01" * 32)

    def test_existing_file_and_symlink_preserved(self):
        original = self.path.read_bytes()
        alias = self.vault / "alias.key"
        alias.symlink_to(self.path)
        for target in (self.path, alias):
            with self.assertRaises(storage.KeyFileError):
                storage._create_test_owner(target, b"\x02" * 32)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(alias.is_symlink())

    def test_short_writes_completed(self):
        real_write = os.write
        target = self.vault / "short.key"
        with patch.object(storage.os, "write", side_effect=lambda fd, data: real_write(fd, data[:7])):
            storage._create_test_owner(target, b"\x01" * 32)
        self.assertEqual(storage.read_test_owner(target), b"\x01" * 32)

    def test_partial_write_preserved_and_retry_refused(self):
        target = self.vault / "partial.key"
        before, real_write = len(os.listdir("/proc/self/fd")), os.write
        def failed(fd, data):
            real_write(fd, data[:7])
            raise OSError("fixture write failure")
        with patch.object(storage.os, "write", side_effect=failed), self.assertRaises(storage.KeyFileError):
            storage._create_test_owner(target, b"\x01" * 32)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)
        original = target.read_bytes()
        self.assertEqual(len(original), 7)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        with self.assertRaises(storage.KeyFileError):
            storage._create_test_owner(target, b"\x02" * 32)
        self.assertEqual(target.read_bytes(), original)

    def test_zero_write_fails(self):
        target = self.vault / "zero.key"
        with patch.object(storage.os, "write", return_value=0), self.assertRaises(storage.KeyFileError):
            storage._create_test_owner(target, b"\x01" * 32)
        self.assertEqual(target.stat().st_size, 0)

    def test_file_or_directory_sync_failure_is_not_success(self):
        real_sync = os.fsync
        for fail_directory in (False, True):
            target = self.vault / (str(fail_directory) + ".key")
            def failed(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode) == fail_directory:
                    raise OSError("fixture sync failure")
                real_sync(fd)
            with patch.object(storage.os, "fsync", side_effect=failed), self.assertRaises(storage.KeyFileError):
                storage._create_test_owner(target, b"\x01" * 32)
            self.assertTrue(target.exists())
            with self.assertRaises(storage.KeyFileError):
                storage._create_test_owner(target, b"\x02" * 32)

    def test_no_implicit_vault_creation(self):
        self.path.unlink()
        self.vault.rmdir()
        with self.assertRaises(storage.KeyFileError):
            storage._create_test_owner(self.path, b"\x01" * 32)
        self.assertFalse(self.vault.exists())


if __name__ == "__main__":
    unittest.main()
