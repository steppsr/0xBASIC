# TN-3b3: preparation-bound offline signing

Status: Windows passed 86 integration tests (19 Linux-only skips), approved-signer matrix 4 positive/10 negative, detached-signature regression 7 positive/26 negative and full RPC lifecycle regression with resources closed. Native LANDO passed, confirmed on 2026-11-12. TN-3b2 is published at `e135e09e4023a2eb8584c30f639eeabcdc7c6686`.

TN-3b2 exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43296025107), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43296024954), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43296024962).

This implements the next part of the selected protected-file signer. It creates a detached signature only after complete preparation revalidation and explicit approval of that preparation's exact byte digest. It does not fund, submit, observe a live node, create a key or configure LANDO.

## Review, then sign

`integration/sign_fee.py` requires the binary, manifest, observation, solution, preparation and maximum fee as explicit inputs. With `--review-only`, it independently regenerates the preparation using the existing public TN-2 checks, compares every field with the saved preparation except the recomputation timestamp, and prints the complete validated preparation plus `preparation_sha256`. Review mode accepts no key-file, output or approval argument and never opens a key. It works on Windows and Linux with the pinned runtime.

The complete review includes network and signing domain, owner public key, input coin, fixed destination bindings, solution values, expected children, input/payment/change/fee/reservation/budget, artifact/binary hashes and observation time. The operator must inspect those values before using the digest. Raw hex puzzle hashes are displayed without truncation; no address decoding or ownership claim is added.

Signing is a separate invocation with the same inputs and explicit `--key-file`, `--out` and `--approve-preparation-sha256` arguments. There is no automatic approval, default digest, stdin secret or generic message-signing option. Approval must be exactly 64 lowercase hex characters matching the saved preparation bytes. Even whitespace changes invalidate an earlier digest. Approval is an explicit operator-supplied value, not proof that a human actually read the review; scripts can supply it, so a program that automatically copies the digest bypasses the intended human review step.

The signing entry point refuses unsupported platforms before filesystem side effects. On Linux, after checking output paths and removing an old response, it repeats full preparation validation and verifies the approved digest. Only then does it load the protected key and match its public key to the independently checked owner binding. Public wrappers remain fixed to testnet11; no CLI network override or isolated identity option is added.

The signer signs only the regenerated full AGG_SIG_ME message with AugSchemeMPL. It stages the existing six-field TN-3a response in the output directory, invokes the detached verifier against the original inputs, and publishes the response by atomic replacement only if independent verification succeeds and its preparation digest still matches approval. TN-3a revalidates inputs again: a preparation changed after key loading cannot be published as a successful response. This is not an atomic snapshot of all files or chain state, and a signature may have been computed in memory before final verification fails.

## Output and failure boundaries

Outputs cannot equal an input, use an existing hard-link alias to an input, be a symlink, or lie inside the supplied key directory. Protected inputs include the owner file, compiler binary, source, observation, solution, preparation and artifact files. Invalid output aliases are rejected without deleting those inputs. After output validation, preparation/digest/key/verification failures leave no old success response. Staged files are removed on failure. Unsupported-platform refusal and argument errors occur before output invalidation; they do not certify an existing response as current.

The response contains schema version, AugSchemeMPL scheme, preparation digest, public key, full signing message and signature. It contains no secret bytes. Success means offline signing and detached verification only, never mempool acceptance or confirmation. The CLI denies socket connect/bind and prints generic failures without key paths or secret data. Existing protected-file and pinned-runtime limits still apply, including no guaranteed Python memory erasure or resistance to compromise of the owner account/root. Atomic response replacement does not establish power-loss durability or protection against a hostile output directory.

The common revalidation logic now lives behind `revalidate_preparation` (fixed public policy) and a private identity-aware helper in `verify_signed_fee.py`. Existing public and isolated verification behavior is preserved and regression-tested. The standalone command uses preflight's process-local Chia roots; do not embed it in a running node process.

## Validation evidence

Six new standard-library methods cover review without key access, missing/wrong approval before key access, failed preparation before key access, stale-response removal, output/hard-link/key-directory protection, platform refusal before mutation and CLI mode constraints. The complete integration suite has 86 tests; 19 underlying filesystem tests require Linux.

`verify_signer.py` verifies partial, exact and zero-fee signing plus a real review CLI subprocess. Ten rejection cases cover wrong/missing approval, changed raw preparation bytes, changed solution, approved-but-tampered preparation, stale observation, wrong domain, wrong owner, final verifier failure and preparation mutation after loading the key. Failure cases require no response or staged file to remain. Pre-key rejection cases assert no key loader call.

Windows exercises real cryptography with a public fixture loader and an explicit test-only platform mock; it does not claim protected Windows key loading. Linux exercises the actual protected loader against a disposable public fixture file in a temporary native-home vault. Neither test opens operator keys or contacts a live node. Reports `.work/testnet/signer-<platform>.json` include source/binary hashes, case names and scope flags; simulator CI runs the matrix and uploads these reports. Existing detached verification and isolated RPC regression cover the shared helper refactor.

## Native LANDO gate

Run as `steve`, without sudo. No real key/vault setup is needed:

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
.work/m4/venv/bin/python integration/verify_signer.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python integration/verify_signing.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/full_node_smoke.py --rpc --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **86 tests, no skips**, signer **4 positive/10 negative** with **native key loading=True**, detached verification **7 positive/26 negative**, and full RPC lifecycle PASS with resources closed. Preserve `.work/testnet/signer-linux.json`, `.work/testnet/signing-linux.json` and `.work/m5/full-node-rpc-linux.json`. After native success, commit/push, verify exact CI and review remaining host/baseline and operator submission/observation work before any public trial.
