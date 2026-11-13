# TN-4c3: bounded read-only operator monitoring

Follow-up: [TN-4c4](testnet-monitor-history.md) adds optional saved history. The final-only behavior and test counts below describe the original TN-4c3 gate.

Status: Windows integration suite passed 105 tests (19 Linux-only skips), confirmation CLI matrix 9 positive/11 negative and monitor CLI matrix 5 positive/2 negative over mutual TLS, with resources closed. Native LANDO passed, confirmed on 2026-11-12. TN-4c2 is published at `b68910682db177e12622d79bf7016c5053a16165`.

TN-4c2 exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43360230637), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43360231038), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43360230793).

`integration/monitor_fee.py` adds bounded repeated observation of one independently verified historical signed spend. It never signs, submits, rebroadcasts, funds or changes a fee. It uses the [historical verification contract](testnet-historical-confirmation.md) and existing authenticated confirmation core. No live host or user key has been accessed for this gate.

## Verification and budget

All original compiler/artifact/observation/solution/preparation/signature-response inputs and maximum fee remain explicit. The monitor always uses the historical read-only verifier and reconstructs the exact input, reveal, solution, expected children and bundle ID before starting any worker. Original recorded-time consistency and age-at-preparation checks remain mandatory. Saved report flags are never accepted instead of revalidation.

The operator must also supply:

| Argument | Required range |
| --- | --- |
| `--duration` | Finite number greater than zero, at most 600 seconds |
| `--interval` | Finite number from zero through duration |
| `--max-attempts` | Integer 1..1000 |
| `--depth` | Integer 1..10000 |

The monotonic duration starts **after offline verification**, at the observation loop. Process startup, RPC reads and intervals consume that loop budget. Offline compiler verification, operating-system scheduling, process termination/reaping and final report writing can make total command duration longer. The tool does not promise a hard real-time deadline for the whole command.

Each observation runs in a fresh Python worker. The parent supplies only the already verified expectations, explicit TLS settings and current comparison anchor over stdin. The worker performs one read-only confirmation and starts no compiler, signer or child process. Remaining loop time bounds communication with the worker; on timeout or interruption the parent terminates and reaps it and closes its pipes before returning. This avoids retaining a background socket-read thread after the parent decides an observation timed out.

The original per-socket timeout remains separate (default 10 seconds, maximum 30). If the worker reports an RPC/TLS/validation failure before the loop deadline, the monitor fails rather than retrying it. Duration expiry does not convert malformed data into a valid observation. A result arriving at or after the deadline is discarded even if it says confirmed.

## State and anchor rules

Only valid `unspent` and `confirming` observations continue the loop. Once a confirming observation provides an inclusion anchor, the parent carries that exact input/height/hash into the next worker. A later confirmed observation must therefore still agree with the remembered anchor. `confirmed`, `reorged` and `conflicting-spend` stop immediately. There is no automatic recovery from a reorg or conflicting spend.

Optional `--previous-height` and `--previous-header-hash` must be supplied together. Their input ID comes from the verified spend. As in the one-shot command, the prior anchor is a comparison hint, not proof of chain history. The result's `last_anchor` is the last known inclusion anchor; after a reorg it is historical, not a current confirmation claim. `last_observation` always contains the last accepted on-time result; a late or timed-out worker does not replace it.

| Exit | Result |
| --- | --- |
| 0 | Observed confirmed at the requested depth |
| 3 | Timed out, reorged or conflicting spend; valid final report retained |
| 1 | Invalid inputs, RPC/worker/validation failure, interruption or file error |
| 2 | Invalid CLI argument usage |

Timeout reasons distinguish attempt limit, deadline and observation timeout. Attempts include the read that timed out. Reaching a limit does not establish transaction rejection or absence from a mempool. No mempool status is queried by this monitor.

## Reports and restart rules

The final `historical-verified-read-only-monitor` report contains expected bundle/preparation/response identifiers, status/reason/attempts/timing, last observation/anchor and worker cleanup. It explicitly records no chain proof, no submission freshness, zero transactions submitted and `automatic_resume_allowed=false`. Expectations are fixed in memory for the run; changes to input files do not redirect a running monitor to a new spend. A new invocation must revalidate its supplied inputs.

Report path protections and atomic publication follow the one-shot operator command. An old report is removed after path validation. Errors before publication leave no current result, and temporary output is cleaned up. The report omits endpoint and credential paths/content. A worker's raw result makes only the existing RPC observation claim; it does not assert signature verification independently of the parent.

This slice writes only the final result. It has no incremental journal, authenticated checkpoint import or automatic resume. If interrupted, in-memory observations may be lost; an old external copy remains historical. To start another observation run, provide original signed inputs and an explicitly chosen prior anchor and revalidate them. Do not infer that an interrupted observation means a transaction was unsent, and do not rebroadcast because a monitoring report is absent. Durable monitoring history and submission intent/outcome records remain separate next work.

## Validation and native gate

Ten new unit methods cover anchor carry-forward, attempt timeout, reorg/conflict termination, retaining the prior valid observation on timeout, rejecting late confirmation, numeric bounds before reads, no retry on errors/wrong identity, real child timeout termination/reaping, failed-child cleanup, and CLI status/stale-report handling. The suite has 105 methods, including the 19 existing Linux-only protected-file cases.

The existing actual CLI/mutual-TLS matrix retains its 9 positive/11 negative one-shot cases and adds five monitor cases: immediate confirmation, pending attempt timeout, advancing depth, replaced anchor and a deliberately delayed server response requiring worker timeout. Two monitor failures cover invalid signature before worker/RPC and an RPC identity error with no retry. Tests use public fixture signatures and certificates; they neither contact a live node nor modify a real key vault.

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

Expected: **105 tests, no skips**; confirmation **9 positive/11 negative**, monitor **5 positive/2 negative**, resources closed. Preserve `.work/testnet/operator-confirmation-linux.json`, which now includes both sets of cases. Existing CI runs this expanded matrix without workflow changes. Shared preparation/signature/confirmation algorithms and simulator code are unchanged; no separate full-node or signing rerun is needed locally for this wrapper. After native success, publish, verify exact CI and continue durable observation/submission-state design.
