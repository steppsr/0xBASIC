# M4-0: payment validation design

Status: design checkpoint, 2026-10-20. M3 is complete: Windows 274 and Linux 275 tests passed. Compiler remains `0.1.0-m3.8b`. No simulator was installed or executed by the original M4-0 checkpoint; implementation updates follow below. The [scenario matrix](m4-payment-scenarios.json) records expectations and explicitly marked implementation evidence; unmarked scenarios remain planned.

## Selected approach

Keep the [target profile](target-profile.md): Chia 2.7.4 at commit `98aba3d176b24b5814e84a33f9d1c11af67a9cdc`, `chia_rs==0.48.0`, Python 3.13. Use `SpendSim.managed` and `SimClient` from that exact source checkout, with upstream mempool/signature validation enabled. This is a separate Python integration harness consuming Rust CLI artifacts; compiler users do not acquire a Python runtime dependency. No new CLI signing or deployment command is proposed.

The cached source files for SpendSim, dependency manifest, constants and mempool manager were rechecked against [recorded SHA-256 evidence](upstream-evidence.json). This confirms reviewed source identity, not installation compatibility or fresh registry availability. M4-1 must resolve and lock the complete environment before executing scenarios; never substitute a newer upstream version silently.

A Rust-only consensus harness would require duplicating the selected coin-store/mempool lifecycle. A full-node simulator has broader coverage but more setup; retain it as a later smoke test before release, as already required by the target profile. SpendSim is the selected first implementation, not a claim of complete network/block validation.

## Environment and isolation

Use a dedicated project test environment, separate from the existing M0 reference packages (which use a different chia_rs). Keep the pinned checkout, environment, caches, scratch databases and reports under ignored project work directories. On Linux over Samba, use a native Linux checkout/environment; executable placement must follow the established Linux testing workflow. Any new external write location must be explicitly agreed before use. Never use existing mainnet/testnet roots, wallets, keychains or RPC endpoints.

M4-1 records exact Python patch version, source commit, resolved package versions and artifact hashes for Windows/Linux; an environment is not reproducibly pinned merely because top-level dependencies are pinned. Produce a reviewable lock/install recipe and smoke report. Verify that private test modules are present, `SpendSim.managed` opens/closes successfully, and one real farmed block yields observable records. Fail explicitly if packages, wheels, constants or APIs do not match. Dependency resolution/downloads are an environment task, not a compiler upgrade.

Use in-memory SpendSim state by default, one fresh instance per independent scenario. Close async resources reliably. Any persisted debugging database/report stays in project scratch space. Use only deterministic public test seeds; no real secrets. Installation may require network access; scenario execution must not contact a running node.

## Artifact-to-spend data flow

1. Build the existing height-locked payment example with deterministic test-key public key, recipient puzzle hash, A=1000 and H=10. Preserve the original M0 bindings/vector as a separate conformance check.
2. Read the generated puzzle bytes and recompute byte/tree hashes with upstream tools; compare them to the compiler manifest. Consume the bound puzzle, never the unbound template. Encode the empty solution as nil.
3. Farm simulator rewards to a test-only funding puzzle, then spend a funding coin to create the contract coin of exactly A and a separate change output. Confirm funding before payment. Do not insert fabricated contract records directly into CoinStore. Verify actual parent, puzzle hash, amount and coin ID through upstream coin APIs.
4. Independently construct the application message from the specified domain prefix, owner key, recipient, U64BE amount and U32BE height, then SHA-256 it. Compare with the emitted AGG_SIG_ME message. Never reuse M0's synthetic coin ID as the funded coin ID.
5. Sign `application_message || actual_coin_id || AGG_SIG_ME_ADDITIONAL_DATA` with upstream augmented BLS. Confirm upstream condition/signature-pair extraction agrees. Construct the CoinSpend and SpendBundle from actual coin, bound reveal, empty solution and signature. Never set DONT_VALIDATE_SIGNATURE or use CostLogger as the authorization oracle.
6. Submit through SimClient, inspect status and reason, then farm inclusion and query coin records/additions/removals. Mempool acceptance alone does not complete a positive scenario. Require the input spent and exactly the expected recipient child (parent is input coin ID, amount A, correct puzzle hash), with no unintended payment output. Funding/change coins are separate from this assertion.

