# TN-4d4: operator review and explicit submission

Status: Windows integration suite passed 145 tests (19 Linux-only skips); the pinned CLI/TLS matrix and offline review passed, with resources closed and source hashes verified. Native LANDO passed, confirmed on 2026-11-13. The preceding [full-node dispatch gate](testnet-full-node-dispatch.md) passed native Linux and is published at `c0c93a788496beed79f02f72ff6b3b868de6416c`. All exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43545780538), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43545780559), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43545780543).

## Dispatch review and remaining boundaries

The internal path now has fresh artifact/preparation/signature verification, exact bundle approval, fixed public and simulator identities, intent-before-dispatch persistence, fresh node/coin checks, bounded workers, conservative unknown outcomes and separate confirmation monitoring. The isolated full-node rehearsal established exact mempool/confirmation evidence for normal and deliberately lost replies. Those tests do not establish a deployed public node's effective constants or authorize real transactions.

This gate adds `integration/submit_fee.py`, an operator wrapper around that tested public dispatch path. It introduces no new signing, wallet discovery, fee changes or automatic retries. The compiler and published packages are unchanged. Tests use public fixture keys and disposable TLS endpoints only.

Before live use, complete the dedicated host/version/configuration baseline, choose test-only owner and recipient/change destinations, record funding/spend fee limits and confirmation policy, and review each concrete funding or spend transaction. No host, key, address or budget is selected by this document. After this gate, consolidate the operator walkthrough and host-readiness record; actual setup and trial transactions remain separate actions.

## Two separate invocations

Both modes require `--binary`, `--manifest`, `--observation`, `--solution`, `--preparation`, `--signature-response` and `--max-fee`. `--max-observation-age` defaults to 300 seconds and retains the verifier's existing bounds. The pinned runtime is required. All paths are explicit.

First invoke `--review-only`. It freshly reconstructs and verifies the original signed preparation without loading an owner key. Socket connect/bind operations are denied by the existing audit hook. JSON output includes the exact bundle ID and serialized-bundle hash, preparation/response hashes, network and full preparation: destinations, amounts, fee accounting, conditions, signing request and provenance. It reports zero submissions and no confirmation. Review mode rejects approval, TLS, attempt and dispatch-timing options and does not create an attempt file.

After reviewing that output, a separate invocation supplies `--approve-bundle-id` with that exact ID. It also requires `--endpoint`, `--ca-cert`, `--client-cert`, `--client-key`, `--attempt`, `--duration` and `--timeout`. There are no default credentials, endpoint or dispatch timing values. The attempt directory must already exist and the filename must be new. This mode repeats fresh verification rather than trusting saved review output.

The endpoint remains literal-loopback HTTPS with mutual TLS. The command uses fixed public identity checks; it has no network override, simulator mode or historical-verification option. Fresh coin reads precede the exact approved bundle's single dispatch. The worker and persistence limits are those of [verified dispatch](testnet-verified-dispatch.md), including possible whole-command runtime beyond the worker budget.

## Command forms for a later reviewed trial

These forms use operator-selected variables, not a request to run a live transaction now. Review all resolved values and destinations first. Do not automatically extract an approval ID from unreviewed output and submit it.

```bash
.work/m4/venv/bin/python integration/submit_fee.py \
  --binary "$BINARY" --manifest "$MANIFEST" \
  --observation "$OBSERVATION" --solution "$SOLUTION" \
  --preparation "$PREPARATION" --signature-response "$SIGNATURE_RESPONSE" \
  --max-fee "$MAX_FEE" --review-only
```

The separately reviewed submission form is:

```bash
.work/m4/venv/bin/python integration/submit_fee.py \
  --binary "$BINARY" --manifest "$MANIFEST" \
  --observation "$OBSERVATION" --solution "$SOLUTION" \
  --preparation "$PREPARATION" --signature-response "$SIGNATURE_RESPONSE" \
  --max-fee "$MAX_FEE" --approve-bundle-id "$REVIEWED_BUNDLE_ID" \
  --endpoint "$ENDPOINT" --ca-cert "$CA_CERT" \
  --client-cert "$CLIENT_CERT" --client-key "$CLIENT_KEY" \
  --attempt "$NEW_ATTEMPT_FILE" --duration "$DURATION_SECONDS" --timeout "$SOCKET_TIMEOUT_SECONDS"
```

## Outcomes and next observation

| Exit | Meaning |
| --- | --- |
| 0 | Offline review completed, or submission received `reply-success`; neither proves confirmation |
| 3 | Submission received `reply-pending`; not confirmation |
| 1 | Verification, worker, persistence or other operation failed/interrupted; inspect any attempt record, which may be unknown |
| 2 | Invalid or mixed command arguments; no dispatch |

Existing attempt files and input/credential aliases are refused without overwriting them. No separate final success report is created; the attempt file is the durable record. A file may contain intent only or unknown even if the node accepted the bundle. A missing or incomplete record does not authorize retry. A new filename is not permission to resend. Errors omit raw worker/node exception details and never claim that nothing was sent.

Use the existing [read-only monitor](testnet-bounded-monitor.md) with original signed inputs, explicit depth/bounds and optionally a new [history file](testnet-monitor-history.md). Monitoring never submits or changes the spend. A pending/unspent/timeout observation does not prove rejection or absence from every mempool. Resolve uncertainty by observation and review; there is no automatic recovery command.

## Validation and native gate

Four unit methods cover full review output/socket-denial hook without dispatch, missing/mixed arguments, success/pending/error exit statuses, and exceptions/interruption without retries or private-detail output. The pinned operator matrix now invokes the actual CLI for all seven public dispatch cases and checks offline review output against independent verification before any RPC. It retains isolated dispatch and confirmation/monitor regressions.

Run on LANDO as `steve`, without sudo. This block runs fixtures only:

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

Expected: **145 tests without skips**; confirmation **9/11**, monitor **5/4**, public dispatch **2/5**, isolated dispatch **1/2** positive/negative cases; resources closed. Preserve `.work/testnet/operator-confirmation-linux.json`, which also records CLI dispatch and offline review checks. Existing CI executes the matrix. Shared dispatch/signing/transport and full-node harness code are unchanged; no separate full-node rerun is needed for this wrapper.
