# Public FOR/NEXT activation checkpoint

Status: development compiler `0.2.0-alpha.1`, language `0.2`, ABI 1. This implements the [activation plan](for-next-activation.md). The public source compiler now accepts loops by default. Windows and native Linux validation passed; the native Linux pass was confirmed on 2026-10-27. No new release, tag or package has been published; the existing `0.1.0-m3.8b` release remains unchanged.

## Implementation and compatibility

Reusable loop parser, analysis, IR and CLVM code is compiled normally. Unit-test helpers and VM counters remain test-only. The parser flag and whole-module rejection are removed; there is no alternate legacy-language mode or enabling flag. Public parse/analyze/check/compile paths cover contract/function loops, nested returns, typed captures, snapshotted headers and ordered conditions.

Simple contracts containing loops bypass the old non-loop fast path so full semantic analysis always checks counter immutability, scoping, types and unreachable branches. The complete module value budget includes statements after the final isolated body, as well as functions. Existing non-loop generation stays unchanged.

The compiler/workspace and lockfile package identities are `0.2.0-alpha.1`; the language constant and manifest language schema are `0.2`. ABI, VM flags/profile, dependency versions, manifest schema, JSON envelope and optimization identity remain unchanged. Current compiler and language identities are required by the artifact reader. FOR/TO/STEP/NEXT are reserved case-insensitively; migrate identifiers and boundary JSON keys before rebuilding. See [usage and migration](loops-tutorial.md).

The [language 0.2 specification](../language-v0.2.md), [grammar](grammar.ebnf), implemented reference, CLI and compatibility documents now describe loops. Historical [language 0.1](../language-v0.1.md) retains its [original grammar](grammar-v0.1.ebnf). The released beginner tutorial stays explicitly targeted at the old downloadable compiler; the new loop tutorial uses source builds.

## Validation scope

The former private parser/semantic/backend tests now exercise public paths. The four pinned loop fixtures retain identical program hashes, tree hashes, costs and output bytes. External library integration tests check the same fixtures with the normal library build, verify semantic analysis for simple loop contracts, and enforce aggregate value accounting after a loop.

CLI tests cover check/build/run and every explain stage, fixed/solution fields, function return within a loop, template-only artifacts, exact-cost limits, invalid unused raw fields even for empty ranges, no-overwrite behavior, zero-step diagnostics, reserved-name migration, parse-only AST versus checked IR, and previous compiler/language identity rejection. Inspection and artifact CLVM bytes agree. The fixed-integer legacy fixture renamed its `step` parameter to `stride` without changing parameter order or expected program behavior.

This checkpoint does not replace the later loop-specific spend/full-node, source-inclusive package and release-review gates. Local execution still reports `clvm-execution-only`.

## Windows results

All 326 Rust tests passed, including public library goldens and CLI integration; formatting, Clippy with warnings denied and workspace build passed. The loop tutorial's check/build/AST/IR/CLVM/run commands were exercised with a separate output directory. The actual SHA-verified released Windows compiler rejects a new manifest with E0400, and the new compiler rejects an artifact built by that old executable with E0400. This directly verifies both reader directions, beyond mutated-identity tests.

All 40 Python verifier commands from compiler CI passed, including the M5 653-CLI-call checks, three frozen non-loop size/hash/cost/output baselines, and nine payment tutorial commands. The legacy binding fixture and verifier also migrated STEP to STRIDE. Specification links and grammar/schema checks pass. The four loop program baselines remain unchanged. Native Linux verification passed, as confirmed by the tester on 2026-10-27: 327 Rust tests and all four handoff Python verifiers. The handoff correction below includes workflow files needed by the documentation link checks and uses `python3`.

## Native Linux validation commands

This activation changes root manifests/lockfile, both crates, tools, fixtures and documentation. The earlier source-only copy is insufficient. Include `.github/`: the documentation verifier checks links to workflow files. On native Linux, invoke the verifiers with `python3`; a `python` alias is not required. From the existing native checkout:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/.gitignore /mnt/artoo/e/DEV/0xBASIC/Cargo.toml /mnt/artoo/e/DEV/0xBASIC/Cargo.lock /mnt/artoo/e/DEV/0xBASIC/README.md ./
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a /mnt/artoo/e/DEV/0xBASIC/crates/ crates/
rsync -a /mnt/artoo/e/DEV/0xBASIC/tools/ tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/examples/ examples/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/language-v0.1.md /mnt/artoo/e/DEV/0xBASIC/docs/language-v0.2.md /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 tools/verify_m3_bindings.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 tools/verify_m5.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 tools/verify_tutorial.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
"$CARGO_TARGET_DIR/debug/0xbasic" --version
```

Expected: 327 native Linux Rust tests and version compiler `0.2.0-alpha.1`, language `0.2`, ABI `1`, target `chia-clvm-0.19-strict-v1`. Python commands above use the explicit native binary where supported. No simulator or release rebuild is required yet. After publishing this checkpoint, verify exact-revision hosted CI before adding the representative authorized loop-spend scenario.
