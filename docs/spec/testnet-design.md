# TN-0: testnet connection and spend design

Status: testnet direction selected by the user on 2026-11-09. Design/source review complete; executable integration and public-network compatibility remain unvalidated. Start with the [selected plan](testnet-integration-plan.md). No host has been configured or contacted, no credentials accessed and no funds moved.

## Selected baseline and source evidence

Select **testnet11** for this milestone. Official [testnet documentation](https://docs.chia.net/reference-client/install-and-setup/testnets/) identifies it as the supported network. Select **Chia 2.7.5** as the initial node/API baseline: the [official latest release](https://github.com/Chia-Network/chia-blockchain/releases/tag/2.7.5) resolved to commit `ff71448437a137c7092775923d5ecbbe104433e7` during this review. These are dated selections; a later node version needs its own review rather than an automatic acceptance rule.

The compiler remains 0.3.0-alpha.1 / language 0.3 / ABI 1 / profile v2, with clvmr 0.19.0. Existing isolated locks remain Chia 2.7.4 / chia_rs 0.48.0 / Python 3.13.7. The new node baseline does not upgrade those environments or certify a new simulator lock.

[Source audit](testnet-upstream-audit.json) records SHA-256 for nine files fetched at the selected 2.7.5 commit and comparisons with installed 2.7.4 source. Seven inspected files are identical after line-ending normalization: default_constants, condition_tools, rpc_server, rpc_client, full_node_rpc_api, mempool_manager and server. The initial configuration differs only by a timelord inactivity setting; its testnet11 overrides are unchanged. The selected pyproject permits chia_rs >= 0.48.0,<0.49; that range alone does not prove which wheel an operator's node uses. This scoped source comparison is not a complete release diff or live-node validation.

Primary source anchors:

- [Network configuration](https://github.com/Chia-Network/chia-blockchain/blob/ff71448437a137c7092775923d5ecbbe104433e7/chia/util/initial-config.yaml): testnet overrides and address prefix.
- [Constants and override defaults](https://github.com/Chia-Network/chia-blockchain/blob/ff71448437a137c7092775923d5ecbbe104433e7/chia/consensus/default_constants.py): fork settings and testnet adjustments.
- [RPC server](https://github.com/Chia-Network/chia-blockchain/blob/ff71448437a137c7092775923d5ecbbe104433e7/chia/rpc/rpc_server.py): get_version and get_network_info response fields.
- [Full-node RPC](https://github.com/Chia-Network/chia-blockchain/blob/ff71448437a137c7092775923d5ecbbe104433e7/chia/full_node/full_node_rpc_api.py): state, coin lookup and submission semantics.
- [Signing pairs](https://github.com/Chia-Network/chia-blockchain/blob/ff71448437a137c7092775923d5ecbbe104433e7/chia/consensus/condition_tools.py): coin/domain message construction.
- [TLS construction](https://github.com/Chia-Network/chia-blockchain/blob/ff71448437a137c7092775923d5ecbbe104433e7/chia/server/server.py): private CA and client certificate behavior.

## Network identity and profile boundary

Expected network name is `testnet11`, address prefix `txch`, and genesis challenge:

```text
37a90eb5185a9c4439a91ddc98bbadce7b4feba060d50116a067de66bf236615
```

The selected upstream configuration sets AGG_SIG_ME_ADDITIONAL_DATA to the same bytes. This equality is a reviewed configuration fact, not a generic rule to derive a signing domain from any RPC response. It differs from the synthetic 32-byte-aa SpendSim domain. Public test fixture signatures cannot be reused.

The reviewed testnet overrides set HARD_FORK_HEIGHT 0, SOFT_FORK8_HEIGHT 3755000 and SOFT_FORK9_HEIGHT 3924000. Offline calculation with pinned chia_rs 0.48.0 gives consensus flags 0 before fork8, 512 at fork8,50332225 at fork9; with that library's MEMPOOL_MODE the corresponding flags are 34210327,34210327,50987607. The audit JSON records the boundary calculations. No current network height was queried.

These are not the local runner's 0x0257 flags. Do not compare local VM cost directly to node consensus cost or treat local execution as mempool acceptance. TN-2/TN-4 must independently execute the selected contract under reviewed height-derived network rules, including signature validation, and confirm exact outputs. A node reporting the expected name/genesis/version is necessary but insufficient: RPC metadata does not attest all effective constants, dependency versions or binary integrity. Record the operator's baseline and reject unreviewed versions; require the later isolated RPC rehearsal before any public spend.

## TN-1 read-only interface contract

Implement a separate standard-library Python tool under a new `integration/` directory. It must require an explicit loopback HTTPS endpoint, private-CA certificate, client certificate and client-key path. Use operator-provided files, without opening a default root, daemon or keychain. No node installation, configuration edits or certificate copying occurs implicitly. A remote host is reached through an operator-established SSH tunnel to a loopback endpoint; no public RPC binding is part of this tool.

Use mutual TLS with CA validation and certificate-chain verification enabled. Chia's pinned client disables hostname matching for its private certificates while retaining CERT_REQUIRED; the integration client may follow that behavior only for the explicit loopback endpoint and CA. Do not permit plaintext fallback, arbitrary redirects or environment proxy discovery. Bound timeouts and response size, validate JSON types, and redact credential paths from durable public reports. No private CA key is required merely to verify the server certificate.

Allow only these POST routes initially:

| Route | Request | Required handling |
| --- | --- | --- |
| get_version | empty object | exact reviewed 2.7.5 version; unknown version is not silently accepted |
| get_network_info | empty object | exact name/prefix/genesis; reject mainnet and mismatches |
| get_blockchain_state | empty object | non-null peak/hash/height, synced true and sync_mode false; record observation time |
| get_coin_record_by_name | explicit optional 32-byte coin ID | distinguish missing from malformed/error; recompute coin ID and check amount/parent/hash/spent state; no inference from address prefix alone |

Coin inspection must compare expected puzzle hash and amount when supplied. A probe without a coin can establish connection readiness only. Query chain state around coin lookup and record both observations; a changed peak or disagreement is not an atomic snapshot. Reorg/spend readiness must be checked again by later preparation/submission tools.

Use a versioned report with network expectation, node version, observed genesis/peak/sync state, optional coin record, timestamp, reviewed profile identity and explicit `validation: rpc-observation-only`. Include no signature, seed or credential content. Remove stale success before execution; publish only after all requested checks and resource cleanup. A failure report/status must never imply consensus approval.

TN-1 tests use local fake transport and isolated TLS fixtures: approved-route enforcement, wrong network/version/genesis, empty/unsynced state, malformed/oversized JSON, missing/spent/mismatched coins, timeout/redirect/TLS failure and stale-report invalidation. A separate TLS smoke exercises actual transport. No live endpoint is necessary for these development gates. Supply exact Windows/native LANDO commands when implementation exists.

## Funding and signing model

Use an operator-controlled test wallet for a deliberate funding transaction to the compiled puzzle hash. It is separate from the custom contract's owner key. Select a fresh dedicated BLS test owner, keeping secret material outside source, reports and the public fixture keys. Do not assume a standard wallet's message-signing RPC signs the raw AGG_SIG_ME message needed by this contract; its scheme/derivation must be reviewed before adoption.

The first integration path uses an offline signing request containing the exact puzzle/solution, coin, reviewed network domain, public key and expected conditions/outputs. The signer independently rebuilds the application message and full AGG_SIG_ME message, then returns a signature for explicit verification. TN-3 will specify secret-file permissions, key creation/import and encoding before implementation. Do not pass secrets as CLI arguments or store them in the prepared-spend artifact.

The first trial spends one funded fee-payment coin. Require operator-selected recipient/change hashes, positive input/payment and payment+fee<=input. Funding and spend fee budgets are separate. Re-read coin/network state before each reviewed transaction. Public-chain fee units are mojos; use decimal strings in integration artifacts. RPC integer values must retain exact precision.

Submission later uses push_tx and records bundle ID. Upstream SUCCESS may mean an already-present mempool bundle; PENDING is not confirmation. Confirmation requires exact input spend and expected children on the observed chain at a selected depth; a timeout or reorg must remain explicit. No automatic fee bump, replacement funding or signing retry is planned.

## Operator choices and next gate

Host selection is pending (LANDO in a separate environment, another dedicated host, or defer). TN-1 development can proceed using isolated fixtures; a real connection waits for explicit endpoint/certificate choices. No host setup commands are appropriate yet. Test-only key custody, wallet funding method, destinations, amounts, fee budget and confirmation depth remain operator choices for later slices; they do not block the read-only implementation.

TN-0 is documentation/source review only. Specification/link checks passed; no native Linux testing is required. Next: TN-1 read-only client and its isolated test matrix. This does not authorize contacting an existing farmer, funding a coin or submitting a public transaction. Live operations require their concrete reviewed inputs as specified by the selected plan.
