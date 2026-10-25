# Implemented language reference

Applies to compiler `0.1.0-m3.8b`, language `0.1`, ABI `1`. This page describes executable features. The [language specification](../language-v0.1.md) gives complete syntax and evaluation rules; the [compatibility policy](experimental-compatibility.md) explains experimental version changes.

## Program structure

One UTF-8 `.bas` file contains one `CONTRACT` and zero or more pure `FUNCTION` declarations. Names and keywords are ASCII case-insensitive; string contents are not. LF, CRLF and an initial UTF-8 BOM are supported. Apostrophe and `REM` introduce comments. There are no line numbers, interactive prompts, runtime file access or imports.

Contract-header parameters are fixed when building the bound puzzle. Initial `SOLUTION name AS type` declarations describe untrusted data supplied by a spender. Both are immutable; use initialized `DIM` locals for reassignment. `INPUT` is not a declaration. Generated guards check fixed/solution shapes and values even when unused. See [ABI 1](abi-v1.md) for exact encoding and JSON rules.

| Construct | Implemented behavior | Example |
| --- | --- | --- |
| `DIM`, assignment | Explicit type or inference from initializer; no later type widening | [Locals](../../examples/m2-functions.bas) |
| `CONST` | Compile-time values and supported operators/list literals; no function or built-in calls | [Strings](../../examples/m2-strings.bas) |
| `IF` / `ELSEIF` / `ELSE` | Structured multiline branches with strict BOOLEAN conditions | [Language rules](../language-v0.1.md#expressions-and-control-flow) |
| `ASSERT` | Abort local/on-chain CLVM evaluation when false | [Payment](../../examples/height-locked-payment.bas) |
| `FUNCTION`, `RETURN` | Typed parameters and result, pure nonrecursive calls, all normal paths return | [Functions](../../examples/m2-functions.bas) |
| `EMIT` | Append one CONDITION in execution order; functions can return a CONDITION but cannot emit | [Height lock](../../examples/height-lock.bas) |

Arithmetic supports INTEGER unary `+`/`-`, multiplication, addition and subtraction; ordering requires INTEGER. Equality supports matching scalar types, not collections or CONDITION. BOOLEAN `NOT`, `AND` and `OR` are strict; AND/OR short circuit. Arguments evaluate left-to-right. Branches skip unselected runtime work, but unreachable source is still checked.

## Types and external values

| Type | Meaning | Binding/solution JSON |
| --- | --- | --- |
| INTEGER | Arbitrary-precision signed integer within compiler/VM resource budgets | Canonical decimal string, e.g. `"100"` |
| BOOLEAN | Strict false/true | `false` or `true` |
| BYTES | Byte string preserving leading zeros | `{"hex":"00ff"}` |
| STRING | Strict Unicode scalar string, no normalization | JSON string |
| AMOUNT | Integer in `0..2^64-1`, distinct from INTEGER | Canonical decimal string |
| PUZZLEHASH | Exactly 32 bytes | `{"hex":"..."}` with 64 hex digits |
| PUBLICKEY | Canonical 48-byte BLS G1 subgroup point, excluding infinity | `{"hex":"..."}` with 96 hex digits |
| `PAIR OF (A, B)` | Typed pair | `{"first":valueA,"rest":valueB}` |
| `LIST OF T` | Proper homogeneous list, including nested lists/pairs | JSON array |
| CONDITION | Internal value from a condition constructor | Not allowed as a fixed parameter or solution field |

INTEGER and AMOUNT JSON values are strings, not JSON numbers. Conversion does not coerce wrong types or ignore extra fields. Duplicate and case-colliding field names fail. Empty lists need an expected element type. Fixed/solution schemas support recursively nested lists/pairs, up to 32 fields in each category; see development status and ABI documentation for resource/depth limits.

## Built-ins

| Group | Implemented functions |
| --- | --- |
| Bytes and hashing | `BYTE_LENGTH`, `CONCAT`, `SHA256` |
| Integer encodings | `INT_BYTES`, `INT_FROM_BYTES`, `U32BE`, `U64BE` |
| UTF-8 | `UTF8`, `STRING_FROM_UTF8` |
| Domain values | `AS_AMOUNT`, `AMOUNT_VALUE`, `AS_PUZZLEHASH`, `HASH_BYTES`, `AS_PUBLICKEY`, `KEY_BYTES` |
| Collections | `PAIR`, `FIRST`, `REST`, `CONS`, `LIST_LENGTH` |
| Conditions | `ASSERT_MY_AMOUNT`, `ASSERT_HEIGHT_ABSOLUTE`, `AGG_SIG_ME`, `CREATE_COIN` |

The [built-in signature table](../language-v0.1.md#built-ins) gives accepted types and failure rules. There are no implicit domain conversions. `FIRST`/`REST` fail on an empty list. `CREATE_COIN` has two arguments and no memos. `AGG_SIG_ME` preserves the application message, with a 1024-byte limit; it does not sign or append coin/network context. `PaymentMessage` in the tutorial source is an ordinary function, not a built-in.

## Commands and validation scope

`check` validates source; `build` writes a new artifact directory; `run` executes a bound artifact with a local cost limit; `explain --stage ast|ir|clvm` inspects it. A successful `run` is labeled `clvm-execution-only`. The compiler has no signing, wallet, RPC or submission commands. The separate Python harnesses test signing and confirmed spends using public test keys in isolated simulators. Follow the [payment tutorial](payment-tutorial.md) for the distinction and executable commands.

Not implemented: loops, user recursion, floating point, division/remainder, bitwise source operators, SUB, modules/imports, runtime I/O, a package manager, formatter/language server, wallet funding/key management, or testnet deployment. Validated simulator examples do not add those capabilities to the CLI.
