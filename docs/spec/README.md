# Documentation index

Current development documentation targets compiler `0.3.0-alpha.1`, language `0.3`, ABI 1, profile `chia-clvm-0.19-strict-v2`. [RESERVE_FEE activation](reserve-fee-activation.md) adds a fee-reservation constructor alongside FOR/NEXT. Windows/native validation status is recorded there. The downloadable [counted-loop prerelease](loop-release-review.md) remains `0.2.0-alpha.1` / language `0.2` / profile v1; it does not support RESERVE_FEE. Historical checkpoints retain their original scope.

## Choose a starting point

| Task | Read |
| --- | --- |
| Download and run the compiler | [Release record](loop-release-review.md), then [package usage](package-usage.md) |
| Write and compile your first program | [Beginner walkthrough](first-program.md) |
| Learn the implemented language | [Implemented reference](implemented-reference.md) |
| Pay part of an input and return change | [Walkthrough](payment-change-tutorial.md), [milestone review](payment-change-review.md), [local example](payment-change-local.md), [SpendSim validation](payment-change-spendsim.md), [full-node validation](payment-change-full-node.md), [selected plan](payment-change-plan.md) |
| Add an authorized fee amount to a payment | [Fee-payment walkthrough](fee-payment-tutorial.md), [milestone review](fee-payment-review.md), [local verification](fee-payment-local.md), [signed SpendSim validation](fee-payment-spendsim.md), [full-node validation](fee-payment-full-node.md), [selected plan](fee-payment-plan.md) |
| Compile and inspect a payment contract | [Payment tutorial](payment-tutorial.md) |
| Supply fixed parameters or solution values | [ABI 1](abi-v1.md) |
| Integrate CLI output or read artifacts | [CLI, manifests and diagnostics](cli-v1.md) |
| Understand what artifact validation proves | [Manifest validation and diagnostic examples](manifest-validation.md) |
| Inspect, rebuild and compare artifact identities | [Artifact workflow](artifact-workflow.md) |
| Upgrade without confusing artifact identities | [Experimental compatibility](experimental-compatibility.md) |
| Understand conversion, execution and size-limit failures | [Built-in failures and resource limits](limits-and-failures.md) |
| Test loop packages and offline rebuilds | [Loop package checkpoint](loop-package-validation.md), [packaged loop walkthrough](package-loops.md) |
| Rebuild the distributed compiler or modify a dependency | [Source distribution](source-distribution.md) and [rebuild instructions](../../distribution/REBUILD.md) |
| Contribute to the compiler or run checks | [Architecture](../architecture.md) and [contribution guide](../../CONTRIBUTING.md) |
| Test signed spends in isolation | [Simulator guide](../../simulator/README.md), [loop payment validation](loop-payment-validation.md) |

## Released contracts and supporting evidence

The following documents specify different parts of the interface. Examples and milestone reports illustrate them; historical plans do not add supported features. If documentation, implementation and tests disagree, record the discrepancy and resolve it explicitly rather than silently treating one as permission to change the released behavior.

| Contract | Specification | Implementation and representative checks |
| --- | --- | --- |
| Lexical rules, syntax, types and evaluation | [Language 0.2](../language-v0.2.md), [token grammar](grammar.ebnf) | [Syntax](../../crates/compiler/src/syntax.rs), [analysis](../../crates/compiler/src/analysis.rs), [core conformance](../../crates/compiler/tests/core_conformance.rs), [short-circuit checks](../../crates/compiler/tests/short_circuit.rs) |
| Currying, external representations and entry validation | [ABI 1](abi-v1.md) | [ABI conversion](../../crates/compiler/src/abi.rs), [generated CLVM](../../crates/compiler/src/clvm.rs), [scalar](../../crates/compiler/tests/scalar_boundaries.rs), [pair](../../crates/compiler/tests/pair_boundaries.rs) and [list](../../crates/compiler/tests/list_boundaries.rs) checks |
| Commands, artifact integrity and diagnostics | [CLI v1](cli-v1.md), [manifest schema](manifest.schema.json), [compatibility](experimental-compatibility.md) | [CLI](../../crates/cli/src/main.rs), [artifact reader](../../crates/cli/src/artifact.rs), [command tests](../../crates/cli/tests/commands.rs), [diagnostic tests](../../crates/cli/tests/diagnostic_contract.rs) |
| Pinned execution rules and dependency identities | [Target profile](target-profile.md) | [Cargo lock](../../Cargo.lock), [toolchain](../../rust-toolchain.toml), [CLVM adapter](../../crates/compiler/src/clvm.rs) |

These links are representative, not a claim that a single test proves every clause. The grammar describes token syntax; semantic rules such as exactly one contract, boundary-type restrictions and nonrecursion are specified in the language/ABI documents and enforced separately. JSON schema validation alone also does not replace the artifact reader's path, digest and version checks.

## What validation establishes

