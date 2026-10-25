# M5-3: generated-input and regression checkpoint

Status: Windows and native Linux passed, 2026-10-24; Linux success confirmed by the user. M5-2 native Linux tests passed as confirmed by the user. This checkpoint adds verification tooling, frozen observations and a compiler CI step; it changes no compiler code, version, ABI, dependencies or Rust test counts (277 Windows / 278 Linux).

## Repeatable corpus

`tools/verify_m5.py` uses a specified 32-bit xorshift generator seeded with `0x0b451503`, rather than platform randomness. It requires only Python's standard library and the existing project verification helper. Every CLI invocation has a ten-second timeout and must return a handled, valid JSON envelope without stderr or E9000. Unexpected process exits, panics, timeouts, invalid JSON and mismatched expectations fail the gate.

| Family | Cases | Required evidence |
| --- | ---: | --- |
| Source byte mutations | 128 | One to four insert/delete/replace edits of a valid small contract; `check`/`build` agree on acceptance and diagnostics; rejection publishes no output directory |
| Arithmetic controls | 32 | Generated nonnegative expressions produce independently calculated `left + right * 3` conditions |
| Boundary controls | 64 pairs | Canonical INTEGER/BOOLEAN JSON and independently serialized raw solutions have identical output and cost; emitted height matches the generated integer |
| Invalid JSON boundaries | 64 | Eight families including wrong scalar types, noncanonical integer, absent/extra fields, duplicate/case-colliding keys and broken JSON; E0300 |
| Invalid raw ABI trees | 64 | Six families including noncanonical integer, invalid/paired unused BOOLEAN, improper list and wrong arity; E0500 despite valid serialization |
| Damaged manifests | 64 | Unsupported schema/compiler versions, escaped binary path, wrong tree hash, bad provenance, unknown/missing/duplicate fields; E0400 or E0600 as appropriate |
| Frozen regression examples | 3 | Exact source/binding identities, template/puzzle byte lengths, puzzle byte/tree hashes, output and cost; execution succeeds at exact cost and fails at one less |

Total: **653 CLI invocations**. This is a finite, bounded mutation corpus with positive controls, not an exhaustive fuzzer or a security audit. Random source mutations may remain valid; success is permitted when check/build agree. The raw ABI mutations test generated guards, not malformed CLVM deserialization. Existing conformance tests retain coverage for serialization and larger structural/resource limits. New failures must be minimized into permanent regression fixtures before being considered resolved; do not merely change the seed or weaken an expectation.

Each run retains inputs/artifacts beneath a unique ignored `.work/m5/generated-*` directory. `active-case.json` records the last case ID and command before process launch; the last stdout/stderr files aid diagnosis. On failure, the exception identifies that directory. Re-running the fixed seed with the same code reconstructs the earlier cases, while the active failing input remains on disk. No failures were found by the initial Windows corpus, so no minimized crash fixture was needed.

Prior aggregate success is removed before preflight. Only a fully successful run atomically publishes `.work/m5/generated-windows.json` or `generated-linux.json`, recording counts, seed, binary/verifier/baseline digests. Run one verifier at a time per checkout. Windows/Linux binary digests can differ; the fixed generated cases and baseline observations must pass on both.

## Frozen baseline

[m5-regression-baseline.json](m5-regression-baseline.json) was captured from compiler `0.1.0-m3.8b` on 2026-10-24. These are observed regression values, not an independently derived proof of correctness. Independent arithmetic/boundary oracles and the existing compiler/payment conformance suites serve different purposes. Earlier M1/M2 golden fixtures are unchanged.

| Existing example | Bound puzzle bytes | Local VM cost |
| --- | ---: | ---: |
| `m2-strings.bas` | 395 | 6,159 |
| `m2-list-operations.bas` | 715 | 15,626 |
| `height-locked-payment.bas` with committed bindings | 2,109 | 1,487,727 |

The verifier has no baseline-update switch. A deliberate code-generation or profile change requires reviewing byte/hash/size/cost differences and compatibility implications before updating the fixture. These are local execution costs, not consensus spend costs. The fixture preserves full output trees as well as costs; a cheaper incorrect result does not pass.

## Native Linux verification

From the same native checkout used for the successful M5-2 tests, run:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/tools/verify_m5.py tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/m5-regression-baseline.json docs/spec/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
if [ ! -x "$CARGO_TARGET_DIR/debug/0xbasic" ]; then
    cargo build --workspace --locked
fi
python3 tools/verify_m5.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

The shared verification helper, examples and bindings already exist in the previously tested checkout. No package installation, Rust-suite rerun or simulator run is required. The conditional build is only for a missing executable. The changes remain local until publication; `git pull` alone cannot obtain them yet.

Expected: six PASS lines, ending with `PASS: M5 generated-input and regression checks (653 CLI calls).` followed by the report path. The verifier prints its retained input directory before starting. Each family prints progress as it completes. A failure provides its case ID and directory; retain those for investigation.

Windows verification: all 653 invocations and all three frozen baselines passed; `git diff --check` passed. The existing compiler workflow now runs this tool on both platforms after the conformance steps; no hosted result is claimed for this unpublished change. After native Linux confirmation, proceed to M5-4 implemented-feature reference and payment tutorial.

Regression input fingerprints normalize CRLF to LF to match Git text fixtures, including rsync copies from Windows. Compiled byte/hash/cost/output expectations remain exact and unchanged. This normalization applies only to regression input fingerprints; compiler artifact provenance continues to hash the actual source bytes.
