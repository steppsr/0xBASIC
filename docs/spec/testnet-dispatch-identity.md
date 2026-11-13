# TN-4d3a: fixed isolated dispatch adapter

Status: Windows unit suite passed 141 tests (19 Linux-only skips); pinned TLS matrix passed confirmation 9/11, monitor 5/4, public dispatch 2/5 and isolated dispatch 1/2 positive/negative cases, with resources closed. Native LANDO passed, confirmed on 2026-11-13. The previous verified-dispatch gate passed native Linux and is published at `ef08322e48addb537a0c094ab653885ad41e7d3d`. All exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43465338734), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43465338440), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43465338240).

## Fixed adapters before full-node integration

The public adapter is fixed to reviewed Chia 2.7.5/testnet11; the existing full-node rehearsal uses pinned Chia 2.7.4 and `0xbasic-simulator`. This gate shares dispatch logic without rewriting public documents or weakening the public verifier to make the identities match.

`simulator/isolated_dispatch.py` exports `dispatch_isolated(args)` and `read_isolated_attempt(path)` and starts only its private worker protocol. All bind the existing `ISOLATED_REHEARSAL` singleton in code. Public dispatch, attempt reading and worker entry remain fixed to `PUBLIC_TESTNET`. Arguments, packet fields, RPC responses and saved documents cannot select the identity. Private helpers reject arbitrary identity objects, including value-identical copies of reviewed singletons.

Shared parent logic still freshly reconstructs the preparation, verifies the detached signature, requires exact bundle approval, protects paths, freezes bytes and persists intent. The isolated branch uses the existing isolated verifier with its signing domain and consensus-constants evidence checks. It launches a separate fixed simulator worker script. Fresh node identity, stable synced peak, exact unspent coin and original-observation freshness checks precede the same single-use push transport.

Public attempt records keep their prior schema/network/`submission-attempt-record-only` label. Simulator records use their own network and `isolated-submission-attempt-record-only`. Each reader checks its fixed label and network along with strict schema/hash validation and rejects the other domain. Unknown-outcome, no-confirmation and no-automatic-retry semantics are unchanged. Hashes remain corruption checks, not authentication against wholesale rewrites.

These private adapters do not defend against arbitrary Python code execution. Workers trust their verified parent and are not an operator CLI. No public identity selector, dependency/version/profile change or live transaction is introduced.

## Validation and next gate

Five new unit methods cover cross-domain reader refusal; copied identities rejected before I/O; fixed verifier/worker selection; fresh-read rejection against the other node identity despite packet fields; and fixed worker script selection. Existing public dispatch tests remain unchanged.

The pinned local-TLS matrix adds actual compiled/signed isolated fixtures: successful isolated verification and exact dispatch, public verification refusing isolated inputs before RPC, and an isolated worker refusing a public-version node before push. The public attempt reader also rejects the successful simulator record. All prior public confirmation/monitor/dispatch cases remain.

This is synthetic RPC coverage over real local TLS, not real mempool/consensus acceptance. TN-4d3b will connect the adapter to the existing full-node rehearsal, compare exact verified bytes with mempool and confirmation evidence, and exercise ambiguous outcomes without automatic retry. Public operator commands, host baseline and concrete live transaction authorization remain subsequent work.

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
python3 -m unittest discover -s integration -p 'test_*.py'
.work/m4/venv/bin/python integration/verify_operator_confirmation.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **141 tests without skips**; confirmation **9 positive/11 negative**, monitor **5 positive/4 negative**, public dispatch **2 positive/5 negative**, isolated dispatch **1 positive/2 negative**, resources closed. Preserve `.work/testnet/operator-confirmation-linux.json`. Existing CI runs the expanded matrix and discovers the new tests. No live node or real keys are needed; the full-node harness has not yet been changed to invoke this adapter.
