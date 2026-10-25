# Manifest validation and diagnostic examples

Applies to released compiler `0.1.0-m3.8b`, manifest schema `1`. This guide explains the existing [artifact reader](../../crates/cli/src/artifact.rs); it does not change the schema or acceptance rules. The normative interface is [CLI v1](cli-v1.md).

## Schema and reader responsibilities

The [JSON Schema](manifest.schema.json) describes manifest structure. The executable uses typed JSON deserialization and explicit checks, not a runtime JSON Schema engine. A validator accepting a document does not establish that its files exist, that its compiler is supported, or that it can execute.

| Property | Schema description | Additional reader checks |
| --- | --- | --- |
| Required fields and shapes | Required members, types and forbidden extra properties | Typed deserialization rejects duplicate/unknown members and malformed JSON; input size/nesting budgets also apply |
| Compiler identity | `compiler.version` is a string; other identities have constants | Exact supported compiler, manifest, language, ABI, profile and optimization identities; unsupported values use E0400 |
| Provenance | Rust version and lowercase digest shape | Rust version must match the executable; invalid provenance uses E0600. Source and lock digest contents are not compared with external files |
| Field declarations | Normalized name patterns and recursive type shapes | Unique names, no fixed/input overlap, field counts and type budgets |
| Bindings | Object for a bound puzzle, null for a template-only artifact | Typed values must match fixed fields and already be normalized; object property order is not significant |
| Artifact references | Fixed filenames and lowercase digest shapes | Resolved paths stay beneath the manifest directory; canonical hex matches binary; actual byte digest and CLVM tree hash match |
| Template/puzzle relationship | Separate artifact descriptions | Currying the template with the encoded fixed-value list must reproduce the puzzle bytes exactly |
| Executability | Template-only artifacts are valid descriptions | `run` rejects a null puzzle with E0400; it does not execute templates directly |

The schema does not express all reader limits or dynamic relationships. In particular, it does not enforce the exact compiler version, uniqueness across field arrays, type depth/node budgets, binding normalization, or byte-level rebinding. Duplicate JSON members must be detected while parsing: a generic parser may discard them before a schema validator sees the object.

## Reader order and limits of the guarantee

The reader checks JSON structure, supported identities, provenance formats, descriptive names and boundary schemas before loading program files. It rejects template-only execution before inspecting template file contents. A failed load is not an exhaustive report of every defect in the directory; the first applicable check determines the diagnostic.

For a bound manifest, the reader converts and checks normalized bindings, resolves and validates both template and puzzle files, and checks exact rebinding. Solution conversion and VM execution occur afterward. Raw malformed solution serialization can produce E0300 before evaluation; an invalid runtime value in a correctly serialized tree can instead produce E0500.

Successful loading establishes consistency of the supplied artifact set. It does **not** prove that:

- the advertised source produced the template;
- the source or Cargo.lock digest matches an available file or the running compiler's lock;
- the declared solution schema accurately describes arbitrary replacement CLVM;
- an author or publisher signed the artifact;
- execution returns valid consensus conditions or a spend will be accepted.

Moving a complete artifact directory is supported. Its advertised source file need not be present. Static path/symlink containment checks do not lock the filesystem against concurrent replacement. See the [compatibility policy](experimental-compatibility.md) for identity and upgrade rules.

## Captured diagnostics

These examples were checked on 2026-10-25 using the Windows executable extracted from the published prerelease, whose archive SHA-256 is `52b8234edc20d85a4f5968904933d7627bd0a33e850025448b47052465411d78`. JSON whitespace and object key order below are presentation choices. Codes, field meanings and exit categories are the contract; exact message wording may change.

The [source example in CLI v1](cli-v1.md#json-output-and-exit-status) records E0200 with an actual source span. Manifest failures normally have `source: null` and `span: null`: the reader does not fabricate a source-code location for artifact metadata.

For a valid bound artifact whose `compiler.version` was changed to `unsupported`, `0xbasic run artifact/manifest.json --json` exited 2 with empty stderr:

```json
{"schema_version":1,"command":"run","ok":false,"diagnostics":[{"code":"E0400","severity":"error","message":"Unsupported manifest/compiler/language/ABI/target profile","source":null,"span":null,"notes":[]}],"result":null}
```

Starting from the original manifest again and changing only `puzzle.tree_hash` to 64 zero digits produced exit 4 with empty stderr:

```json
{"schema_version":1,"command":"run","ok":false,"diagnostics":[{"code":"E0600","severity":"error","message":"Artifact digest mismatch","source":null,"span":null,"notes":[]}],"result":null}
```

As a contrast in validation scope, changing only the original manifest's `source.sha256` and `compiler.cargo_lock_sha256` to 64 zero digits still allowed the empty `CONTRACT Demo()` artifact to run. It returned `clvm-execution-only`, the empty atom and cost `1309`. This is an observation for that exact fixture and compiler, not a universal execution cost. It confirms that well-formed provenance strings are not authenticated by the reader.

All mutations were performed in an isolated scratch directory, restoring the original between independent cases. Five CLI invocations covered the source diagnostic, baseline build and three manifest probes. No release files or reader behavior changed.

## Existing regression evidence

[CLI tests](../../crates/cli/tests/commands.rs) cover invalid versions/provenance, artifact path aliases and traversal, matching digests with incorrect template rebinding, canonical hex, missing/unknown members, and relocation without source files. [Diagnostic contract tests](../../crates/cli/tests/diagnostic_contract.rs) cover Unicode/BOM/CRLF/tab spans, human/JSON streams and representative exit categories. These tests passed in the release's Windows/Linux CI; this documentation audit adds no new native-test requirement.
