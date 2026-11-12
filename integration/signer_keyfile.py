"""Linux-only protected test-owner storage; no cryptographic signing."""
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import re
import stat
import sys

HEADER = b"0xbasic-test-owner-v1\n"
SIZE = len(HEADER) + 65


class KeyFileError(ValueError):
    """Sanitized failure: never include secret bytes or paths."""


def require(value):
    if not value:
        raise KeyFileError("Protected test-owner file validation failed")


def _home(uid):
    import pwd
    return Path(pwd.getpwuid(uid).pw_dir)


def _directory(info, uid, *, vault=False):
    require(stat.S_ISDIR(info.st_mode))
    require(info.st_uid == uid if vault else info.st_uid in (0, uid))
    require(stat.S_IMODE(info.st_mode) == 0o700 if vault else not info.st_mode & 0o022)


def _file(info, uid):
    require(stat.S_ISREG(info.st_mode) and info.st_uid == uid
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and info.st_size == SIZE)


def _decode(raw):
    require(type(raw) is bytes and len(raw) == SIZE and raw.startswith(HEADER)
            and re.fullmatch(b"[0-9a-f]{64}\n", raw[len(HEADER):]) is not None)
    material = bytes.fromhex(raw[len(HEADER):-1].decode("ascii"))
    require(any(material))
    # Scalar validity and public-key binding belong to the cryptographic signer.
    return material


def _platform():
    require(sys.platform == "linux" and os.open in os.supports_dir_fd)
    uid = os.getuid()
    require(uid != 0)
    return uid


@contextmanager
def _open_vault(path):
    """Keep the checked directory descriptors alive for the entire operation."""
    descriptors = ExitStack()
    try:
        uid = _platform()
        home = _home(uid)
        require(home.is_absolute() and home != Path("/") and ".." not in home.parts)
        vault = home / ".local/share/0xbasic-signer"
        supplied = os.fspath(path)
        require(type(supplied) is str and "\x00" not in supplied)
        target = Path(supplied)
        require(target.is_absolute() and ".." not in target.parts and target.parent == vault
                and target.name.endswith(".key") and target.name != ".key")
        repository = Path(__file__).resolve().parents[1]
        require(not vault.is_relative_to(repository))
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

        def keep(fd):
            descriptors.callback(os.close, fd)
            return fd

        parent = keep(os.open("/", flags))
        _directory(os.fstat(parent), uid)
        for index, part in enumerate(vault.parts[1:]):
            parent = keep(os.open(part, flags, dir_fd=parent))
            _directory(os.fstat(parent), uid, vault=index == len(vault.parts) - 2)
        yield uid, parent, target.name, keep
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise KeyFileError("Protected test-owner file validation failed") from None
    finally:
        descriptors.close()


def read_test_owner(path):
    """Read encoded material; the cryptographic caller must validate its scalar."""
    with _open_vault(path) as (uid, parent, name, keep):
        fd = keep(os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent))
        before = os.fstat(fd)
        _file(before, uid)
        raw = bytearray()
        while len(raw) <= SIZE:
            block = os.read(fd, SIZE + 1 - len(raw))
            if not block:
                break
            raw.extend(block)
        after = os.fstat(fd)
        _file(after, uid)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns))
        return _decode(bytes(raw))


def _create_test_owner(path, material):
    """Exclusive creation after caller's crypto validation. Never replace/delete.

    A write or synchronization failure may leave a protected incomplete file.
    It must be inspected explicitly; retrying the same name refuses overwrite.
    """
    require(type(material) is bytes and len(material) == 32)
    raw = HEADER + material.hex().encode("ascii") + b"\n"
    _decode(raw)
    with _open_vault(path) as (uid, parent, name, keep):
        fd = keep(os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                          0o600, dir_fd=parent))
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            require(written > 0)
            offset += written
        _file(os.fstat(fd), uid)
        os.fsync(fd)
        os.fsync(parent)
