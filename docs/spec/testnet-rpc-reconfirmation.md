# TN-4b4: bounded observation and unchanged-bundle reconfirmation

Status: Windows passed 43 simulator reporting/polling tests and the extended RPC rehearsal; native LANDO passed, confirmed on 2026-11-11. [TN-4b3](testnet-rpc-reorg.md) passed native Linux and is published at `36f7f72c718e7a940de588e03a4ada5871be3456`.

All exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43043431754), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43043431875) and [packages](https://github.com/steppsr/0xBASIC/actions/runs/43043434018).

This extends the isolated full-node lifecycle after the actual reorg. It tests bounded read-only observation, then deliberately resubmits the original fixture bundles and verifies their new inclusion. It adds no public submission command, live signer or automatic recovery transaction.

## Bounded observation

`simulator/rpc_poll.py` accepts an asynchronous validated observation callback and explicit timeout, interval and maximum attempts. Bounds are finite and type-checked: timeout in `(0, 600]` seconds, interval in `[0, timeout]`, attempts from 1 through 1000; booleans are rejected as numeric parameters.

The helper uses a monotonic deadline and limits each awaited observation to the remaining budget. `unspent` and `confirming` observations continue within the bounds; `confirmed`, `reorged` and `conflicting-spend` end observation immediately. Exhaustion reports `timed-out` with a reason (`attempt-limit`, `deadline` or `observation-timeout`), attempt count, elapsed time and last valid observation. It never turns timeout or mempool acceptance into confirmation. A confirmation returned after the deadline is rejected even if a callback delays cancellation. Invalid statuses and non-timeout transport/validation errors propagate; caller cancellation also propagates.

The callback remains responsible for validating chain evidence and identity. The polling helper does not authenticate an arbitrary status dictionary. It does not sign, submit, replace, farm or raise fees; its result always records zero transactions submitted.

Async cancellation is not a hard process deadline. A callback may delay cancellation, and canceling a thread-backed RPC await does not forcibly terminate its underlying socket operation. The transport retains per-socket timeouts, late confirmations are never accepted, and the full rehearsal retains its separate ten-minute worker timeout. There is no new claim of a hard wall-clock deadline across arbitrary callbacks.

## Actual node recovery scenario

`simulator/rpc_reconfirm.py` receives the original three accepted fee-control bundles and the validated rollback evidence:

1. Deserialize the original bundles and compare their IDs to the original fee report. Submit exactly those three bundles through authenticated RPC; require success and exact bundle equality in mempool. No signature is created and no puzzle, solution, recipient, amount or fee is changed.
2. Run bounded observation with a 30-second budget, 20-millisecond interval and two attempts while farming no block. All five inputs remain unspent. Require a `timed-out` result caused by the attempt limit; retain that result as historical evidence.
3. Farm one real transaction block containing the three bundles. Independently require exactly five removed inputs, eight recreated non-reward outputs, and total block fee 51 mojos (11 + 10 + 30). Read exact puzzle/solution and input/output records through RPC and compare with the actual coin store. Require `confirming` at depth one.
4. Farm another block and run bounded observation again. Require `confirmed` at depth two, with the same new inclusion anchor and a height later than the rollback peak.
5. Require all three bundle IDs absent from RPC mempool lookup, the actual active mempool empty, and all original funding change coins unspent with unchanged identities/creation heights.

The resubmission is an explicit action in this isolated test scenario. The polling helper never triggers it. The node may already have retained a bundle after reorg; exact resubmission is idempotent and must never manufacture a replacement. This scenario uses the existing local simulator identity and public fixture keys, not a live network.

## Evidence and tests

The existing `.work/m5/full-node-rpc-<platform>.json` now includes `reconfirmation` after the historical `reorg` observation. It preserves the pending timeout, depth-one observation and bounded depth-two result separately. Historical `confirmation_peak` and `reorg.after` remain earlier checkpoints; top-level `outcome.peak_height` is the final chain height after reconfirmation.

The reconfirmation object records the original bundle IDs, three explicit submission calls, zero signatures created, required depth, block fee, funding preservation and final mempool checks. The earlier submission list still describes only the original funding/rejection/control phase. Source hashes include both new lifecycle modules. The parent audit rejects changed bundle IDs, stale success, wrong new heights/anchors/depth, fee changes and incomplete state checks before publishing the report.

Seven new polling tests cover attempt exhaustion, pending-to-confirmed, reorg/conflict terminals, invalid bounds without I/O, deadlines including cancellation-delayed success, malformed/failed reads and caller cancellation. Two new reconfirmation audit tests cover valid evidence and mutations. The existing RPC evidence test also includes the new stage. The suite totals **43 tests**. The real node exercises attempt exhaustion; deadline/cancellation branches are unit-tested rather than represented as actual network stalls.

The current gate does not add durable incremental observation storage or integrate the strict production TN-2/TN-3a/testnet11 observer with an isolated identity policy. Those remain subsequent TN-4 work. TN-3b live signer/host choices and separately reviewed public transactions remain prerequisites for TN-5.

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

Expected: **43 tests pass**, then the RPC PASS line includes **four rejections, three fee controls, reorg, bounded pending timeout and unchanged-bundle reconfirmation**, with resources closed. No live node, credentials, dependency change or original `--payment` rerun is needed for this RPC-only extension. After native confirmation, commit/push, verify exact-revision CI and continue the remaining TN-4 work.
