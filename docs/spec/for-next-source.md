# FOR/NEXT private contract-lowering checkpoint

Status: private `cfg(test)` implementation, 2026-10-26. The [kernel checkpoint](for-next-kernel.md) passed Windows/native Linux and was published as `65e7339`. This slice connects parsed, semantically checked **contracts without functions** to typed loop IR and the executable CLVM kernel. Normal builds, public library entry points and the CLI still do not accept loops. Compiler/language/ABI identities, released packages and the beginner tutorial remain unchanged.

## Implemented bridge

A private test helper parses with FOR/NEXT enabled, performs full semantic analysis, explicitly rejects modules containing functions, and lowers the contract. The ordinary module-lowering entry point retains its whole-module loop rejection, including unreachable loops. The new IR variant and backend adapter are compiled only into compiler unit tests.

Headers become ordered outer-frame value bindings: start, end, explicit step or INTEGER 1. Existing binding continuations evaluate these once in source order before invoking the kernel. Changing a captured end/step variable in the body cannot change the header snapshots. Nested headers execute afresh on each entry.

Each loop has an isolated typed body frame containing its counter followed by lexical captures in deterministic name order. Captures include immutable and unchanged bindings as well as assigned locals. This is a simple complete lexical frame, broader than the semantic analyzer's minimal list of assigned outer locals. Capture parameters prevent mutable values from being folded to their entry literals. Body-local declarations are recreated during each execution and do not become outputs. Existing constant evaluation rules and its work budget remain active.

The loop IR records header IDs, capture IDs/names, body values/types, output IDs and emissions. Its backend adapter packs state as `[conditions, captures...]`, invokes the body with its counter and captured values, binds the result once, appends that iteration's conditions in execution order, and carries the output frame. Nested loops and IF/ELSE use the same body lowering. The final state supplies outer-local projections and a spread condition sequence for following statements.

Two private compiler guards accompany this representation:

- At most 4,096 value bindings across the outer contract and recursively contained loop bodies, including parameter bindings. Checks include completed bodies as they are added, and the complete lowered contract.
- At most 65,536 nodes for the new frame type copies, shared across nested and sibling loops. Each capture charges two copies of its recursive type plus one node for the loop counter, before creating those frame copies. This is separate from semantic metadata and existing expression/type/constant budgets.

## Executable evidence

Eight new source-to-VM tests cover:

- Evaluate-once end/step snapshots, sequential carried assignments, body-local initialization and zero-iteration preservation.
- Descending ranges, nested header re-entry, conditional updates, and exact pre/body/nested/post condition order.
- 300 runtime emissions from one syntactic EMIT, demonstrating that the existing 256-statement syntax limit is not a new runtime condition limit.
- INTEGER, BOOLEAN, BYTES, STRING, AMOUNT, PUZZLEHASH, PUBLICKEY, LIST, PAIR and CONDITION local state, including an outer constant used by a body constant.
- Zero step, failing header conversions, skipped bodies/branches, and eager failure of an unused executed initializer. Costly earlier headers exhaust a small VM budget before later failing conversions; a larger budget reaches the later E0500 failure. This distinguishes start-before-end and end-before-step evaluation.
- Dynamic solution bounds, exact measured-cost success/cost-minus-one failure, and rejection of an invalid unused BOOLEAN input even when the loop would execute zero times.
- Deterministic generation on repeated calls, typed IR serialization and code size that does not grow with numeric iteration count; a huge range is stopped by the VM budget.
- Shared frame-type budget acceptance/rejection at 32/33 copies of a 1,023-node captured type, and the combined value limit across isolated bodies.

The earlier 23 parser/analysis/kernel tests remain, including the public frontend rejection checks. Repeated local generation is not a claim of a new cross-platform golden-byte fixture.

## Remaining work

This slice rejects every module containing a FUNCTION. Source-level function calls, loops inside functions and nested early-return propagation are the next bounded integration task. The kernel's isolated early-return test is not evidence that source-level function returns are connected.

Condition accumulation currently appends the accumulated prefix each iteration. It is correct for the tested ordering cases but can have quadratic cost for emitting loops. Review the representation and measure costs before public activation. Allocation/stack measurements, wider adversarial nesting/resource tests, public AST/IR/CLI/artifact integration, version/keyword migration and spend integration also remain. No source-loop release or compatibility promise is made by this private checkpoint.

Windows verification passed: all 308 Rust tests (31 private FOR/NEXT tests), formatting, Clippy with warnings denied, workspace build, and three frozen production size/hash/cost/output regressions with exact cost-limit checks. The user confirmed native Linux formatting, Clippy and all 309 Rust tests passed. The hosted CI results for `65e7339` cover the preceding kernel checkpoint.

Published revision `8bbdb4b` passed GitHub [compiler checks](https://github.com/steppsr/0xBASIC/actions/runs/40376021236), [simulator checks](https://github.com/steppsr/0xBASIC/actions/runs/40376021305), and [package checks](https://github.com/steppsr/0xBASIC/actions/runs/40376021147).

The subsequent [function/return checkpoint](for-next-functions.md) extends the private bridge to functions and nested early returns. The function exclusions above describe this historical contract-only slice.

## Native Linux verification

From the existing native checkout:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/crates/compiler/src/ crates/compiler/src/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

Expected: 308 Windows / 309 Linux Rust tests, including 31 private FOR/NEXT tests. No feature flag, dependency install, simulator rerun or release rebuild is required. This checkpoint passed native Linux and was published as `8bbdb4b`; the function/return checkpoint is the next implementation slice.
