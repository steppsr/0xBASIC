# TN-3a: detached-signature verification and offline bundle assembly

Status: Windows passed 26 integration tests and 7 positive/26 negative detached-signature cases; native LANDO passed, confirmed on 2026-11-10. TN-2 is published at `97ae6a4e40d356c6e74fb53af26c149e17d24eda`, with [compiler](https://github.com/steppsr/0xBASIC/actions/runs/42752673479), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/42752673729) and [package](https://github.com/steppsr/0xBASIC/actions/runs/42752673495) CI passing. This is the first part of the [TN-3 signing boundary](testnet-integration-plan.md).

## Scope

`integration/verify_signed_fee.py` accepts a TN-2 preparation and an externally produced detached BLS signature response. It reloads the original artifacts, observation and solution, reruns the complete independent TN-2 preparation checks, verifies the signature, and assembles a one-coin SpendBundle for review. It never reads private keys, generates keys, calls a wallet, contacts a node or submits the bundle.

The supplied response is untrusted. Before cryptographic verification, the tool compares the entire original preparation against independently regenerated evidence. Only prepared_at varies during regeneration: the original value must be timezone-aware, no earlier than observation_time and no later than verification time. Every other field must match, with type-exact canonical JSON comparison so false cannot masquerade as 0. Observation freshness, input/binary hashes, fee budget, reviewed contract bytes, conditions and full signing message are checked again.

This does not independently authenticate the RPC observation or establish current spendability. Equal caller-supplied observations are not chain proof. TN-4 RPC rehearsal and a fresh node check remain necessary before public submission.

## Detached response format

Exactly these fields are accepted:

```json
{
  "schema_version": 1,
  "scheme": "AugSchemeMPL",
  "preparation_sha256": "<SHA-256 of the exact preparation file bytes>",
  "public_key": "<the request's lowercase 48-byte key hex>",
  "message": "<the request's exact lowercase full signing-message hex>",
  "signature": "<lowercase 96-byte signature hex, without 0x>"
}
```

The full signing message is the independently reconstructed application message followed by actual coin ID and the reviewed testnet11 additional-data domain. Signing only the application message, using another domain or key, or replaying a signature from another coin fails. The verifier uses pinned chia_rs AugSchemeMPL and checked G1/G2 decoding; infinity and invalid signatures fail.

The preparation hash associates a response with exact file bytes. The BLS signature authenticates the AGG_SIG_ME message, not that file hash or every report field. Do not describe this as a signature over the whole preparation document. A signer must independently review/reconstruct the request; merely copying a displayed message into an arbitrary wallet signing API is not a supported signing flow.

Private-key custody, test key creation/import, signer permissions and a concrete operator signing tool remain TN-3b decisions before live use. This slice verifies returned signatures and tests the protocol using public fixture scalars entirely in memory. It is not a production key-management implementation.

## Command and output

Use the existing pinned simulator Python environment, with the original inputs and an explicit maximum fee:

```text
python integration/verify_signed_fee.py --binary PATH_TO_COMPILER --manifest PATH_TO_MANIFEST --observation PATH_TO_OBSERVATION --solution PATH_TO_SOLUTION --preparation PATH_TO_PREPARATION --signature-response PATH_TO_RESPONSE --max-fee MOJOS --out PATH_TO_SIGNED_REVIEW
```

As in TN-2, --max-observation-age accepts 1..3600 seconds, default 300. Output/input aliases and output symlinks fail. Any previous success at the output path is removed before verification; success replaces it atomically only after validation and cleanup. Exit 0 means offline signature verification and assembly passed, exit 1 is a validation/runtime/file failure, exit 2 is argument usage failure.

The version 1 output contains the revalidated preparation, exact preparation/response digests, verification timestamp, network, upstream JSON `spend_bundle`, bundle ID and serialized byte SHA-256. It requires a successful upstream SpendBundle JSON round trip. Outer signature_verified is true; the nested original unsigned preparation retains its historical false value. mempool_validated remains false and transactions_submitted remains 0. No node admission, confirmation or key ownership beyond possession of a valid signature is claimed.

The nested spend_bundle is upstream serialization, including numeric coin amounts; downstream tools must preserve exact uint64 values when handling JSON. The outer object is a review record, not itself a push_tx request. A valid signed bundle can authorize a spend, so keep the exact reviewed bundle under operator control until deliberate submission. This tool provides no submission command.

## Validation

`integration/verify_signing.py` runs synthetic offline checks with the public example key (scalar 1), an alternate public test key (scalar 2), and no persisted secrets. Seven positive controls cover partial/exact/zero-fee bundles and freshly signed payment, fee, coin and recipient mutations. Each bundle round-trips through upstream JSON, its ID and serialized digest match, and the returned signature verifies against the request.

Twenty-six negatives cover ten preparation mutations (message, key, domain, output, fee, coin amount, flags, fixed recipient, solution and scope type); eleven response/signature mutations (file hash, key, message, scheme, extra fields, short/malformed/infinity signatures, wrong owner, wrong domain and application-message-only signing); four stale-signature mutations with freshly signed controls; and an actual CLI failure that removes its previous success report. Correctly signed tampered requests still fail preparation revalidation.

The standard-library integration suite has 26 methods, including four new response/publication tests. The independent signing matrix runs under the existing pinned environment in simulator CI and uploads `.work/testnet/signing-<platform>.json`. Its report includes complete positive fixture evidence, negative scenario names, binary/source hashes and cleanup/scope indicators. The verifier forbids socket bind/connect in its own process. The actual tool has no RPC or key-loader path.

## Native LANDO gate

This gate uses only public synthetic keys and local observations. No actual node, wallet or credentials are needed:

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
.work/m4/venv/bin/python integration/verify_signing.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: 26 integration tests, then 7 positive/26 negative detached-signature cases pass. Preserve `.work/testnet/signing-linux.json`. No package, SpendSim or full-node rerun is needed for this offline verifier slice; dependencies and existing compiler/preparer behavior are unchanged.

After native confirmation, commit/push and verify exact-revision CI. Continue through planning that needs no native testing. TN-3b must resolve an operator signing/key-custody path before live operation; a TN-4 isolated rehearsal can use explicit fixture keys without claiming that decision is complete. Existing releases remain unchanged.
