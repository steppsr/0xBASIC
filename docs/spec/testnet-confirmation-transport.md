# TN-4b1: authenticated confirmation reads

Status: Windows passed 48 integration tests, including eight new real loopback mutual-TLS tests. Native LANDO passed, confirmed on 2026-11-10. [TN-4a](testnet-confirmation.md) passed native LANDO and is published at `57723a7f118e4b128dfb3c3d7bfa9011caedde82`.

All TN-4a exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/42916460597), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/42916460508) and [packages](https://github.com/steppsr/0xBASIC/actions/runs/42916460486).

This is the transport gate within TN-4b. It connects the existing confirmation observer to authenticated HTTP reads against an isolated fixture server. The next gate is the real full-node RPC rehearsal. These TLS tests do not establish consensus acceptance or complete TN-4.

## Transport boundary

`integration/confirmation_transport.py` provides `ConfirmationTransport`, a subclass of the existing read-only TN-1 transport. Its constructor requires the same explicit literal-loopback HTTPS endpoint, CA certificate, client certificate and client key. It inherits CA verification, required client credentials, TLS 1.2 minimum, no environment proxies, no redirects, one-megabyte response limit, strict JSON envelope decoding and connection cleanup. Hostname checking remains disabled for Chia private certificates, with CA verification enabled. The timeout is per socket operation, not a total observation deadline.

The base transport now has a separate request-validation method invoked before opening a connection. The base allowlist remains its original four read routes. Only the confirmation subclass adds:

| Route | Exact request fields | Validation |
| --- | --- | --- |
| `get_block_record_by_height` | `height` | uint32 integer, excluding booleans |
| `get_puzzle_and_solution` | `coin_id`, `height` | 32-byte coin ID and uint32 integer height |

Missing/extra fields, invalid IDs, negative/overflow/string/boolean/float heights and unapproved routes fail before HTTP I/O. No submission, wallet, private-key retrieval or arbitrary route is added. The original probe rejects both added routes.

An integration caller connects the existing pieces as follows:

```python
transport = ConfirmationTransport(endpoint, ca_cert, client_cert, client_key)
result = observe_confirmation(
    transport.call, verified_coin_spend, verified_children, depth, previous_anchor
)
```

This illustrates the Python API, not a new executable command. The spend/children must originate from independent preparation/signature validation, as specified by the [confirmation contract](testnet-confirmation.md). There is no saved-report loader, credential discovery or public-node command in this slice.

## Evidence and limits

The new tests run an actual loopback HTTPS server requiring a client certificate, using the repository's deliberately public TLS fixtures. They exercise the entire confirmation read sequence over TLS, depth and reorg statuses, ignored environment proxies, original probe route restrictions, mutation/private/path-route rejection, request schema validation, wrong CA and missing client certificates, redirects, oversized/duplicate-key responses, socket timeout and endpoint restrictions. The server and listener thread are closed after the tests.

The returned chain and coin data are synthetic. No actual Chia service is started, no signature is generated and no transaction is submitted. There is no public-network or node-version compatibility claim beyond the already reviewed route shapes. The complete integration suite now has 48 tests; compiler CI discovers them automatically on Windows and Linux.

## Native LANDO gate

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

Expected: specification checks and **48 integration tests** pass. The tests bind only ephemeral loopback ports and use public fixture credentials. No Cargo build, Chia environment, live credentials, signing matrix or full-node rerun is required for this transport gate.

After native confirmation, commit/push and verify exact-revision CI. Continue with TN-4b2 full-node RPC rehearsal: isolated roots and credentials, actual funding/preparation/signing/submission, rejection controls, mempool versus confirmation reporting, bounded observation, reorg/timeout handling and cleanup evidence. Resolve the pinned simulator's 2.7.4/test-constants identity versus the reviewed 2.7.5/testnet11 expectations explicitly; do not spoof version/network responses to make the rehearsal pass. Live host and operator key-custody selection remain separate prerequisites for TN-5.
