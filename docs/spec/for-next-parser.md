# FOR/NEXT parser checkpoint

Status: parser/AST prototype, 2026-10-25. This implements the first bounded slice of the [FOR/NEXT proposal](for-next-design.md). **The released language and normal CLI still do not support loops.** No grammar, ABI, compiler identity, dependency or release asset has changed.

## Compatibility and partial-feature decision

The prototype is compiled only inside the compiler crate's unit-test build, using Rust `cfg(test)`. A private parser mode enables it for those tests. There is no Cargo feature, environment switch, public library entry point or CLI flag enabling loop syntax. Normal parsing uses the existing reserved-name set, including continued acceptance of FOR, TO, STEP and NEXT as ordinary identifiers where previously permitted.

This permits parser development without publishing a partially executable language or changing `0.1.0-m3.8b` behavior. Public `check`, analysis, build and AST/IR/CLVM inspection continue to reject FOR statements. Even if the test-only AST is passed directly to analysis/lowering, it returns E0205 rather than treating the loop as executable. Compiler/language version changes remain required before exposing loop-aware behavior publicly. The proposal's language `0.2` decision must be finalized with that activation; no version was selected or incremented in this slice.

## Implemented prototype

- FOR header with start, end and optional STEP expressions; omitted STEP remains absent in the parsed AST rather than being synthetically evaluated.
- Body parsing in contracts and functions, nested FOR/IF/ELSEIF/ELSE structures, comments and continued expressions.
- Required case-insensitive matching `NEXT counter`; diagnostics for missing, mismatched or malformed terminators and headers.
- Original-byte source spans for FOR, counter, TO, STEP, header, expressions, NEXT and closing counter. BOM, CRLF, tabs and Unicode comments retain the existing location convention.
- A flat debug AST For node with child expression/body indexes before the parent. This test view is not a public inspection format.
- At most 256 syntactic FOR statements per contract/function body, counting loops in skipped branches; a shared depth limit of 32 with existing conditional/ELSEIF depth accounting. Other existing statement budgets remain unchanged.
- Prototype-only reservation of FOR, TO, STEP and NEXT for declarations and expression references.

Syntax-only parsing deliberately does not establish counter scope, read-only assignment rules, INTEGER header types, step validity, definite returns or loop execution. Those are the next semantic slice. Parser acceptance of a BOOLEAN header or a literal zero step is not a claim of executable validity.

## Verification and native Linux handoff

Nine new unit tests cover source locations, flat AST structure, optional/negative steps, functions/nesting, malformed syntax and counters, keyword compatibility, exact count/depth boundaries, semantic rejection of prototype ASTs, and all public frontend gates. The existing production compiler tests also run with the parser mode disabled.

Windows verification passed: all 286 Rust tests, formatting, Clippy with warnings denied, and a normal workspace build. The three frozen generated-program byte/hash/cost/output regressions and their exact cost boundaries also passed. Native Linux verification also passed, confirmed by the user on 2026-10-25 (287 tests). Both native gates for this parser checkpoint are complete.

From the existing native Linux checkout, copy the changed compiler source tree, then run:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/crates/compiler/src/ crates/compiler/src/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

Expected: nine additional `syntax::for_next` unit tests pass; full totals are 286 Windows / 287 Linux Rust tests. Do not add a feature flag: the unit-test build activates test infrastructure, while public APIs still use the original parser mode. No package install, simulator rerun, dependency update or new release build is needed for this checkpoint.

## Next slice

After native Linux confirmation, add scoped INTEGER counters, header checking/snapshots and typed loop-state analysis behind the same private test gate. Resolve carried locals, emission ordering and conservative return analysis before backend support. Public loop activation waits for a coherent implementation and versioned compatibility checkpoint; the beginner tutorial remains accurate for the existing release.
