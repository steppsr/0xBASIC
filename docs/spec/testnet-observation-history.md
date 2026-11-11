# TN-4b5: saved lifecycle observations

Status: Windows passed 49 simulator tests and the full RPC lifecycle with nine saved checkpoints; native LANDO passed, confirmed on 2026-11-11. TN-4b4 is published at `de2c3ebc38a4932625be60f03611c3dc4da59122`; [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43047358945), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43047358047) and [package](https://github.com/steppsr/0xBASIC/actions/runs/43047358109) CI passed.

This extends the [bounded-observation/reconfirmation rehearsal](testnet-rpc-reconfirmation.md) with incremental local history. An interrupted run can retain its last fully written observations without presenting them as fresh chain validation or authorizing automatic submission.

## Journal format and writing

`simulator/observation_journal.py` creates a fresh `observations.json` inside the existing isolated run directory. Existing files and symlink destinations are rejected. The journal is a single-writer helper for this harness, not a concurrent database or an API for resuming old runs.

The version 1 document contains immutable context and an ordered list of records. Context includes the actual node version/network, compiler binary digest and pinned RPC source hashes; it contains no private keys, certificates or credential paths. Each record has a sequence, named stage, observation snapshot, previous digest and its own SHA-256 digest. The first record chains from the context digest. Digests detect accidental alteration and ordering errors; they are not signatures, chain proof or protection against an attacker who can rewrite the entire file.

For each update, the writer serializes a complete snapshot, enforces an eight-megabyte bound, writes a temporary file in the same directory, flushes and fsyncs the file, closes it, then atomically replaces the destination. Memory advances only after replacement succeeds. A failed flush leaves the previous snapshot intact and cleans up the temporary file. An unexpected external change is rejected before overwrite. The implementation assumes one trusted writer; it does not provide locking against concurrent writers or hostile filesystem races.

The tests demonstrate recovery after abrupt process exit and preservation on an injected write failure. They do not establish a guarantee against every filesystem, operating-system crash or power failure; directory metadata is not separately fsynced. A malformed or truncated file fails validation rather than being silently repaired.

## Checkpoints

The harness saves these validated phase observations in order:

1. `ready`: initial node/chain readiness observation.
2. `fees-confirmed`: IDs of the three original validated fee-control bundles.
3. `depth-pending`: the original anchor below the selected deeper target.
4. `depth-confirmed`: the same anchor at the selected depth.
5. `reorged`: replacement chain, restored inputs and missing outputs.
6. `pending-timeout`: the bounded pending result after deliberate unchanged-bundle resubmission.
7. `reconfirming`: new inclusion at depth one.
8. `reconfirmed`: validated depth-two observation after accounting/state checks.
9. `rpc-closed`: the authenticated RPC server has closed.

This is a phase journal, not a record of every RPC call, polling attempt, funding transaction or submission intent. For example, interruption during resubmission may leave `reorged` as the last saved checkpoint even though a request reached the node. Therefore history must never be used to infer that an action did not occur or to trigger an automatic retry.

`rpc-closed` describes only RPC shutdown. The enclosing successful report separately requires node/keyring cleanup and all existing full-node assertions. A failed run keeps any valid journal prefix in its private run directory but does not publish the normal success report.

## Reading after interruption

`read_history(path)` checks the size, strict JSON, schema/types, exact ordered prefix, context chain and record digests. It always returns these scope markers, even for all nine records:

```json
{
  "validation": "historical-observations-only",
  "fresh_chain_validation_required": true,
  "automatic_resume_allowed": false
}
```

Reading does not contact a node, revalidate signatures, restore execution state or submit anything. A later operation must independently recheck the current network, inputs, bundle/mempool status and chain state. Old confirmed or timed-out observations remain historical facts about that run, not current spendability or permission to resend.

Successful `.work/m5/full-node-rpc-<platform>.json` reports embed the validated history. The parent reparses its canonical bytes, verifies the journal digest and compares every saved observation with the corresponding independently validated lifecycle result. Missing records, modified observations and changed scope flags cannot publish success. CI's existing RPC artifact therefore includes the successful history; an interrupted run's local prefix remains at the run path printed beside its log.

## Validation and native LANDO gate

Six new tests cover copied immutable inputs/historical scope, stage ordering and existing-file rejection, altered/truncated/duplicate-key data, failed fsync preserving the prior snapshot, unexpected external changes, and a subprocess that exits abruptly after saving two checkpoints. Existing RPC audit mutation tests now reject incomplete or altered embedded history. The suite totals **49 tests**.

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

Expected: **49 tests pass**, followed by the existing full RPC lifecycle PASS and resources closed. The audited report now includes nine historical checkpoints. No live node, credentials, dependency change or separate original-payment rerun is needed.

After native confirmation, commit/push and verify exact-revision CI. The next remaining TN-4 work is an explicit isolated-identity policy connecting the strict production preparation/signature/confirmation pipeline to the rehearsal. This journal does not relax production identities or complete that integration. Live signer/host choices and reviewed public transactions remain later gates.
