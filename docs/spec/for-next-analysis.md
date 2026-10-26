# FOR/NEXT semantic-analysis checkpoint

Status: private unit-test prototype, 2026-10-26. The user confirmed the [parser checkpoint](for-next-parser.md) passed native Linux testing; that checkpoint was published in `b3443ab`. This slice adds semantic checking under the same `cfg(test)` boundary. **Normal builds and public CLI/library entry points still do not support loops.**

## Semantic rules implemented

- Check start, end and explicit STEP expressions in source order, in the enclosing scope, requiring INTEGER. The counter is introduced only afterward. Omitted STEP stays absent in syntax metadata for later defaulting.
- Introduce a fresh, case-insensitive INTEGER counter with existing no-shadowing rules. It is read-only, visible only in the loop body, and cannot be used to initialize itself or referenced after NEXT.
- Analyze the body in a cloned lexical scope. Body-local declarations cannot escape. Assignments to outer DIM locals retain their declared type; fixed/solution/function parameters and constants remain immutable.
- Analyze all source, including an empty-looking range, an unselected branch and code after RETURN. Function calls in headers/bodies still participate in recursion-cycle detection.
- Enforce typed function RETURN, forbid contract RETURN and function EMIT, and conservatively treat every loop as potentially executing zero times. A return only inside a loop does not prove a function returns on all paths.
- Do not evaluate header values during analysis. A correctly typed zero step or a failing INTEGER-producing conversion is accepted for later runtime handling, preserving the design's failure timing.

## State metadata and execution boundary

Each analyzed loop records its owning contract/function, counter name, source span, header expressions in source order, and the names/types of outer mutable locals assigned anywhere in its body. Nested loops and conditional branches contribute assignments; body-local variables and untouched outer locals are excluded. Carried-local entries use deterministic name order. A nested loop can carry a local declared in the enclosing loop body, while that local remains absent from the outer loop's entry state.

The metadata also conservatively records whether the body contains EMIT or RETURN, including nested/unreachable occurrences. These flags are not an ordered condition sequence, a runtime path prediction, or executable IR. Header expressions are retained rather than folded from mutable locals; runtime evaluate-once snapshots and actual state transitions are still to be implemented.

Metadata type copies have a separate 65,536-node budget per analyzed module, including each counter and recursively counted carried-local types. The implementation charges before cloning each type. Existing expression/type/constant budgets remain active. This is an internal compiler-work guard, not an on-chain iteration or value-size rule.

The test-only backend gate scans the entire module before lowering fast paths or unreachable-code pruning. It rejects every loop-containing module with E0205, even a loop after RETURN or inside `IF FALSE`. Passing semantic analysis cannot accidentally enable partial loop compilation. Existing production output formats do not include the new metadata.

## Verification

Nine new semantic tests cover header typing/order, counter scoping and immutability, all supported carried-local types, nested/conditional assignment metadata, return-path rules, unreachable source and recursion checks, backend rejection, and exact state-metadata budget boundaries. Together with the nine parser tests, there are 18 private FOR/NEXT tests.

Runtime claims are deliberately deferred: no test in this slice proves iteration values, zero-step runtime failure, actual snapshot timing, carried state execution, condition order or early-return continuation behavior. Those require executable lowering and VM tests in the next slice.

Windows verification passed: all 295 Rust tests (including all 18 private FOR/NEXT tests), formatting, Clippy with warnings denied, workspace build, and the three frozen regression cases through 12 CLI calls. The user confirmed native Linux verification passed: formatting, Clippy and all 296 Rust tests.

The published parser revision `b3443ab` passed GitHub [compiler checks](https://github.com/steppsr/0xBASIC/actions/runs/40263346020), [simulator checks](https://github.com/steppsr/0xBASIC/actions/runs/40263346045), and [package checks](https://github.com/steppsr/0xBASIC/actions/runs/40263346135). Those results cover the parser revision, not these uncommitted semantic changes.

## Native Linux commands

From the same native checkout used for the parser checkpoint:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/crates/compiler/src/ crates/compiler/src/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

Expected: 18 FOR/NEXT unit tests and 295 Windows / 296 Linux Rust tests overall. The new `analysis/for_next.rs` file is included by the source-directory copy. Do not supply a feature flag. No simulator, package installation or release rebuild is needed for this private analysis checkpoint.

After Linux confirmation, proceed to typed executable loop lowering and VM validation in a bounded implementation slice. Keep the test-only gate until execution, compatibility/version changes and the relevant integration gates are complete. Existing experimental packages and the beginner tutorial remain unchanged.
