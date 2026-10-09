# Development status and roadmap

## Current checkpoint

M3-6b PUBLICKEY support is implemented in compiler `0.1.0-m3.6b`. M3-6a is complete on both platforms; the user confirmed all 234 Linux tests. M3-6b passed 240 Windows Rust tests, build, formatting and Clippy. All CI-listed Python verifiers passed, including the 59 PUBLICKEY cases and historical M3 modes with independent Python CLVM result/cost comparisons. The user confirmed all 241 Linux tests passed; M3-6b is complete on both platforms. Development is paused at the user’s request, with M3-7a next upon resumption. This evidence covers compiler and local CLVM execution behavior, not consensus validation or a security audit.

The typed BASIC core supports scalar and collection values, local assignment, structured branches, pure nonrecursive functions, byte/string operations, and explicit condition emission. Contract boundaries accept INTEGER, BOOLEAN, BYTES, STRING, AMOUNT, PUZZLEHASH, PUBLICKEY, and nested PAIR/LIST fixed parameters and solution fields (up to 32 of each). INTEGER JSON values are canonical decimal strings, BOOLEAN values are JSON booleans, and BYTES values are exact `{"hex":"..."}` objects. STRING values are JSON strings of Unicode scalars: unpaired surrogate escapes and malformed UTF-8 are rejected. Raw STRING atoms are validated by generated CLVM even when unused. Empty strings, NUL, BOM and noncharacters are preserved without Unicode normalization. Byte leading zeros are preserved; hex is normalized to lowercase. LIST values are JSON arrays of recursively typed elements; generated checks require proper list tails and validate every element. Host conversion allows at most 65,536 tree nodes per complete fixed/solution list, including collection spines and nil tails. This host budget is separate from VM execution limits. PAIR values are exact `{"first":valueA,"rest":valueB}` objects with recursively typed children. Duplicate keys, including inside pair and hex objects, are rejected. Schema depth is limited to 32, schema size to 1024 nodes per field, and host JSON nesting to 96 containers. Generated CLVM validates raw boundary values, including unused fields.

AMOUNT is a distinct type in `0..2^64-1`; PUZZLEHASH is a distinct 32-byte type. `AS_AMOUNT` and `AS_PUZZLEHASH` validate at runtime, while `AMOUNT_VALUE` and `HASH_BYTES` explicitly extract their underlying representations. Same-type equality is supported; arithmetic and ordering require INTEGER. Calls remain forbidden in CONST. JSON uses canonical decimal strings for AMOUNT and exact hex objects for PUZZLEHASH. Generated guards also enforce canonical amount atoms and hash length on unused raw fields, including nested collections.

PUBLICKEY requires a canonical 48-byte BLS G1 encoding, subgroup membership, and a non-infinity point. `AS_PUBLICKEY(BYTES)` validates; `KEY_BYTES(PUBLICKEY)` explicitly extracts its encoding. Checked host decoding and generated strict `point_add` validation reject invalid keys even when unused or nested. JSON uses exact hex objects. Public-key validation does not verify ownership or authorize a spend.

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

The next implementation slice is ASSERT_MY_AMOUNT and CREATE_COIN (M3-7a). AGG_SIG_ME follows in M3-7b. Each slice must cover host conversion and hostile raw CLVM input, preserve reproducibility, and pass Windows/Linux checks before advancing.

The first complete payment example will bind the owner key, recipient, exact amount, and earliest height. It must require authorization, assert the coin amount, enforce the height lock, and create the intended payment. A local Chia simulator must demonstrate both accepted and rejected spends before testnet work. Wallet discovery, fee selection, and transaction submission are separate concerns.

Loops, user recursion, floating point, a language server, and an IDE are outside the current implementation scope. There is no version 1 release date yet.

## Verification

See [CONTRIBUTING](../CONTRIBUTING.md) for local commands. The [CI workflow](../.github/workflows/ci.yml) defines the full Windows/Linux check matrix. Default Python verifiers use the standard library; selected scripts also offer optional upstream-reference modes. Those modes require the separately documented reference dependencies and are not needed for normal builds.

Golden fixtures and synthetic signing vectors are public test data, never wallet credentials. VM execution results do not establish that a spend will be accepted by consensus.
