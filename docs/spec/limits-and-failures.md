# Built-in failures and resource limits

Audit baseline: compiler `0.1.0-m3.8b`, language `0.1`, ABI `1`. This records existing behavior; it introduces no new language rules, compiler limits or version changes. The exhaustive signatures remain in the [language specification](../language-v0.1.md#built-ins).

## Failure stages

| Stage | Example | Meaning |
| --- | --- | --- |
| Source checking | Wrong built-in argument type or arity; any call in CONST | Compile-time diagnostic; no VM execution |
| Fixed-value conversion | Negative JSON AMOUNT or invalid PUBLICKEY binding | E0301 before binding; no puzzle execution |
| Solution conversion | Wrong JSON shape, invalid typed value or host tree budget exceeded | E0300 before execution |
| Generated entry validation | Noncanonical INTEGER or invalid UTF-8 in raw solution | VM failure, E0500; unused declared fields are still validated |
| Evaluated built-in | Out-of-range U32BE, FIRST of an empty list, oversized AGG_SIG_ME message | VM failure, E0500, even if its result would be unused |
| VM cost | Evaluation exceeds the supplied cost budget | E0501 |
| Host result rendering | Completed VM result exceeds serialization/display budget | E0500; VM completion alone is insufficient for CLI success |

Earlier file-read or manifest-validation failures can prevent later stages from running. Diagnostic codes distinguish categories, not every underlying cause; exact wording is not the compatibility contract. See [CLI diagnostics](cli-v1.md) and [compatibility](experimental-compatibility.md).

Short-circuited operands and unselected branches do not evaluate their built-ins. Nevertheless, the compiler checks their syntax and types. Initialized locals and assignments evaluate eagerly; discarding or overwriting their result does not suppress a failure. This distinction is covered by [unsigned conversion tests](../../crates/compiler/tests/unsigned_bytes.rs), [short-circuit tests](../../crates/compiler/tests/short_circuit.rs) and [signature-condition tests](../../crates/compiler/tests/signature_conditions.rs).

## Signature and validation review

The documented byte/domain signatures agree with `byte_builtin`, payment signatures with `payment_builtin`, and collection operations with their contextual analysis in [expression lowering](../../crates/compiler/src/ir/expressions.rs) and [analysis](../../crates/compiler/src/analysis.rs). No signature correction was needed.

| Group | Important distinction | Representative evidence |
| --- | --- | --- |
| INT_BYTES / INT_FROM_BYTES | Minimal signed encoding; INT_FROM_BYTES rejects noncanonical encodings rather than normalizing them | [Integer encoding tests](../../crates/compiler/tests/integer_bytes.rs) |
| U32BE / U64BE | Fixed-width unsigned bytes; reject negative or oversized integers when evaluated | [Unsigned encoding tests](../../crates/compiler/tests/unsigned_bytes.rs) |
| STRING_FROM_UTF8 | Strict Unicode scalar validity, including when the result is unused | [UTF-8 validation](../../crates/compiler/tests/utf8_validation.rs) |
| AS_AMOUNT / AS_PUZZLEHASH / AS_PUBLICKEY | Range, exact length, or full canonical subgroup/non-infinity validation respectively | [Domain tests](../../crates/compiler/tests/domains.rs), [key tests](../../crates/compiler/tests/public_keys.rs) |
| FIRST / REST | Pair projection versus list head/tail; empty list fails | [Pair tests](../../crates/compiler/tests/pairs.rs), [list operations](../../crates/compiler/tests/list_operations.rs) |
| AGG_SIG_ME | Message lengths 0 through 1024 are accepted; 1025 fails at construction, including an unused result. Ordinary BYTES may be longer | [Signature-condition tests](../../crates/compiler/tests/signature_conditions.rs) |

ASSERT_HEIGHT_ABSOLUTE checks `0..2^32-1` while constructing its condition. ASSERT_MY_AMOUNT and CREATE_COIN accept typed AMOUNT values, including zero; a particular application may assert a positive amount separately. Constructing a condition neither emits it automatically nor establishes consensus acceptance.

## User-facing budgets

These are separate checks, not a single interchangeable size allowance. Passing one does not guarantee passing the others.

| Budget | Current limit | Source |
| --- | --- | --- |
| CLI source, binding, solution and manifest file reads | 1,048,576 bytes per file; raw solution hex counts text bytes | [CLI reader](../../crates/cli/src/main.rs) |
| Artifact binary / companion hex file | 1,048,576 / 2,097,153 bytes | [Artifact reader](../../crates/cli/src/artifact.rs) |
| Fixed fields / solution fields / function parameters | 32 each | [Parser](../../crates/compiler/src/syntax.rs) |
| Boundary type | Depth 32 from root depth zero; 1,024 nodes per field type | [ABI schemas](../../crates/compiler/src/abi.rs) |
| Boundary JSON | 1,048,576 bytes; container nesting 96 | [ABI conversion](../../crates/compiler/src/abi.rs) |
| Host-encoded fixed or solution list | 65,536 tree nodes including list structure; 1,048,576 serialized bytes | [ABI conversion](../../crates/compiler/src/abi.rs) |
| Program/solution decoding and result serialization | 1,048,576 bytes | [CLVM adapter](../../crates/compiler/src/clvm.rs) |
| Result display | 8,192 nodes; depth 512 from root depth zero | [CLVM adapter](../../crates/compiler/src/clvm.rs) |
| CLI execution cost | Default 10,000,000; explicit positive u64 | [CLI](../../crates/cli/src/main.rs) |

The compiler also has parser, analysis, type-construction and constant-work budgets. This table focuses on external data and execution; it is not an exhaustive list of internal compiler resource guards. INTEGER being arbitrary precision does not mean unbounded literal size, memory or evaluation cost.

The [list-boundary tests](../../crates/compiler/tests/list_boundaries.rs) explicitly distinguish the host node budget from generated runtime validation. File and artifact limits are exercised in [CLI tests](../../crates/cli/tests/commands.rs). Not every limit in this audit has a dedicated boundary test; source inspection and representative existing tests are identified rather than claiming exhaustive coverage.

## Audit outcome

The built-in signature table required no semantic changes. The ABI and CLI specifications were missing explicit host budgets and the fact that result rendering can fail after successful VM reduction; those details are now documented. No compiler behavior, frozen byte/hash/cost expectation or release asset changed.

## Language 0.2 loop budgets

The development compiler additionally enforces 256 syntactic FOR statements per body, shared IF/FOR depth 32, aggregate value counts across isolated bodies, and separate 65,536-node state/frame type budgets. There is no implicit runtime iteration cap or new runtime EMIT count cap. See [normative counted loops](../language-v0.2.md#counted-loops).
