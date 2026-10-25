# M5-0: experimental release readiness

Status: design checkpoint, 2026-10-24. M4 is complete. Native Windows/Linux reporting and reproducibility passed; compiler and simulator CI passed on `75002bbbd980966f41c1ac3913544ba991817a5f`. No additional M4 testing is needed. M5 implementation and release remain pending.

## Baseline and gaps

The compiler remains `0.1.0-m3.8b`; preserve the current ABI, puzzle bytes/hashes, dependency locks and 274 Windows / 275 Linux Rust test baseline. The existing compiler workflow covers format, lint, tests and conformance. The simulator workflow covers 15 SpendSim cases, 12 rejections and 15 confirmed payments per fresh run, with two identical runs and uploaded evidence.

The repository has source-build instructions, an Apache-2.0 LICENSE, detailed language/ABI/CLI specifications and targeted malformed-input/cost tests. These are useful existing assets, not substitutes for the following release gates:

| Slice | Deliverable | Exit evidence |
| --- | --- | --- |
| M5-1a | Isolated full-node environment and block-generation smoke | Pinned imports and dependencies; project-local roots, plots and test keys; real full blocks accepted; reward records observable; all resources close on Windows/Linux |
| M5-1b | Full-node compiled payment lifecycle | Fund contract through a confirmed spend, reject a premature or invalidly signed attempt, confirm valid payment and exact recipient output; record actual consensus constants, heights and state |
| M5-2 | Experimental compatibility and diagnostics policy | Document compiler/ABI/profile identities and rebuild rules; verify stable diagnostic codes, spans, JSON shape and exit status with representative CLI fixtures |
| M5-3 | Focused generated-input testing and regression budgets | Deterministic malformed parser/JSON/artifact/raw-boundary inputs finish without unresolved panic/hang; retain failing seeds; representative byte-size, hash and cost checks |
| M5-4 | Implemented-feature reference and payment tutorial | Reconcile specification status with executable subset; run all tutorial commands in temporary directories; explain compile/run versus signed spend validation |
| M5-5 | Windows/Linux experimental packages | Build with pinned toolchain/locks; archive executable, license and usage/version information; checksums; extract and smoke-test without a source checkout or Rust installation |
| M5-6 | Release review | All preceding evidence linked, limitations and ownership/attribution reviewed, exact release version selected; publish only after release authorization |

No release tag/version bump, dependency upgrade, new language feature or testnet transaction is part of M5-0. Implementation slices may be subdivided; preserve the established Windows-then-native-Linux checkpoint workflow. Packaging follows correctness/integration gates.

## M5-1a implementation contract

Use the existing Python 3.13.7 / Chia 2.7.4 / chia_rs 0.48.0 environment initially. Audit any newly imported simulator modules and extend recorded source hashes before relying on them. If additional dependencies are required, resolve and hash-lock them explicitly without changing the working SpendSim locks incidentally.

Use a fresh subprocess and `.work/m5` for node config, database, keys, certificates, plots, temporary files and reports. Set process-local roots before importing Chia because upstream default paths are resolved at import time. Verify resolved paths remain under the project. Pass an isolated test keychain explicitly; never rely on a default keychain. Configure only loopback listeners, disable discovery, external peers and UPnP, and close services on success and failure. Do not connect to the user's existing node, wallet or RPC service.

Source inspection of the installed pinned distribution found specific setup concerns:

- `simulator_test_tools.get_full_chia_simulator` creates a default `Keychain()` if none is supplied, adds a public test mnemonic, and starts a daemon and simulator service. It must not be called with its defaults.
- `block_tools.get_plot_dir` derives its cache from `DEFAULT_ROOT_PATH.parent`, independently of the explicit node root. In automated CI it also requires the plot directory to exist. Both plot and plot-temporary paths need explicit containment checks before plotting.
- `start_simulator.async_main` configures current-time blocks, uses upstream `test_constants`, and requests both original and v2 test plots. Do not copy SpendSim's constants or assert whole-report byte equality for full-node runs without assessing nondeterministic fields.

Select the narrowest upstream setup that preserves real full-block validation. The smoke must inspect an actual blockchain peak and confirmed reward records after farming enough transaction blocks, then demonstrate shutdown. Mere import success or a fabricated CoinStore record is insufficient. Report source/package identities, effective constants, plot configuration, peak/block hashes, reward records and cleanup outcome. Invalidate prior success before startup; write success only after all assertions and shutdown.

First implementation checkpoint: a standalone environment/block smoke, with its exact Windows result and native Linux command documented. Do not require the user to rerun M4 or the unchanged Rust suite for this Python-only slice. Linux execution becomes a gate only after a runnable, Windows-verified harness exists.

## M5-1b payment scope

Reuse the compiler-artifact and independent signing-message checks from M4 where applicable. Derive signatures from actual coin IDs and the full-node simulator's effective signature domain. Confirm funding and payment in real blocks, inspect additions/removals and recipient amount/puzzle hash, and prove the rejected attempt leaves state unchanged. Determine height scheduling from the real full-node validation context; do not transplant SpendSim's simplified height assumptions. Record local VM cost separately from consensus spend cost. The existing 15-case SpendSim suite stays the fast regression gate; this smoke adds full-node integration evidence, not network/testnet certification.

## Evidence and references