- `check` checks source without binding or executing it. `explain --stage ast` only parses; `ir` adds analysis, and `clvm` adds code generation and optional binding. None executes a spend.
- `build` produces artifacts. `run` executes a bound puzzle locally and reports `clvm-execution-only`; it does not sign, submit or confirm a transaction.
- SpendSim tests exercise accepted/rejected signed spends with their recorded isolated constants. Full-node tests separately exercise block inclusion and exact coin changes. Neither is wallet/RPC integration or a production/network certification.
- Package tests verify source inventories, offline rebuilds, modified-library replacement and extracted CLI behavior. They certify the documented tested hosts, not every older OS or libc version.

See the [generated regression checks](m5-generated-checks.md), [tutorial](payment-tutorial.md), [simulator guide](../../simulator/README.md) and [release record](experimental-release.md) for the corresponding evidence. No new native testing is required merely to read or reorganize these documents.

## History and future work

The [FOR/NEXT design proposal](for-next-design.md) specifies the next counted-loop increment and its planned acceptance matrix. It is not part of the released grammar or executable feature set.

The [parser/AST checkpoint](for-next-parser.md) records the private test-only implementation boundary and exact native Linux verification commands. It does not enable loops in normal builds.

The subsequent [semantic-analysis checkpoint](for-next-analysis.md) adds header/counter checks and typed state metadata. The [private executable kernel](for-next-kernel.md) begins VM validation; the [private contract-lowering bridge](for-next-source.md) now exercises source-level contract loops. The [function/return checkpoint](for-next-functions.md) adds calls and nested early returns behind the same private gate. The [emission/resource checkpoint](for-next-emissions.md) improves accumulation and records VM measurements. The [depth/golden-fixture checkpoint](for-next-hardening.md) tests maximum nesting and pins cross-platform program expectations. The [public-activation compatibility plan](for-next-activation.md) selects compiler `0.2.0-alpha.1` / language `0.2` as future targets and specifies the migration and integration gates. The [public activation checkpoint](for-next-public.md) supersedes those private gates in the local development candidate.

[M4 validation planning](m4-validation-plan.md), the [M5 work plan](m5-release-plan.md) and the original [M5 packaging checkpoint](m5-packaging.md) retain dated development history. Read their current-status notes before following old test handoffs. The [M5 release review](m5-release-review.md) records completion; the [development roadmap](../development.md) separates future work from the released interface.

WHILE/DO loops, user recursion, division/remainder, floating point, modules, a language server and wallet/network tooling remain outside this release. Future specifications need explicit semantics and validation criteria before implementation. The activation candidate uses the selected identities; the current downloadable release remains unchanged.

Testnet integration is selected for future implementation: [plan](testnet-integration-plan.md), [TN-0 design and upstream audit](testnet-design.md). No live-node or public-spend capability is implemented by these documents.

[TN-1 read-only integration and native gate](testnet-readonly.md) documents the experimental probe and isolated tests.

[TN-2 offline unsigned fee preparation](testnet-preparation.md) documents the review format and native gate.

[TN-3a detached fee signatures](testnet-signing.md) defines offline verification and its native gate.
## Confirmation observation checkpoint

[TN-4a confirmation observations](testnet-confirmation.md) specifies exact spend/child checks, explicit depth, conflicting spends and reorg observations. This fixture-tested read-only function precedes full-node RPC rehearsal.

[TN-4b1 authenticated confirmation reads](testnet-confirmation-transport.md) connects those checks to explicit mutual-TLS transport and tests the full read sequence through a loopback fixture server.

[TN-4b2 full-node fee RPC rehearsal](testnet-full-node-rpc.md) validates actual isolated funding, rejection, duplicate submission, mempool and confirmed-spend RPC evidence.

[TN-4b3 real RPC depth and reorg checks](testnet-rpc-reorg.md) verifies actual chain rollback and distinguishes historical confirmations from current restored inputs and absent outputs.

[TN-4b4 bounded observation and reconfirmation](testnet-rpc-reconfirmation.md) tests pending timeout and recovery of the exact original bundles to a new confirmed inclusion.

[TN-4b5 saved observation history](testnet-observation-history.md) preserves atomic lifecycle checkpoints after interruption without treating historical observations as fresh validation.

[TN-4b6 fixed observation identities](testnet-observation-identity.md) connects shared confirmation logic to the real isolated node while keeping public-testnet defaults strict.

[TN-4b7 shared offline pipeline](testnet-offline-pipeline.md) connects preparation and detached-signature verification to actual isolated RPC submissions, with fixed consensus constants and independent fee-oracle comparisons.

[TN-4 exit review](testnet-rehearsal-review.md) maps isolated evidence to the plan and identifies signer, host and operator-tooling work before the public trial.

[TN-3b1 protected test-owner files](testnet-signer-keyfile.md) implements the Linux file-reading boundary for the selected offline signer direction, with a focused native LANDO gate.
