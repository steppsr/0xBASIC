# 0xBASIC 0.1 language specification

Status: historical normative 0.1 language rules, reconciled with compiler `0.1.0-m3.8b` at M5-4. This document describes the historical release. The [current implemented-feature reference](spec/implemented-reference.md) and [language 0.2](language-v0.2.md) describe newer development behavior. Changes require a recorded decision and corresponding conformance cases. Complete syntax: [grammar.ebnf](spec/grammar-v0.1.ebnf). External representations: [ABI 1](spec/abi-v1.md).

## Program and lexical rules

A compilation unit is one UTF-8 `.bas` file containing exactly one named contract and zero or more functions, in any order. No top-level executable statements, imports, overloading, or multiple contracts. All function signatures are visible throughout the file. Direct and indirect recursion are compile-time errors in 0.1.

Accept LF and CRLF and a final line without newline. An initial UTF-8 BOM is ignored for tokenization; source byte offsets still refer to the original file. Lone CR, invalid UTF-8, and embedded NUL source characters are errors. Keywords and identifiers use ASCII case-insensitive matching; strings remain unchanged. Identifiers match `[A-Za-z][A-Za-z0-9_]*`. There are no line numbers.

Spaces/tabs separate tokens. Newline ends a statement unless inside parentheses or square brackets, where it is whitespace. Delimiters must balance. Blank and comment-only lines are allowed between statements. No colon separators, underscore continuation, or single-line IF in 0.1.

An apostrophe starts a comment outside a string. The identifier-delimited token `REM`, case-insensitive, also starts a comment to the physical line end. `remember` is an identifier. Comments end even within continued statements. Structural keywords are reserved; built-in callable names cannot be redefined or shadowed.

Literals:

- Decimal integer: `0` or a nonzero digit followed by digits. No separators, exponent, leading zeros, or floating point. Negative values use unary minus.
- Hex integer: `&H` followed by at least one hex digit, case-insensitive prefix; leading zeros allowed. Nonnegative before unary operators.
- Bytes: `0x` followed by an even number of hex digits, case-insensitive prefix. Bare `0x` is empty bytes. Leading zeros are significant. Reject invalid contiguous literals rather than splitting off valid prefixes.
- String: double-quoted UTF-8 text; doubled quotes inside encode one quote. Backslash is literal, not an escape. Physical newlines are forbidden. No Unicode normalization.
- `TRUE` and `FALSE` are booleans. No untyped `NIL`; `[]` is an empty list requiring an expected element type.

## Contracts, inputs, and functions

```basic
CONTRACT MinimumPayment(recipient AS PUZZLEHASH)
    SOLUTION requested AS INTEGER
    ASSERT requested > 0
    EMIT CREATE_COIN(recipient, AS_AMOUNT(requested))
END CONTRACT
```

This illustrates inputs, not an ownership-secured contract. Contract-header parameters are fixed bindings. `SOLUTION name AS type` declarations occur only at the start of a contract, before executable statements, and name untrusted solution fields in declaration order. `SOLUTION` is a declaration of spend-supplied data, not an interactive operation. The former `INPUT` declaration spelling is no longer accepted. Generated entry code validates the entire input shape and every value before the body, even for unused inputs. Fixed parameters are immutable within source.

```basic
FUNCTION AddExtra(value AS INTEGER, enabled AS BOOLEAN) AS INTEGER
    DIM total AS INTEGER = value
    IF enabled THEN
        total = total + 5
    END IF
    RETURN total
END FUNCTION
```

Functions have mandatory parameter/return annotations and are pure. Function parameters are immutable; declare a local accumulator when needed. Functions cannot access contract parameters, inputs, or locals without receiving arguments. Every reachable normal exit returns a compatible value. `RETURN` is forbidden in contracts; `EMIT` and `SOLUTION` are forbidden in functions. Declarations cannot nest. Expression statements and discarded calls are unsupported.

## Declarations, scope, and assignment

`DIM name [AS type] = expression` initializes a mutable local. Without `AS`, infer its type without later widening. `CONST name [AS type] = expression` declares an immutable compile-time local. Constant expressions contain literals, list literals, unary/binary operators, and previously declared constants only; calls are excluded. Compile-time evaluation obeys runtime arithmetic/boolean rules.