Use a deterministic test-only recipient puzzle whose hash is known and which can be spent for the eventual lifecycle smoke. The original M0 recipient hash remains a condition-vector fixture; it need not provide a recipient reveal for simulator funding/payment tests. Funding and payment are separate bundles, so fee/change accounting cannot hide a contract payment error. Establish a valid zero-fee baseline under the isolated simulator policy before negative scenarios.

## Heights, domains and failure isolation

Retain DEFAULT_CONSTANTS activation heights. Use synthetic additional data `aa` repeated 32 bytes and derive the other six signature domains by upstream rules. Record constants and effective validation flags, rather than forcing local CLI flags onto the simulator.

Farm real blocks and inspect the actual mempool peak height passed to time-lock validation (distinct from its block record’s previous-transaction-height field). Exercise H-1, H and H+1; do not infer height solely from the number of farm calls or use a counter-only pass_blocks shortcut. If setup cannot reach the chosen H with valid funding, document and adjust fixture scheduling before interpreting outcomes. A premature spend may be pending; assert nonacceptance with the height-lock reason. After advancing, inspect whether it was promoted or resubmit only if needed.

Run signature failures at a valid height with valid coin/reveal/amount/solution. Each negative scenario changes one targeted property where possible. A changed fixed recipient changes the puzzle hash: testing a wrong reveal is different from funding a new variant and testing a stale signature. Capture actual upstream error names; don't invent numeric codes before the pinned harness runs. Rejections must preserve coin state and must not create outputs. Fresh positive controls distinguish fixture/setup failures from the intended rejection. Resubmission after confirmed spend must not create another output, regardless of exact rejection wording.

## Reporting and completion

Each scenario report records profile and upstream/environment identities, compiler version and source/artifact digests, bindings, actual coin IDs, context heights, effective constants/flags, expected and observed status/reason, and before/after coin records. Record local CLI VM cost separately from simulator spend/condition cost; they need not agree. Reports contain test data only and explicitly label SpendSim scope. Harness failures and skipped scenarios never count as passes.

| Checkpoint | Deliverable and completion gate |
| --- | --- |
| M4-1 | Isolated, fully locked environment and one-block smoke on Windows/Linux; no payment claim |
| M4-2 | Artifact loading, independent message derivation, test funding and one correctly signed confirmed payment |
| M4-3 | Height H-1/H/H+1 and missing/wrong/message-only/network-domain signatures |
| M4-4 | Cross-coin replay, confirmed double-spend, reveal/amount/solution/recipient variants and state invariants |
| M4-5 | Complete scenario report, reproducible reruns and CI integration on both platforms; document remaining full-node/testnet scope |

Split any row further if environment or API work requires it. M4 completion requires all planned scenarios with accepted/rejected state evidence on both platforms. Full-node simulator smoke remains a pre-release requirement; testnet, wallet integration and deployment stay separate later work.

## Primary references

