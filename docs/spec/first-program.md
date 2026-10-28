# Your first 0xBASIC program

Write a small contract, compile it to CLVM, inspect the generated program, and execute it locally. This walkthrough uses the experimental compiler **`0.1.0-m3.8b`**, language `0.1`, ABI `1`. It uses only released features; FOR/NEXT is unavailable in that release. The [development loop tutorial](loops-tutorial.md) targets the newer source-built compiler.

0xBASIC programs describe conditions for spending Chia coins. They do not print messages or prompt for keyboard input. Our first example returns a condition requiring a minimum block height. It is a learning example, **not an ownership-protected payment contract**.

## 1. Get the experimental compiler

Download the Windows ZIP or Linux tar.gz from the [experimental release](https://github.com/steppsr/0xBASIC/releases/tag/v0.1.0-m3.8b-experimental), verify its adjacent SHA-256 checksum, and extract it into a new directory. See the [release record](experimental-release.md) for tested operating-system versions. No Rust or Python installation is needed for this walkthrough.

Open a terminal in the extracted directory. The executable is:

| Platform | Executable |
| --- | --- |
| Windows PowerShell | `./bin/0xbasic.exe` |
| Native Linux | `./bin/0xbasic` |

Commands below use the Linux spelling. **On Windows, replace `./bin/0xbasic` with `./bin/0xbasic.exe` in every command.** Keep the rest of each command unchanged. Linux extraction must preserve the executable permission.

```text
./bin/0xbasic --version
./bin/0xbasic --help
```

Expect compiler version `0.1.0-m3.8b`. These two standalone commands do not take `--json`; the other commands below use it for structured results.

## 2. Write the source

In a plain-text editor, create **`hello.bas`** in the extracted directory. Save it as UTF-8, not `hello.bas.txt`.

```basic
CONTRACT HeightLock(earliestHeight AS INTEGER)
    ' Reject negative heights before returning a condition.
    ASSERT earliestHeight >= 0
    EMIT ASSERT_HEIGHT_ABSOLUTE(earliestHeight)
END CONTRACT
```

Here is what each part means:

- `CONTRACT ... END CONTRACT` defines the single contract in this file.
- `earliestHeight AS INTEGER` declares a **fixed parameter**, supplied when compiling the bound puzzle. It is not a keyboard prompt.
- An apostrophe begins a comment. `REM` comments are also supported.
- `ASSERT` requires a BOOLEAN expression to be true when the program executes; otherwise execution fails.
- `ASSERT_HEIGHT_ABSOLUTE(...)` constructs a height condition. It requires an INTEGER in `0..4294967295`.
- `EMIT` appends that condition to the program's result. It does not contact a node or wait for a block.

Names and keywords are case-insensitive. Use one statement per line and structured `END` blocks; there are no line numbers or colon-separated statements.

## 3. Check the source

```text
./bin/0xbasic check hello.bas --json
```

Expect `"ok": true`, an empty `diagnostics` array, and a result naming the contract. Checking verifies syntax and types without needing a concrete height or executing the program. On an error, `ok` is false and the diagnostic identifies the problem; fix it before building.

## 4. Supply the fixed value and compile

Create **`hello.bindings.json`** beside the source:

```json
{"earliestHeight":"100"}
```

The quotes around `"100"` are required: INTEGER values in binding/solution JSON are decimal **strings**, not JSON numbers. The field name must match the declared parameter, case-insensitively.

```text
./bin/0xbasic build hello.bas --bindings hello.bindings.json --out hello-build --json
```

Expect `"ok": true`. `hello-build` must not already exist; the compiler refuses to overwrite it. For another experiment, use a new output name such as `hello-build-2`.

The new directory contains:

| File | Purpose |
| --- | --- |
| `template.clvm` | Binary serialized CLVM before the fixed parameters are bound |
| `template.hex` | The same template bytes represented as readable hexadecimal |
| `puzzle.clvm` | Binary CLVM with the fixed height bound into it |
| `puzzle.hex` | The bound puzzle bytes in hexadecimal |
| `manifest.json` | Compiler/profile identities, schemas, normalized bindings, filenames and hashes |

The **bound puzzle** is the program whose tree hash identifies a coin's puzzle. The template and bound puzzle have different roles. Keep the source, binding file and complete artifact directory together for your records.

## 5. View the CLVM

**Yes—the compiler can show its generated CLVM.** Run:

```text
./bin/0xbasic explain hello.bas --stage clvm --bindings hello.bindings.json --json
```

Look in `result.representation.template` and `result.representation.puzzle`. Each includes serialized `hex`, a serialized-byte `program_sha256`, a CLVM `tree_hash`, and a flat tree described by `root` and `nodes`.

In that node list, `{"atom":"..."}` contains atom bytes as hex. `{"pair":[a,b]}` refers to two node indexes. This exposes the generated CLVM structure without requiring an external disassembler. The generated hex and hashes match the corresponding build artifacts for the same source and bindings.

`explain` regenerates the representation from **source and bindings**; it does not open `hello-build/manifest.json`. To inspect the saved files directly, open `puzzle.hex` and `manifest.json` in a text editor. Do not open binary `.clvm` files expecting source text. The released CLI does not provide a separate saved-bytecode disassembly command or a conventional symbolic CLVM listing.

You can also inspect earlier compiler stages:

```text
./bin/0xbasic explain hello.bas --stage ast --json
./bin/0xbasic explain hello.bas --stage ir --json
```

`ast` shows parsed syntax; `ir` shows the checked intermediate representation. These inspection commands do not execute the program or write build artifacts.

## 6. Run the compiled puzzle locally

```text
./bin/0xbasic run hello-build/manifest.json --json
```

Expect `"ok": true`, `"validation": "clvm-execution-only"`, a measured cost, and this raw result tree:

```json
{"pair":[{"pair":[{"atom":"53"},{"pair":[{"atom":"64"},{"atom":""}]}]},{"atom":""}]}
```

As a list of decimal values, that is **`((83 100))`**: condition opcode 83 (`ASSERT_HEIGHT_ABSOLUTE`) with height 100. `53` and `64` above are hexadecimal atoms; the empty atom is the list terminator.

This is the **program's output condition list**, not a disassembly of the compiled puzzle. The local runner does not know the current blockchain height or confirm a spend. It can successfully return the height condition even when an actual chain would reject spending the coin too early.

Our contract declares no `SOLUTION` fields, so no solution file is needed. For contracts that do, `run` accepts `--solution FILE` for JSON values or `--solution-hex FILE` for a serialized CLVM solution written in hex.

## What testers can use today

These are the released language building blocks. Consult the historical [language specification](../language-v0.1.md) for exact signatures and restrictions.

| Area | Supported syntax or names |
| --- | --- |
| Structure | `CONTRACT ... END CONTRACT`; `FUNCTION ... AS type ... END FUNCTION`; function `RETURN` |
| Inputs | Fixed contract parameters; initial `SOLUTION name AS type` declarations for spender-supplied values |
| Local values | Initialized `DIM`; reassignment to DIM locals; compile-time `CONST` (no calls in constant expressions) |
| Branches and checks | Multiline `IF ... THEN`, `ELSEIF`, `ELSE`, `END IF`; `ASSERT`; `EMIT` in contracts |
| Arithmetic | INTEGER unary `+`/`-`, addition, subtraction and multiplication |
| Comparisons and logic | `=`, `<>`; INTEGER `<`, `<=`, `>`, `>=`; BOOLEAN `TRUE`, `FALSE`, `NOT`, short-circuit `AND`/`OR` |
| Scalar types | `INTEGER`, `BOOLEAN`, `BYTES`, `STRING`, `AMOUNT`, `PUZZLEHASH`, `PUBLICKEY` |
| Structured types | `LIST OF T`, `PAIR OF (A, B)`; internal `CONDITION` values |
| Byte/string functions | `BYTE_LENGTH`, `CONCAT`, `SHA256`, `UTF8`, `STRING_FROM_UTF8` |
| Integer encodings | `INT_BYTES`, `INT_FROM_BYTES`, `U32BE`, `U64BE` |
| Domain conversions | `AS_AMOUNT`, `AMOUNT_VALUE`, `AS_PUZZLEHASH`, `HASH_BYTES`, `AS_PUBLICKEY`, `KEY_BYTES` |
| Collections | List literals such as `[1, 2]`; `PAIR`, `FIRST`, `REST`, `CONS`, `LIST_LENGTH` |
| Condition constructors | `ASSERT_HEIGHT_ABSOLUTE`, `ASSERT_MY_AMOUNT`, `CREATE_COIN`, `AGG_SIG_ME` |

Functions are pure and nonrecursive. Fixed parameters, SOLUTION fields and function parameters are immutable. There are no implicit conversions between distinct types. CONDITION cannot be an external fixed parameter or solution field. String text is quoted; byte literals use `0x` followed by pairs of hex digits.

**Not supported by this released compiler:** `FOR/NEXT` or other loops, user recursion, `PRINT`, interactive `INPUT`, division/remainder, floating point, `GOTO`, `SUB`, imports/modules, runtime file I/O, or wallet/signing/submission commands. A design proposal is not an executable feature.

## What can you do with the compiled result?

- **Inspect it:** examine the manifest, hex and generated CLVM tree as shown above.
- **Test it locally:** run it with different solution values where declared, and inspect its output and execution cost. Changing a fixed parameter requires a new build.
- **Compare builds:** preserve original artifacts and compare bytes and puzzle identities using the [rebuild walkthrough](artifact-workflow.md).
- **Test actual spends in isolation:** use the separate [simulator harness](../../simulator/README.md), which handles signing and confirmation in test scenarios.
- **Develop a real contract:** extend the example with appropriate authorization and payment conditions; the [signed-payment tutorial](payment-tutorial.md) is the next step. Funding a coin, signing, paying fees, submitting and confirming a spend require tools outside this CLI. Rebuilding a program does not change an existing coin's puzzle.

This height-only example does not require an owner's signature or specify where funds must go. Do not treat it as a secure payment or savings contract. Compilation and local execution alone do not establish production readiness.

## Walkthrough verification

The source, bindings and command blocks were checked with the published Windows experimental executable. The generated CLVM bytes/hashes match the saved artifacts, and local execution returns the exact condition tree shown above. This tutorial documents existing released behavior; it introduces no new compiler feature or native Linux test requirement.
