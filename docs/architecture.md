# 0xBASIC architecture

This describes the released `0.1.0-m3.8b` compiler and tooling; future extensions are identified explicitly. See the [current status](development.md) for implemented features and remaining milestones. The [language specification](language-v0.1.md) and [ABI](spec/abi-v1.md) define detailed syntax and encoding.

## Scope and intended experience

Write readable `.bas` contracts, check them locally, compile them directly to CLVM, inspect what they produce, and test actual spends. Preserve QuickBASIC's structured feel without aiming for QuickBASIC source compatibility. No line numbers, `GOTO`, runtime file access, or mutable global blockchain storage.

The initial deliverable is an experimental compiler and local development tool. It is not a wallet, node implementation, or general-purpose BASIC runtime. Production suitability requires evidence beyond completing the initial milestones.

## Components and flow

```text
Source text + build configuration
             |
     lexer / parser / source spans
             |
      syntax tree and diagnostics
             |
  name resolution / types / entry checks
             |
 functional IR: bindings, branches, calls,
 values, failures, condition accumulation
             |
       CLVM expression tree
             |
  serialization / tree hash / build manifest

CLI ------------------------> compiler library
Future editor --------------> compiler library
Local runner ---------------> upstream CLVM runtime
Spend scenario harness -----> upstream Chia validation / simulator
```

The compiler core accepts source and explicit configuration and returns artifacts or diagnostics. It does not read keys, contact nodes, submit transactions, or print directly to the terminal. The CLI owns filesystem operations and presentation. Network tools, when introduced later, remain separate from compilation.

The Cargo workspace contains the `oxbasic-compiler` library and `oxbasic-cli` executable. Compiler stages are modules rather than separate crates. Rust 1.95.0 and the dependency lock are pinned; see the [target profile](spec/target-profile.md).

Current repository layout:

```text
crates/
  compiler/src/   # syntax, analysis, IR, CLVM, ABI, diagnostics, explain
  compiler/tests/ # language/boundary/conformance integration tests
  cli/src/        # command handling and artifact validation
  cli/tests/      # command and diagnostic contract tests
simulator/        # isolated SpendSim/full-node harnesses and dependency locks
tools/            # conformance, tutorial, regression and package verifiers
examples/         # source programs and public binding fixtures
distribution/     # rebuild instructions and pinned upstream notices
docs/spec/        # specifications, schemas, evidence and tutorials
```

Do not create placeholder website, IDE, or book packages during the compiler MVP. A single repository is the working organizational default. The project uses the Apache-2.0 license.

## Front end and language model

The handwritten parser handles statements and expression precedence. Source spans refer to original source bytes. Comments and whitespace are consumed during lexing; AST inspection does not preserve them as nodes. Lossless formatting/editor support would require additional design. Reject lexical errors; never skip invalid source and emit a seemingly successful program.

Use case-insensitive names, explicit declarations, static types, and local inference where specified. Keep integers, booleans, bytes, strings, lists, and pairs distinct at the source level even where CLVM shares a representation. Integers are arbitrary precision. AMOUNT is a distinct, bounded type measured in mojos, with explicit INTEGER conversion. Floating point is unsupported.

Validate declarations, symbol resolution, type compatibility, definite assignment, return paths, and the placement of `EMIT`. Functions are pure and return values. Local reassignment is permitted; mutation through references and mutation of outer scope are excluded initially.

The first subset contains structured conditionals and nonrecursive function calls. Loops and recursion are unsupported; any future addition needs its own specification, cost model and conformance work. Their implementation is not promised by this release.

## Contract and function boundary

A contract has two distinct classes of values:

- **Fixed parameters:** bound into the puzzle by a deterministic binding operation. Changing these produces a different bound program and generally a different puzzle hash.
- **Solution inputs:** supplied by the spender, always treated as untrusted. The calling convention defines their order, representation, and exact input shape.

The compiler emits runtime validation for supported declared solution-input types by default. Host-side JSON validation alone is insufficient because someone can construct a raw solution independently. Domain types must validate the invariants their operations rely on; byte length alone does not establish every cryptographic invariant. [ABI 1](spec/abi-v1.md) defines the exact obligations and unsupported cases. Both fixed and solution fields are guarded, including unused fields.

