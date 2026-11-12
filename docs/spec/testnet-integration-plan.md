# Testnet integration: selected milestone

Current executable gate: [TN-3b2 exclusive owner-key creation and validation](testnet-owner-creation.md). Windows tests passed; native LANDO passed, confirmed on 2026-11-12. It remains separate from signing approval and live host setup.

Next executable slice: [TN-3b1 protected test-owner file boundary](testnet-signer-keyfile.md). The user selected the LANDO/separate-testnet and protected-file offline signer direction on 2026-11-12. Windows policy/refusal tests passed; native filesystem validation passed, confirmed on 2026-11-12. No node installation or real key creation has occurred.

Current position (2026-11-11): TN-4b7 passed Windows and native LANDO. The [TN-4 exit review](testnet-rehearsal-review.md) consolidates isolated coverage and remaining live-use work. Earlier slice descriptions below record what remained at each historical checkpoint; the consolidated review supersedes those outstanding-work lists.

Status: selected by the user on 2026-11-09 after the fee-payment milestone and approved 0.3 prerelease. [TN-0 design](testnet-design.md) selects testnet11/Chia2.7.5 and records the source audit; [TN-1 read-only integration](testnet-readonly.md) passed Windows and native LANDO, confirmed on 2026-11-09. This document defines work to review; it does not change compiler commands or authorize public transactions. The current compiler remains 0.3.0-alpha.1, language 0.3, ABI 1, profile chia-clvm-0.19-strict-v2.

## Objective

Demonstrate that a compiled fee-payment contract can be deliberately funded and spent on a selected Chia test network, with independently checked authorization, fees, outputs and confirmation evidence. Preserve the existing local compiler and isolated test harnesses. Start with a separate experimental integration tool so network operations and credentials do not become implicit behavior of `check`, `build`, `run` or `explain`.

The selected roadmap has completed isolated spend validation; public testnet integration remains future work. This proposal addresses that gap without adding language features or changing the existing payment contract.

## Decisions before implementation

| Decision | Required record |
| --- | --- |
| Network and node version | Verify the currently supported test network against official upstream sources, then record its identifier, genesis/signing domain, node version and relevant validation rules. No network name or current default is assumed here. |
| Target-profile applicability | Compare the compiler's pinned profile with the chosen network at the applicable activation height. Isolated test constants do not establish public-network compatibility. Resolve any differences before signing or sending. |
| Host and endpoint | Select a dedicated test environment and an explicit authenticated RPC endpoint. Do not discover or reuse JABBA's farming services or a default Chia root. |
| Key and funding model | Decide how an operator-controlled test-only key signs the custom contract and how a wallet funds its exact puzzle hash. The existing public deterministic fixture keys are unsuitable for public-network custody. |
| Destinations and budget | Identify test-only recipient/change destinations, maximum funding amount and fee budget in mojos. Record ownership/recovery expectations. |
| Confirmation policy | Choose the required depth and observation timeout explicitly; record how reorgs and dropped mempool entries affect status. |

TN-0 inspects pinned code and current official documentation, then records exact source references and endpoint assumptions. Any dependency change or new compiler/CLI behavior receives a separate compatibility decision. Existing released archives and target identities are not silently reinterpreted.

## Slices and exit gates

| Slice | Deliverable | Exit evidence |
| --- | --- | --- |
| TN-0 | Network/profile, RPC, signing and funding design | Reviewed upstream sources, explicit network/version selection, artifact schema and validation matrix; no credentials or network operations needed for the design |
| TN-1 | Read-only connection and coin inspection | Explicit endpoint/root; network mismatch rejection; synced peak and unspent coin observations; certificate/connection errors; bounded timeouts; no signing, funding or submission |
| TN-2 | Offline spend preparation | Load verified compiler artifacts; bind exact coin/puzzle/amount/network; construct unsigned spend and signing request; calculate expected outputs/reservation and reviewable fee summary |
| TN-3 | Explicit signing boundary | Test-only signing flow selected in TN-0; verify returned signatures against exact requested keys/messages; reject mutated coin, amount, destination, fee or network; no submission |
| TN-4 | Isolated end-to-end rehearsal | Fund, prepare, sign, submit and observe through the intended RPC interface in a dedicated isolated environment; reject wrong network/coin/signature; preserve prior state and verify cleanup |
| TN-5 | Operator-reviewed public testnet trial | Confirm exact network, funding/spend inputs, destinations and fee; fund and submit a concrete reviewed transaction; observe exact outputs, spend height and confirmation depth; report timeout/reorg truthfully |
| TN-6 | Tutorial, evidence review and distribution decision | Tested commands, redacted reproducible reports, limitations and package scope; separate approval for any new release |

TN-1 through TN-4 may be split further if credential handling, wallet funding or RPC lifecycle needs its own checkpoint. Windows validation precedes exact native LANDO commands for each executable slice. User-confirmed native success precedes commit/push and exact-revision CI. Documentation-only design needs no native test.

## Preparation and evidence contract

A prepared spend should identify source/binary/artifact hashes, compiler/language/profile, fixed bindings, ordered solution values, puzzle reveal, actual coin ID/parent/hash/amount, network signing domain, emitted conditions, signing messages, expected children and reservation totals. Record local VM cost separately from measured node cost and fees. Re-read relevant chain state before submission; preparation does not lock a coin or guarantee later acceptance.

The first public trial should be a single contract spend without unrelated companion inputs. Verify `input = recipient + change + fee` for that spend, and explain that RESERVE_FEE remains an additive aggregate minimum rather than an exact cap. Aggregated fee-offset behavior is already covered in isolated tests; it need not be introduced into the first public trial.

