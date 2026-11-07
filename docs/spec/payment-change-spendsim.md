# PC-2: signed payment and change in SpendSim

Status: Windows and native Linux (LANDO) passed; Linux success was confirmed on 2026-11-07. This implements the isolated SpendSim slice of the selected [payment/change plan](payment-change-plan.md), following [PC-1 local execution](payment-change-local.md). Compiler `0.2.0-alpha.1`, language `0.2`, ABI 1 and simulator dependency/profile pins are unchanged.

## What is now exercised

[payment_change.py](../../simulator/payment_change.py) compiles the existing BASIC example with a deterministic public test key, known distinct recipient/change puzzle hashes and fixed input amount 1000. Each scenario starts a fresh pinned SpendSim instance, farms test rewards and funds the exact bound puzzle. All signing and transaction submission stay inside that isolated in-process test chain.

The harness independently constructs the application-message preimage and the expected ordered conditions. It checks artifact byte/tree hashes, the current compiler identity, local CLI/upstream VM result and cost parity, and upstream signature-pair extraction. Signing uses the actual funded coin ID and the pinned AGG_SIG_ME domain. Signature validation remains enabled.

Partial payment 600 must produce recipient 600 and change 400. Exact payment 1000 must produce only the recipient child. The changed-payment control uses 700 and change 300, proving that a correctly reauthorized solution succeeds. All accepted payments consume exactly their contract input and allocate its entire amount to the expected children. Assertions cover exact child IDs, parents, puzzle hashes, amounts, confirmation/spend heights, empty final mempool and unchanged funding change records.

The change destination is a known public test puzzle, not a wallet address or automatically recreated PaymentChange contract. The harness deliberately reserves funding change coins so funding a second test input cannot consume the change whose preservation is being checked.

## Scenario matrix

| Scenario | Rejected attempt | Confirmed control |
| --- | --- | --- |
| Partial | None | 600 payment + 400 change |
| Exact | None | 1000 payment; no change child |
| Missing signature | `BAD_AGGREGATE_SIGNATURE` | Same coin, signed 600/400 |
| Wrong owner key | `BAD_AGGREGATE_SIGNATURE` | Same coin, correct owner |
| Wrong network domain | `BAD_AGGREGATE_SIGNATURE` | Same coin, correct domain |
| Changed payment, stale signature | Signature for 600 cannot authorize 700: `BAD_AGGREGATE_SIGNATURE` | Same coin, newly signed 700/300 |
| Cross-coin replay | Signature from another identically bound/funded coin: `BAD_AGGREGATE_SIGNATURE` | Target coin signed for its own ID; source coin remains unspent |
| Wrong actual coin amount | Coin funded with 1001 against a puzzle requiring 1000: `ASSERT_MY_AMOUNT_FAILED` | Separately funded correct coin; rejected coin remains unspent |
| Zero payment | `GENERATOR_RUNTIME_ERROR` | Same coin, signed 600/400 |
| Overspend | Payment 1001 from input 1000: `GENERATOR_RUNTIME_ERROR` | Same coin, signed 600/400 |
| Missing raw solution field | `GENERATOR_RUNTIME_ERROR` | Same coin, valid solution |
| Noncanonical raw amount | Leading-zero integer atom: `GENERATOR_RUNTIME_ERROR` | Same coin, canonical amount |

All ten rejected attempts return FAILED. Before and after farming another block, the rejected coin record must remain unchanged and unspent, no contract children may exist, funding change records must remain unchanged, and no attempt may enter the active mempool. The wrong-amount and replay scenarios also verify the unaffected coin remains unspent after the positive control.

## Evidence and limits

Windows passed twelve scenarios, ten rejections and twelve confirmed controls per run, with two complete fresh runs producing identical reports. All eighteen simulator reporting/isolation unit tests passed. New reporting tests reject missing/duplicate scenarios, incomplete rejection/cleanup/output evidence, failed runs and differing fresh runs. Old success evidence is removed before preflight, and a new success report is published only after both audits and equality checks succeed.

The report `.work/m4/payment-change-windows.json` records source/executable/lock hashes, runtime versions, constants, manifests, bindings, application/final signing messages, signatures, conditions, coins and before/after records. Local VM cost and total simulator spend cost have distinct fields. Linux writes `.work/m4/payment-change-linux.json`. Fresh-run equality is required within a platform; it is not a claim that platform-specific report metadata is identical.

[Simulator CI](../../.github/workflows/simulator.yml) runs this suite and uploads its report on both platforms. Existing payment/loop fixtures and suites are unchanged. PC-2 establishes the stated SpendSim behavior only; payment/change confirmation through real full blocks remains PC-3. It adds no wallet, RPC, testnet or mainnet integration and changes no published release asset.

## Native LANDO commands

Use the existing isolated Python environment. No reinstall, Rust test-suite rerun or full-node run is needed for this slice.

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/simulator/ simulator/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/payment_change.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: eighteen tests pass, then twelve scenarios, ten rejections and twelve confirmed controls per run, with two identical fresh runs. Preserve the Linux report. After native confirmation, commit/push PC-2 and verify exact-revision CI. Next is PC-3's representative full-node partial/exact payment and rejection evidence.
