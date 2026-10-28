# Counted loops with the development compiler

This guide targets source-built compiler `0.2.0-alpha.1`, language `0.2`, ABI 1. The downloadable `0.1.0-m3.8b` release remains unchanged and cannot compile these loops. The activation candidate is undergoing native validation; it is not a newly published release.

From the repository root, build and check the version:

```text
cargo build --workspace --locked
cargo run --locked -p oxbasic-cli -- --version
```

Expect compiler `0.2.0-alpha.1`, language `0.2`, ABI `1`, and target profile `chia-clvm-0.19-strict-v1`. No feature flag enables loops: they are part of this compiler's default public language.

## A complete program

The repository includes [counted-heights.bas](../../examples/counted-heights.bas):

```basic
CONTRACT CountedHeights()
    FOR height = 5 TO 1 STEP -2
        EMIT ASSERT_HEIGHT_ABSOLUTE(height)
    NEXT height
END CONTRACT
```

FOR introduces a fresh INTEGER counter, NEXT must name it, and bounds are inclusive. The body executes with heights 5, 3 and 1. Omitting STEP uses 1. A correctly typed zero step passes check but fails when entered at runtime, even for an empty-looking range. The counter is read-only and only visible inside its body.

Compile into a new directory, inspect, and run:

```text
cargo run --locked -p oxbasic-cli -- check examples/counted-heights.bas --json
cargo run --locked -p oxbasic-cli -- build examples/counted-heights.bas --out counted-heights-build --json
cargo run --locked -p oxbasic-cli -- explain examples/counted-heights.bas --stage ast --json
cargo run --locked -p oxbasic-cli -- explain examples/counted-heights.bas --stage ir --json
cargo run --locked -p oxbasic-cli -- explain examples/counted-heights.bas --stage clvm --json
cargo run --locked -p oxbasic-cli -- run counted-heights-build/manifest.json --json
```

`counted-heights-build` must not exist before build. It contains template/puzzle binary and hex files plus the manifest. CLVM inspection exposes program bytes, byte hashes, tree hashes and the flat tree view; it does not execute the program or provide a conventional symbolic-disassembly command. The local result is the raw condition list `((83 5) (83 3) (83 1))`. These conditions do not authorize spending or represent three separate transaction heights. The runner reports local CLVM execution, not a signed or confirmed blockchain spend.

## Available loop behavior

Headers evaluate once in source order. Outer DIM locals keep their types and carry updates through iterations and following statements; body-local declarations initialize each time and cannot escape. Nested loops, IF/ELSEIF/ELSE, all supported local types, assertions, calls and EMIT work inside the appropriate contract/function context. RETURN in a function exits through nested loops and skips subsequent work. Functions still cannot EMIT or recurse.

There is no runtime iteration cap; VM cost and existing output limits remain. Use assertions for application bounds when loop headers come from solution data. The compiler has static source, nesting, value and type-work limits described in [language 0.2](../language-v0.2.md#counted-loops).

WHILE/DO, EXIT/CONTINUE, GOTO, PRINT, interactive INPUT, user recursion, division/remainder, floating point, imports/modules and runtime file I/O remain unsupported.

## Migrating source and artifacts

FOR, TO, STEP and NEXT are now reserved case-insensitively. Rename affected declarations and every reference, including boundary JSON keys when fields change. For example, rename `DIM step = 1` to `DIM stride = 1`. Do not rename string contents or comments merely because they contain these words.

Old manifests require the old compiler; new manifests require the new one. A new reader rejects old compiler/language identities with E0400 even if a non-loop puzzle's bytes are unchanged. Keep old artifacts and their matching tools, rebuild new artifacts into a separate directory, and compare puzzle identities. Never edit manifest version fields to force acceptance. A changed puzzle hash cannot update an existing coin's rules.
