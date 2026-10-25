# CLI, artifacts, and diagnostics v1

Status: normative interface specification. `check`, `build`, and `run` support the [M3-8b subset](../development.md): the typed BASIC core plus scalar and recursive PAIR/LIST fixed parameters and SOLUTION fields, JSON binding/solution conversion and generated raw-tree validation. AMOUNT, PUZZLEHASH and PUBLICKEY boundaries and explicit conversions are supported; ASSERT_MY_AMOUNT, CREATE_COIN and AGG_SIG_ME constructors are implemented; `explain --stage ast|ir|clvm` is implemented. Program name: `0xbasic`; internal Rust package names use `oxbasic` because Rust identifiers cannot begin with a digit.

Experimental upgrade/rebuild rules and the stable diagnostic contract are documented in the [compatibility policy](experimental-compatibility.md).

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

`explain` inspects source in memory without writing build artifacts or executing CLVM. `ast` parses only, so syntactically valid source may be inspected even if it has semantic errors. `ir` performs the same analysis and lowering as `check`. Neither requires fixed bindings or solution data; both reject binding flags. The `clvm` stage uses build's binding semantics: default bindings are `{}`, `--bindings` supplies fixed values, and `--template-only` omits binding. Missing required fixed values fail E0301. It generates code but never executes it. Debug AST/IR structure is versioned with the compiler and is not an independent stable interchange API. It must retain enough source references to support diagnostics.

AST/IR success results contain `stage`, `compiler_version`, `source` (basename and SHA-256 of original bytes), and `representation`. AST representation contains `contract`, `functions`, and a flat `nodes` array. Statement/expression references are zero-based array indexes; child nodes precede their parents. Each node has `kind`, `span`, and kind-specific `data`. Declaration and operator spans also refer to original source bytes. Comments and whitespace are not nodes; identifiers follow parser normalization. IR representation is the checked contract, including typed values, value references, functions, locals and emissions. These debug structures may change with compiler versions. The JSON envelope remains schema version 1.

CLVM results use the same result wrapper with `stage: "clvm"`. Their representation includes `contract`, `fixed_parameters`, `inputs`, normalized `bindings`, `template`, and `puzzle`. Template-only mode sets bindings and puzzle to null. Each program includes lowercase serialized `hex`, `program_sha256`, `tree_hash`, `root` (zero), and a flat `nodes` array. Nodes are either `{"atom":"hex"}` or `{"pair":[firstIndex,restIndex]}`; children have larger indexes than their parent. This avoids recursively nested JSON even for large programs. These bytes and hashes match build artifacts; no execution cost or spend-validity claim is made.

An output directory must not already exist; fail instead of overwriting. Write all artifacts to a new sibling staging directory and rename it into place only after success. Failed work must not publish a success manifest. Resolve manifest artifact paths beneath the manifest directory, reject path traversal/absolute paths, and do not fetch missing dependencies from a manifest.

## Files and manifest

### File and result limits

The CLI reads at most 1,048,576 bytes from each source, bindings, JSON solution, raw solution-hex or manifest file. The raw solution-hex limit counts the textual file, including whitespace, before hex decoding; it is not a 1 MiB binary allowance. Exceeding these file-reader limits produces E0600/exit 4.

Artifact binary files permit at most 1,048,576 bytes each. Their companion hex files permit 2,097,153 bytes (twice the binary budget plus a newline). Generated programs, decoded program/solution serialization and serialized execution results have separate 1,048,576-byte limits.

After successful VM reduction, the runner also limits the displayed result tree to 8,192 visited nodes and depth 512, counting the root at depth zero. Exceeding result serialization or display limits produces E0500/exit 3 even if VM evaluation finished within `--max-cost`. Raising the cost limit does not raise file, conversion or display budgets. These host limits are distinct from network consensus rules; see [limits and failure stages](limits-and-failures.md).

Build output:

- `template.clvm`: traditional serialized unbound tree, binary.
- `template.hex`: lowercase hex of those bytes plus LF.
- `puzzle.clvm` and `puzzle.hex`: corresponding bound puzzle; absent with `--template-only`.
- `manifest.json`: UTF-8 JSON, 2-space indentation, LF; deterministic key order chosen by schema field order, no timestamp.

The [manifest JSON Schema](manifest.schema.json) defines exact required fields. JSON property names are case-sensitive here. The argument type representation is a recursive object: scalar `{"kind":"INTEGER"}`; list `{"kind":"LIST","element":type}`; pair `{"kind":"PAIR","first":type,"rest":type}`. In addition to schema validation, check unique field names and validate normalized binding values against the fixed-field schema; every artifact path/hash must match its role. The schema is descriptive, not permission to execute arbitrary code.

Include source basename and SHA-256 of original source bytes, compiler version, exact Rust version, Cargo.lock SHA-256, language/ABI/profile versions, optimization level, fixed/input schemas in declaration order, normalized bindings or null, and file/hash descriptions. Paths are relative POSIX names, never local absolute paths. Type/name schemas originate in source, not from trusting an arbitrary manifest. Lowercase identifiers in schemas and normalized binding keys. Compiler output never serializes private keys.

Manifest loading establishes internal consistency, not authorship. It checks the supported compiler/language/ABI/profile and Rust version, schema validity, normalized bindings, artifact bytes/hex/hashes, and exact template rebinding. Source and Cargo.lock digests must be lowercase SHA-256 strings, but the loader does not open external source/lock files or require the lock digest to equal the running CLI's build. Source basename and contract name are descriptive metadata, not authenticated identities. Moving a complete artifact directory is supported. A self-consistent replacement program is still arbitrary CLVM; successful loading or execution does not prove its advertised source, schema, or spend validity.

Artifact filenames are fixed by role (`template.clvm`, `template.hex`, `puzzle.clvm`, `puzzle.hex`). All four resolved paths must remain beneath the manifest directory. This checks static path/symlink escapes; it does not provide a filesystem snapshot against concurrent modification by another process. Publication's no-overwrite guarantee is separate from these reader checks.

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
