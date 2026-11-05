# Run the packaged loop example

This guide is included as `LOOPS.md` in compiler `0.2.0-alpha.1` candidate packages (language `0.2`, ABI 1). It does not apply to the older `0.1.0-m3.8b` release. These commands use only files extracted from the package; Rust and Python are not needed to run the executable.

From the extracted package root, use `./bin/0xbasic` on Linux or `./bin/0xbasic.exe` on Windows:

```text
./bin/0xbasic check examples/counted-heights.bas --json
./bin/0xbasic explain examples/counted-heights.bas --stage ast --json
./bin/0xbasic explain examples/counted-heights.bas --stage ir --json
./bin/0xbasic explain examples/counted-heights.bas --stage clvm --json
./bin/0xbasic build examples/counted-heights.bas --out loop-build --json
./bin/0xbasic run loop-build/manifest.json --json
```

`loop-build` must not already exist. The source loops from 5 down to 1 with STEP -2, emitting the raw condition list `((83 5) (83 3) (83 1))`. AST and IR inspection describe the parsed and checked program. CLVM inspection shows serialized bytes, hashes and the flat tree; it does not execute the program. `run` reports `clvm-execution-only`, not a signed or confirmed spend.

The complete source bundle `source.tar.gz` includes the loop implementation, tests, examples, `docs/spec/loops-tutorial.md`, and `docs/language-v0.2.md`. Follow `REBUILD.md` to rebuild it offline with a prepared Rust toolchain, or to rebuild with a modified library. Simulator sources and pinned setup files are included for reference; offline Cargo rebuild support does not include an offline Python simulator installation.