- [Successful simulator CI](https://github.com/steppsr/0xBASIC/actions/runs/40111434978), including both evidence artifacts.
- [Successful compiler CI](https://github.com/steppsr/0xBASIC/actions/runs/40111434985).
- M5 scope: installation and packaging, implemented-feature documentation, payment tutorial, diagnostics, compatibility policy, focused generated-input testing, and size/cost regressions.
- Pinned Chia sources: [simulator helpers](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/simulator/simulator_test_tools.py), [block tools](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/simulator/block_tools.py), [startup](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/simulator/start_simulator.py). Setup concerns above were inspected in the installed 2.7.4 distribution; new module hashes still require verification against the pinned source before execution.
- [Official simulator guide](https://docs.chia.net/guides/simulator-user-guide/) describes separate roots, ports and small test plots. Its interactive default-keychain setup is not this project's automation recipe.

## M5-1a Windows implementation checkpoint — 2026-10-24

The [full-node block smoke](../../simulator/README.md#m5-1a-full-node-environment-and-block-smoke) is implemented. Eight additional installed upstream files match the pinned commit. All 12 reporting/isolation tests and the final full-node Windows run passed: peak height 3, four confirmed recipient reward records, three k19 plots, no peer/RPC services started, and node/keyring cleanup verified. The implementation manages the full node directly and disables transport/discovery; it does not start the interactive simulator service or daemon. No package/compiler changes. Native Linux verification is the next gate; M5-1b payment work waits for that confirmation.

## M5-1a complete and M5-1b Windows checkpoint — 2026-10-24

User confirmed native Linux M5-1a testing passed. The [full-node payment harness](../../simulator/README.md#m5-1b-compiled-payment-through-the-full-node) now passes on Windows: confirmed funding, exact missing-signature rejection with state preserved across a block, and correctly signed payment confirmed with exact additions/removals and change preserved. All 12 reporting/isolation tests pass. The existing source pins, dependencies and compiler are unchanged. Native Linux M5-1b is the next gate; exact refresh/test commands are in the simulator guide. After confirmation, proceed to M5-2 compatibility/diagnostic policy.

## M5-1b complete; M5-2 compatibility checkpoint — 2026-10-24

The user confirmed the M5-1b Linux gate by authorizing the next step. Full-node funding, invalid-signature rejection and confirmed payment now pass on both platforms. M5-2 adds the [experimental compatibility/diagnostics policy](experimental-compatibility.md) and three CLI integration tests covering Unicode source positions, human/JSON streams, error categories, version identities and success output. This is a documentation/test-only change; compiler version, semantics, artifact bytes and dependencies remain unchanged. Native Linux M5-2 commands and expected counts are in that policy. Next after Linux confirmation: M5-3 focused generated-input testing and cost/size regressions.

## M5-2 complete; M5-3 Windows checkpoint — 2026-10-24

User confirmed native Linux M5-2 tests passed. M5-3 adds the [fixed-seed generated-input verifier and frozen size/cost baselines](m5-generated-checks.md), plus a compiler CI step. Windows passed all 653 CLI invocations, covering source mutations, arithmetic controls, JSON/raw boundaries, damaged manifests and three exact byte/hash/cost/output baselines. No crashes or timeouts were found. No compiler or dependency change; Rust totals remain277Windows/278Linux. Native Linux M5-3 is the next gate; exact refresh/test commands are in that checkpoint.

## M5-3 complete; M5-4 Windows checkpoint — 2026-10-24

User confirmed all native Linux M5-3 checks passed. M5-4 adds an [implemented-feature reference](implemented-reference.md), a [payment tutorial with exact Linux verification commands](payment-tutorial.md), and tools/verify_tutorial.py. The verifier executes the nine marked command blocks directly from the tutorial in isolated scratch space and checks artifact identity, original payment conditions, costs, intended failures and non-overwrite behavior. Windows passed all nine commands and assertions. README/language status was reconciled; no compiler/source fixture/dependency changes. Native Linux M5-4 is next; after confirmation proceed M5-5 experimental packaging.

## M5-4 complete; M5-5 Windows packaging checkpoint — 2026-10-24

User confirmed native Linux M5-4 passed. M5-5 adds [native experimental packaging and exact Linux commands](m5-packaging.md). Windows release build/archive and standalone extracted smoke passed eight commands with an empty PATH; three archive-integrity rejection tests passed. The package workflow builds both platforms and verifies downloads in separate jobs without compiler source checkouts. Native Linux package/permissions/runtime validation and first hosted workflow are pending. No release/tag published. After Linux confirmation, M5-6 reviews evidence, compatibility/runtime scope, dependency attribution and publication readiness.

## M5-5 complete; M5-6 release review open — 2026-10-24

User confirmed all native Linux package checks passed. The [release review](m5-release-review.md) records complete native evidence and outstanding distribution/hosted-CI gates. Locked dependency inventory contains124Windows/125Linux normal/build packages, including three Malachite0.9.2 crates declaring LGPL-3.0-only. Candidate archives currently contain only the project license; distribution/attribution review is unresolved. Full-node payment was added to simulator CI, but no workflow has been pushed/dispatched for these M5 changes. No additional native testing requested now; no release or package-distribution clearance claimed.

## M5-6a source-inclusive package — Windows passed, Linux pending

The [source distribution checkpoint](source-distribution.md) implements the pinned-runtime source/rebuild strategy: 134 vendored crates, authoritative upstream notices, source hashes and rebuild instructions. Windows passed four rejection tests, 8,969 source-file checks, two offline builds including a modified library, and eight extracted CLI checks in both builder and standalone verification. Native Linux packaging is next; exact commands are in that checkpoint. Compiler/dependency versions are unchanged. Final review, publication and hosted CI remain pending; no release authorization is implied.

## M5-6a native gates complete — 2026-10-24

User confirmed native Linux source-inclusive packaging passed, including the offline original/modified-library builds and extracted checks. Both native gates are complete. Proceed with publishing the reviewed M5 source and checking all three hosted workflows on that exact revision. No further manual native testing is required for the documentation checkpoint. Final tagged-release naming, ownership records and authorization remain open.