No uninitialized declarations. A name is unavailable in its own initializer. Duplicate names after case folding are errors. Locals cannot shadow visible enclosing names, module callable names, or built-ins. Sibling branches have separate scopes. Different functions may reuse local names.

Assignment updates an existing `DIM` local only, with a compatible type. SOLUTION values are immutable too; copy one to a DIM local to update it. Branches may update outer locals; a branch not assigning one retains its incoming value. Branch-local declarations do not escape. Lower assignments into fresh immutable bindings and branch results. Initializers and assignments evaluate eagerly even if the value is never read; a possibly failing evaluation cannot simply be removed.

## Types

| Type | Meaning |
| --- | --- |
| `INTEGER` | Arbitrary-precision signed integer; resource limits still apply |
| `BOOLEAN` | Exactly true or false; no implicit numeric truthiness |
| `BYTES` | Arbitrary byte string |
| `STRING` | Valid Unicode scalar sequence encoded in UTF-8, without normalization |
| `LIST OF T` | Proper finite list of T values |
| `PAIR OF (A, B)` | Pair of A and B values |
| `PUZZLEHASH` | Exactly 32 bytes |
| `PUBLICKEY` | Canonically encoded, subgroup-valid, non-infinity BLS G1 key |
| `AMOUNT` | Integer in `0..18446744073709551615`, in mojos |
| `CONDITION` | Opaque value created by a supported condition constructor |

No implicit conversions between distinct types, including AMOUNT/INTEGER or STRING/BYTES. List/pair types are invariant. Functions may return any type above. CONDITION, including nested occurrences, is prohibited in fixed-parameter and solution-input schemas.

List literals `[a, b]` use an expected list type from a declaration, assignment, return, or parameter; otherwise all elements must infer the same type. Empty lists without an expected type are errors. Pair construction uses `PAIR(a, b)`. No indexing, heterogeneous lists, user type variables, or implicit flattening.

## Expressions and control flow

Highest precedence first:

| Level | Operators | Rules |
| --- | --- | --- |
| 1 | Literals, names, calls, lists, parentheses | Positional calls, exact arity |
| 2 | Unary `+`, `-` | INTEGER; right associative |
| 3 | `*` | INTEGER; left associative |
| 4 | Binary `+`, `-` | INTEGER; left associative |
| 5 | `=`, `<>`, `<`, `<=`, `>`, `>=` | One comparison without explicit parentheses |
| 6 | `NOT` | BOOLEAN; right associative; `NOT a = b` means `NOT (a = b)` |
| 7 | `AND` | BOOLEAN; left associative; short circuit |
| 8 | `OR` | BOOLEAN; left associative; short circuit |

Ordered comparison accepts INTEGER only. Equality requires identical scalar types: INTEGER, BOOLEAN, BYTES, STRING, PUZZLEHASH, PUBLICKEY, or AMOUNT. No list/pair/condition equality. Strings compare exact UTF-8 bytes. Comparisons return BOOLEAN.

Operands/arguments evaluate left to right, once semantically. `AND` skips the right operand when the left is false; `OR` skips it when true. IF/ELSEIF tests run in source order and only the selected body executes. Unselected branches cannot emit, fail, or incur evaluation costs. Optimizations preserve these rules.

`ASSERT booleanExpression` continues when true and aborts CLVM execution when false. No exception recovery. RETURN prevents subsequent execution in that function. Unreachable code is still parsed and type-checked; the current compiler does not issue an unreachable-code warning.

## EMIT

`EMIT expression` accepts one CONDITION and appends it in execution order. It does not immediately create a coin or enforce a height. Normal completion returns the proper accumulated list; empty contracts return `()`. An empty/unselected branch adds no element. Failure aborts evaluation without a partial result.

`EMIT []` and `EMIT [condition]` are type errors. A function may return a CONDITION which the contract emits, but cannot emit on its caller's behalf.

## Built-ins

This list is exhaustive for 0.1. T/A/B represent compiler-internal polymorphism, not user-declarable type parameters. Calls are case-insensitive and parenthesized, with exact arity.