- [Pinned SpendSim source](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/_tests/util/spend_sim.py).
- [Pinned dependency manifest](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/pyproject.toml).
- [Pinned mempool manager](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/full_node/mempool_manager.py).
- [Official simulator guide](https://docs.chia.net/guides/simulator-user-guide/) for the later full-node simulator route; it is not the installation recipe for this in-process harness.

## M4-1 implementation update

The [isolated setup](../../simulator/README.md) now installs the hash-locked 2.7.4 release distribution instead of an editable checkout. Its SpendSim, mempool-manager and constants files are byte-identical to the recorded commit evidence. Runtime locks are separate for Windows/Linux; source-package build tools are version-constrained from a separate lock. Windows Python 3.13.7 installation and one-block smoke passed, including a second clean offline installation. Linux resolution succeeded; execution remains pending. No spend/signature scenario is implemented yet. Compiler unchanged.

## M4-2 implementation update

User confirmed M4-1 Linux smoke success. The [payment harness](../../simulator/README.md) now completes test funding, independent artifact/message checks, actual-coin AGG_SIG_ME signing, mempool acceptance and exact inclusion/state checks. Two fresh Windows runs in separate environments produced identical reports. Linux payment validation is pending. Only `authorized-at-height` is exercised; all negative and replay scenarios remain planned. The pinned manager checks time locks against mempool peak height 10 in this positive case; its record's previous-transaction height is 9 and inclusion is 11. No compiler, ABI, dependency or source-language changes.

## M4-3 implementation update

User confirmed Linux smoke and M4-2 payment passed. `payment.py --suite` now runs seven fresh-simulator height/signature scenarios, checks exact rejection reasons and unmodified coin state, and confirms a correct payment after every negative attempt. Windows showed pending height rejection at peak9, automatic promotion at10, and signature failures at valid peak10. Both isolated Windows environments produced identical complete reports. Linux suite confirmation is pending. M4-4 replay and remaining mutation cases have not been implemented; no full-node consensus claim is made.

## M4-4 implementation update

User confirmed M4-3 Linux tests passed. The mutation harness implements all eight remaining planned cases in separate simulators, using confirmed funding, exact error checks, a subsequent farm to prove rejection has no delayed effect, and appropriate positive controls. Double-spend retains the existing output; malformed amount/zero-bound coins remain unspent while a separate valid coin proves the environment works. Windows replay/mutation runs in both isolated environments produced identical reports. The previous seven scenarios and smoke regressions passed. All 15 planned cases now have Windows evidence; Linux mutation confirmation and M4-5 evidence/CI integration remain pending. No compiler or dependency change.

## M4-4 platform confirmation and publication checkpoint

The user confirmed the Linux smoke, height/signature suite and mutation suite all passed. All 15 planned scenarios have now passed on both platforms. Earlier pending-status entries above describe their historical checkpoints and are superseded by this confirmation. M4-5 evidence audit, reproducible reporting and simulator CI integration are next and have not started. Publication includes the simulator harnesses and current documentation; local virtual environments, scratch reports, private handoff notes and unrelated artwork are excluded. Rust tests and compiler/dependency versions remain unchanged.

## M4-5 implementation checkpoint — 2026-10-24

The complete runner and Windows/Linux workflow are implemented; see [commands and evidence status](../../simulator/README.md#m4-5-complete-evidence-and-reproducible-runs). The aggregate requires all 15 cases, 12 exact rejections, 15 confirmed payments, current compiler/environment identities and identical complete reports from two fresh runs. It embeds detailed state evidence and source/binary digests. Failure invalidates prior aggregate success; negative reporting tests cover missing/duplicate cases, corrupt evidence, mixed environments, stale compiler, failed subprocess/preflight and differing reruns.

The saved Windows evidence passes the new audit and reporting tests pass. Fresh smoke passed, but restricted Windows execution denied access to the payment temporary directory; no aggregate success is claimed. Fresh Windows/Linux runner results and hosted CI are pending. M4 completion remains gated on those results; full-node simulator validation remains a pre-release requirement. No compiler or dependency changes.

## M4-5 native Linux confirmation

The user confirmed all native Linux testing passed, closing the Linux reporting/reproducibility gate. A Windows retry in the restricted session again passed smoke and failed at temporary-directory access before payment execution. Windows aggregate verification and hosted simulator CI remain pending; M4 is not complete. The next gate is the documented native Windows test/verification commands, followed by publication and verification of both hosted simulator jobs. This session has read-only access to `.git`, so publication requires a session with repository-write access.

## M4-5 Windows/Linux confirmation and publication checkpoint — 2026-10-24

The user confirmed all Windows and Linux testing passed, including reporting tests and complete aggregate verification. Both native reporting/reproducibility gates are closed, superseding the historical restricted Windows failures above. Publication is authorized; verify both hosted simulator jobs and compiler CI for the published commit before closing M4-5. Unrelated artwork and private local reports/notes are excluded. Compiler, dependency locks and Rust test counts are unchanged.
