# 0xBASIC experimental package

This archive contains a native compiler/local runner, its license, package provenance and public payment examples. It is a development candidate, not a published production release. No Rust or Python installation is needed to run the executable. Native operating-system runtime libraries are still required; this package is tested on its build/smoke platform, not certified for every Windows version or older Linux distribution. Linux uses the GNU/glibc target; the builder's libc version is recorded in `package.json`. macOS and ARM packages are not provided.

Check the adjacent `.sha256` file against the downloaded archive before extraction. Checksums detect changes; they are not a publisher signature. Extract into a new directory and run commands from its root. On Linux retain executable permissions for `bin/0xbasic`. On Windows substitute `./bin/0xbasic.exe` for `./bin/0xbasic` below. No administrator installation or global PATH change is required.

```text
./bin/0xbasic --version
./bin/0xbasic --help
./bin/0xbasic check examples/height-locked-payment.bas --json
./bin/0xbasic explain examples/height-locked-payment.bas --stage clvm --bindings examples/height-locked-payment.bindings.json --json
./bin/0xbasic build examples/height-locked-payment.bas --bindings examples/height-locked-payment.bindings.json --out payment-build --json
./bin/0xbasic run payment-build/manifest.json --json
```

`payment-build` must not already exist. Expect local cost `1487727` and validation label `clvm-execution-only`; the result is a raw condition tree for amount, height, signature requirement and recipient output. This command does not sign, contact a node, fund a coin or confirm a spend. Example bindings are public fixtures, not wallet credentials. Keep generated artifacts separate from the executable installation.

`package.json` identifies compiler, target and Rust version, Cargo.lock digest, source-file hashes and packaged-file hashes. It is provenance information, not source authentication. A compiler upgrade can require rebuilding artifacts, and changed puzzle bytes can change coin puzzle identity. Preserve original source, bindings and artifact directories; do not edit a manifest's versions to force compatibility.

Compiler errors are structured with `--json`. Exit codes: 0 success, 1 source/type/binding/solution conversion error, 2 usage/unsupported version, 3 execution/cost failure, 4 I/O/artifact integrity failure, 70 handled internal failure. Local execution is not consensus spend validation.

The repository supplies the complete language reference and isolated simulator harnesses: https://github.com/steppsr/0xBASIC . The root LICENSE applies to project code. Third-party dependency attribution/distribution review and final release authorization are part of the separate release gate; this candidate archive is not that approval.

The accompanying `source.tar.gz` includes application and locked dependency sources. `THIRD-PARTY-NOTICES.txt` contains dependency terms and credits; `REBUILD.md` explains offline builds and replacement of a library with modified source. Keep these materials with the executable when distributing the candidate.
