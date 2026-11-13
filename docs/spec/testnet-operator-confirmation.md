# TN-4c1: read-only operator confirmation command

Status: Windows integration suite passed 92 tests with 19 Linux-only skips; the actual CLI matrix passed six positive/five negative cases over mutual TLS with resources closed. Native LANDO passed, confirmed on 2026-11-12. TN-3b3 passed native Linux and is published at `096967f5aaac0388b1c2adf6e05be153932f11c7`.

TN-3b3 exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43357405557), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43357405538), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43357405533).

This slice exposes the existing independently verified spend and authenticated confirmation checks as one operator command. It does not add transaction submission, key loading, polling, automatic retry or live host configuration. The [TN-4 exit review](testnet-rehearsal-review.md) remains the reference for public-trial prerequisites.

## Inputs and trust boundary

`integration/confirm_fee.py` requires the compiler binary, artifact manifest, original observation, solution, preparation, detached signature response and maximum fee. It independently invokes TN-3a verification on those original inputs; it does not accept a saved report's `signature_verified` flag as authority. A failed verification prevents all RPC requests.

Expected input/puzzle/solution and child coins are derived from the successful verifier result. The caller also supplies an explicit confirmation depth (1..10000), loopback HTTPS endpoint, CA certificate, client certificate/key paths and output report. The client key is an RPC TLS credential, not a contract owner key. No default root, wallet, keychain, endpoint or credential discovery occurs.

The public identity remains fixed to the reviewed testnet11/Chia 2.7.5 policy. Existing confirmation transport allows only its six read routes, including get_block_record_by_height and get_puzzle_and_solution. It rejects mutation/private routes, proxies, redirects and non-loopback endpoints, and retains strict JSON/response-size and mutual-TLS checks. The timeout is per socket operation (default 10 seconds, maximum 30), not a hard end-to-end deadline; this command makes one observation rather than a polling loop.

Optional `--previous-height` and `--previous-header-hash` must be supplied together. The input ID is derived from the verified spend. A prior anchor is an operator-supplied comparison hint, not trusted proof or permission to submit anything. A replaced anchor produces a reorged observation. There is no automatic import/resume from a prior report.

## Results and exit codes

The command compares exact on-chain input/reveal/solution and child identities/creation heights, checks the canonical inclusion anchor and inclusive depth, and requires unchanged synchronized surrounding peaks. The report retains the confirmation core's explicit lack of atomic snapshot or independent chain proof.

| Exit | Meaning | Report |
| --- | --- | --- |
| 0 | Valid observation says `confirmed` at the requested depth | Published |
| 3 | Valid observation says `unspent`, `confirming`, `conflicting-spend` or `reorged` | Published with that status |
| 1 | Signature/input verification, transport, RPC validation or file operation failed | No current success report |
| 2 | Invalid CLI argument usage | No command execution |

Exit 3 is a meaningful non-confirmed observation, not a successful spend. In particular, an unspent input does not imply mempool presence. The command never signs, funds, submits, rebroadcasts or changes fees.

The wrapper records `expected_bundle_id`, preparation/signature-response hashes and `signature_verified_offline`, alongside the complete observation. The bundle ID identifies the independently verified expectation: it is not a claim that RPC returned that aggregate bundle ID or signature from a block. Chain observation establishes only the checked spend/child facts.

Report paths may not be symlinks, equal inputs/credentials, or existing hard-link aliases to them. After path validation, an old report is removed; successful observations are published using a temporary file and atomic replacement. Failures remove temporary files and emit a generic message without credential paths or server tracebacks. Path/argument rejection preserves protected inputs; atomic publication is not a durability or hostile-filesystem guarantee.

## Current freshness limitation

Each invocation retains TN-3a's original observation freshness checks: default maximum age 300 seconds, explicit maximum 3600 seconds. The saved observation describes the earlier unspent coin; the new RPC read may correctly find it spent. An expired original observation is refused even when the spend is already confirmed.

Do not rewrite an observation timestamp, recreate an unspent observation for a spent coin, or weaken identity checks to bypass this limit. Historical signed-bundle revalidation and bounded long-running/resumed monitoring require a separate reviewed design before relying on this tool for delayed public confirmations. This first command alone does not complete operator submission/monitoring readiness.

## Validation

Six new standard-library test methods cover all five statuses, signature rejection before RPC, invalid depth/anchor before verification, report hard-link protection, exit codes/stale-report removal and the real mutual-TLS wiring. The complete suite has 92 methods; 19 protected-key filesystem methods remain Linux-only.

`integration/verify_operator_confirmation.py` invokes the actual CLI subprocess with the pinned BLS verifier and a local mutual-TLS fixture server. Six positive cases cover confirmed partial/exact payments, insufficient depth, unspent input, conflicting solution and replaced anchor. Five failures cover invalid signature, stale original observation, wrong RPC network, wrong child creation height and invalid depth. Failed signature/freshness/depth cases assert that the server received no requests; every failure invalidates stale output. Threads and sockets are closed before the report is published. The fixture is not consensus or live-node evidence; the existing full-node rehearsal supplies that separate scope.

Simulator CI executes this matrix and uploads `.work/testnet/operator-confirmation-<platform>.json`, including source/binary hashes, case names and cleanup/scope flags. No existing compiler, preparation, signer, confirmation core or transport behavior changes in this slice.

## Native LANDO gate

These tests use public fixture signatures/certificates and an ephemeral local server. No real node, wallet, owner key or RPC credentials are needed. Run as `steve`, without sudo:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 -m unittest discover -s integration -p 'test_*.py'
.work/m4/venv/bin/python integration/verify_operator_confirmation.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **92 tests pass without skips**, then **6 positive/5 negative operator confirmation cases PASS**, resources closed. Preserve `.work/testnet/operator-confirmation-linux.json`. No full-node, signer or package rerun is needed locally for this new wrapper. After native success, commit/push, verify exact CI and continue historical monitoring/submission design before any public transaction.
