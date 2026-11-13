# TN-4d1: submission intent and outcome boundary

Status: Windows integration suite passed 123 tests (19 Linux-only skips), plus specification/artifact checks; native LANDO passed, confirmed on 2026-11-12. No submission CLI or RPC adapter is introduced. The preceding [saved monitor history](testnet-monitor-history.md) passed Windows and native LANDO and is published at `c29c5219cd81f124d7204acabe06db3d5d4699c6`. All exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43367813598), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43367813696), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43367813543).

## Purpose and implementation scope

A submission can reach a node even if the caller never receives a reply. The operator must retain the exact bundle identity before dispatch, preserve ambiguity after interruption, and never infer that a missing success report makes retry safe.

`integration/submission_attempt.py` implements an internal `_attempt(path, context, dispatch)` boundary. Only disposable test callbacks currently call it. It has no command-line interface, node connection, signer or dependency change. Context accepts exactly five canonical 32-byte hex identifiers: bundle ID, serialized bundle SHA-256, input coin ID, preparation SHA-256 and signature-response SHA-256. Records also contain the fixed public testnet identity, a schema version and a SHA-256 over canonical record content. No raw reply, endpoint, credentials or exception text is saved.

These are caller-supplied identifiers. Format validation does not independently establish a valid signature, approval, network connection or a matching callback payload. A future submission adapter must perform those checks before entering this boundary. Saved records are historical evidence, never executable authority.

## Single-attempt lifecycle

1. Validate identifier shape and require an existing destination directory. Exclusively create a new file with `outcome: null`, flush and fsync it, then close it. Existing files or symlinks are refused. Any failure here prevents callback invocation; partial or complete files are preserved and cannot be reused.
2. Invoke the supplied callback exactly once. It must already be bound to the independently verified bundle. There is no internal retry or automatic resume.
3. Accept only the normalized labels `reply-success`, `reply-pending` or `reply-failure`. These describe an adapter's reply, not block confirmation or proof of network-wide rejection. Callback exceptions, keyboard interruption and invalid labels attempt to save `unknown`, then propagate failure. Exception details are not persisted.
4. Save the outcome by writing, flushing and fsyncing a same-directory temporary snapshot, then replacing the intent file atomically. Detect external changes before replacement. An outcome write failure leaves the intent snapshot and does not invoke the callback again.

The reader validates a bounded 16 KiB document, exact keys/types/content, fixed network, identifiers and digest. Duplicate keys, non-finite values, altered flags and malformed outcomes are rejected. Every readable record returns `dispatch_may_have_occurred=true` and `fresh_chain_validation_required=true`; `automatic_retry_allowed` and `confirmation_established` are always false. Even `outcome: null` is ambiguous: it could mean an interrupted process before dispatch, during dispatch, or after a reply but before recording it. A completed node reply is also historical.

Abrupt process death may leave an intent-only snapshot or an unused temporary file. There is no directory fsync or universal power-loss guarantee. This is a single-writer trusted-filesystem boundary; hash validation is corruption detection, not authentication against a writer that can replace all content. It does not provide cross-process/cross-filename deduplication or exactly-once delivery. Creating another filename does not establish permission to send again.

## Following implementation steps

TN-4d2 will define and test the authenticated submission adapter with local TLS fixtures. Before dispatch it must independently revalidate original artifacts, fresh preparation, detached signature and exact approved bundle ID; check live node identity, synced state and the exact unspent coin; and freeze the verified bundle bytes. Historical monitor verification must never authorize submission. The operator's explicit approval binds one exact bundle, not an arbitrary saved verification flag. Output/input/credential path aliases must be refused before creating records.

That adapter must use an explicit loopback mutual-TLS endpoint and a separate mutating route allowlist, with no proxy, redirect, endpoint discovery or automatic HTTP retry. Raw node replies need strict normalization into the labels above; malformed replies and transport failures are ambiguous. Adapter mapping and bounded request/worker cleanup require their own executable tests before a public command is enabled. A successful reply remains distinct from the existing read-only confirmation monitor.

After those fixture gates, connect the boundary to an isolated full-node rehearsal and verify exact bytes, duplicate/ambiguous outcomes and cleanup. Then review the public operator command and host baseline. Live installation, owner creation, funding and public submission still require concrete host/transaction details and authorization. No current test step sends a public transaction.

## Validation and native gate

Ten new unit methods cover persisted intent before dispatch, all normalized reply labels, existing-file refusal, invalid context/missing directory, initial fsync failure, exception/interruption/malformed reply ambiguity, outcome fsync and replacement failures, copy isolation/external edits, actual abrupt subprocess exit, and bounded/corrupt document rejection. No network or real key is involved. Existing compiler CI discovers these tests automatically.

Run on LANDO as `steve`, without sudo:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
python3 tools/verify_m0.py
python3 -m unittest discover -s integration -p 'test_*.py'
)
```

Expected: **123 tests, no skips**, plus specification/artifact checks passing. No Cargo build, pinned Chia runtime matrix or full-node rerun is needed for this internal standard-library-only addition. After native success, publish and verify exact-revision CI, then implement the adapter gate described above.
