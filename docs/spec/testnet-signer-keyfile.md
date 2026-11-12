# TN-3b1: protected test-owner file boundary

Status: LANDO with a separate testnet environment and a protected-file offline signer selected on 2026-11-12. Windows policy/refusal tests passed; native LANDO filesystem validation passed, confirmed on 2026-11-12. This slice implements only the file-reading boundary, not key generation, cryptographic signing, installation or live transactions.

The [TN-4 exit review](testnet-rehearsal-review.md) identified owner-key custody as the next implementation decision. A dedicated test-only owner is separate from the wallet that later funds its contract. Public deterministic fixture keys remain test data and must never become public-network custody keys.

## Storage contract

`integration/signer_keyfile.py` reads an explicit absolute filename ending in `.key` directly inside the fixed vault `ACCOUNT_HOME/.local/share/0xbasic-signer`. The account home comes from the operating system's password database for the current UID, not HOME or XDG_DATA_HOME. Relative paths, parent traversal, root execution and a vault located inside this repository are rejected. No alternate vault option or default key filename is supplied.

Use a native local Linux filesystem outside the synchronized share. The reader does not attest filesystem type, encryption, mount provenance or backup destinations; those remain host-setup requirements. LANDO is selected as the design target, but no service or directory has been configured by this slice.

The vault must be owned by the current user with exactly mode `0700`. Every ancestor must be a directory owned by root or the current user, with no group/other write permission. The key file must be a regular file owned by the current user, exactly mode `0600`, with one hard link and the exact format length. Special permission bits are rejected on the vault/file. Symlinks at every path component are rejected.

The file's byte format is the ASCII header `0xbasic-test-owner-v1` followed by LF, 64 lowercase hexadecimal digits, and a final LF. No BOM, CRLF, spaces, uppercase hex, extra fields or trailing bytes are accepted. All-zero material is rejected. The reader returns 32 bytes; **valid BLS scalar decoding and owner-public-key matching remain mandatory work for the next cryptographic slice**. Passing this reader alone does not mean a key is cryptographically valid.

## Descriptor and failure behavior

The reader opens the path from `/` one directory at a time using descriptor-relative opens with O_DIRECTORY/O_NOFOLLOW/O_CLOEXEC. It validates the actual opened descriptors rather than resolving a path and reopening it. The leaf adds O_NONBLOCK so a FIFO cannot hang the reader; its type is checked before any bytes are read. Reads are capped at the expected size plus one, short reads are completed, and metadata is checked again afterward. Size, identity or modification metadata changes fail the read. All descriptors close on success or failure.

Errors expose a generic message without secret bytes or paths. Nothing is written, printed, uploaded, signed or sent by this module. No CLI loads keys yet. Unsupported platforms, including Windows, fail before filesystem access; Windows ACL support is not implied by a POSIX mode check.

This protects against accidental exposure, unsafe filesystem setup and symlink/hard-link substitution within the checked path model. It does not resist compromise of the owning account/root, malicious mount changes, concurrent edits by a trusted owner that evade metadata detection, debugger access or memory disclosure. Python does not guarantee erasure of returned secret bytes. Filesystem permissions do not encrypt custody material.

## Tests and next slices

Four portable policy tests exercise canonical encoding, metadata requirements, directory rules and unsupported-platform refusal. Twelve Linux-only tests exercise real private temporary files, descriptor cleanup on success/failure, unsafe modes, directory/leaf symlinks, hard links, FIFO refusal, paths, environment independence, sanitized failures, root refusal, permission changes during reading and short reads. Tests create only disposable public fixture bytes in a temporary directory under the native home and remove them afterward; they never open an existing owner key.

Next, after this native gate: implement separate exclusive key creation with OS randomness and valid scalar decoding; then a review-bound signing flow that regenerates the preparation, matches the owner, signs the exact approved request and produces a response independently accepted by TN-3a. Specify and test durable creation, permissions and failure handling before creating any real owner key. Continue with explicit host/baseline configuration and operator submission/observation tooling as described in the exit review.

## Native LANDO gate

Run as the normal `steve` account, without sudo, on the existing native checkout. These tests require no Chia runtime, compiler build, node, wallet or credentials:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
python3 tools/verify_m0.py
python3 -m unittest discover -s integration -p 'test_*.py'
)
```

Expected: **70 tests pass with no skips on Linux**. Windows runs the same suite with the 12 native filesystem tests explicitly skipped. Do not loosen home permissions to make a failure disappear; preserve the error so the actual boundary can be checked. No full-node, package or public signing matrix rerun is required for this independent, unused key-file module. After the native pass, commit/push and verify exact-revision CI before proceeding.
