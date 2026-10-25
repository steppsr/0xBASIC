# Source-inclusive experimental distribution

This checkpoint implements a source/rebuild approach for the pinned runtime's third-party dependencies. The compiler and dependency versions are unchanged. It replaces the earlier binary-only candidate layout; older six-file candidates are superseded and should not be selected for release.

## Basis and scope

GNU LGPL v3 section 4(d)(0) describes supplying the relevant library source and application code in a form that permits rebuilding with a modified library. The project uses that approach: the binary archive now carries `source.tar.gz`, complete `THIRD-PARTY-NOTICES.txt`, and `REBUILD.md`. The embedded source archive contains the application's source/build files, Cargo.lock, vendored sources for every locked registry package, notices and an offline Cargo configuration. The project remains Apache-2.0; dependencies retain their own terms. This is an engineering implementation of that distribution approach, not an independent legal opinion.

References: [LGPL v3 section 4](https://www.gnu.org/licenses/lgpl-3.0.html), [GNU FAQ on static/dynamic LGPL linking](https://www.gnu.org/licenses/gpl-faq.en.html#LGPLStaticVsDynamic). The official license/FAQ explain why merely omitting a runtime feature flag is not the selected distribution strategy.

The package states that modification and reverse engineering for debugging modifications are permitted. Rebuilt executables run directly without publisher keys, a remote activation service, or a required installation system. General-purpose Rust/C/C++ toolchains and ordinary system libraries remain host prerequisites; the full Cargo dependency source set is included.

## Notices and source provenance

`tools/collect_license_sources.py` fetched five missing notice/license files from the exact commits recorded by the affected registry crates. Their URLs, revisions and SHA-256 digests are committed under `distribution/upstream-notices/sources.json`. Packaging checks those digests and matches supplemental notices to the crates' `.cargo_vcs_info.json` commits before proceeding.

- Malachite: `LICENSE`, `COPYING` and `COPYING.LESSER` from commit `78c822c126a0627ecc8b9b89d0058cec8116e1b2`, providing LGPL v3 and GPL v3 texts.
- Chia Rust crates: `LICENSE` from commit `da47ae281f1f8801542a743263db84fff3612de1`.
- blst: `LICENSE` from commit `54e6e55674722fc2797ebb4bbb71b26d881eb4b8`.

The complete lock contains 134 registry crates, including platform-specific and build-only sources beyond the earlier 124/125 native graph inventory. Both r-efi versions place their terms/credits in `AUTHORS`; the notice collector includes that file and selects the MIT alternative for those packages. It also preserves other available license/copying/notice/authors/copyright texts throughout vendored sources. Packaging fails if a crate has no declared license or collected notice. This mechanical completeness check does not independently determine all legal obligations of every file.

Cargo vendor preserves checksum information and normalized manifests. Original source files and their copyright headers remain included. `DEPENDENCIES.json` describes packaged crates/notices; `SOURCE-MANIFEST.json` hashes every source-bundle file except itself. Binary metadata hashes the embedded source archive and validates its application source hashes/Cargo.lock against the binary's recorded provenance. Do not split the binary away from its accompanying source/notices when distributing this candidate.

Only explicit application directories and vendored dependencies enter the source snapshot. The repository's artwork, `.git`, local environments, scratch reports, user configuration and real keys are excluded. The five downloaded notice files are pinned project inputs; normal package creation does not refetch them. Cargo vendor may fetch missing locked crate archives before assembly. The rebuild tests themselves use `--offline` and an empty Cargo cache.

## Verification

The package builder now runs two source rebuilds in addition to the eight extracted executable checks:

1. Extract and verify the complete source inventory; build the original application offline with `--locked`, a new empty Cargo home and a new target directory. Compile/run the included payment and compare its hash, conditions and cost to the frozen baseline.
2. Copy vendored malachite-bigint to a local path, add a harmless exported constant as a real source modification, add `[patch.crates-io]`, and rebuild offline without `--locked` so Cargo can record the path override. Confirm metadata resolves the modified local library, then repeat the payment checks.

The modification probe is confined to the temporary test tree; delivered dependency sources remain unchanged. It demonstrates the documented replacement/rebuild mechanism. It does not claim that arbitrary library modifications preserve behavior, nor that rebuilt executable bytes are identical across hosts.

Four rejection tests cover changed archive checksums, traversal paths, altered internal hashes, and missing source/notice materials. The standalone verifier checks the embedded source inventory even without `--rebuild-source`; the package builder always requests both rebuilds. CI carries both verifier modules to its separate extracted-smoke job; the build job performs the rebuild tests before upload.

## Native Linux handoff

Windows passed four rejection tests, both offline source rebuilds (including the modified library), 8,969 source-file checks and eight extracted CLI commands. The source-inclusive ZIP SHA-256 is `67c0c868d40773355d99ef5b7f46a788baa165dbe568eee68a46490fa66d5582`. Native Linux verification of this layout passed, user confirmed on 2026-10-24. The commands below remain available for reproduction; no repeat is required.

From the same native checkout used for M5-5, run:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/tools/{package_experimental.py,package_sources.py,verify_package.py,verify_package_sources.py,test_package.py} tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/distribution/ distribution/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
python3 -m unittest discover -s tools -p test_package.py
python3 tools/package_experimental.py
python3 tools/verify_package.py \
  .work/packages/0xbasic-0.1.0-m3.8b-experimental-x86_64-unknown-linux-gnu.tar.gz \
  --report .work/packages/extracted-linux.json
```

Expect four tests passing, two successful offline source rebuilds during packaging, and the existing eight-command package/extraction PASS messages. `package-linux.json` must report `offline_rebuilds: 2`; `extracted-linux.json` verifies the source inventory and eight executable commands without repeating compilation. The target release build and all dependency vendoring occur automatically. The fresh source builds take longer than the earlier package smoke. No full Rust-suite or simulator rerun is needed because production compiler/runtime code is unchanged.

All native and exact-revision hosted gates passed, and explicit final release approval was received. The source-inclusive archives are now published in the [experimental prerelease](experimental-release.md). Historical local archive hashes above describe the earlier native checkpoint; the release manifest records the final CI-built assets.
