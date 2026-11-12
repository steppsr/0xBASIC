# TN-3b2: exclusive owner-key creation and scalar validation

Status: Windows passed 80 integration tests with 19 native filesystem cases skipped, and the pinned BLS matrix with six rejection cases. Native LANDO passed, confirmed on 2026-11-12. TN-3b1 is published at `f269da884cd1e59f14ceacc97e016b1608938e5d`. This follows the selected LANDO/protected-file signer direction; no real owner key or live service has been created by this development gate.

TN-3b1 exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43284724476), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43284724631) and [packages](https://github.com/steppsr/0xBASIC/actions/runs/43284724519).

## Creation boundary

`integration/owner_keys.py` adds a separate, explicit Linux-only key creation command. The internal `create_owner(path)` checks platform support, validates the existing pinned simulator environment, obtains 32 bytes from operating-system randomness, invokes the pinned AugSchemeMPL key generator and revalidates the resulting serialized private scalar. There is no seed argument, secret argument, import option, default key filename, network selector or wallet discovery.

It uses the [TN-3b1 fixed vault and descriptor rules](testnet-signer-keyfile.md). The vault must already exist with its required ownership and permissions; creation does not configure a home, repair permissions or create directories. The CLI accepts only `--key-file ABSOLUTE_PATH`. Do not run it to create a real owner until the host/vault setup and intended custody have been reviewed. The native test block below never invokes it against an operator vault.

The storage helper opens a new leaf with O_CREAT/O_EXCL/O_NOFOLLOW, using the already checked directory descriptor. It sets exactly mode `0600`, completes short writes, verifies final file metadata, synchronizes the file and then the containing directory, and only then returns success. Existing regular files, symlinks or other entries are never replaced. Success output is JSON containing schema version, test-only purpose, AugSchemeMPL scheme and the 48-byte public key in lowercase hex. Private bytes, seeds and paths are absent from that output.

On write or synchronization failure, any created file is deliberately preserved and success is not printed. It may be incomplete or may contain a complete key whose durability was not established. The same filename cannot be retried automatically because exclusive creation will refuse it. Inspection/recovery is an explicit later operator action; this tool neither deletes the file nor silently generates a replacement at that name. Successful fsync calls do not promise resilience against every filesystem, device or power-loss failure. A failure printing public output after creation can likewise leave a completed file without a success response.

The command denies socket connect/bind through a process audit hook and has no node/keychain path. Pinned-runtime preflight changes only this process's unused Chia root variables; use the standalone process, not an embedded live-node process. Windows is refused before runtime loading, entropy generation or file access. The key remains plaintext under filesystem permissions, with the account/root/memory/mount limitations described in TN-3b1.

## Loading for the later signer

`load_owner(path, expected_public_key)` requires an explicit canonical lowercase 48-byte owner public key. It reads through the protected storage boundary, decodes with pinned `PrivateKey.from_bytes`, requires nonzero material, an exact serialization round trip and a non-infinity public key, then compares the derived public key with the supplied owner. Zero, out-of-range and wrong-length scalars fail. The low-level TN-3b1 reader alone still does not perform crypto validation; a future signer must use this checked loader after independently validating its preparation.

This step does not implement spend signing, interactive approval, funding, submission or recovery. Next is the review-bound signing flow: independently regenerate the preparation, present exact network/coin/destinations/amounts/fee and preparation digest, require approval of those bytes, then emit a detached response that TN-3a independently verifies. A valid owner key is not approval to sign an arbitrary message.

## Evidence and tests

The standard-library suite adds platform refusal before runtime/entropy, sanitized CLI failure, socket-hook rejection, and seven actual Linux creation tests. Native cases check exact permissions and file-before-directory synchronization order, existing-file/symlink preservation, short writes, partial/zero writes, descriptor cleanup, file/directory fsync failures, refused retry and no implicit vault creation. Existing reader tests cover the refactored shared descriptor walk.

`integration/verify_owner_keys.py` uses the pinned cryptographic runtime and public deterministic fixtures. It verifies scalar loading, owner binding, a fixture sign/verify check, generation from the specified fixture entropy and public-only output. Six rejection cases cover zero/out-of-range/short/long scalars and wrong/noncanonical owner. Linux additionally exercises the real exclusive-create/read/load round trip in a disposable private directory under the native home; Windows reports that portion as false. The test patches only its fixture home/entropy, never an operator vault. No production switch accepts those overrides.

Reports `.work/testnet/owner-keys-<platform>.json` contain source hashes, case names and scope/cleanup flags, never secret material. Simulator CI runs this matrix and uploads the report; compiler CI already discovers the expanded standard-library tests. No dependency or compiler change is required.

## Native LANDO gate

Run as `steve`, without sudo. Do not create a real vault or owner key for this gate:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
python3 tools/verify_m0.py
python3 -m unittest discover -s integration -p 'test_*.py'
.work/m4/venv/bin/python integration/verify_owner_keys.py
)
```

Expected: **80 tests pass with no skips**, then owner-key matrix PASS with **six rejections** and **native storage roundtrip=True**. Preserve `.work/testnet/owner-keys-linux.json`. No compiler rebuild, full-node test or existing public preparation/signature matrix rerun is needed for this unused owner-key boundary. After native success, commit/push, verify exact CI and continue the signing-review slice.
