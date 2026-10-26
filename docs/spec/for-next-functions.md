# FOR/NEXT private function/return checkpoint

Status: private unit-test implementation, 2026-10-26. The [contract-lowering checkpoint](for-next-source.md) passed Windows and native Linux and was published as `8bbdb4b`. This slice connects functions and return-aware continuations to the same typed loop IR and CLVM kernel. **The public compiler/library/CLI still reject loops.** Compiler/language/ABI identities and release assets remain unchanged.

## Function integration

The private test helper now uses the shared module-lowering implementation after parsing and semantic checking. The ordinary module entry point retains its whole-module loop rejection; only the private test helper bypasses that gate. Full semantic analysis still checks unreachable syntax/types and prohibits user recursion.

Function dependency discovery descends into isolated loop bodies. A function can therefore call a later-declared function from a nested loop body, as well as from its header. Code generation waits for those callees before constructing the caller. The existing function parameter and signature rules apply.

Return discovery now descends through FOR and IF. Functions with a return inside a loop use the existing optional-return state: nil means continuing, while a singleton list means returned, even if the return value is zero, FALSE, empty bytes/string or an empty list.

Loop frames inherit the enclosing function result type and carry this return state as an internal capture. Loop IR records the return-state output index. The CLVM body adapter passes that optional return to the kernel along with the updated frame. On return, the kernel skips increment and the next iteration. The lowerer guards the remaining source continuation, so a return also skips following statements, enclosing loop iterations and subsequent loops. Nested IF/FOR paths propagate the same state until the function result is extracted. A callee's return remains local to that callee; it does not return from its caller's loop.

A zero-iteration function loop preserves the incoming frame and reaches its following continuation. Definite-return analysis still treats every loop as potentially executing zero times; a return only inside a loop does not prove all function paths return.

## Module budgets

The 4,096-value module count now includes recursively contained loop-body values in the contract and every function, both during lowering and before backend construction. Function readiness checks also traverse those body values.

The 65,536-node frame-copy budget is shared across contract and function lowering. In addition to two copies of each capture type and the counter node, a function loop charges the inherited result-type copy before constructing its body frame. The cross-function fixture accepts two functions with 16 loops each, each capturing a 1,023-node type (65,536 total charged nodes), and rejects 17 loops in each. Existing semantic metadata/type/constant limits remain separate.

## Verification scope

Five new tests cover:

- Early return through nested IF/FOR, zero/empty ranges reaching a fallback, and skipping failing statements or a later zero-step loop after return.
- Return values across INTEGER, BOOLEAN, BYTES, STRING, LIST, PAIR, AMOUNT, PUZZLEHASH, PUBLICKEY and CONDITION, explicitly including false/empty values.
- Forward dependencies in nested bodies and headers, function-produced conditions emitted by contract loops, and a callee returning without terminating its caller's loop. Exact measured cost succeeds and cost-minus-one fails.
- Conservative definite return, wrong-type unreachable returns, recursion detected in an empty-looking loop, entered versus unselected zero-step failures, and public frontend rejection.
- Frame-copy and aggregate value budgets spanning multiple functions.

The existing parser, semantic, kernel and contract-loop cases remain. These tests validate private source-to-VM behavior, not public CLI/artifact integration or a new release.

## Remaining work

The next bounded task is emission-accumulation performance and resource measurement. The current adapter repeatedly appends the accumulated condition prefix; emitting-loop cost can grow quadratically. Measure and improve that representation while preserving nested order and function return behavior. Stack/allocation measurements and adversarial mixed nesting are still required.

After those private backend checks, complete public activation/version and keyword migration, inspection/CLI/artifact compatibility, Windows/native Linux and applicable spend/full-node integration, then source-inclusive packages and release review. Do not enable loops or change release identities merely because the private tests pass.

Windows verification passed: all 313 Rust tests (36 private FOR/NEXT tests), formatting, Clippy with warnings denied, workspace build, and three frozen production size/hash/cost/output regressions with exact cost-limit checks. The user confirmed native Linux formatting, Clippy and all 314 Rust tests passed. Hosted CI for `8bbdb4b` covers the preceding contract-only checkpoint.

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

Expected: 313 Windows / 314 Linux Rust tests, including 36 private FOR/NEXT tests. No feature flags, installation, simulator rerun or release rebuild is required for this checkpoint.