| Signature | Behavior / failure |
| --- | --- |
| `SHA256(BYTES) -> BYTES` | 32-byte SHA-256 digest |
| `CONCAT(BYTES, BYTES) -> BYTES` | Concatenate exactly two byte strings |
| `BYTE_LENGTH(BYTES) -> INTEGER` | Byte count |
| `UTF8(STRING) -> BYTES` | Exact UTF-8 encoding |
| `STRING_FROM_UTF8(BYTES) -> STRING` | Fail unless strictly valid UTF-8 |
| `INT_BYTES(INTEGER) -> BYTES` | Minimal signed big-endian encoding from ABI |
| `INT_FROM_BYTES(BYTES) -> INTEGER` | Fail on noncanonical encoding |
| `U64BE(INTEGER) -> BYTES` | Exactly 8 unsigned big-endian bytes; range `0..2^64-1` |
| `U32BE(INTEGER) -> BYTES` | Exactly 4 unsigned big-endian bytes; range `0..2^32-1` |
| `AS_AMOUNT(INTEGER) -> AMOUNT` | Range check |
| `AMOUNT_VALUE(AMOUNT) -> INTEGER` | Extract integer |
| `AS_PUZZLEHASH(BYTES) -> PUZZLEHASH` | Check length 32 |
| `HASH_BYTES(PUZZLEHASH) -> BYTES` | Extract bytes |
| `AS_PUBLICKEY(BYTES) -> PUBLICKEY` | Full key validation, reject infinity |
| `KEY_BYTES(PUBLICKEY) -> BYTES` | Extract canonical bytes |
| `PAIR(A, B) -> PAIR OF (A, B)` | Construct pair |
| `FIRST(PAIR OF (A, B)) -> A` | Left element |
| `REST(PAIR OF (A, B)) -> B` | Right element |
| `FIRST(LIST OF T) -> T` | First element; fail on empty |
| `REST(LIST OF T) -> LIST OF T` | Tail; fail on empty |
| `CONS(T, LIST OF T) -> LIST OF T` | Prepend element |
| `LIST_LENGTH(LIST OF T) -> INTEGER` | Linear element count |
| `CREATE_COIN(PUZZLEHASH, AMOUNT) -> CONDITION` | `(51 hash amount)`; no memos |
| `ASSERT_MY_AMOUNT(AMOUNT) -> CONDITION` | `(73 amount)` |
| `ASSERT_HEIGHT_ABSOLUTE(INTEGER) -> CONDITION` | `(83 height)`; range-check `0..2^32-1` |
| `AGG_SIG_ME(PUBLICKEY, BYTES) -> CONDITION` | `(50 key message)`; reject message over 1024 bytes |

Range/validation failures abort VM execution when the call is evaluated. Constant folding must not turn an unexecuted failing conversion into a compilation error; it may lower an evaluated failing call to a runtime raise. `PAYMENT_MESSAGE` is an ordinary [example function](../examples/height-locked-payment.bas), not a built-in. Compiler-generated validators may recurse even though user recursion is excluded.

`check` verifies built-in arity and types, not successful evaluation for particular values. An invalid domain value supplied through bindings or solution JSON can instead fail during host conversion, before a call executes. Calls in `CONST` expressions are prohibited even when their arguments are literals. The 1024-byte `AGG_SIG_ME` message limit applies when constructing that condition; it is not a general BYTES length limit. Condition constructors return values; `EMIT` determines whether they enter the returned condition list. See [failure stages and resource limits](spec/limits-and-failures.md) for the separate host and runtime budgets.

## Exclusions and conformance

No floating point, division/remainder/exponentiation, bitwise operators, loops, user recursion, SUB, mutable globals, references, closures, macros, imports, raw opcodes, runtime I/O, or package manager. Unsupported constructs produce diagnostics. Loops/recursion remain planned Core features.

[Source fixtures](spec/source-cases.json) define accepted/rejected examples. [ABI vectors](spec/vectors.json) cover encoding, binding, and payment authorization. They are acceptance inputs, not compiler pass results. `python tools/verify_m0.py` checks specification artifacts; `--with-upstream` additionally compares installed Chia libraries and reports their versions.
