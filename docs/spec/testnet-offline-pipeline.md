# TN-4b7: shared offline preparation and signature rehearsal

Status: Windows passed 54 integration tests, 50 simulator tests, both public offline matrices, the full RPC lifecycle and original payment regression; native LANDO passed, confirmed on 2026-11-11. TN-4b6 is published at `20a83df2da219d44e03818b0ab15370c441ba07d`, with successful [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43091206662), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43091206406) and [package](https://github.com/steppsr/0xBASIC/actions/runs/43091206654) CI.

The isolated RPC rehearsal now submits the partial and exact-payment bundles returned by the shared TN-2 preparation and TN-3a detached-signature verifier. It compares those bundles, signing messages and expected children with the existing independent fee oracle before submission. The aggregate control retains the existing independent oracle; the shared offline interface supports one input.

## Fixed consensus policy

Public `prepare` and `verify_signed` entry points remain bound to testnet11. Their CLIs gain no network override. Private common helpers accept only the reviewed identity singleton objects. `simulator/isolated_preparation.py` binds the isolated object, and inputs cannot select consensus policy.

The isolated branch uses the pinned upstream `test_constants`, after verifying full-node source hashes, instead of public-testnet constants. Its report records a canonical JSON hash of all consensus constants and the actual `AGG_SIG_ME` additional data. The running node independently compares both with its own constants. Source, artifact, fixed bindings, fee budget, freshness, conditions, signature and exact preparation revalidation checks remain shared.

Isolated reports use `isolated-offline-unsigned-fee-preparation` and `isolated-offline-signature-verified-fee-bundle`, retain the real simulator identity, and claim neither mempool validation nor submission. Public entry points reject them. This is a trusted Python application boundary, not a sandbox against arbitrary local code.

## Process and evidence boundaries

For each single-input control, the harness observes the actual unspent coin through mutual TLS, then starts `simulator/offline_bridge.py` in a separate process. This keeps preparation preflight's process-local Chia root changes away from the running node. The child receives the compiled artifact, observation, solution and independently generated fixture bundle. It loads no private keys and rejects socket connect/bind operations. It extracts the fixture signature into the existing detached-response format and checks it against the recomputed request. This does not implement an external signer or decide live key custody.

Each control must reject seven cases: public preparation of isolated evidence, public signature verification of isolated evidence, changed response message, infinity signature, insufficient fee budget, wrong observation genesis, and changed saved constants evidence. Only a successful final revalidation publishes the child result atomically. The parent verifies exact bundle equality before submitting the verifier's returned bundle. Existing direct node-state checks still run before submission; observations are not atomic chain proofs.

The full report adds `rpc.offline_pipeline` with two controls and their complete preparation/signature evidence. Parent auditing requires both controls, all seven rejections each, exact submitted bundle IDs/content, matching signing messages, constants evidence and confirmed children. The existing lifecycle still covers actual RPC rejection, mempool checks, confirmation depth, rollback, bounded timeout, unchanged-bundle reconfirmation, journal history and resource cleanup. Runtime hashes include the new adapters/worker and shared offline sources.

After native confirmation and publication, review the complete TN-4 exit criteria and remaining TN-3b signer/host choices before planning a public trial. This milestone authorizes no public transaction or release.

## Native LANDO gate

Run this entire block on LANDO. The subshell stops on failure without closing the SSH shell; the explicit target directory avoids the previous `/debug/0xbasic` path issue.

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
python3 -m unittest discover -s integration -p 'test_*.py'
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python integration/verify_preparation.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python integration/verify_signing.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/full_node_smoke.py --rpc --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/full_node_smoke.py --payment --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: 54 integration tests, 50 simulator tests, preparation 10 positive/21 negative, signing 7 positive/26 negative, full RPC lifecycle PASS and original payment PASS (14 rejections/seven controls), both with resources closed. Preserve `.work/testnet/preparation-linux.json`, `.work/testnet/signing-linux.json`, `.work/m5/full-node-rpc-linux.json` and `.work/m5/full-node-payment-linux.json`. No dependency upgrade or live credentials are needed.
