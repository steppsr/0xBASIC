# TN-4d2a: isolated submission transport boundary

Status: Windows integration suite passed **130 tests (19 Linux-only skips)**. Native LANDO passed, confirmed on 2026-11-13. The previous [attempt-record gate](testnet-submission-attempt.md) passed native Linux and is published as `893e53d5a90c1a44c5056df1c0cbbbb528f53766`. All exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43370953860), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43370953849), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43370953857).

## Scope

The submission adapter is split into transport (this gate), verified dispatch and bounded worker lifecycle, then an isolated full-node rehearsal. `integration/submission_transport.py` is an internal transport used only by disposable local TLS tests. There is no public submission command. It does not establish signature validity, operator approval, node identity, synced state or an unspent input. Those checks remain mandatory before wiring a real caller.

`_SubmissionTransport` uses a separate allowlist containing only `push_tx`. The existing probe and confirmation transports continue rejecting that route. It requires an explicit literal-loopback HTTPS endpoint, CA certificate and client certificate/key; it inherits CA verification, TLS 1.2 minimum, no proxies, no redirects, bounded JSON responses and connection cleanup from the existing transport. It does not discover endpoints or use a default keychain.

Construction validates and copies one bundle into immutable JSON bytes: exactly one spend, exact coin/spend/bundle keys, uint64 amount, fixed-length coin hashes/signature and nonempty even-length program hex. Requests are capped at 1 MiB. This is wire-shape validation only: it does not parse CLVM, validate a BLS point/signature, derive the bundle ID or compare approval. Tests deliberately use synthetic public bytes rather than real spendable bundles.

The transport accepts only its frozen request and invokes HTTP at most once per instance. It marks the instance used before attempting the connection. A timeout or connection failure cannot make the same instance usable again. There is no global duplicate prevention: constructing another instance is not permission to retry. A future caller must enter the [intent-record boundary](testnet-submission-attempt.md) before invoking `push()`.

## Reply semantics and limits

The pinned [Chia 2.7.5 push_tx implementation](https://github.com/Chia-Network/chia-blockchain/blob/2.7.5/chia/full_node/full_node_rpc_api.py#L827) returns a status name and raises a structured RPC error on FAILED. The adapter accepts only an exact boolean-success/status envelope with SUCCESS or PENDING, mapped to `reply-success` or `reply-pending`. Neither establishes block confirmation.

All false envelopes, unknown statuses, extra or contradictory fields, duplicate JSON keys, malformed JSON, oversized bodies, redirects, unexpected content types, disconnects and timeouts raise failure. When called inside `_attempt`, these preserve an `unknown` outcome. This first transport does not map node errors to `reply-failure`: a negative reply is not treated as proof that the bundle could not have reached a node. No raw reply or exception detail is persisted in attempt records.

The per-socket timeout is finite and in (0,30] seconds. It is **not a total request deadline**, including for a trickled response. Process-isolated deadline enforcement, termination/reaping and interruption reporting belong to the next verified-dispatch gate. This internal class must not be presented as the complete public submission adapter.

## Following gate

TN-4d2b must freshly and independently verify original artifact/preparation/signature inputs, require approval of the exact bundle ID, check public node identity/synced state/exact unspent coin, freeze verified payloads and reject attempt/report/input/credential aliases. It must combine intent-before-dispatch with a bounded worker and conservative unknown outcomes after worker loss. A saved monitor report or historical signature verification cannot authorize dispatch. Then test the combined path with actual isolated full-node submission before enabling any operator CLI. Live host configuration and concrete public transactions remain separate authorization decisions.

## Validation and native gate

Seven new test methods cover frozen exact payloads and one-call behavior; pending replies with intent already saved; invalid/negative/contradictory replies recorded unknown; HTTP/JSON/disconnect/timeout failures without retries; separate route allowlists and payload mutation refusal; request shape/size rejection before TLS setup; and endpoint, timeout, wrong-CA and missing-client-certificate rejection. A disposable server requires mutual TLS and is shut down and joined. No live node or real keys are used.

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

Expected: specification/artifact checks pass and **130 tests pass with no skips**. This gate uses Python's standard library and disposable loopback TLS only; no Cargo build, pinned Chia matrix or full-node rerun is required. Existing compiler CI discovers the added tests. After native success, publish, verify exact-revision CI and proceed to TN-4d2b.
