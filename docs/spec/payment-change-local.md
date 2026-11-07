# PC-1: local payment and change

Status: Windows and native Linux (LANDO) passed; Linux success was confirmed on 2026-11-06. This implements the first executable slice of the selected [payment/change plan](payment-change-plan.md). It uses the existing compiler `0.2.0-alpha.1`, language `0.2`, ABI 1. Compiler code, dependencies and released archives are unchanged.

## What the example does

[payment-change.bas](../../examples/payment-change.bas) fixes an owner key, recipient hash, change hash and input amount. The spender supplies `paymentAmount`. The contract requires positive amounts, payment no greater than the input, and distinct destination hashes. It emits an input-amount assertion, a signature requirement and the payment output. It emits change only when the remainder is positive.

The [public fixture bindings](../../examples/payment-change.bindings.json) fix input amount 1000. The [partial solution](../../examples/payment-change.partial.json) pays 600 and returns 400; the [exact solution](../../examples/payment-change.exact.json) pays 1000 with no change output. These hashes and key are test data, not configured wallet destinations. Change goes to the fixed change puzzle; it does not automatically recreate the original contract. The example allocates the full input to outputs and does not reserve a transaction fee.

The application message uses the domain and fixed-width encoding specified in the plan, committing the owner, both destinations, input amount and requested payment. Changing the solution amount changes the message without changing the bound puzzle. Emitting AGG_SIG_ME is a signature requirement, not proof of authorization. Signature generation, verification, coin existence and confirmation are later simulator gates.

## Try it locally

Build the current CLI, then run these commands from the repository root. On Windows, substitute `target/debug/0xbasic.exe`; with a custom Cargo target directory, substitute its `debug/0xbasic` path. The output directory must not already exist.

```text
cargo build --workspace --locked
target/debug/0xbasic check examples/payment-change.bas --json
target/debug/0xbasic build examples/payment-change.bas --bindings examples/payment-change.bindings.json --out payment-change-build --json
target/debug/0xbasic run payment-change-build/manifest.json --solution examples/payment-change.partial.json --json
target/debug/0xbasic run payment-change-build/manifest.json --solution examples/payment-change.exact.json --json
target/debug/0xbasic explain examples/payment-change.bas --stage clvm --bindings examples/payment-change.bindings.json --json
```

The partial result contains ordered conditions `ASSERT_MY_AMOUNT(1000)`, `AGG_SIG_ME(owner, message)`, `CREATE_COIN(recipient, 600)` and `CREATE_COIN(changeRecipient, 400)`. The exact result contains the first two conditions with its own payment-dependent message and a single `CREATE_COIN(recipient, 1000)`. Both executions report `clvm-execution-only`.

## Verification scope

[verify_payment_change.py](../../tools/verify_payment_change.py) uses the Python standard library and invokes the actual CLI in a temporary directory. Its independent oracle constructs the SHA-256 preimage and exact ordered condition tree directly from fixture values. It does not derive expected results from compiler output.

- Eight positive cases: partial payment, exact payment, payment 1, integer sign-bit boundary 128, change 1, a one-mojo input, maximum AMOUNT input with payment 1, and exact payment of maximum AMOUNT.
- Four contract-negative cases through both host-decoded and raw solutions: zero payment, overspend, zero input, and equal destination hashes.
- Nine invalid JSON solution cases and eight malformed raw solution cases: missing/extra fields, malformed amount values, noncanonical integers, range violations and invalid list shapes. Host errors are E0300; generated puzzle failures are E0500.
- Four invalid fixed-binding cases: negative/overflow input amounts, short recipient hash, and invalid owner key. These fail with E0301 and create no artifacts.
- Repeated baseline builds must be byte-for-byte identical. ABI declaration order and CLVM inspection/build hashes must agree. A failed overwrite must leave every artifact byte unchanged.
- Every positive case compares host/raw execution and tests both exact VM cost success and cost-minus-one E0501 failure.

Windows passed all 8 positive and 25 negative cases across 72 CLI invocations. The report `.work/payment-change/local-windows.json` records input and executable hashes, messages, exact condition trees, observed costs and puzzle identities. A failed new run removes the previous success report before validation. Evidence explicitly records that no signatures were verified and no spends were submitted. Maximum-value cases establish local arithmetic/encoding behavior only.

The verifier is added to compiler CI for both platforms. It requires no simulator environment. This is an example/verifier change, so another Rust test-suite run is not needed for the native handoff.

## Native LANDO commands

Run from the native checkout. The subshell stops on failure without closing SSH and explicitly restores the compiler target path.

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a /mnt/artoo/e/DEV/0xBASIC/examples/ examples/
rsync -a /mnt/artoo/e/DEV/0xBASIC/tools/ tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 tools/verify_payment_change.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: specification checks pass, followed by `8 payment/change positives, 25 negatives, 72 CLI calls`. Preserve `.work/payment-change/local-linux.json`. After confirmation, publish PC-1 and verify exact-revision CI. PC-2 then adds actual signature validation and confirmed partial/exact payments in isolated SpendSim, with adversarial controls.
