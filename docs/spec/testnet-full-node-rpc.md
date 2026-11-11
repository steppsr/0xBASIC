# TN-4b2: isolated full-node fee RPC rehearsal

Status: Windows passed 32 simulator reporting/isolation tests, the new RPC rehearsal (four rejected spends and three confirmed fee controls), and the existing full-node regression (14 rejections/seven controls). Native LANDO passed, confirmed on 2026-11-10. TN-4b1 is published at `c123a9a2e0aa9d4dae811822a9aa9b72065ede01`; [compiler](https://github.com/steppsr/0xBASIC/actions/runs/42918282246), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/42918282556) and [package](https://github.com/steppsr/0xBASIC/actions/runs/42918282227) CI passed.

This gate starts a real authenticated full-node RPC server and submits compiled fee-payment transactions to its actual mempool. It replaces the synthetic responses of [TN-4b1](testnet-confirmation-transport.md) with real node responses. It remains an isolated simulator rehearsal, not a public-testnet operation or completion of the entire [TN-4 milestone](testnet-integration-plan.md).

## Identity and isolation

The existing pinned Python/Chia environment remains unchanged: Chia 2.7.4 with the existing test consensus constants and three local k19 plots. The harness configures the explicit local network name `0xbasic-simulator`, prefix `txch`, and the actual test-constants genesis `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. It asserts that changing the network configuration does not change consensus constants. It reads the actual version/network/genesis through RPC and compares them with the node.

The upstream simulator-network readiness rule treats this peerless network as synced. RPC submission uses the ordinary `push_tx` route and does **not** pass `test=True` to `add_transaction`. Consensus and aggregate-signature validation remain active. This is a simulator-specific readiness rule, not evidence of synchronization with testnet11. The production TN-1 probe must reject this node; the rehearsal asserts that rejection without modifying or spoofing its version/network responses.

The parent process retains the existing ten-minute worker timeout, stale-success removal, isolated node/key/plot/temp roots and loopback-only socket audit. The harness starts only the upstream full-node RPC server on an ephemeral loopback port, with its generated private CA and explicit client certificate/key under the isolated root. No daemon or peer transport is started. A dedicated harness transport adds only `push_tx` and `get_mempool_item_by_tx_id`; production probe/confirmation clients remain read-only.

Seven RPC source files are pinned in `simulator/rpc_sources.json`, supplementing the existing full-node/runtime source checks. Reports contain source/binary hashes and public transaction evidence, not private key/certificate contents. RPC shutdown, node shutdown, test-keyring cleanup and absence of peer/daemon connections are required before publishing success. Expected rejection and missing-mempool exceptions may appear in the private worker log; the parent PASS line and audited report determine success.

## Real RPC flow

`simulator/full_node_smoke.py --rpc --binary PATH` invokes `simulator/full_node_rpc.py` inside the isolated worker. It reuses the independently checked fee-payment contract and full-block assertions from the existing fee harness. A new optional submission callback sends its transactions through authenticated RPC; the original `--payment` path retains its existing behavior.

1. Farm local rewards to the fixture funding puzzle. Submit six funding transactions through RPC and confirm their exact contract/change outputs in full blocks.
2. Check every accepted bundle through `get_mempool_item_by_tx_id`, deserialize it and require equality with the submitted bundle. Resubmit the identical bundle and require idempotent success. This does not create a new spend or change its fee.
3. Reject missing signatures, stale signatures after a fee change, a mismatched actual coin amount, and an aggregate with insufficient net fee for its additive reservations. Require the exact upstream errors and unchanged inputs/children/funding change after farming.
4. Confirm partial payment (fee 11), exact payment (fee 10), and a three-input aggregate (fee/reservation 30). Verify exact additions/removals, emitted conditions, signature messages, mempool accounting and block fees using the existing independent oracle.
5. Read the five confirmed coin spends through `get_puzzle_and_solution`; compare the full coin, reveal and solution with the signed bundles. Read canonical inclusion blocks and all expected child/input records through RPC and compare them with independently checked block/store evidence. Normalize only the upstream RPC's extra backwards-compatible `spent` field when comparing coin records.
6. Require unchanged surrounding peaks, record inclusive confirmation depth, and verify all 13 submitted bundle IDs are absent from the final mempool. Accepted submissions total nine (six funding/three controls), with nine identical resubmissions; four original submissions fail.

The parent validates the RPC evidence against the fee evidence before publication: exact spend bytes/children, block hash/height and confirmation count must agree, as well as rejection/control counts and cleanup flags. Unit tests mutate these fields and reject missing evidence or stale report reuse.

The report is `.work/m5/full-node-rpc-<platform>.json`, with validation `isolated-full-node-rpc-fee-rehearsal`. The separate legacy report remains `.work/m5/full-node-payment-<platform>.json`. Simulator CI runs both modes and uploads the RPC report separately.

## Limits and remaining TN-4 work

This gate validates real funding, signing, submission and inclusion over RPC using the existing simulator fee oracle. It does not feed an invented testnet11 observation into the production TN-2/TN-3a preparation/signature pipeline. That pipeline continues to require its reviewed testnet11 identity/domain. The rehearsal does not claim compatibility with a live 2.7.5 node.

Confirmation reads use the shared authenticated transport and compare against full-block evidence, but the strict testnet11 confirmation observer is not relaxed to accept this simulator. No general submission command, automatic funding, live key loader, bounded confirmation polling driver or automatic retry is introduced. Actual node reorg/polling-timeout scenarios and an explicit policy for connecting the production pipeline to an isolated identity remain subsequent TN-4 work. Existing synthetic confirmation/reorg tests retain their narrower scope. TN-3b live signer/host decisions and separately reviewed public transactions remain prerequisites for TN-5.

## Native LANDO gate

Run the reporting tests, new RPC rehearsal and the original payment regression because they share the full-node harness:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/simulator/ simulator/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/full_node_smoke.py --rpc --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/full_node_smoke.py --payment --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **32 tests**, RPC **four rejections/three confirmed controls**, and legacy **14 rejections/seven confirmed controls**, with resources closed. No live Chia service or credentials are required. Keep both reports. After native confirmation, commit/push, verify exact-revision CI and continue with the remaining TN-4 observation/pipeline work.
