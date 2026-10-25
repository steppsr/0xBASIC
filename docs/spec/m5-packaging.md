# M5-5: experimental native packages

Historical baseline: the six-file layout and three-test results below are superseded by [source-inclusive packaging](source-distribution.md). Current archives add `source.tar.gz`, `THIRD-PARTY-NOTICES.txt` and `REBUILD.md`; four rejection tests and two offline rebuilds are required. Windows passed; use the newer checkpoint's exact Linux commands, which copy both new helper modules and distribution inputs.

Status: Windows and native Linux packaging passed, 2026-10-24; Linux success confirmed by the user. Release readiness remains open in the [M5-6 review](m5-release-review.md). M5-4 native Linux tutorial verification passed, as confirmed by the user. No release/tag has been published. Compiler remains `0.1.0-m3.8b`; ABI, dependencies and Rust test totals (277 Windows / 278 Linux) are unchanged.

## Package construction

`tools/package_experimental.py` verifies Rust 1.95.0 and a native x86_64 Windows MSVC or Linux GNU host, then runs `cargo build --release --locked -p oxbasic-cli --target HOST`. It respects `CARGO_TARGET_DIR`. Downloads may be needed if the release/target build dependencies are not cached. No Python packages are required.

The candidate contains only six files: native executable under `bin/`, project LICENSE, `PACKAGE.md`, payment source and public bindings under `examples/`, and `package.json`. The metadata contains file hashes, compiler/target/toolchain identities, Cargo.lock digest, source-file digests, build OS/libc information and the frozen payment expectation. It does not claim that a dirty local tree equals a published Git commit. No artwork, simulator environment, user key material or project scratch files are packaged.

Windows produces ZIP; Linux produces gzip-compressed tar with executable permission preserved. Archive entry order/timestamps are normalized; that does not promise bit-identical compiler executables across build hosts. Each archive has an adjacent `.sha256` file. These checksums are integrity checks, not publisher signatures.

Candidates are assembled beneath ignored `.work/packages/candidate-*`, verified, then moved into `.work/packages`. A failed run publishes no new archive and invalidates the platform's evidence report. A previous successfully verified archive may remain; only the current successful report identifies the completed attempt. Run one packaging operation per checkout at a time. Release naming/version policy and third-party attribution/distribution review remain M5-6 gates before public release.

## Extracted smoke checks

`tools/verify_package.py` is a standalone standard-library verifier. It checks the archive checksum, file inventory/hashes and safe relative paths before executing anything. It extracts into an OS temporary directory outside the source checkout. On Linux it preserves archived permission bits and requires an executable binary. CLI subprocesses receive an empty PATH and unavailable Cargo/Rustup home directories.

Eight commands check version, help, source checking, bound CLVM inspection, artifact building, local payment execution, exact expected cost-limit failure and overwrite refusal. Outputs match the frozen payment tree/hash/cost; built provenance matches the package toolchain/lock metadata. Generated artifacts must remain unchanged after expected failures. Each command has a 20-second timeout; temporary resources close before evidence is returned.

Three unit tests reject a changed archive checksum, traversal paths in both ZIP/tar, and altered payload hashes. Windows packaging plus standalone extracted verification passed all eight CLI commands; all three rejection tests passed. The Windows ZIP is approximately 1.28 MB. The user confirmed native Linux passed the tar writer, permissions and GNU executable checks.

An empty PATH and an isolated working directory demonstrate that these operations need neither Rust commands nor repository files. They are not a pristine-OS compatibility certification: native runtime libraries supplied by the test host are still present. Linux is GNU/glibc, not a static/musl package; inspect recorded libc provenance and validate each supported deployment OS before release. Windows runtime compatibility likewise remains tied to the tested host. No macOS/ARM package claim is made.

The separate [package workflow](../../.github/workflows/packages.yml) builds both native archives, uploads candidate artifacts, then downloads each in a new job with no source checkout and runs the standalone verifier. The verifier tool travels alongside the candidate as a CI aid, outside the six-file archive. Hosted runners can have preinstalled tools; the executable tests still remove PATH access. This workflow uploads CI evidence only, with read-only repository permissions and no release creation. Its first hosted execution is pending publication.

## Native Linux commands

From the same native checkout used for M5-4:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/tools/{package_experimental.py,verify_package.py,test_package.py} tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/package-usage.md docs/spec/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
python3 -m unittest discover -s tools -p test_package.py
python3 tools/package_experimental.py
python3 tools/verify_package.py \
  .work/packages/0xbasic-0.1.0-m3.8b-experimental-x86_64-unknown-linux-gnu.tar.gz \
  --report .work/packages/extracted-linux.json
```

Expected: **3 tests pass**, then `PASS: experimental package built and verified; 8 extracted CLI commands passed.` and `PASS: extracted package verified; 8 CLI commands passed with empty PATH.` The script performs the release build automatically. No separate full Rust suite or simulator rerun is needed.

Outputs: Linux `.tar.gz` plus `.tar.gz.sha256`, `package-linux.json` and `extracted-linux.json` under `.work/packages`. Keep the archive and evidence for the M5-6 release review. All changes currently remain local; copying from the share is required until publication.
