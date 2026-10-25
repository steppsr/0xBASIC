# Rebuild and replace libraries

This source bundle accompanies the matching experimental binary. Keep it with the binary when redistributing the candidate. The bundle includes 0xBASIC source under Apache-2.0, complete Cargo-vendored dependency sources with their original licenses, supplemental notices from exact upstream commits, and build configuration. THIRD-PARTY-NOTICES.txt includes the GNU LGPL v3 and GNU GPL v3 texts for Malachite. The program uses Malachite through clvmr; no claim is made that disabling a runtime flag removes that library from distribution.

Install Rust 1.95.0 with rustup and the ordinary native C/C++ toolchain (MSVC Build Tools on Windows; C compiler/build tools on Linux). These are general-purpose build tools, not included binaries. A prepared toolchain can rebuild with Cargo networking disabled. Extract source.tar.gz into a new directory and run from its root:

```text
cargo build --release --locked --offline -p oxbasic-cli
```

Cargo's local .cargo/config.toml redirects registry dependencies to the included vendor directory. The built program is target/release/0xbasic.exe on Windows or target/release/0xbasic on Linux unless CARGO_TARGET_DIR overrides the output. Run it directly; installation, signing keys, a network service and publisher approval are not needed. No technical restriction prevents using a locally modified executable.

To rebuild with a modified Malachite library, copy vendor/malachite-bigint to modified-libraries/malachite-bigint, make the desired source edits, and append this to the root Cargo.toml:

```toml
[patch.crates-io]
malachite-bigint = { path = "modified-libraries/malachite-bigint" }
```

Then use `cargo build --release --offline -p oxbasic-cli`. Omit `--locked` for this deliberate modification: Cargo updates the lock entry from a registry source to the local path. Other dependencies continue to resolve from vendor. The path override avoids editing checksum-protected vendor contents. To modify malachite-base or malachite-nz as well, copy each to its own modified-libraries directory and add the corresponding path override. Keep and identify modifications when redistributing them under their applicable licenses.

After rebuilding, check `--version`, build examples/height-locked-payment.bas with its companion bindings JSON, and run the resulting manifest. Unmodified sources should preserve the documented puzzle hash/conditions and local cost 1487727. A source/library modification can intentionally change compiler behavior or puzzle bytes; compare outputs and repeat relevant validation before using new artifacts. Binary-byte reproducibility across toolchains/paths/hosts is not promised.

The package tests demonstrate an offline build from the extracted source bundle and a second offline build using a locally modified malachite-bigint path dependency. Those are engineering checks, not an independent legal opinion. Modification and reverse engineering for debugging modifications are permitted by this distribution; no additional restriction is imposed on those activities. The applicable upstream license terms remain in force.
