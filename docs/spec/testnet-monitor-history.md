# TN-4c4: saved operator monitor history

Status: Windows integration suite passed 113 tests (19 Linux-only skips); the mutual-TLS CLI matrix passed confirmation 9 positive/11 negative and monitor 5 positive/4 negative, with resources closed. Native LANDO passed, confirmed on 2026-11-12. The preceding bounded-monitor step passed native Linux and is published at `3d62ece8e723545c0e033bdb0fa719630298ea1d`; its [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43365978126), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43365978187) and [package](https://github.com/steppsr/0xBASIC/actions/runs/43365978167) CI all passed.

## Usage and records

Add `--history /explicit/new-monitor-history.json` to the [bounded monitor](testnet-bounded-monitor.md) command. All original signed inputs, explicit credentials, bounds and report arguments remain required. Omitting the option retains final-report-only behavior. This command remains read-only.

After independent historical verification, the writer exclusively creates a new history file before starting any observation worker. Existing files and symlinks are refused, never reused. History and report paths must be distinct and cannot alias protected inputs or credentials. Choose a new filename for every run.

The snapshot contains `schema_version: 1`, a context and ordered records. Context binds the verified input and expected bundle IDs, preparation and signature-response hashes, network, requested depth, initial comparison anchor and polling limits. It contains no endpoint or credential paths/content. Each accepted on-time observation is saved before the next read, with its attempt number. Late results and failed reads are not saved as observations. A normal terminal result or timeout adds a final `finished` record containing the outcome. No records may follow it.

Records have a sequence number, kind, value, previous hash and SHA-256 over the canonical record body. The first previous hash covers the context. Canonical JSON uses sorted keys and compact separators. Limits are 8 MiB and 1,001 records (1,000 observations plus the final outcome). The final report records the history file's byte hash and record count; without history its `history` field is null.

## Persistence and interpretation

Each update writes a complete replacement snapshot to a temporary file in the same directory, flushes and fsyncs that file, then atomically replaces the previous snapshot. In-memory state advances only after replacement. A failed checkpoint aborts monitoring and leaves no current final report; previously completed snapshots remain available. The writer checks for external changes before updating and refuses them.

This is a single-writer, trusted-filesystem contract. It does not protect against concurrent hostile writers or filesystem races. There is no directory fsync or universal power-loss guarantee. Initial exclusive creation can leave an incomplete file if interrupted; preserve it and use a new filename. Abrupt termination may leave an unused temporary file. Persistence and process cleanup can extend total command time beyond the observation budget; checkpoint time inside the loop consumes that budget.

`monitor_history.read_history(path)` checks bounded JSON, duplicate keys, non-finite numbers, schema, ordering and hashes. It does **not** independently validate record semantics, signed spends or current chain state. Hashes detect accidental corruption but do not authenticate history against someone able to rewrite the entire file. Reader results explicitly require fresh chain validation and disallow automatic resume.

A prefix without `finished` records only completed checkpoints. An empty prefix does not prove no RPC read was attempted. A finished history can exist without a final report if report publication subsequently fails. Neither history nor a missing report establishes whether a transaction was submitted elsewhere. There is no automatic resume, import, rebroadcast or retry. A new monitor invocation revalidates original inputs; any manually supplied prior anchor remains only a comparison hint. Submission intent/outcome handling is separate next work.

## Validation and native gate

Eight new unit methods cover round-trip/copy isolation, exclusive creation, fsync and size failures preserving prefixes, external edits, malformed or corrupted snapshots, an actual abruptly exiting writer, and checkpoint rejection for late observations or write failure. The existing CLI test also checks history/report alias refusal. The operator matrix checks saved history for all five monitor outcomes, invalid signature before history creation, RPC failure with empty history, RPC failure after one completed observation, and refusal to overwrite an existing history.

Run on LANDO as `steve`, without sudo:

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

Expected: **113 tests, no skips**; confirmation **9 positive/11 negative**, monitor **5 positive/4 negative**, resources closed. Preserve `.work/testnet/operator-confirmation-linux.json`. These use disposable public fixtures and local mutual TLS, with no live node or real owner key. Existing CI discovers the unit tests and runs the expanded operator matrix. Shared compiler, signing and confirmation algorithms are unchanged; no separate full-node or signing rerun is needed for this gate. After native success, publish and verify exact-revision CI before proceeding.
