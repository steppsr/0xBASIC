# FP-4: fee payments through an isolated full node

Status: Windows and native Linux (LANDO) passed; the user confirmed the native gate on 2026-11-08. This extends the [selected plan](fee-payment-plan.md) and [SpendSim validation](fee-payment-spendsim.md). Compiler `0.3.0-alpha.1`, language 0.3, ABI 1, profile v2 and dependencies remain unchanged.

`simulator/full_node_fee_payment.py` runs inside the existing `full_node_smoke.py --payment` process, after the legacy, loop and payment/change fixtures. It funds five contract coins and one test-only anyone-can-spend companion from unspent farmed rewards. It preserves funding change and earlier fixtures' outputs.

## Cases and accounting

All amounts are mojos; CLVM and mempool costs are recorded separately.

| Attempt | Required observed result |
| --- | --- |
| Missing signature | `FAILED / BAD_AGGREGATE_SIGNATURE` |
| Fee changed from 10 to 11, retaining the signature for 10 | `FAILED / BAD_AGGREGATE_SIGNATURE` |
| Actual input 1001, bound input 1000, otherwise valid signature | `FAILED / ASSERT_MY_AMOUNT_FAILED` |
| Two contracts reserve 10 and 20; companion input 100 creates output 110 | Aggregate inputs 2100, outputs 2080, net fee 20 below reservation sum 30: `FAILED / RESERVE_FEE_CONDITION_FAILED` |
| Freshly signed partial payment with fee 11 | Input 1000, recipient 600, change 389, block fee 11 |
| Exact payment with fee 10 | Input 1000, recipient 990, no change, block fee 10 |
| Same two-contract aggregate with companion output 100 | Inputs 2100, outputs 2070, reserved and block fee 30; three inputs and five children |

The aggregate control includes two compiled contract spends, each paying 600, with change 390 and 380 respectively. Its third spend is an explicit test-only companion. Reservations add across spends; they enforce an aggregate minimum, not a per-input guarantee or exact fee cap. FP-3 separately tests zero fees, excess aggregate fees and the intentionally unreserved comparison.

## Evidence and isolation

Each rejection checks all six funded input records and the absence of children immediately and after another farmed block. Funding change must remain unchanged, the active mempool must be empty, and the new block must contain no transaction additions/removals or fees. The wrong-amount coin remains unspent after all controls.

For every positive contract spend, independently constructed application messages and ordered conditions must match pinned upstream execution and CLI output/cost. Signatures include the actual coin ID and node signature domain; upstream condition-derived signing pairs must agree. Deterministic public test keys are used and signature bypass flags are forbidden.

Measured mempool fees, reservation sums, input totals and output totals must match independent accounting. Every funding/control block must become the accepted peak and exist in the full-block store. Its nonreward additions/removals, coin parents, puzzle hashes, amounts and confirmation/spend heights must exactly match expectations. The full block's transaction fee must equal removals minus additions and the measured mempool fee. All confirmed outputs remain unspent after later controls; unused inputs and funding change remain unchanged.

As in the established full-node harness, `test=True` skips offline peer/wall-clock readiness only. Signature, condition and full-block validation remain enabled. No network service, RPC server or wallet starts. This is isolated real full-node evidence, not public-network integration.

Success is published only after resource cleanup and audits of both payment/change and fee evidence. Reporting tests reject incomplete scenarios, wrong errors, incorrect fee sums/block fees, coin counts, changed state and missing fee evidence. A failed run invalidates any previous success report. Source/binary/environment hashes, manifests, signatures, signing messages, coins, blocks, fee accounting and costs are retained in `.work/m5/full-node-payment-windows.json` (Linux: `full-node-payment-linux.json`), with this slice under `outcome.fee_payment`.

The existing simulator CI command automatically runs these cases and uploads the combined report. Across all four fixtures, the run checks **14 rejections and seven confirmed control bundles**. FP-4 contributes four rejections and three controls; its aggregate control contains two contract spends plus the companion.

## Native LANDO gate

Windows passed the combined full-node run and all **28 reporting/isolation tests**, with resources closed and no network services started. Run this in the existing LANDO checkout and pinned environment; synchronize the local changes before testing:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/simulator/ simulator/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/full_node_smoke.py --payment --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **28 tests pass**, then `PASS: full-node legacy, loop, change and fee cases, fourteen rejections and seven confirmed control bundles verified; resources closed.` Allow several minutes for the isolated plots and chain. Preserve `.work/m5/full-node-payment-linux.json`. No dependency install, additional Rust test suite or SpendSim rerun is needed for this harness-only slice.

Native confirmation is complete. Publication proceeds through commit/push and exact-revision CI. Next is FP-5: tutorial, evidence review and package validation. Release publication requires separate explicit approval.
