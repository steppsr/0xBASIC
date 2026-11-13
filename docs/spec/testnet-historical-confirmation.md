# TN-4c2: historical signed expectations for read-only confirmation

Status: Windows passed 95 integration tests (19 Linux-only skips), the expanded operator matrix (9 positive/11 negative), preparation (10/21), detached verification (7/26), approved signing (4/10) and the full RPC lifecycle regression with resources closed. Native LANDO passed, confirmed on 2026-11-12. TN-4c1 is published at `2e980754ba324ce7dbdee87e3c452ff2459aef42`.

TN-4c1 exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43358746112), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43358746123), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43358746120).

This addresses TN-4c1's inability to inspect an old signed spend after the original unspent observation expires. It adds an explicit historical branch only for read-only confirmation. It does not extend signing freshness, allow submission or implement automatic monitoring/recovery.

## Explicit historical verification

`confirm_fee.py --historical` selects `verify_historical_signed`. Without this flag, the existing fresh verification path is unchanged. There is no historical option on the preparation, signing-review, signing or detached-verifier CLIs.

Both paths reconstruct the reviewed contract from the compiler artifacts and fixed bindings, independently execute conditions, verify exact coin/amount/destinations/fee/network/signing message, compare the complete regenerated preparation and verify the detached owner signature. Historical mode changes only the time used to evaluate the original observation's age: the saved preparation's `prepared_at`, instead of the current wall clock.

Before reconstruction, both recorded times must be timezone-aware and satisfy:

```text
observation_time <= prepared_at <= current UTC time
```

The original observation file's timestamp must then match the preparation during full comparison. Its age at recorded preparation must fit the invocation's `--max-observation-age` budget (default 300 seconds, allowed 1..3600). This is a consistency check against the selected budget; the original invocation's age budget was not stored as an authenticated policy. A record already stale at preparation time is rejected. Future or reversed timestamps are rejected before RPC.

All source files, observation bytes, preparation bytes and response bytes are read without rewriting timestamps or refreshing the record. The raw preparation digest must still match the detached response. VM flags are reconstructed from the recorded observation height under the reviewed baseline; they do not assert present-day mempool eligibility. A changed compiler/runtime baseline still requires compatibility review.

## What historical verification means

The historical verifier returns `historical-offline-signature-verified-fee-bundle` with `fresh_for_signing=false`, `fresh_for_submission=false`, `historical_timestamps_are_proof=false` and the recorded reference time. It retains the original preparation as evidence; the nested preparation is not a new fresh approval.

The confirmation wrapper uses `historical-verified-spend-rpc-observation-only` and `verification_mode=historical`. Its RPC observation is a new read of current network identity, peak, input/spend, expected outputs and confirmation anchor. The expected bundle ID remains a local expectation, not an aggregate bundle/signature claimed to have been recovered from a block. Prior-anchor comparison and exit codes remain unchanged: 0 observed confirmed, 3 valid non-confirmed state, 1 failure, 2 argument error.

Preparation/observation timestamps are not cryptographic proof of actual preparation, signing time or historical chain state. The BLS signature authorizes its exact message; it does not authenticate every metadata field or prove an earlier RPC observation happened. Consistent rewrites of metadata are outside any timestamp-attestation claim. The historical branch is suitable for deriving expectations to compare against current authenticated read-only RPC; it must never be used as a freshness shortcut for signing, funding or submission. Ordinary signing review still rejects expired observations, including ones accepted for historical confirmation.

Current RPC observations remain non-atomic and are not independent chain proofs. This command still performs one observation. Bounded polling, persisted monitoring/restart state, explicit submission intent and ambiguous-submit handling remain future operator-tooling steps. No live endpoint, key or transaction was used for this development gate.

## Validation

Three new unit methods check separate default/historical verifier selection, strict boolean mode selection before verification, and aware/ordered/non-future preparation times. The integration suite has 95 methods, including 19 Linux-only protected-file cases.

The actual CLI/mutual-TLS matrix now contains nine positives and eleven negatives. New positives confirm, inspect unspent, and detect replaced anchors for signed preparations recorded two days earlier; their input files must remain byte-identical. New negatives require the default command to reject those old records, reject observations stale at their recorded preparation, reject future/reversed preparation times and reject invalid historical signatures, all before RPC. The ordinary signing-review function must also reject an expired record. Existing identity/output/signature and stale-report cases remain.

Preparation, detached signing, approved signing and the isolated full-node RPC lifecycle are regression gates because the private reconstruction helper is shared. Public functions retain their existing signatures and fresh default policy. The helper's reference-time parameter is private; no input field or public preparation CLI selects it.

## Native LANDO gate

Run the entire block as `steve`, without sudo. Fixtures use public keys/certificates and isolated local nodes only:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 -m unittest discover -s integration -p 'test_*.py'
.work/m4/venv/bin/python integration/verify_operator_confirmation.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python integration/verify_preparation.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python integration/verify_signing.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python integration/verify_signer.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/full_node_smoke.py --rpc --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **95 tests, no skips**; operator confirmation **9 positive/11 negative**; preparation **10/21**; detached verification **7/26**; approved signing **4/10**, native key loading true; full RPC lifecycle PASS with resources closed. Preserve the four `.work/testnet/*-linux.json` reports from these commands and `.work/m5/full-node-rpc-linux.json`. CI already runs the expanded matrices; no workflow or dependency change is needed. After native success, publish, verify exact CI and continue bounded operator monitoring/submission design.
