# FOR/NEXT executable kernel checkpoint

Status: private `cfg(test)` backend prototype, 2026-10-26. The [semantic-analysis checkpoint](for-next-analysis.md) passed Windows and native Linux and was published as `636918e`. This next slice executes a reusable CLVM loop kernel in the pinned VM. **It is not connected to source-level IR lowering, and public compiler entry points still reject loops.** Compiler/language/ABI identities and released packages are unchanged.

## Kernel contract

The kernel accepts an internal list `[start, end, step, state, body-program]`. Its caller must supply already evaluated INTEGER headers and a compiler-generated body. This is an internal calling convention, not a new public ABI or raw-input validator.

- Reject zero step before checking the range, including empty-looking ranges.
- Use inclusive signed comparisons and arbitrary-precision counter addition.
- Invoke the reusable body with `[counter, state]` for each visited counter.
- Evaluate each body result once. The body returns a pair `(optional-return . next-state)`.
- Represent an absent return as nil and a present return as a singleton list containing its value. Returning nil therefore remains distinguishable from no return.
- On a present return, return the body's result immediately, without incrementing or evaluating the next iteration. Otherwise carry the updated state and advance.
- On normal completion, return `(nil . final-state)`. A skipped body leaves the supplied state unchanged.

The implementation constructs a fixed recursive program; numeric bounds are runtime input and never control code-generation size. It uses the existing pinned CLVM dialect and runner, including E0500 runtime failures and E0501 cost failures.

## Verification and limits

Five kernel tests cover:

- 324 small signed ranges against an independent host-side iteration/sum model, including equal bounds, wrong direction, negative values and non-unit steps.
- Zero step for ascending, descending and equal endpoints; failure in an executed body versus a skipped body.
- A present nil return at counter 3, with a later failing iteration at counter 4 that must never run.
- Integers above machine width, exact measured-cost success, cost-minus-one failure, and a huge range stopped by a practical VM budget.
- 10,000 iterations carrying an integer sum, with expected result 50,005,000. The kernel is 429 serialized bytes and this fixture costs 51,573,857 under the pinned profile.

The 10,000-iteration test is a bounded execution smoke test, not a proof of constant host memory or a maximum supported range. Allocation/stack measurements remain necessary before public activation. The kernel carries an opaque CLVM state tree, but this slice's execution fixtures exercise integer state only.

Header expression evaluation and left-to-right snapshot timing, typed state layout, all supported local value types, nested loops, ordered EMIT accumulation, nested function-return propagation, and source/IR inspection are not implemented by this slice. The existing whole-module lowering rejection remains in place. The kernel accepts a body program directly only inside private unit tests; it does not allow user recursion or arbitrary programs through the CLI.

Windows verification passed: all 300 Rust tests, formatting, Clippy with warnings denied, workspace build, and three frozen size/hash/cost/output regressions with exact cost-limit checks. The user confirmed native Linux formatting, Clippy and all 301 Rust tests passed. The hosted CI results for `636918e` cover the preceding semantic checkpoint, not this uncommitted kernel slice.

Published revision `65e7339` passed GitHub [compiler checks](https://github.com/steppsr/0xBASIC/actions/runs/40343939343), [simulator checks](https://github.com/steppsr/0xBASIC/actions/runs/40343939346), and [package checks](https://github.com/steppsr/0xBASIC/actions/runs/40343939449). The subsequent [private contract-lowering checkpoint](for-next-source.md) connects typed source frames and emissions to this kernel; the limitations above describe the standalone kernel checkpoint.

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

Expected: 300 Windows / 301 Linux Rust tests, including 23 private FOR/NEXT tests (nine parser, nine analysis, five kernel). No feature flag, package installation, simulator run or release rebuild is required.

This checkpoint has passed native Linux and is published. The contract-lowering checkpoint is the subsequent implementation slice. Preserve the public gate until complete execution semantics, compatibility/version changes and integration checks are ready.
