# TN-4d2b: verified dispatch and bounded worker

Status: Windows unit suite passed 136 tests (19 Linux-only skips), plus the pinned TLS matrix: confirmation 9 positive/11 negative, monitor 5 positive/4 negative, dispatch 2 positive/5 negative; resources closed. Native LANDO passed, confirmed on 2026-11-13. The previous [transport gate](testnet-submission-transport.md) passed native Linux and is published as `f7525c0fe7d56ac0ab0a398ce4437cff95161780`. All exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43445893997), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43445894058), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43445894061).

## Internal boundary

`integration/submission_dispatch.py` combines the fresh detached verifier, exact bundle approval, [attempt persistence](testnet-submission-attempt.md) and [single-use transport](testnet-submission-transport.md). It has an internal `_dispatch(args)` entry point and a worker protocol, not a supported operator submission CLI. Only fixture validation invokes it at this gate. The worker protocol trusts its parent; invoking it directly bypasses parent verification and is not a supported submission workflow.

The parent requires original binary, manifest, observation, solution, preparation and detached response paths, maximum fee/observation age, explicit approved bundle ID, endpoint and CA/client credential paths, a new attempt filename, socket timeout and worker duration. It rejects attempt aliases to inputs/credentials and existing attempts before verification. The attempt's directory must already exist.

It calls the **fresh** verifier, independently reconstructing the preparation and verifying the detached signature. Historical monitor verification is never used. The approved bundle ID must exactly match the verified bundle. The parent freezes the resulting single-input bundle in memory; the worker never rereads signing/artifact inputs or invokes the compiler or signer. The attempt context binds verified bundle/input/preparation/response identifiers.

## Ordering, worker and ambiguity

The parent persists intent before starting the worker. The worker uses the read-only probe to check the fixed public node version/network, synced stable peak and exact unspent coin before invoking the separate push transport. It also checks original preparation-observation freshness immediately before dispatch. Invalid/spent/mismatched node or coin observations prevent push. These reads are not an atomic chain snapshot: state can change after the check, and node validation remains necessary.

Unlike an offline-verification failure (which creates no attempt), a worker preflight failure leaves a saved unknown outcome. This conservative distinction avoids inferring delivery from an incomplete worker exchange. Intent can therefore precede a failed read with zero actual submissions. Unknown does not mean rejected or safe to retry.

Duration must be finite in (0,600] seconds; socket timeout is in (0,30]. The monotonic worker budget starts after offline verification and intent persistence and includes process startup and communication. On timeout, interruption or failure the parent kills any remaining worker, reaps it and closes its pipes. Results arriving at or after the deadline are rejected. Offline verification, filesystem persistence, operating-system scheduling and process cleanup can extend total command time beyond the worker budget. Termination cannot retract bytes already delivered to a node or guarantee that no dispatch occurred around the deadline.

A successful on-time worker reply is normalized to `reply-success` or `reply-pending`. Neither proves confirmation. Errors/timeouts/interruption save unknown when possible, then propagate failure. If outcome persistence itself fails, the previous intent remains. There is no retry, resigning, fee adjustment or automatic resume. Attempt-file persistence and corruption/authentication limits remain those of TN-4d1. No endpoint, credential content or worker stderr is saved in the record.

## Evidence and next gate

Six new unit methods cover verification/approval before intent, path/existing-file refusal, timeout/interruption ambiguity without retry, numeric bounds, actual child termination/reaping/pipe closure, and fresh-read/expired-preparation prevention of push. The existing pinned operator matrix additionally uses actual compiled fee-payment artifacts, public fixture signatures and a disposable mutual-TLS node: success/pending compare the exact transmitted bundle; wrong approval, invalid signature, spent coin, wrong network and existing attempt all prevent push.

The fixture node does not establish real mempool admission or consensus validity. The next gate connects this internal dispatch path to the isolated full-node rehearsal, including ambiguous worker/transport outcomes and exact bundle identity. A public operator command, dedicated host baseline, concrete funding/spend review and live authorization remain separate subsequent work. No public node or real keys are used here.

## Native LANDO gate

Run as `steve`, without sudo:

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
)
```

Expected: **136 tests without skips**; confirmation **9 positive/11 negative**, monitor **5 positive/4 negative**, dispatch **2 positive/5 negative**, resources closed. Preserve `.work/testnet/operator-confirmation-linux.json`. Existing CI discovers the new units and executes the expanded matrix without workflow changes. After native pass, publish and verify exact-revision CI before proceeding to the full-node gate.
