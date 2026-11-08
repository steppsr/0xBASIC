# FP-1: RESERVE_FEE activation

Status: Windows and native LANDO passed, confirmed by the user on 2026-11-07. The workspace Rust suite, format/Clippy checks, all 43 compiler CI Python commands, the independent constructor gate and seven package tests passed. Compiler `0.3.0-alpha.1`, language `0.3`, ABI 1, profile `chia-clvm-0.19-strict-v2`. No released tag or archive changes. [FP-0](fee-payment-semantics.md) records the selected semantics and migration; the [plan](fee-payment-plan.md) separates later fee-payment examples and funded validation.

`RESERVE_FEE(AMOUNT) -> CONDITION` returns `(52 amount)`. Zero is valid, integer arguments require explicit conversion, and only EMIT adds the condition to the returned list. Calls evaluate their argument through the existing eager expression path. Domain guards still reject malformed or out-of-range values, including unused expressions and raw boundary data. Functions, locals, branches and FOR/NEXT can construct or carry the condition using existing rules. CONST calls, wrong arity/types and shadowing the reserved name are rejected.

```basic
CONTRACT MinimumFee()
    SOLUTION fee AS AMOUNT
    EMIT RESERVE_FEE(fee)
END CONTRACT
```

This minimal constructor example demonstrates output generation only. It has no ownership authorization and is not the upcoming complete fee-payment contract. Local execution does not verify fee sufficiency, signatures, funded inputs or confirmation.

## Compatibility and validation

Rename existing identifiers named RESERVE_FEE and rebuild old sources into fresh artifact directories. The reader rejects mismatched compiler, language and target profile identities with E0400. ABI and schema version remain 1. [Language 0.3](../language-v0.3.md) and [profile v2](target-profile-v2.md) describe the activated surface; profile v1 and released archives remain unchanged. Cargo.lock changes only the two workspace package versions, with no dependency upgrade.

Three Rust tests cover canonical zero/one/sign-bit/maximum encoding; unused and failing calls; function/branch/loop and saved-condition ordering; exact-cost exhaustion; wrong types/arity, CONST calls and reserved identifiers. Existing Rust tests retain the broader AMOUNT and CONDITION boundary rules.

`tools/verify_reserve_fee.py` checks seven amounts through host/raw solutions, exact and insufficient VM budgets, malformed host/raw values, fixed bindings, CLVM inspection/build equality, and rejection of all three old identities. Its optional upstream mode uses the pinned Chia Program runtime to independently compare conditions, costs and invalid raw-input rejection. It performs 58 CLI calls, excluding the standalone version command. It records local-only validation, binary/source hashes and costs in `.work/fp1/reserve-fee-<platform>.json`; a failed new run removes stale success first.

Before rebuilding the old `0.2.0-alpha.1` executable, its height-locked payment, counted-heights and partial payment/change outputs were captured in [frozen legacy baselines](fee-legacy-baselines.json). The verifier requires unchanged LF-normalized source digests (plus exact per-build manifest source hashes), template/puzzle byte hashes and tree hashes, returned trees and local costs. Legacy builds use temporary LF-normalized source copies so Git checkout line endings cannot invalidate the check. Original capture hashes are retained alongside normalized hashes; frozen program hashes and costs are not rewritten. Existing historical Rust/reference fixtures are unchanged. The manifest's producer/profile/lock metadata intentionally changes.

Compiler CI runs the new standard-library verifier. Simulator CI also runs it with the pinned independent VM. Package compatibility recognizes the new compiler as retaining FOR/NEXT coverage; old package identities remain supported. Full fee-package/rebuild evidence remains FP-5, and no new release is approved by this activation.

## Native LANDO gate

Use the existing local checkout and isolated simulator Python. The source refresh is required because these changes are not on GitHub yet. This sync preserves the native `.work` environment and Cargo output directory.

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a /mnt/artoo/e/DEV/0xBASIC/crates/ crates/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/tools/ tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/language-v0.3.md /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
rsync -a /mnt/artoo/e/DEV/0xBASIC/Cargo.toml /mnt/artoo/e/DEV/0xBASIC/Cargo.lock /mnt/artoo/e/DEV/0xBASIC/README.md /mnt/artoo/e/DEV/0xBASIC/.gitignore ./
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 tools/verify_m1.py
python3 tools/verify_reserve_fee.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python tools/verify_reserve_fee.py --with-upstream --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 tools/verify_m5.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 tools/verify_payment_change.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 tools/verify_tutorial.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 tools/verify_payment_change_tutorial.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 -m unittest discover -s tools -p test_package.py
)
```

All commands must pass; both fee verifiers report 58 CLI calls and three unchanged legacy cases. No full-node or SpendSim suite rerun is requested for this constructor-only gate. Those remain covered by hosted regression CI and the later funded fee slices. After native confirmation: update the checkpoint, commit/push and verify exact-revision compiler/simulator/package CI before proceeding to FP-2.
