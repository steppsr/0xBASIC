# Fee-payment milestone review

Status: FP-1 through FP-4 passed Windows, native Linux (LANDO) and exact-revision GitHub CI. FP-5 adds the [fee-payment walkthrough](fee-payment-tutorial.md), command verification and fee-specific package/rebuild checks. FP-5 Windows validation passed: six fee tutorial commands, five existing payment/change commands, nine package tests and 30 extracted CLI commands with two matching offline rebuilds. Native LANDO passed, confirmed by the user on 2026-11-09. Publication and exact-revision CI are the remaining gates.

| Layer | Evidence and limits |
| --- | --- |
| [FP-0 semantics](fee-payment-semantics.md) | Pinned-upstream reservation, additive aggregate minimum and compatibility decision |
| [FP-1 constructor](reserve-fee-activation.md) | RESERVE_FEE analysis/lowering/type/boundary checks; independent VM; unchanged historical program hashes, conditions and costs |
| [FP-2 local](fee-payment-local.md) | 16 positive and 45 negative cases across 120 CLI calls; message/accounting oracle, max amounts, raw/host boundaries, deterministic artifacts and cost limits |
| [FP-3 SpendSim](fee-payment-spendsim.md) | 20 scenarios, 14 rejections and 20 confirmed control bundles per run; two identical fresh runs; signature/replay/amount/raw-input cases, additive fees, zero fees, excess fees and an explicitly weakened unreserved comparison |
| [FP-4 full node](fee-payment-full-node.md) | Four representative rejections and three controls for fees; combined legacy/loop/change/fee run: 14 rejections and 7 controls, exact block fees and coin/store/height accounting; 28 reporting tests |
| FP-5 tutorial | Six actual document command blocks; partial/exact/zero-fee condition oracle, inspection/build byte/hash parity and unchanged artifacts; local execution only |
| FP-5 packages | Fee fixtures and FEES.md in native archives; language 0.3 in source bundle; independent partial/exact/zero-fee oracle, budgets and overwrite checks against extracted binary and original/modified-library offline rebuilds |

FP-4 is published at `35555dca59e6c7ae597687e5d923eff1a0f2d861`. Its [compiler CI](https://github.com/steppsr/0xBASIC/actions/runs/42558305943), [simulator CI](https://github.com/steppsr/0xBASIC/actions/runs/42558305960) and [package CI](https://github.com/steppsr/0xBASIC/actions/runs/42558305944) passed on both platforms, including both extracted smokes. Those package runs cover the earlier payment/loop checks; they do not certify the new FP-5 fee package checks.

Compiler CI now runs the fee tutorial verifier. Existing package CI runs the extended archive verifier, including offline rebuilds and a separate job without a source checkout. The standalone verifier retains support for prior released compiler identities and requires fee materials only for 0.3.0-alpha.1. Windows also verified the existing 0.1.0-m3.8b and 0.2.0-alpha.1 archives using the updated verifier (8 and 17 CLI commands respectively). Simulator behavior is unchanged in FP-5; no additional full-node or SpendSim run is needed for this slice.

## Compatibility and release scope

Fee support uses compiler 0.3.0-alpha.1, language 0.3, ABI/schema 1 and profile chia-clvm-0.19-strict-v2. Dependencies, VM flags and existing program meanings are unchanged. The compatibility gate rejects older compiler/language/profile artifact identities with E0400; rebuild old sources under the selected compiler rather than editing manifests. FP-1 freezes historical bytes/hashes/costs and tests these identity failures.

The published v0.2.0-alpha.1-experimental release and older assets remain unchanged. FP-5 creates local/CI candidate archives only. Any new prerelease requires separate explicit approval after review. Public fixture keys are test material. Wallet discovery, production key management, coin selection, fee estimation and public-network submission remain out of scope.

## Native FP-5 gate

Use the existing LANDO checkout. These commands synchronize the new tutorial/package changes and run the relevant checks. Package creation builds a release binary and performs two offline source rebuilds; allow several minutes and sufficient temporary disk space. No simulator environment change is needed.

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/tools/ tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 tools/verify_fee_payment_tutorial.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 tools/verify_payment_change_tutorial.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 -m unittest discover -s tools -p test_package.py
python3 tools/package_experimental.py
)
```

Expected: six fee tutorial commands, five existing payment/change tutorial commands, nine package tests and successful package creation with 30 extracted CLI commands and two offline rebuilds. Preserve `.work/payment-fee/tutorial-linux.json` and `.work/packages/package-linux.json`. The package report must include `packaged_fee`, two matching `rebuilt_fees`, and `offline_rebuilds: 2`. Native confirmation is complete. Commit/push, verify exact-revision CI, then close FP-5 and review the next direction or a separately approved release.