Funding and spending are separate transactions with separate confirmation evidence. Funding must create the exact compiled puzzle hash and amount. A successful RPC response or mempool admission is not block confirmation. Reports should distinguish prepared, signed, submitted, mempool-observed, confirmed, timed-out and reorged states. Retrying must identify the same bundle and must not silently create new spends or increase fees.

Keep reusable test credentials outside report and source artifacts. Reports may include public keys, coin IDs, bundle IDs and signatures, but never private keys, seed phrases or RPC private certificate contents. Tests use explicit temporary roots and test credentials; public-network operation is opt-in and separate from ordinary CI. A rejected or failed run must not leave an old success report presented as current.

## Validation matrix

| Case | Expected behavior |
| --- | --- |
| Missing/wrong endpoint or certificate | Clear error and no fallback to another node or default keychain |
| Wrong network/domain or unsupported profile | Refuse preparation/signing/submission before any transaction is sent |
| Unsynced node or stale/spent/mismatched coin | Report the observed state; refuse an invalid spend |
| Modified artifacts or mismatched producer identity | Apply the existing artifact integrity/compatibility checks |
| Changed payment, fee, coin or network after signing | Signature verification failure; no submission |
| Partial, exact and zero-fee solutions | Offline/isolated expected conditions, correct children and fee accounting; public trial scope selected separately |
| Duplicate submit or transient RPC failure | Record bundle ID and query status; do not manufacture a replacement spend |
| Mempool acceptance without confirmation | Remain unconfirmed; bounded observation cannot claim success |
| Confirmed spend | Exact removed input, child parents/hashes/amounts and confirmation/spend heights at the selected depth |
| Reorg or conflicting spend | Update report state and preserve evidence; no automatic resigning or fee change |

## Boundaries and direction choice

No mainnet operation, automatic wallet discovery, background daemon, fee estimator, general coin selector, production key custody, IDE or new language syntax is included. Any publicly submitted transaction is reviewed with its concrete network, inputs, destinations and amounts first. The plan itself does not grant that authorization.

Alternative next milestones are compiler/language extensions or developer tooling/diagnostics. The user selected testnet. TN-0 records the design and outstanding operator choices; begin TN-1 with isolated fixtures before connecting to a live node. Do not ask the user to rerun the completed fee-payment tests merely to begin this design.

[TN-2 offline preparation](testnet-preparation.md) is implemented; Windows and native LANDO passed, confirmed on 2026-11-09.

TN-3 is split into [TN-3a detached-signature verification](testnet-signing.md), Windows and native LANDO passed (confirmed 2026-11-10), and TN-3b operator signing/key-custody setup before live use. Fixture signing in isolated tests does not select a user key-management approach.

TN-4 is split into [TN-4a confirmation observation rules](testnet-confirmation.md), implemented with Windows validation passed and native LANDO passed (confirmed 2026-11-10), and TN-4b authenticated RPC wiring and isolated end-to-end full-node rehearsal. TN-4a uses synthetic RPC responses and does not complete the full-node exit gate. Isolated rehearsal can use public fixture keys while TN-3b live custody choices remain open.

TN-4b begins with [TN-4b1 authenticated confirmation reads](testnet-confirmation-transport.md), Windows and native LANDO passed (confirmed 2026-11-10). This real TLS/fixture gate precedes the TN-4b2 actual full-node RPC rehearsal described below.

[TN-4b2 isolated full-node fee RPC rehearsal](testnet-full-node-rpc.md) is now implemented and passed Windows, with native LANDO passed (confirmed 2026-11-10). It validates actual RPC submissions and confirmed fee records on the explicitly named pinned simulator network. Remaining TN-4 work includes bounded observation/reorg scenarios and an explicit isolated-identity policy for integrating the strict production preparation/confirmation pipeline; the full TN-4 exit gate is not yet complete.

[TN-4b3 real depth/reorg observation](testnet-rpc-reorg.md) passed Windows with native LANDO passed (confirmed 2026-11-11). It replaces actual fee-control blocks and verifies restored inputs/removed children through RPC and the coin store. Bounded polling/timeouts, reconfirmation and production-pipeline integration remain outstanding; the reorg milestone alone does not complete TN-4.

[TN-4b4 bounded observation and reconfirmation](testnet-rpc-reconfirmation.md) passed Windows with native LANDO passed (confirmed 2026-11-11). It verifies attempt-bounded pending timeout and exact original-bundle recovery to depth two after reorg. Durable incremental observation storage and production-pipeline/isolated-identity integration remain outstanding; TN-4 is not yet complete.

[TN-4b5 saved lifecycle observations](testnet-observation-history.md) passed Windows with native LANDO passed (confirmed 2026-11-11). It saves validated phase checkpoints atomically and treats all recovered history as requiring fresh chain validation, never automatic resubmission. Production-pipeline/isolated-identity integration remains the next TN-4 gap.

[TN-4b6 fixed observation identities](testnet-observation-identity.md) passed Windows with native LANDO passed (confirmed 2026-11-11). The real rehearsal now exercises shared confirmation checks under an explicit isolated identity while public defaults remain strict. The offline preparation/signature bridge is still outstanding.

[TN-4b7 shared offline pipeline](testnet-offline-pipeline.md) implements that bridge for partial and exact-payment controls. Windows passed 54 integration/50 simulator tests, both public matrices, the full RPC lifecycle and original payment regression; native LANDO passed, confirmed on 2026-11-11. After this gate, review the complete TN-4 exit criteria and the remaining live signer/host decisions before TN-5.
