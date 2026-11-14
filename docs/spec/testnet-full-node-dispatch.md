# TN-4d3b: verified dispatch through the isolated full node

Status: Windows passed 51 simulator evidence tests and the complete full-node RPC rehearsal with resources closed. Native LANDO passed, confirmed on 2026-11-13. The preceding fixed-identity adapter passed native Linux and is published at `4f521848c005f49b05d801e3665656c4dfe393b6`. All exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43471536114), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43471536115), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43471536123).

## Real-node integration

The isolated RPC rehearsal now sends its partial and exact single-input fee controls through [verified isolated dispatch](testnet-dispatch-identity.md). Funding, intentionally invalid spends and the aggregate control retain the existing harness RPC path. No public submission CLI or public-network operation is added.

The offline bridge creates original observations, solutions, preparations and detached fixture responses, comparing verified bundles with the independent fee oracle. The rehearsal associates those paths with each control's bundle ID. A separate `simulator/dispatch_bridge.py` process repeats fresh verification and exact bundle approval, persists intent and starts the fixed isolated dispatch worker. Fresh node/coin checks precede mutual-TLS submission. Runtime preflight stays outside the live node process; the harness verifies unchanged Chia environment roots.

The node's mempool must contain exactly the independently verified bundle. Existing farming and confirmation checks establish matching input spends, outputs and fees. Reorg, bounded pending observation and unchanged-bundle reconfirmation coverage remain. Reports include dispatch records and source hashes for the bridge, adapter and shared dispatch/transport/persistence code.

## Ambiguous outcome exercise

The partial payment persists a normal worker reply. For the exact payment, the harness deliberately raises an exception **after a successful worker reply but before the parent saves the outcome**. The attempt becomes `unknown`; only one dispatch worker is invoked. This models loss at the parent outcome boundary, not an actual network-disconnect or process-crash experiment. Existing transport/worker tests cover those separate failures.

A read-only exact mempool query establishes acceptance for this run without retrying. The attempt remains unknown even after the harness observes acceptance. It does not retroactively become success or confirmation. Accepted receipts for these controls identify mempool evidence and do not fabricate a raw RPC response.

The pre-existing duplicate-submission test still deliberately sends each accepted bundle again **after** exact mempool presence is established. That is a separate isolated idempotence check, not blind recovery from an unknown attempt or new dispatcher behavior. Later reorg reconfirmation remains an explicitly controlled harness action.

## Evidence and limits

The audit requires both scenarios; fixed network/record label; all five identifiers matching the verified preparation/bundle; expected success/unknown outcome; one worker call; the fault marker; unchanged node environment; and no automatic retry. Exact mempool bytes must match the subsequently confirmed bundle. Nine mutations check missing controls, extra calls, changed loss/outcome/identity/confirmation flags, environment changes, retry claims and changed mempool bytes.

This validates pinned Chia 2.7.4, fixture keys and simulator constants. It does not establish deployed public-node compatibility or authorize funding/submission there. The next step reviews completed dispatch evidence and the operator-command/host/trial workflow. Live setup, owner keys, funding and public sends remain separate explicit operations.

## Native LANDO gate

Run as `steve`, without sudo:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/simulator/ simulator/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/full_node_smoke.py --rpc --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **51 simulator tests pass**, then full-node RPC passes with resources closed. Preserve `.work/m5/full-node-rpc-linux.json`; `outcome.rpc.verified_dispatch` contains partial `reply-success` and exact `unknown`, both with matching mempool bundles and one worker call. Existing CI runs the expanded RPC rehearsal. No separate public TLS matrix or payment-only full-node rerun is needed because shared integration modules and payment algorithms are unchanged in this slice.
