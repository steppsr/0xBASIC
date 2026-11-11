# TN-4 exit review and next implementation boundaries

Review date: 2026-11-11. TN-4b7 Windows and native LANDO gates passed. Implementation revision: `e03519bd41b9413f0771d628b734c80014156e1e`. Exact-revision CI is recorded below. This review concerns the dedicated isolated rehearsal, not public-network deployment.

## Exit evidence

| Required behavior | Implemented evidence | Scope |
| --- | --- | --- |
| Fund exact compiled contracts | Real full-node funding through authenticated RPC; exact coin and funding-change checks | Fresh isolated node, temporary fixture keys |
| Prepare and verify signatures | Shared TN-2/TN-3a cores with actual pinned simulator constants; independent oracle compares bundles, messages and children | Partial and exact single-input controls; aggregate control uses the independent fee oracle |
| Reject wrong network, coin and signature | Fixed public/isolated identities; shared preparation mutations; real node wrong-amount and signature rejection | Public identity is never rewritten to match the simulator |
| Submit and inspect admission | Actual push_tx, exact mempool bundle comparison, duplicate submission checks | Harness-only mutating transport; no public submission CLI |
| Observe confirmed spend | RPC puzzle/solution, exact input/children, canonical block and depth, independent store comparison | Shared observer follows the partial-payment control; direct checks cover all five inputs |
| Preserve unaffected state | Rejected-spend state checks; funding change and unrelated inputs preserved | Deliberate isolated test transactions only |
| Report pending, timeout and reorg | Bounded pending attempts, actual alternate chain rollback, unchanged-bundle reconfirmation | No automatic resigning, replacement or fee bump |
| Preserve history and clean up | Nine atomic historical checkpoints; failure-path tests; full-node/RPC/keyring cleanup | History requires fresh validation and never authorizes automatic resume |

The isolated TN-4 exit gate is satisfied by these combined slices, subject to successful CI for the implementation revision. The baseline remains Chia 2.7.4 with reviewed simulator constants. The separate public baseline remains the dated TN-0 selection of Chia 2.7.5/testnet11; neither RPC identity nor this rehearsal proves a live node's effective constants, dependencies or binary integrity.

Windows and user-confirmed native coverage: 54 integration tests, 50 simulator tests, preparation 10 positive/21 negative, detached signing 7 positive/26 negative, full RPC lifecycle and original full-node payment regression (14 rejections/seven controls). The RPC bridge adds seven rejection cases for each of two controls. Zero-fee behavior is covered by the public offline matrices and existing SpendSim fee matrix; no zero-fee public relay guarantee is inferred. Conflicting-spend parsing is fixture coverage; actual chain replacement is full-node coverage.

## Remaining work before a public trial

1. **TN-3b signing design and implementation.** Select test-only owner-key custody, then implement and test that boundary. The existing verifier accepts detached responses but does not create or store private keys. The protected-file signer proposed below is not selected merely by this review.
2. **Dedicated host and baseline record.** Select the host and separate testnet root, explicit loopback endpoint and certificate paths. Record installed node/dependency versions and effective configuration against the reviewed baseline. Revisit upstream compatibility if that baseline changes. Run the read-only probe only after the endpoint is explicitly selected.
3. **Operator submission and observation tooling.** The rehearsal's push_tx adapter is not a public operator command. Specify and test an explicit single-bundle submission boundary that revalidates the detached result and fresh coin/network state, records intent/bundle identity and reports ambiguous transport outcomes without blind retry. Expose bounded confirmation observation separately. This executable work needs its own Windows/native gate before live use.
4. **Concrete trial manifest and funding review.** Record owner public key, artifact hashes, funding wallet method, exact puzzle hash/amount, recipient/change hashes, separate funding/spend fee budgets, required depth and timeout. Funding is a distinct transaction; observe its coin ID before preparing the spend. No real destinations or budgets are selected here.
5. **TN-5 and TN-6.** Review each concrete public transaction before sending, preserve funding/spend/confirmation evidence, then write the tested operator tutorial and review distribution scope. A new release remains a separate decision.

## Proposed TN-3b protected-file signer

The proposed first implementation is a dedicated offline process on a selected Ubuntu environment. It accepts explicit artifact, observation, solution and preparation paths, a test-only key-file path, maximum fee and output path. It does not discover wallets or keychains, call RPC, or take secret bytes as CLI arguments. It regenerates the complete preparation, compares it type-exactly, checks the owner's public key, presents full destinations/amounts/fee/network and the exact preparation digest for review, and signs only reviewed bytes. Output is the existing six-field detached response accepted by TN-3a.

Key creation would be a separate explicit operation using operating-system randomness, exclusive creation and restrictive owner-only permissions. Files must live outside the repository, synchronized share and reports. Specify encoding, symlink handling, regular-file/ownership/mode checks and failure cleanup before implementation. Filesystem permissions do not encrypt a key or protect against compromise of its account. Windows support would require a separately tested ACL design; POSIX mode bits are insufficient there.

Tests would use disposable keys and cover wrong owner, altered preparations/destinations/amounts/fees/domain, malformed encoding, unsafe ownership/modes, output/input aliases, stale success, denied sockets and independent verification of every produced response. No key is generated, imported or requested by this document. An identified external signer can replace this proposal after review of its raw AugSchemeMPL/AGG_SIG_ME behavior against the request contract.

## CI checkpoint

Implementation revision workflows: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43093774535), [isolated simulator](https://github.com/steppsr/0xBASIC/actions/runs/43093774330), [experimental packages](https://github.com/steppsr/0xBASIC/actions/runs/43093774334). Require successful completion of all three for the implementation gate. This documentation-only review passed specification/link checks and needs no additional native Linux run.

References: [selected plan](testnet-integration-plan.md), [dated network design](testnet-design.md), [detached verification](testnet-signing.md), [offline bridge](testnet-offline-pipeline.md), [historical observations](testnet-observation-history.md).
