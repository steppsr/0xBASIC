# Documentation index

This index describes the experimental release `v0.1.0-m3.8b-experimental`: compiler `0.1.0-m3.8b`, language `0.1`, ABI `1`. The [release record](experimental-release.md) identifies the exact source revision, packages, tested hosts and CI evidence. Documentation on `main` may clarify the release; it does not change the already-published binaries or their tag.

## Choose a starting point

| Task | Read |
| --- | --- |
| Download and run the compiler | [Release record](experimental-release.md), then [package usage](package-usage.md) |
| Write and compile your first program | [Beginner walkthrough](first-program.md) |
| Learn the implemented language | [Implemented reference](implemented-reference.md) |
| Compile and inspect a payment contract | [Payment tutorial](payment-tutorial.md) |
| Supply fixed parameters or solution values | [ABI 1](abi-v1.md) |
| Integrate CLI output or read artifacts | [CLI, manifests and diagnostics](cli-v1.md) |
| Understand what artifact validation proves | [Manifest validation and diagnostic examples](manifest-validation.md) |
| Inspect, rebuild and compare artifact identities | [Artifact workflow](artifact-workflow.md) |
| Upgrade without confusing artifact identities | [Experimental compatibility](experimental-compatibility.md) |
| Understand conversion, execution and size-limit failures | [Built-in failures and resource limits](limits-and-failures.md) |
| Rebuild the distributed compiler or modify a dependency | [Source distribution](source-distribution.md) and [rebuild instructions](../../distribution/REBUILD.md) |
| Contribute to the compiler or run checks | [Architecture](../architecture.md) and [contribution guide](../../CONTRIBUTING.md) |
| Test signed spends in isolation | [Simulator guide](../../simulator/README.md) |

## Released contracts and supporting evidence

The following documents specify different parts of the interface. Examples and milestone reports illustrate them; historical plans do not add supported features. If documentation, implementation and tests disagree, record the discrepancy and resolve it explicitly rather than silently treating one as permission to change the released behavior.

| Contract | Specification | Implementation and representative checks |
| --- | --- | --- |
| Lexical rules, syntax, types and evaluation | [Language 0.1](../language-v0.1.md), [token grammar](grammar.ebnf) | [Syntax](../../crates/compiler/src/syntax.rs), [analysis](../../crates/compiler/src/analysis.rs), [core conformance](../../crates/compiler/tests/core_conformance.rs), [short-circuit checks](../../crates/compiler/tests/short_circuit.rs) |
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

The subsequent [semantic-analysis checkpoint](for-next-analysis.md) adds header/counter checks and typed state metadata. The [private executable kernel](for-next-kernel.md) begins VM validation; the [private contract-lowering bridge](for-next-source.md) now exercises source-level contract loops. The [function/return checkpoint](for-next-functions.md) adds calls and nested early returns behind the same private gate. The [emission/resource checkpoint](for-next-emissions.md) improves accumulation and records VM measurements. Adversarial boundary checks and public activation remain future work.

[M4 validation planning](m4-validation-plan.md), the [M5 work plan](m5-release-plan.md) and the original [M5 packaging checkpoint](m5-packaging.md) retain dated development history. Read their current-status notes before following old test handoffs. The [M5 release review](m5-release-review.md) records completion; the [development roadmap](../development.md) separates future work from the released interface.

Loops, user recursion, division/remainder, floating point, modules, a language server and wallet/network tooling remain outside this release. Future specifications need explicit semantics and validation criteria before implementation. No new language feature or version is selected by this documentation cleanup.
