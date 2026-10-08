# CLI, artifacts, and diagnostics v1

Status: normative interface specification. `check`, `build`, and `run` support the [M3-2 subset](../development.md): the typed BASIC core plus INTEGER fixed parameters and SOLUTIONs, JSON binding/solution conversion and generated raw-tree validation. Other boundary types and `explain` remain planned. Program name: `0xbasic`; internal Rust package names use `oxbasic` because Rust identifiers cannot begin with a digit.

## Commands

```text
0xbasic check SOURCE [--json]
0xbasic build SOURCE --out DIRECTORY [--bindings FILE | --template-only] [--json]
0xbasic run MANIFEST [--solution FILE | --solution-hex FILE] [--max-cost N] [--json]
0xbasic explain SOURCE --stage ast|ir|clvm [--bindings FILE | --template-only] [--json]
0xbasic --version
0xbasic --help
```

No network, wallet, signing, node discovery, or deployment side effects. File paths may contain spaces. SOURCE is one `.bas` file; FILE is a UTF-8 JSON file except `--solution-hex`, which reads traditional serialized CLVM as hex. Hex files contain one contiguous even-length hex string without prefix, with optional surrounding ASCII whitespace only.

`check` lexes/parses/resolves/types without requiring actual fixed values. `build` defaults to bindings `{}`; missing required fields fail. `--template-only` emits no bound puzzle and is mutually exclusive with `--bindings`. Even parameterless normal builds emit the ABI binding wrapper.

`run` loads and validates the manifest, loads its bound program, checks byte digest and tree hash, converts/loads the solution, and executes with a cost limit. Reject template-only manifests; do not accidentally interpret a solution as an unbound-template environment. Default solution is `{}` and fails if inputs are required. Default max cost is `10000000`; N must be a decimal integer in `1..2^64-1`. The CLI limit is not a network consensus budget. Output labels successful execution as `clvm-execution-only`, never a valid spend.

`explain` performs compilation in memory without writing build artifacts. `ast` and `ir` operate on the template and reject binding flags. `clvm` supports build's binding semantics. Debug AST/IR structure is versioned with the compiler and is not an independent stable interchange API. It must retain enough source references to support diagnostics.

An output directory must not already exist; fail instead of overwriting. Write all artifacts to a new sibling staging directory and rename it into place only after success. Failed work must not publish a success manifest. Resolve manifest artifact paths beneath the manifest directory, reject path traversal/absolute paths, and do not fetch missing dependencies from a manifest.

## Files and manifest

Build output:

- `template.clvm`: traditional serialized unbound tree, binary.
- `template.hex`: lowercase hex of those bytes plus LF.
- `puzzle.clvm` and `puzzle.hex`: corresponding bound puzzle; absent with `--template-only`.
- `manifest.json`: UTF-8 JSON, 2-space indentation, LF; deterministic key order chosen by schema field order, no timestamp.

The [manifest JSON Schema](manifest.schema.json) defines exact required fields. JSON property names are case-sensitive here. The argument type representation is a recursive object: scalar `{"kind":"INTEGER"}`; list `{"kind":"LIST","element":type}`; pair `{"kind":"PAIR","first":type,"rest":type}`. In addition to schema validation, check unique field names and validate normalized binding values against the fixed-field schema; every artifact path/hash must match its role. The schema is descriptive, not permission to execute arbitrary code.

Include source basename and SHA-256 of original source bytes, compiler version, exact Rust version, Cargo.lock SHA-256, language/ABI/profile versions, optimization level, fixed/input schemas in declaration order, normalized bindings or null, and file/hash descriptions. Paths are relative POSIX names, never local absolute paths. Type/name schemas originate in source, not from trusting an arbitrary manifest. Lowercase identifiers in schemas and normalized binding keys. Compiler output never serializes private keys.

`program_sha256` hashes serialized bytes; `tree_hash` is the CLVM tree hash. Treat them as different values. A dependency/toolchain change requires a new lock digest and compatibility checks even if bytes happen to match. 0.1 fixes optimization to `none` (required lowering is not an optional optimization). No unrecorded optimizer modes.

`--version` reports compiler, language, ABI, and target-profile identifiers. Do not claim an unimplemented command or language feature is supported.

## JSON output and exit status

With `--json`, stdout is one JSON object followed by LF; stderr contains only unexpected process-level failures. Normal diagnostics are in the JSON envelope:

```json
{"schema_version":1,"command":"check","ok":false,"diagnostics":[{"code":"E0200","severity":"error","message":"Unknown name: value","source":"demo.bas","span":{"start_byte":21,"end_byte":26,"line":2,"column":6},"notes":[]}],"result":null}
```

Every diagnostic has code, severity (`error` or `warning`), message, source (basename or null), span (or null), and notes (string array). Byte spans are half-open offsets into original UTF-8. Line/column are one-based Unicode-scalar positions; a tab counts as one column, CRLF as one newline. A BOM occupies bytes but no displayed column. Error messages may improve without code changes.

Successful results: `check` gives contract name; `build` gives relative output file names and bound/template tree hashes; `run` gives `validation:"clvm-execution-only"`, cost as a decimal string, and a raw result tree. Raw trees use exactly `{"atom":"lowercasehex"}` or `{"pair":[left,right]}`; do not pretend every list returned by arbitrary CLVM is a decoded valid condition. `explain` gives stage and a compiler-versioned representation.

Exit codes: 0 success, 1 source/typing/binding errors, 2 command usage or unsupported option/profile, 3 VM/validation/cost execution failure, 4 I/O/artifact integrity failure, 70 internal compiler failure. On failure result is null. Human mode writes diagnostics to stderr, results to stdout. Color is disabled for nonterminal output.

## Initial diagnostic codes

| Code | Meaning |
| --- | --- |
| E0001 | Invalid source encoding/character |
| E0002 | Invalid literal |
| E0100 | Unexpected token or malformed syntax |
| E0101 | Wrong number of contracts / invalid module structure |
| E0200 | Unknown name or callable |
| E0201 | Duplicate or shadowed name |
| E0202 | Type mismatch / ambiguous empty list / call arity |
| E0203 | Invalid assignment target, including constant/input/parameter |
| E0204 | Function may finish without a return |
| E0205 | Construct forbidden in this context |
| E0206 | Recursive call cycle |
| E0300 | Invalid ABI/solution value or shape |
| E0301 | Invalid/missing fixed binding |
| E0400 | Unsupported language/ABI/target version |
| E0500 | VM execution failure (including contract ASSERT) |
| E0501 | Execution cost limit exceeded |
| E0600 | File/I/O/artifact integrity failure |
| E9000 | Internal compiler invariant failure |

Generated on-chain checks fail via CLVM raise, not a promise of source-level diagnostic payloads. A local runner may map an observed failure to a more specific diagnostic only with evidence; otherwise use E0500. Raw malformed serialized solution errors discovered before execution use E0300; validly serialized but invalid runtime values may surface as E0500.
