# Experimental testnet integration

[TN-4d2b verified bounded dispatch](../docs/spec/testnet-verified-dispatch.md) adds an internal fresh-verification/approval boundary and one bounded worker with fresh coin checks. No public CLI. Current suite: 136 tests (19 Linux-only); the pinned operator matrix adds dispatch 2 positive/5 negative. Native LANDO passed, confirmed on 2026-11-13.

[TN-4d2a isolated submission transport](../docs/spec/testnet-submission-transport.md) adds an internal single-use `push_tx` transport, exercised only against disposable TLS fixtures. Original read-only allowlists are unchanged. Current suite: 130 tests (19 Linux-only); native LANDO passed, confirmed on 2026-11-13. Fresh verification/approval and bounded dispatch must be wired before a public submission command exists.

[TN-4d1 submission attempt records](../docs/spec/testnet-submission-attempt.md) adds an internal intent-before-dispatch persistence boundary, exercised only by disposable callbacks. It has no CLI or RPC adapter. Current integration suite: 123 tests (19 Linux-only); native LANDO passed, confirmed on 2026-11-12.

[TN-4c4 saved monitor history](../docs/spec/testnet-monitor-history.md) adds optional `monitor_fee.py --history NEW_FILE`. Accepted observations and the final outcome are saved atomically as historical evidence. Existing files are refused; history never authorizes automatic resume. Current suite: 113 tests (19 Linux-only); operator matrix: confirmation 9 positive/11 negative and monitor 5 positive/4 negative.

[TN-4c3 bounded monitoring](../docs/spec/testnet-bounded-monitor.md) adds `monitor_fee.py` with required duration, interval and attempt limits. Each read runs in a worker that is terminated/reaped on timeout. There is no submission, error retry or automatic resume. The suite has 105 tests (19 Linux-only); the existing operator matrix now also covers monitor progression/reorg/deadline cases.

[TN-4c2 historical confirmation](../docs/spec/testnet-historical-confirmation.md) adds `confirm_fee.py --historical` for old signed expectations. It preserves current RPC checks and fresh signing defaults. The suite now has 95 tests (19 Linux-only), and the operator CLI matrix has 9 positive/11 negative cases.

[TN-4c1 operator confirmation](../docs/spec/testnet-operator-confirmation.md) adds `confirm_fee.py`, a single read-only observation after revalidating original signed inputs. Exit 0 means observed confirmed; exit 3 records a valid non-confirmed state; neither submits anything. Original-observation freshness still applies. The integration suite has 92 tests (19 Linux-only); the separate CLI matrix runs over local mutual TLS.

[TN-3b3 approved offline signing](../docs/spec/testnet-approved-signing.md) adds `sign_fee.py`: full `--review-only` output followed by a separate Linux signing invocation with an explicit preparation digest. It never submits. The integration suite now has 86 tests (19 Linux-only); the pinned signer matrix uses public fixtures and reports whether native key loading was exercised.

[TN-3b1 protected test-owner files](../docs/spec/testnet-signer-keyfile.md) adds the Linux-only file reader. [TN-3b2 owner-key creation](../docs/spec/testnet-owner-creation.md) adds exclusive creation and scalar/owner validation; TN-3b3 now uses the checked loader. The separate pinned-runtime owner-key matrix continues using only public disposable fixtures.

TN-1 adds `testnet_probe.py`, a separate standard-library Python read-only client. It does not change the compiler or connect automatically. See the [design](../docs/spec/testnet-design.md) and [TN-1 checkpoint](../docs/spec/testnet-readonly.md).

The only allowed POST routes are get_version, get_network_info, get_blockchain_state and get_coin_record_by_name. Network testnet11, prefix txch, reviewed genesis and exact node version2.7.5 are required. The endpoint must use HTTPS with a literal loopback IP and explicit port; localhost/DNS names and non-loopback addresses are rejected. Remote access requires a separately established SSH tunnel. The tool does not discover nodes, use environment proxies, follow redirects, load default credentials, start services or send transactions.

All credential paths and the output report are explicit. Provide a private-CA certificate plus an unencrypted client certificate/key pair; encrypted private keys are rejected without an interactive password prompt. The CA's private key is not needed. Do not use the public test fixtures with a live node. RPC certificate trust follows the reviewed Chia private-CA scheme with chain verification enabled and hostname matching disabled. Each socket operation has a configurable timeout in(0,30] seconds, default10; responses are capped at1MiB. The timeout is not a total wall-clock deadline for an adversarial trickle response.

