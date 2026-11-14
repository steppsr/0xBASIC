# Experimental testnet operator walkthrough

Status: documentation-only consolidation after TN-4d4 passed Windows and native Linux. This describes the supported workflow; it is not a completed public trial or an instruction to send a transaction now. Start with the [host-readiness record](testnet-host-readiness.md). The released compiler/packages are unchanged.

Implementation revision: `1ee9791f7781ed7aa0372403fa7daad115e6dd3f`. All exact-revision CI passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43546684872), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43546684836), [packages](https://github.com/steppsr/0xBASIC/actions/runs/43546684881). The Linux gate confirmed 145 integration tests and the public/isolated CLI fixture matrices; full-node dispatch evidence is recorded in its linked gate.

## Keep the four environments distinct

| Environment | Role |
| --- | --- |
| Compiler checkout and built CLI | Build and independently validate the reviewed fee-payment contract |
| Pinned `.work/m4/venv` | Offline CLVM/signature calculations and integration commands; retains Chia 2.7.4/chia_rs 0.48.0 |
| Dedicated testnet node | Reviewed public baseline Chia 2.7.5/testnet11; explicit configuration, separate runtime/root and loopback mutual-TLS RPC |
| Linux signer vault | Test-only owner file under the account's native home, outside the checkout, share and reports |

The isolated full-node rehearsal is disposable and uses simulator constants. Passing it does not make a public node's effective configuration match the reviewed baseline. Never change the verifier's network identity merely to accept a different node.

## Workflow and records

Use a new local trial directory for each trial and new filenames for each attempt/history. Preserve original inputs unchanged. Choose actual values only after the host, destinations and budgets are reviewed.

| Step | Action | Evidence and prerequisite |
| --- | --- | --- |
| 1. Host readiness | Record dedicated runtime, version/dependencies, effective constants/configuration, explicit RPC endpoint and credential paths | Complete the [readiness record](testnet-host-readiness.md); no default node/root/keychain discovery |
| 2. Owner and destinations | Create or select a test-only owner through the protected Linux file boundary; identify recipient/change puzzle hashes | Follow [owner creation](testnet-owner-creation.md) and [file requirements](testnet-signer-keyfile.md). Never fund the repository's public fixture owner or destinations |
| 3. Bind and compile | Use reviewed `examples/payment-fee.bas` with the real test owner, recipient, change recipient and fixed input amount | Build with explicit bindings/out directory; retain manifest and all sibling program files. See [fee walkthrough](fee-payment-tutorial.md) |
| 4. Review funding | Review the exact compiled puzzle hash, funding amount, funding wallet method and separate funding fee | Funding is a separate transaction; no wallet funding command is implemented by the integration tools |
| 5. Observe funded coin | Use the [read-only probe](testnet-readonly.md) with explicit TLS settings and exact coin/puzzle/amount | Retain the actual funding coin ID and a fresh observation. A wallet display alone is not the preparation input |
| 6. Prepare | Run [offline preparation](testnet-preparation.md) on original artifacts, fresh observation and explicit solution/maximum fee | Save `preparation.json`; review payment, change, fee, owner, network, coin, conditions and signing message |
| 7. Review and sign | Run `sign_fee.py --review-only`, then a separate signing invocation with the reviewed preparation SHA-256 | Follow [approved signing](testnet-approved-signing.md). Signature response is independently verified before publication; signing sends nothing |
| 8. Review submission | Run `submit_fee.py --review-only` with the original inputs and detached response | Full preparation plus exact bundle ID/hashes; no sockets, key loading or attempt file. See [command forms](testnet-operator-submission.md) |
| 9. Explicit dispatch | After concrete transaction approval, invoke submit mode with the reviewed bundle ID, explicit TLS/bounds and a new attempt file | Fresh verification and node/coin checks repeat; preserve the attempt even on failure. A successful reply is not confirmation |
| 10. Observe confirmation | Run the read-only monitor with original signed inputs, explicit depth/bounds and optionally a new history file | Preserve final report and history; exact input/spend/children/anchor/depth checks establish the reported observation |

The fee solution has exactly `paymentAmount` and `feeAmount` as canonical decimal strings. The accounting is input = payment + change + fee for this single-input contract. RESERVE_FEE remains an aggregate minimum, not an arbitrary bundle-wide maximum. This workflow does not add companion inputs, select coins, estimate fees or replace spends.

## Freshness and interrupted work

Preparation, signing review and submission use fresh-observation checks (default 300 seconds, supported explicit maximum 3600). Plan the reviews before generating a fresh funded-coin observation. If a check expires, preserve existing evidence and regenerate the preparation from a fresh observation; re-review and produce a response bound to its new digest. Do not edit timestamps to make old evidence appear fresh.

Read-only confirmation and monitoring can revalidate historical signed expectations. That mode never authorizes signing or submission. A monitor run does not resume an attempt or broadcast anything.

| Observation | Required interpretation |
| --- | --- |
| Review completed | Offline verification only; nothing sent |
| `reply-success` or `reply-pending` | Historical node reply, not block confirmation |
| Unknown or intent-only attempt | Dispatch may have occurred; no automatic retry |
| Missing/incomplete attempt | Not proof that nothing reached a node; inspect the failure and observe independently |
| Monitor unspent/timeout | Not proof of rejection or absence from all mempools |
| Confirmed at selected depth | Current observation of exact spend/children/anchor; retain evidence and account for reorg risk |
| Reorg/conflicting spend | Preserve history and review; never silently resign, change fees or rebroadcast |

The public monitor does not currently query mempool membership. The isolated rehearsal's explicit duplicate submission and reorg resubmission are tests, not automatic operator recovery features.

## Trial evidence bundle

Keep the host baseline, source/binary/artifact hashes, bindings, solution, funding review and coin ID, original observations/preparations, reviewed digests, detached response, submission review, attempt records and monitor reports/history. Record actual commands, times, expected/observed outcomes and any errors. Keep signer secrets and RPC private certificate contents outside reports and source control. Signatures and coin IDs are public data but may still identify the trial.

After a completed trial, review what the evidence actually proves and update the operator documentation. A new downloadable release is a separate decision. No additional native test is required for this document alone; the linked executable gates retain their own exact test commands.
