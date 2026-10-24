# Contributing to 0xBASIC

The project is in early development. Open an issue before proposing a major syntax, ABI, dependency, or architecture change so implementation work can follow an agreed design. Small fixes and reproducible bug reports are welcome.

## Build and test

Use the pinned Rust toolchain and committed Cargo.lock. Python 3.13 is used in CI for the standard-library verification scripts.

```text
cargo build --workspace --locked
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
python tools/verify_m0.py
python tools/verify_m1.py
python tools/verify_m3_inputs.py
python tools/verify_m3_bindings.py
python tools/verify_m3_scalars.py
python tools/verify_m3_strings.py
python tools/verify_m3_pairs.py
python tools/verify_m3_lists.py
python tools/verify_m3_domains.py
python tools/verify_m3_publickeys.py
python tools/verify_m3_payments.py
python tools/verify_m3_signatures.py
python tools/verify_m3_explain.py
python tools/verify_m3_conformance.py
```

On Linux, use `python3` if `python` is unavailable. The [CI workflow](.github/workflows/ci.yml) lists the complete conformance commands, including earlier language features. Run checks relevant to your change; CI runs the full matrix on Windows and Linux.

When building Linux sources from a Windows/Samba share, place compiled executables on a Linux filesystem:

```sh
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
mkdir -p "$CARGO_TARGET_DIR"
cargo build --workspace --locked
python3 tools/verify_m1.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

Use each verifier's `--help` for binary selection and optional reference modes. Never share a Cargo target directory between Windows and Linux.

## Changes and reviews

- Keep changes focused and explain the behavior they introduce or fix.
- Add meaningful positive and negative cases for compiler or ABI changes, including raw CLVM input where boundary validation is involved.
- Update examples and public specifications when observable behavior changes. Clearly label features that are still planned.
- Preserve deterministic artifacts, condition order, and the distinction between CLVM execution and spend validation.
- Do not commit generated build directories, local caches, secrets, or wallet data.

A typical contribution uses a branch and pull request. Include the problem, the resulting behavior, and the checks you ran. Do not change lockfile dependencies incidentally to an unrelated fix.

## Repository layout

| Path | Purpose |
| --- | --- |
| `crates/compiler` | Parser, type checking, lowering, CLVM generation, and compiler tests |
| `crates/cli` | Commands, artifacts, diagnostics, and CLI integration tests |
| `examples` | Working feature examples and explicitly planned conformance examples |
| `docs/spec` | Grammar, ABI, schemas, target profile, and test vectors |
| `tools` | Independent verification and upstream inspection scripts |

The repository uses the [Apache-2.0 license](LICENSE).

## Simulator integration

The optional [M4 simulator environment](simulator/README.md) has separate platform locks and a one-block smoke test. It is not needed to build or run the compiler. Environment smoke and signed payment passed on both platforms; height/signature and mutation suites also passed on both platforms; use a native Linux project copy, not a Windows virtual environment over Samba.
