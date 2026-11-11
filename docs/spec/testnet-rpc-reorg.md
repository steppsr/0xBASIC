# TN-4b3: real RPC confirmation depth and chain rollback

Status: Windows passed 34 reporting/isolation tests and the real depth/reorg rehearsal; native LANDO passed, confirmed on 2026-11-11. TN-4b2 is published at `5a65d4d5b97b00f7178794cd22d3434ae21a4fd7`, with [compiler](https://github.com/steppsr/0xBASIC/actions/runs/42945562194), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/42945561764) and [package](https://github.com/steppsr/0xBASIC/actions/runs/42945561801) CI passing.

This extends the [real full-node RPC rehearsal](testnet-full-node-rpc.md) with an actual chain reorganization. RPC responses and coin-store results come from the running isolated node; the test does not substitute synthetic rollback records. It retains the honest `0xbasic-simulator` identity, existing consensus constants and strict rejection by public-testnet clients.

## Lifecycle checks

After the original four rejections and three confirmed fee controls, `simulator/rpc_reorg.py` performs these checks:

1. Read the current peak and canonical block containing the first fee control through authenticated RPC. Set an explicit target depth one greater than its current inclusive depth. Record `confirming`.
2. Farm one additional validated transaction block. Require the same inclusion anchor and a peak exactly one block higher. Its inclusive depth now equals the target; record `confirmed`.
3. Use the upstream simulator's real reorg operation to replace the chain after the block immediately before the first fee control, building a longer alternate chain. This replaces all three fee-control blocks while preserving the earlier funding and rejection blocks.
4. Read the replacement canonical hash at the old inclusion height. Require a different hash and a higher peak; record `reorged` with current confirmation count zero, preserving the old anchor as historical evidence.
5. Query all five formerly spent inputs through RPC and require their exact coins and original creation heights, now unspent with spend height zero. Independently compare with the real coin store.
6. Query all eight control outputs through RPC and require `COIN_RECORD_NOT_FOUND`; independently require absence from the coin store. Check that all six funded inputs and their funding change still exist unspent at their original funding heights.
7. Require an unchanged surrounding peak during rollback observation. No transaction is signed or submitted by this lifecycle extension.

Block farming and reorganization use the isolated simulator API; observations use the actual authenticated RPC transport. These operations create and validate real test blocks. They do not simulate a public peer network or establish that a live testnet node will reorganize in the same way.

## Evidence meaning

The RPC report still lives at `.work/m5/full-node-rpc-<platform>.json`. Its original fee-payment evidence describes the **pre-reorg checkpoint**. The peak is now named `confirmation_peak`, and the mempool assertion is `all_submitted_bundles_absent_before_reorg`, so neither is mistaken for current state after rollback.

The new `reorg` object contains the explicit required depth, `before`/`deeper`/`after` observations, old anchor, replacement hash, restored input records, missing output IDs and funding-preservation checks. Top-level `outcome.peak_height` reflects the post-reorg chain. The historical fee confirmations remain in the report for comparison; they must not be displayed as currently confirmed after the `reorged` observation.

The parent audit requires the reorg to target the first recorded fee-control block and start at the earlier confirmation peak. It cross-checks restored input coins/creation heights and missing output IDs against the independently validated fee records. Incorrect depth, unchanged anchor, stale confirmed status, retained outputs, incorrect restored coins, missing cleanup or incomplete evidence cannot publish success. The source hash inventory includes the new lifecycle module. Existing simulator CI already runs `--rpc` and uploads its report.

The extension makes no post-reorg mempool-membership claim. A node may retain or reintroduce previously seen transactions; this test checks canonical chain rollback, not automatic resubmission behavior. Reconfirmation, bounded polling/timeouts, durable observation state and the isolated identity policy for the production TN-2/TN-3a/confirmation pipeline remain subsequent TN-4 work. This does not complete TN-4 or authorize public transactions.

## Native LANDO gate

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
.work/m4/venv/bin/python simulator/full_node_smoke.py --rpc --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **34 tests pass**, then **four rejections, three fee controls and actual depth/reorg rollback verified**, with resources closed. The report must contain five restored inputs and eight missing outputs. No live service, credentials, dependency change or original `--payment` rerun is needed for this RPC-only extension. After native confirmation, commit/push, verify exact CI and continue the remaining TN-4 work.
