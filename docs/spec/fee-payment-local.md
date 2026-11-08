# FP-2: local fee-aware payment

Status: Windows and native Linux (LANDO) passed; the user confirmed the native gate on 2026-11-08. This implements the example/local-verification slice of the [fee-payment plan](fee-payment-plan.md), using compiler `0.3.0-alpha.1`, language 0.3, ABI 1 and profile v2. No compiler, dependency, prior example or release changes are part of FP-2.

## Contract and fixtures

[payment-fee.bas](../../examples/payment-fee.bas) fixes the owner, recipient, change recipient and input amount. The solution supplies `paymentAmount` followed by `feeAmount`. Both use AMOUNT boundary validation. The contract requires positive input/payment, distinct destinations, and payment plus fee no greater than the input. Sum and subtraction use INTEGER arithmetic; change is converted to AMOUNT only when positive.

The contract emits these conditions in order:

1. `ASSERT_MY_AMOUNT(inputAmount)`.
2. `AGG_SIG_ME(owner, message)`.
3. `RESERVE_FEE(feeAmount)`, including when the fee is zero.
4. `CREATE_COIN(recipient, paymentAmount)`.
5. `CREATE_COIN(changeRecipient, change)` only when change is positive.

The independent accounting expectation is `input = payment + change + fee`. The new message is SHA-256 over `UTF8("0xBASIC/payment-fee/v1")`, one zero byte, the owner (48 bytes), recipient (32), change recipient (32), and U64BE(input), U64BE(payment), U64BE(fee), in that order. The earlier payment/change message and fixtures remain unchanged.

The [bindings](../../examples/payment-fee.bindings.json) use public test key/hash values and input 1000. Three ready-to-run solutions are supplied:

| Fixture | Payment | Fee | Change |
| --- | --- | --- | --- |
| [partial](../../examples/payment-fee.partial.json) | 600 | 10 | 390 |
| [exact](../../examples/payment-fee.exact.json) | 990 | 10 | No change child |
| [zero-fee](../../examples/payment-fee.zero-fee.json) | 1000 | 0 | No change child |

Here “exact” means the payment plus fee consumes the input. A fee value is an amount in mojos, not a VM cost budget. These are test destinations, not wallet configuration. Change goes to the fixed change puzzle and does not automatically recreate the contract.

## Try the example

From the repository root, use your built CLI in place of `0xbasic`. On Windows that is normally `./target/debug/0xbasic.exe`; on LANDO use `$CARGO_TARGET_DIR/debug/0xbasic`. Choose a fresh output directory.

```text
0xbasic check examples/payment-fee.bas --json
0xbasic build examples/payment-fee.bas --bindings examples/payment-fee.bindings.json --out payment-fee-build --json
0xbasic run payment-fee-build/manifest.json --solution examples/payment-fee.partial.json --json
0xbasic run payment-fee-build/manifest.json --solution examples/payment-fee.exact.json --json
0xbasic run payment-fee-build/manifest.json --solution examples/payment-fee.zero-fee.json --json
0xbasic explain examples/payment-fee.bas --stage clvm --bindings examples/payment-fee.bindings.json --json
```

The result is local execution only. The signature requirement is emitted but not verified; no coin is funded, spent or confirmed. Fee reservation constrains an aggregate minimum, not an exact aggregate fee or guaranteed attribution to one input. The [semantics decision](fee-payment-semantics.md) records the aggregation counterexample. Signed and funded scenarios, including stale fee signatures and aggregate offsets, belong to FP-3/FP-4.

## Verification evidence

[verify_fee_payment.py](../../tools/verify_fee_payment.py) uses only the Python standard library and actual CLI. Its message preimage, ordered condition tree and raw two-field solution encoding are constructed independently of compiler output.

- Twelve numeric positives cover partial/no-change, zero-fee partial/no-change, changed fee, minimum payment/change, sign-bit boundaries, one-mojo input and maximum AMOUNT arithmetic. Each compares host/raw execution and tests exact-cost success plus cost-minus-one failure.
- Four fixed-term variants change owner, recipient, change recipient and input independently. Each must match the oracle and change both the message and bound puzzle identity. Payment-only and fee-only changes must change the message while preserving the fixed puzzle.
- Seven contract negatives exercise zero input/payment, payment overspend, fee overruns, equal destinations and payment-plus-fee beyond the u64 range. They run through both JSON and raw solutions and fail E0500.
- Twenty malformed JSON solution cases fail E0300, including missing/extra fields, duplicate/case-colliding fee keys, and invalid types/decimal forms in either field.
- Fourteen malformed raw solutions fail E0500: list shape/arity, noncanonical integer atoms, negative/overflow amounts and pairs in either position.
- Four invalid fixed-binding cases fail E0301 without publishing artifacts.
- Repeated builds must be byte-identical; template/puzzle inspection, binary/hex files and manifest hashes must agree. Failed overwrite leaves the artifact set unchanged. ABI field order and current identities are explicit checks.

Windows passed **16 positives, 45 negatives, 120 CLI calls**. The report `.work/payment-fee/local-windows.json` records input/binary hashes, conditions, messages, costs, identities and diagnostics, with `signatures_verified: false` and `spends_submitted: false`. A new run removes previous success before checking prerequisites; the final report is published only after verification and cleanup. Maximum-value cases prove local arithmetic/encoding only.

Compiler CI now includes this verifier on Windows and Linux. No new Rust or simulator suite is needed for this example-only slice.

## Native LANDO gate

Refresh the local native checkout from the Windows share; these changes are not yet on GitHub:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a /mnt/artoo/e/DEV/0xBASIC/examples/ examples/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/tools/ tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 tools/verify_fee_payment.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: specification verification and **16 fee-payment positives, 45 negatives, 120 CLI calls** pass. Preserve `.work/payment-fee/local-linux.json`. After confirmation, commit/push and verify exact-revision CI; FP-3 then adds signed SpendSim and aggregate fee validation.
