# FP-3: signed fee payments and aggregate reservation controls

Status: Windows and native Linux (LANDO) passed; the user confirmed the native gate on 2026-11-08. This extends the [local example](fee-payment-local.md) and [selected plan](fee-payment-plan.md) with pinned SpendSim validation. Compiler `0.3.0-alpha.1`, language 0.3, ABI 1, profile v2 and dependencies remain unchanged.

`simulator/fee_payment.py` runs 20 scenarios, each in its own fresh SpendSim instance. Every rejected attempt is followed by a confirmed control. Two complete fresh runs must produce identical evidence before success is published. Windows passed **20 scenarios, 14 rejections and 20 confirmed control bundles per run**, plus **25 reporting/isolation tests**. These are SpendSim results, not real full-node or public-network validation.

## Single-contract scenarios

Four positive scenarios confirm payment/change/fee accounting for partial 600/390/10, no-change 990/0/10, zero-fee partial 600/400/0 and zero-fee exact 1000/0/0.

| Rejected attempt | Observed upstream error |
| --- | --- |
| Missing signature, wrong owner, wrong network domain | `BAD_AGGREGATE_SIGNATURE` |
| Changed payment with stale signature | `BAD_AGGREGATE_SIGNATURE` |
| Changed fee from 10 to 11 with stale signature | `BAD_AGGREGATE_SIGNATURE` |
| Signature replay from another funded coin | `BAD_AGGREGATE_SIGNATURE` |
| Actual coin 1001, fixed input amount 1000, valid authorization | `ASSERT_MY_AMOUNT_FAILED` |
| Zero payment, payment overspend, fee overruns the available balance | `GENERATOR_RUNTIME_ERROR` |
| Missing fee solution field or noncanonical fee atom | `GENERATOR_RUNTIME_ERROR` |

The stale-payment control signs the new 700 payment; the stale-fee control signs the new fee of 11. The wrong-amount control spends a separately funded correct coin, leaving the rejected coin untouched. Replay uses a distinct funded coin with the same puzzle and amount; the original signing coin remains unspent after the control.

## Aggregate scenarios

The companion coins use an explicit test-only anyone-can-spend puzzle. They are not wallet integration or a recommended payment construction. All figures below are mojos; the runner separately records VM and simulator costs.

| Scenario | Attempt and result |
| --- | --- |
| Reserved offset | Contract: input 1000, outputs 990, reservation 10. Companion: input 100, output 110. Total fee 0 fails `RESERVE_FEE_CONDITION_FAILED`. A companion output of 100 then confirms with fee/reservation 10. |
| Additive offset | Two contracts reserve 10 and 20 and create outputs totaling 1970 from inputs totaling 2000. Companion input 100/output 110 leaves fee 20, below reservation sum 30: rejected with `RESERVE_FEE_CONDITION_FAILED`. Companion output 100 confirms at fee/reservation 30. |
| Unreserved comparison | A private temporary copy of the example omits only its RESERVE_FEE emission. Contract input 1000/output 990 plus companion input 100/output 110 confirms with total fee/reservation 0, despite the signed application message still committing fee 10. This intentionally weakened comparison is labeled in the report and never replaces the real example. |
| Extra fee | Contract reserves 10; companion input 100/output 90 adds another 10. The aggregate confirms with fee 20 and reservation 10, showing that reservation is a minimum, not an exact fee cap. |

The additive control confirms two contract spends in one bundle. Thus the 20 confirmed control bundles contain 21 contract spends, one of which uses the intentionally unreserved comparison source. Three aggregate controls also each include one companion spend, as does the unreserved comparison.

## Evidence and isolation

Funding consumes only unspent farmed rewards and preserves separate funding change. Before and after each rejection and another farmed block, all funded scenario inputs remain identical and unspent, no input has children, funding change is unchanged, and the active mempool is empty. This includes every input involved in rejected aggregates.

Valid controls independently reconstruct the application message and exact ordered conditions. Actual coin IDs and the simulator's effective network domain are included in signatures, compared against upstream condition-derived signing pairs. Deterministic public test keys are used; no signature bypass flags are allowed. CLI conditions and execution costs must match the pinned upstream VM.

Before farming, measured mempool fees, reservation sums, removals and additions must match the independent accounting oracle. After farming, exact nonreward additions/removals, child identities, amounts, parents, puzzle hashes and confirmation/spend heights must match. Inputs outside a positive control remain unchanged; funding change is preserved and the mempool empties. All simulator resources must close.

The report `.work/m4/fee-payment-windows.json` (Linux: `fee-payment-linux.json`) includes manifests, source/binary/environment hashes, constants, bundles/signatures, signing messages, coin records, fee accounting and costs. Audit checks enforce complete scenario coverage, expected rejection codes, exact accounting and cleanup. Reporting tests also reject incorrect additive totals, comparison labeling, missing records and stale success after preflight/scenario/rerun failure. A failed run removes prior success before proceeding.

The simulator CI workflow now runs the fee suite and uploads its report with the existing SpendSim evidence. Earlier payment/change, loop and full-node fixtures are unchanged. FP-4 will add representative real full-node fee cases; no such claim is made by FP-3.

## Native LANDO gate

Use the existing native checkout and pinned isolated environment. Refresh these local changes from the Windows share; they are not yet on GitHub:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/simulator/ simulator/
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/fee_payment.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **25 tests pass**, then **20 scenarios, 14 rejections, 20 confirmed controls per run; two identical fresh runs**. Preserve `.work/m4/fee-payment-linux.json`. No dependency install, additional Rust test suite or full-node run is needed for this slice. After native confirmation: commit/push, verify exact-revision CI, then FP-4. Published releases remain unchanged.