Run `python3 integration/testnet_probe.py --help` for arguments. No live connection is requested as part of this checkpoint. Once a host/endpoint/certificate set is explicitly selected, the command form is:

```text
python3 integration/testnet_probe.py --endpoint https://127.0.0.1:PORT --ca-cert /explicit/ca.crt --client-cert /explicit/client.crt --client-key /explicit/client.key --report .work/testnet/observation.json
```

Optionally add `--coin-id HEX --expected-puzzle-hash HEX --expected-amount DECIMAL`. Amount and puzzle expectations require a coin ID. Coin lookup checks canonical coin identity, uint64 amount, unspent status and confirmation fields. Amounts are decimal strings in the report. Missing coins have a distinct error; malformed or failed RPC replies do not become successful observations. Node-supplied errors and tracebacks are not echoed.

The client compares the chain peak before and after lookup and rejects changes. Even equal peaks are not an atomic snapshot or proof of chain correctness. Reports explicitly say rpc-observation-only, atomic_snapshot=false, spend_validated=false and transactions_submitted=0. No-coin mode establishes only the checked connection observations. Coin readiness must be rechecked in later work.

A failed run removes an earlier success report. Reports may not alias any supplied credential path or be symlinks. Success is written through a temporary file and replaced only after all checks and connection cleanup. Exit0 means the requested observation passed; exit1 means validation/transport/file failure; argparse usage errors exit2. Reports omit endpoint and credential paths/content but include observation time and public coin/network state.

Development tests use synthetic replies and a real loopback-only mutual-TLS server, never a public endpoint:

```text
python3 -m unittest discover -s integration -p 'test_*.py'
```

Tests need no Chia installation or keys beyond the deliberately public fixtures. The source-inclusive compiler archive carries this directory for reproducibility; the integration tool is not an installed compiler command and remains experimental. Host selection and live-node observation are pending.

## Offline preparation (TN-2)

`prepare_fee.py` prepares only the reviewed fee-payment contract from a complete artifact, a coin-bearing observation and an explicit solution/fee budget. It requires the existing pinned simulator Python environment for independent execution; it never creates a node, signs or submits. See [TN-2](../docs/spec/testnet-preparation.md) for its format, limits and exact native test commands. `verify_preparation.py --binary PATH` exercises synthetic observations only.

## Detached signature boundary (TN-3a)

`verify_signed_fee.py` revalidates a TN-2 preparation and verifies a detached AugSchemeMPL response before assembling a one-coin bundle offline. It has no private-key or RPC path. [TN-3a documentation](../docs/spec/testnet-signing.md) defines the response, output and native test gate. The independent `verify_signing.py --binary PATH` matrix uses public fixture keys only. Operator key custody/signing setup remains a separate TN-3b decision.

## Confirmation observations (TN-4a)

`confirmation.py` checks exact coin spends, expected children, explicit confirmation depth and prior block anchors through an injected read-only RPC callable. It has no CLI or transport; its expectations must come from independent preparation/signature validation. [TN-4a documentation](../docs/spec/testnet-confirmation.md) defines statuses, caller responsibilities and the native gate. Fourteen new fixture tests bring the integration suite to 40 tests. Authenticated RPC wiring and the full-node rehearsal remain TN-4b work.

`confirmation_transport.py` adds an explicit mutual-TLS transport for the two additional confirmation reads, retaining the original probe's narrower allowlist. [TN-4b1](../docs/spec/testnet-confirmation-transport.md) exercises the complete read sequence against a real loopback TLS fixture server; the suite now has 48 tests. Actual full-node RPC rehearsal remains the next gate.

[TN-4b6](../docs/spec/testnet-observation-identity.md) introduces fixed public and isolated identities for shared internal observation helpers. Public entry points remain bound to testnet11; only simulator adapters select the reviewed local identity. Isolated reports carry distinct labels and are rejected by public preparation. The integration suite now has 54 tests.

[TN-4b7](../docs/spec/testnet-offline-pipeline.md) shares offline preparation/signature verification with the fixed isolated adapter, using pinned actual simulator constants. Public functions and CLIs retain their testnet11 policy.
