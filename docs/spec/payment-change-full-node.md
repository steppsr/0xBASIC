# Payment and change: PC-3 full-node validation

Status: Windows and native Linux (LANDO) passed; the user confirmed the native gate on 2026-11-07. This extends the [selected plan](payment-change-plan.md) and [SpendSim gate](payment-change-spendsim.md) using the existing compiler and dependencies.

`simulator/full_node_smoke.py --payment` now runs the legacy payment, loop payment and `full_node_payment_change.py` in one isolated full node. The new cases fund three separate contract coins from unspent farmed rewards, preserving previous fixtures' outputs and funding change.

| Case | Required observed result |
| --- | --- |
| Missing signature | `FAILED / BAD_AGGREGATE_SIGNATURE` |
| Payment 700 using the signature for 600 | `FAILED / BAD_AGGREGATE_SIGNATURE` |
| Actual coin 1001, bound input 1000, otherwise valid signature | `FAILED / ASSERT_MY_AMOUNT_FAILED` |
| Partial payment from 1000 | Confirmed recipient 600 and change 400 |
| Exact payment from 1000 | Confirmed recipient 1000, no change child |

Every rejection checks all three contract records, absence of children, preserved funding change and an empty active mempool, immediately and after farming another block. The two positive controls then confirm; the wrong-amount coin remains unspent. PC-2 separately covers a freshly signed 700 payment and the broader adversarial matrix.

Each funding/payment block must be the accepted peak and present in the block store. Nonreward additions and removals must exactly match expected coins, including parents, puzzle hashes and amounts. Confirmation and spend heights must match the inclusion block. Payment outputs exhaust the input value and remain unspent. Independent message construction includes the actual coin ID and effective node signature domain; CLI conditions and VM cost must match upstream execution. Mempool costs are recorded separately.

The harness uses deterministic public test keys. As in the previous full-node gate, `test=True` bypasses offline peer/wall-clock readiness only; signature, condition and full-block checks remain enabled. No network services, wallet or RPC connection start. This is isolated full-node evidence, not public-network integration.

The aggregate includes artifact/source/binary hashes, signing context, block identifiers, coin records and rejection evidence. Publication requires worker success, resource cleanup and complete PC-3 evidence. Reporting tests reject incomplete results and invalidate stale success before a run. The existing simulator CI payment command automatically includes these cases.

## Verification

Windows passed all 21 reporting/isolation tests and the combined full-node run: ten rejections and four confirmed payments across the three fixtures. Resources closed and network services remained unstarted. Evidence: `.work/m5/full-node-payment-windows.json`, under `outcome.payment_change` for PC-3.

Run on LANDO from the existing native checkout/environment:

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

Expected: 21 tests pass, then `PASS: full-node legacy, loop and payment/change cases, ten rejections and four confirmed payments verified; resources closed.` Allow several minutes for the isolated chain and plots. Preserve `.work/m5/full-node-payment-linux.json`. No dependency changes or additional Rust test suite is needed for this slice.

Native confirmation is complete. Publication proceeds through commit/push and exact-revision CI, followed by PC-4 tutorial and evidence review. Compiler `0.2.0-alpha.1`, language 0.2, ABI 1 and published release assets remain unchanged. Any further release needs its own review and approval.
