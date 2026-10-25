# 0xBASIC ABI 1

Status: normative ABI for released compiler `0.1.0-m3.8b`. Language `0.1`, ABI `1`; the original M0 calling convention remains unchanged. Runtime tree values, serialized bytes, and JSON are distinct representations.

## Calling convention

Let P be the unbound template, F the proper list of fixed values in header order, and S the proper list of solution values in SOLUTION order. The template environment is the dotted pair `(F . S)`. Generated entry validation checks both lists, exact arity, and all types before the body.

The bound puzzle is ordinary CLVM currying of **one** argument, the list F:

```text
B = (a (q . P) (c (q . F) 1))
```

Numeric opcodes: a=2, q=1, c=4. Bare atom 1 selects the solution environment. Running B with S runs P with `(F . S)`. Retain the wrapper even for zero fixed parameters, where F is empty. No wrapper removal optimization in 0.1.

Fixed values cannot be overridden through S; extra arguments fail. Zero inputs require the empty atom, serialized `80`. An empty solution is not a missing file. The template is a development artifact; the bound puzzle hash identifies the contract coin.

## Tree values and validation

| Type | Representation/check |
| --- | --- |
| INTEGER | Shortest signed two's-complement big-endian atom; zero is empty |
| BOOLEAN | Empty atom false, atom `01` true; reject other atoms/pairs |
| BYTES | Any atom, preserving leading zeros |
| STRING | Strictly valid UTF-8 atom, without normalization |
| LIST OF T | Proper list of recursively checked T, ending in empty atom |
| PAIR OF (A, B) | Cons cell with recursively checked left/right values |
| PUZZLEHASH | Exactly 32-byte atom |
| PUBLICKEY | 48-byte canonical subgroup-valid non-infinity BLS G1 atom |
| AMOUNT | Canonical INTEGER in `0..2^64-1` |
| CONDITION | Internal constructor-produced proper list; forbidden externally |

For INTEGER, reject nonempty `00`. At length >1, reject leading `00` when the next byte's high bit is zero, and leading `ff` when the next high bit is one. Examples of **atom contents**: 127=`7f`, 128=`0080`, -128=`80`, -129=`ff7f`. Arithmetic and integer-to-byte conversion also produce canonical values.

UTF-8 rejects isolated continuations, truncation, overlong encodings, surrogates, and values above U+10FFFF. Allowed sequences: ASCII `00..7f`; `c2..df 80..bf`; `e0 a0..bf 80..bf`; `e1..ec` or `ee..ef` plus two continuations; `ed 80..9f 80..bf`; `f0 90..bf` plus two continuations; `f1..f3` plus three continuations; `f4 80..8f` plus two continuations. Continuations are `80..bf`. External string NUL is valid although source NUL is forbidden.

PUBLICKEY validation cannot rely on length or a signature condition eventually being emitted. Fixed-binding conversion uses checked upstream G1 decoding and rejects infinity. Runtime validation can use strict `point_add` with one argument, compare canonical output with the input, and reject compressed infinity (`c0` then 47 zero bytes). This forces checked upstream decoding; do not substitute relaxed negate. Preserve validation for unused inputs. Execute negative-key cases before claiming the type is implemented.

Cost/allocation limits can reject very large otherwise valid values. Validation costs are included in execution cost. Correctness of generated checks must not depend on optional runner flags.

## Serialization

Use traditional uncompressed CLVM serialization: `ff` introduces a pair; empty atom is `80`; one-byte atoms below `80` encode directly; other atoms use the standard minimal length prefix. Use upstream serialization adapters. No backreferences or 2026 format in ABI 1.

Tooling readers require exactly one complete tree, no trailing bytes, and canonical serialization: deserialize, reserialize in the selected format, require equality. This artifact rule is distinct from emitted runtime value checks; a puzzle sees tree values, not original serialized bytes.

Tree hash: atom `H(01 || bytes)`; pair `H(02 || leftHash || rightHash)`; H is SHA-256. SHA-256 of serialized bytes is a separate integrity digest, not the puzzle hash.

## JSON interchange

Bindings/solutions are objects keyed by case-insensitive source names. Reject duplicate keys, case-fold collisions, extra/missing fields, and wrong shapes. Order comes from source declarations, not JSON.

| Type | JSON |
| --- | --- |
| INTEGER / AMOUNT | Decimal string matching `0|-?[1-9][0-9]*`; AMOUNT also nonnegative/in range |
| BOOLEAN | JSON boolean |
| BYTES / PUZZLEHASH / PUBLICKEY | Exactly `{"hex":"..."}`, even-length hex, no prefix; normalize lowercase |
| STRING | String of Unicode scalars; reject unpaired surrogate escapes |
| LIST OF T | Array of T |
| PAIR OF (A, B) | Exactly `{"first":valueA,"rest":valueB}` |

JSON numbers are not language integers. Default `{}` bindings/solution work only for zero corresponding fields. Raw `--solution-hex` bypasses JSON conversion, not runtime checks. [CLI and artifact rules](cli-v1.md) define schemas.

## Payment authorization

The [example](../../examples/height-locked-payment.bas) fixes a valid owner key, recipient, positive exact amount, and height in `0..2^32-1`. Application preimage:

```text
UTF8("0xBASIC/payment/v1") || 00 ||
owner[48] || recipient[32] || U64BE(amount)[8] || U32BE(earliestHeight)[4]
```

This is 111 bytes. Integers here are fixed-width unsigned, not CLVM integer encoding. M is SHA-256 of this preimage; the contract emits `(50 owner M)`.

Calculate the spent coin ID with the upstream Coin implementation (parent ID, bound puzzle hash, canonical signed atom encoding of amount). The final augmented-BLS message is:

```text
M[32] || spentCoinID[32] || AGG_SIG_ME_ADDITIONAL_DATA[32]
```

Use the explicit network/simulator consensus constant; do not assume it equals a generic genesis challenge. Pass these 96 bytes to upstream augmented BLS signing, which applies scheme-specific augmentation. No keys/signatures go in the source, bindings, or solution. A changed network domain, coin, or payment term invalidates the corresponding authorization.

[Vectors](vectors.json) include a deliberately public test secret scalar 1, synthetic coin puzzle hash, application hash, final message, and reference signature. These check encoding/signing, not compiled 0xBASIC output. Spend tests later use the actual compiled bound puzzle hash.

Height condition: `previous_transaction_block_height >= earliestHeight`. Simulator tests record this context, reject H-1, accept H, then farm and check the output. This does not promise inclusion in block H.

Pinned upstream sources for these rules are in [the target profile](target-profile.md). The ABI intentionally imposes stricter types/encodings than raw CLVM.
