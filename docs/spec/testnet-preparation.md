# TN-2: offline unsigned fee-payment preparation

Status: Windows passed the offline preparation matrix and integration tests; native LANDO passed, confirmed by the user on 2026-11-09. TN-1 is published at `61454a809094b27c1837d9e01d54a1ea0011ef4b`; its [compiler](https://github.com/steppsr/0xBASIC/actions/runs/42750888900), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/42750888864) and [package](https://github.com/steppsr/0xBASIC/actions/runs/42750888587) CI all passed. This continues the [selected plan](testnet-integration-plan.md) without requiring a host selection.

## Scope and inputs

`integration/prepare_fee.py` is an offline preparation tool specific to the reviewed `examples/payment-fee.bas`. It does not load private keys, verify a signature, contact a node or produce a submitted transaction. It uses the existing pinned simulator environment only for independent CLVM, coin and signing-message calculations; no simulator/node instance starts. The compiler and dependency locks remain unchanged.

Required arguments are `--binary`, `--manifest`, `--observation`, `--solution`, `--max-fee` and `--out`. The manifest must be named manifest.json and have its four sibling program files. The observation is a TN-1 JSON report with a coin; the solution contains exactly paymentAmount and feeAmount as canonical decimal strings. Maximum fee is an explicit mojo budget for this single contract spend, separate from a later funding transaction's fee. An optional `--max-observation-age` accepts 1..3600 seconds, default 300.

Observations must identify testnet11/txch and the reviewed genesis, node 2.7.5 and profile v2. Before/after peaks must match and report synced state; the coin must have a correct ID, positive uint64 amount, unspent state and valid confirmation fields. Future, stale and timezone-free timestamps fail. These are checks on a caller-supplied report, not authenticated chain proof. Editing or replaying a report cannot establish current coin availability. Recheck the real node before signing and submitting.

The CLI reader validates a temporary snapshot of the complete artifact and executes the supplied solution. Preparation also recompiles the LF-normalized, hash-pinned reviewed example with the manifest bindings and requires exact template/puzzle byte equality. This excludes an otherwise valid arbitrary contract or a copy without RESERVE_FEE. The observed coin's puzzle hash and amount must match the artifact and fixed input. All input files remain unchanged.

## Independent execution and signing request

The tool independently constructs the application message and ordered conditions. It executes the puzzle with testnet height-derived flags plus pinned MEMPOOL_MODE, verifies exact conditions against the oracle and CLI result, and checks coin identity using chia_rs. It derives the full AGG_SIG_ME message as application message plus actual coin ID plus the reviewed testnet domain, and compares it with upstream signing-pair extraction.

The local runner's VM cost and the independent network-flags VM cost are recorded separately. Neither is a full mempool/consensus cost or a fee estimate. Computing an expected signature message is not signature verification. Reservation is an additive minimum across a bundle; this tool describes only one spend and no companion inputs.

The existing pinned Chia 2.7.4 / chia_rs 0.48.0 environment is used, with the TN-0 reviewed testnet fork/domain overrides. The node/API baseline remains 2.7.5; this offline calculation does not attest a running node's effective constants. TN-4's real RPC rehearsal is still required before public submission.

## Preparation format

The version 1 JSON is a review artifact, not a push_tx request. In particular, coin/output amounts are decimal strings and there is no aggregate signature or submission-ready SpendBundle wrapper.

| Field group | Meaning |
| --- | --- |
| schema_version, validation | Version 1; offline-unsigned-fee-preparation |
| network, node_baseline, compiler_profile | Reviewed identity expectations |
| prepared_at, observation_time, observed_peak | Preparation and observation timestamps plus the recorded peak |
| bindings, solution_values | Validated fixed terms and the two spend-time amounts |
| input_sha256, source_sha256_lf | Digests of all five input artifact files, observation, solution, binary and reviewed normalized source |
| runtime | Pinned Chia/chia_rs, lock digest, height-derived flags and separately labeled VM costs |
| unsigned_coin_spend | Coin tuple/ID, serialized puzzle reveal and ordered two-field solution |
| conditions_hex, signing_request | Expected ordered conditions, public key, application message, network additional data and full signing message |
| expected_outputs, accounting | Exact child IDs/parents/hashes/amounts, payment/change/fee/reservation and operator maximum fee |
| scope flags | Untrusted observation, recheck required, signature_verified=false, mempool_validated=false, transactions_submitted=0 |

Input/output aliasing and output symlinks are rejected. A failed run invalidates a previous preparation at the chosen output path. Success is atomically replaced only after temporary artifact cleanup. No private material is included. The future signer must revalidate the complete request rather than blindly signing the displayed message.

## Windows verification

The final matrix covers 10 positive and 21 negative cases with synthetic observations; it never connects to a live node. Partial 600/fee10, exact990/fee10 and zero-fee1000 are checked at heights 3754999, 3755000 and 3924000, plus a changed-fee11 case. Independent messages, outputs, accounting and flags are checked. VM costs were 1518006/1514439/1514392 for partial/exact/zero on these selected cases; equality across the two runners is an observation, not a general guarantee.

Negatives cover wrong network/domain/version, stale/future/timezone-free observations, spent/missing/mismatched coins, inconsistent/unsynced peaks, false spend-validation claims, zero payment, overspend, fee budget, duplicate solution fields, old producer identity, corrupt program bytes and a valid compiled contract with its reservation removed. Actual CLI success followed by a failed rerun verifies stale-success removal. Temporary resources close before publishing `.work/testnet/preparation-windows.json` (Linux: preparation-linux.json). The verifier records final source/binary hashes and forbids socket bind/connect in its own process.

The standard-library integration suite now has 22 tests, including four new input/publication tests. Simulator CI runs the independent preparation matrix in its existing pinned environment and uploads the report. There is no dependency or compiler change. Existing packaging automatically includes the integration directory; package CI checks the resulting archives after publication.

## Native LANDO gate

This gate uses synthetic local observations and requires no actual testnet host, keys, certificates or funds. Use the existing isolated environment:

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
.work/m4/venv/bin/python integration/verify_preparation.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: 22 integration tests and 10 positive/21 negative preparation cases pass. Preserve `.work/testnet/preparation-linux.json`. No package, SpendSim or full-node rerun is needed for this slice: the source packager already includes integration files and its implementation is unchanged.

After native confirmation, commit/push and verify exact-revision CI, then continue automatically to TN-3's explicit signing boundary. Host/key custody choices are still pending for live operation; fixtures do not supply real credentials. Existing prerelease assets remain unchanged and no new publication is authorized.