Do not implicitly expose current height, coin ID, balance, or other chain state as ambient variables. Contract logic returns conditions to require facts about a spend; supplied context must be authenticated where it matters.

## EMIT semantics

`EMIT expression` requires one `CONDITION` value and appends it to the contract result in execution order. It does not perform a blockchain operation immediately. Only executed branches contribute conditions. A branch with no emission contributes zero elements, not an empty-list element.

Normal completion returns the accumulated proper list. Any failure aborts the puzzle evaluation; no partial result is returned. Explicit `RETURN` is reserved for functions in the initial subset, avoiding competing ways to produce a contract result. `EMIT` inside an ordinary function is a compile-time error. A pure function may construct and return a condition which its caller emits.

Internally, the compiler threads an immutable condition sequence through the functional IR. The backend may use reverse accumulation or another representation, but must preserve order and avoid repeatedly copying an ever-growing list. General list flattening is not implicit.

## Lowering and backend

Resolve every name before lowering. Translate local reassignment into fresh bindings. Branches explicitly carry values that are subsequently used, including condition accumulation. Unchosen branches must not execute or contribute failures. Preserve the specified evaluation and short-circuit rules during optimization.

Generate a CLVM expression tree directly, then serialize it with established ecosystem tooling. Chialisp source is not a required intermediate language. Use narrow adapters around upstream execution, serialization, tree hashing, and parameter-binding utilities. Do not implement a new VM or cryptographic primitives.

Begin with transparent, correct code generation. Add optimizations only alongside equivalence tests and measured size/cost results. Compiler implementation speed and on-chain execution cost are different measurements.

## Artifacts and reproducibility

A build writes binary and hex template files, bound puzzle files unless `--template-only` is selected, and `manifest.json`. `explain --stage clvm` supplies an inspectable representation without writing artifacts. The manifest records language/compiler version, target profile, source/dependency hashes, options, calling convention, parameter/input schemas, and the program tree hash.

Clearly distinguish an unbound template hash from a bound puzzle hash. Record fixed bindings and resulting identity separately. Never put timestamps or local absolute paths into deterministic program identity. Keep tooling metadata out of the on-chain program unless the calling convention explicitly requires it.

The same source, bindings, pinned toolchain/dependencies, and build configuration must reproduce the same program bytes across supported platforms. Cost reports refer to particular program/solution inputs and target rules; they are not universal cost guarantees.

## CLI and future editor boundary

Initial command families:

| Command | Responsibility |
| --- | --- |
| `check` | Parse and type-check with source diagnostics |
| `build` | Generate artifacts and optionally bind fixed parameters |
| `run` | Execute a compiled program locally with a solution and cost limit |
| `explain` | Inspect AST, checked IR or generated CLVM without executing it |

Exact flags, file extensions, diagnostics, and machine-readable output are specified in [CLI v1](spec/cli-v1.md). Compiler failure must return a failing process status and must not leave newly published success artifacts.

Keep the library independent of terminal and filesystem state. This permits a later language server or educational IDE to share analysis. WebAssembly remains a possible deployment target, not an MVP compatibility promise.

## Testing and platforms

Separate compiler tests, CLVM execution tests, and spend-validation tests. A VM result is not a verdict that a transaction is valid. Use independent reference programs and adversarial solutions as well as golden artifacts; do not rely only on snapshots generated by our own implementation.

Use native Windows and Linux in the initial CI matrix. Preserve macOS portability but verify it before advertising support. The Python SpendSim and full-node harnesses invoke the Rust CLI and consume its artifacts; Python is not a runtime dependency for compilation.

The first complete contract uses a fixed owner key, recipient, exact amount, and earliest height. It requires the coin's amount, requires authorization, enforces the height lock, and emits one payment. Signing-message encoding is specified and tested before implementing the example. Change, fee selection, wallet discovery, and transaction submission are outside its initial scope. See the [development plan](development.md) for acceptance tests.

## Upstream reference boundaries

[Chia's condition model](https://chialisp.com/conditions/) and [CLVM documentation](https://chialisp.com/clvm/) define the target behavior. M0 selected a [pinned target profile](spec/target-profile.md) and explicit execution flags. Do not treat a historical copied condition table as the authority for supported rules.

[Rue](https://github.com/rue-language/rue) informs stage boundaries and editor design. We are not adopting Rue's internals as a backend dependency or inheriting its source-language semantics.
