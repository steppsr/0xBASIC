# Development status and roadmap

## Current checkpoint

M3-2 is complete. The M3-2 baseline was verified on Windows (197 Rust tests) and Linux (198 Rust tests, including a Unix-specific filesystem test). Independent conformance scripts also check artifact bytes, hashes, runtime results, and costs. This evidence covers compiler and local CLVM execution behavior, not consensus validation or a security audit.

The typed BASIC core supports scalar and collection values, local assignment, structured branches, pure nonrecursive functions, byte/string operations, and explicit condition emission. Contract boundaries currently accept only INTEGER fixed parameters and INTEGER solution inputs (up to 32 of each). Their JSON values are canonical decimal strings. Generated CLVM validates raw boundary values, including unused fields.

`check`, `build`, and `run` are implemented. `build --template-only` produces an unbound template. Bound artifacts distinguish the template hash from the puzzle hash. Only `ASSERT_HEIGHT_ABSOLUTE` is currently available as a condition constructor. No node, wallet, signing, or transaction submission integration is implemented.

The [language specification](language-v0.1.md), [ABI](spec/abi-v1.md), and [CLI specification](spec/cli-v1.md) include planned capabilities. Their status notes and this page distinguish those capabilities from the executable subset.

## Source keyword clarification

Compiler `0.1.0-m3.2.1` renames the solution-field declaration to `SOLUTION name AS type`. The former `INPUT` keyword is no longer accepted as a declaration. Contracts do not prompt, read a keyboard, or wait for user interaction. Fixed parameters are still declared in the contract header; solution fields are supplied by the spender.

Update older source declarations and rebuild artifacts with the current compiler. The ABI and generated boundary semantics are unchanged; manifests still require the matching compiler version. The README uses a fixed height-lock example without solution fields. Windows verification passes 199 Rust tests, including new keyword and README-example regressions.

## Roadmap

| Stage | Scope | Status |
| --- | --- | --- |
| M0 | Syntax, ABI, target profile, and independent vectors | Complete |
| M1 | Compiler-to-CLVM pipeline, artifact identity, CLI execution | Complete |
| M2 | Typed BASIC core, functions, bytes, strings, pairs, and lists | Complete |
| M3 | Contract boundaries, domain types, and condition constructors | In progress |
| First complete payment | Signature-authorized, exact-value payment with a height lock | Planned |
| Spend validation | Local simulator success and rejection scenarios, then testnet integration | Planned |
| Developer experience | Richer explanations, documentation, and potential educational editor tools | Future |

The next implementation slice is BOOLEAN and BYTES fixed parameters and inputs. Later slices add STRING and collection boundaries; AMOUNT, PUZZLEHASH, and PUBLICKEY domain types; and payment/signature condition constructors. Each slice must cover host conversion and hostile raw CLVM input, preserve reproducibility, and pass Windows/Linux checks before advancing.

The first complete payment example will bind the owner key, recipient, exact amount, and earliest height. It must require authorization, assert the coin amount, enforce the height lock, and create the intended payment. A local Chia simulator must demonstrate both accepted and rejected spends before testnet work. Wallet discovery, fee selection, and transaction submission are separate concerns.

Loops, user recursion, floating point, a language server, and an IDE are outside the current implementation scope. There is no version 1 release date yet.

## Verification

See [CONTRIBUTING](../CONTRIBUTING.md) for local commands. The [CI workflow](../.github/workflows/ci.yml) defines the full Windows/Linux check matrix. Default Python verifiers use the standard library; selected scripts also offer optional upstream-reference modes. Those modes require the separately documented reference dependencies and are not needed for normal builds.

Golden fixtures and synthetic signing vectors are public test data, never wallet credentials. VM execution results do not establish that a spend will be accepted by consensus.
