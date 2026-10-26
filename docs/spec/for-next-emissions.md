# FOR/NEXT emission accumulation and VM resource checkpoint

Status: private unit-test implementation, 2026-10-26. The [function/return checkpoint](for-next-functions.md) passed Windows/native Linux and was published as `4f76533`. This slice improves condition accumulation and adds measured VM resource tests. Public loop support remains disabled; language/compiler/ABI versions, dependency versions, lockfile and released assets remain unchanged.

## Assembly change

Loop state now holds conditions in reverse execution order. At each iteration, a tail-recursive helper visits only the current body's forward condition list and prepends its reversal to the accumulated state. It no longer traverses the accumulated prefix on every iteration. On loop exit, a single reversal restores forward order. The kernel result is bound once before normalization, so neither execution nor returned state is duplicated.

Final spread-list assembly in private loop-containing frames also uses tail-recursive reversal/assembly. This removes the measured stack growth that remained when the old recursive append assembled a long final result. Ordinary non-loop frames retain their existing encoding. Nested loops normalize their own outputs before their parent consumes them; the existing exact-order, condition-return, skipped-body and nested early-return tests continue to pass.

The per-loop accumulation work is linear in emitted conditions rather than repeatedly copying the entire prefix. Nested loop boundaries can still traverse the same conditions at multiple levels, and arbitrary source expressions have their own costs. This is not a global constant-memory or universal linear-runtime guarantee.

## Measured evidence

The same source fixture emits `ASSERT_HEIGHT_ABSOLUTE(i)` for each counter from 1 through N. Windows before and after runs use the pinned VM profile with identical test-only instrumentation. Exact serialized conditions are compared with an independent constructed expectation. Raw counters and additional fixtures are recorded in [the measurement data](for-next-emission-metrics.json).

| Emissions | Previous VM cost | New VM cost | Previous peak pairs | New peak pairs |
| ---: | ---: | ---: | ---: | ---: |
| 32 | 731,099 | 375,172 | 15,799 | 7,604 |
| 64 | 2,371,163 | 742,180 | 52,423 | 14,324 |
| 128 | 8,397,948 | 1,476,485 | 190,183 | 27,764 |
| 256 | 31,439,100 | 2,947,205 | 723,751 | 54,644 |

At 256 emissions, cost decreases about 90.6% and peak allocated pairs about 92.4%. New peak VM stack entry counts stay at 38 value / 15 environment / 37 operation entries over these samples; previously the 256-emission case reached 795 / 266 / 794. Tests enforce less than 2.2x cost and peak-pair growth when these sample sizes double, and small stack ceilings.

A non-emitting sum loop at 32, 256 and 1,024 iterations keeps measured peak VM stacks at 36 / 14 / 35 entries. Its cost and pair allocations still grow with iteration count. Mixed FOR/IF fixtures at loop depths 1, 4 and 8 execute and validate their final sums; the depth-8 fixture has 16 nested source blocks, costs 9,187,565, and reaches 243 / 96 / 242 VM stack entries and 189,049 peak allocated pairs. These are bounded sampled measurements, not coverage of every permitted nesting shape or the maximum accepted depth.

Counters come from clvmr's `counters` feature, enabled only as a compiler dev-dependency. They measure VM stack entries and allocator statistics, not native thread-stack bytes, process RSS or total application memory. Atom heap counters are not a substitute for pair storage. No allocator limit, iteration cap or consensus rule was changed.

## Validation and remaining work

Three new tests cover emission scaling/order, non-emitting stack samples and mixed nesting. The previous 36 private FOR/NEXT tests remain. The instrumentation does not create a public feature flag or CLI option. The normal runner still enforces its existing VM cost and output limits.

Next, harden maximum-depth and adversarial control-flow cases and establish cross-platform deterministic loop fixtures before selecting public activation/version changes. Public AST/IR/CLI/artifact integration, keyword migration, spend/full-node checks and source-inclusive release review remain planned gates.

Windows verification passed: all 316 Rust tests (39 private FOR/NEXT tests), formatting, Clippy with warnings denied, workspace build and three frozen production size/hash/cost/output regressions with exact cost-limit checks. The user confirmed native Linux formatting, Clippy and all 317 Rust tests passed. Hosted CI for `4f76533` covers the preceding function/return checkpoint.

## Native Linux verification

This checkpoint also changes the compiler manifest to enable test-only counters. Copy both the manifest and source directory from the Windows workspace, from your existing native checkout:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/crates/compiler/Cargo.toml crates/compiler/Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/crates/compiler/src/ crates/compiler/src/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
```

Expected: 316 Windows / 317 Linux Rust tests, including 39 private FOR/NEXT tests. No explicit feature flag, simulator rerun or release rebuild is needed. Cargo may rebuild the already pinned VM with instrumentation for tests.
