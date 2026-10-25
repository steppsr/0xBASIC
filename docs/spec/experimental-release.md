# Experimental release: v0.1.0-m3.8b-experimental

Published 2026-10-25 after explicit release approval. [Download the prerelease](https://github.com/steppsr/0xBASIC/releases/tag/v0.1.0-m3.8b-experimental).

This first experimental preview packages the typed BASIC-to-CLVM compiler for native x86_64 Windows and Linux. It is intended for evaluation and development; it is not a production or mainnet readiness claim.

Compiler version: `0.1.0-m3.8b`; ABI: `1`. Source revision: [`b9411b67e9923549f9355eeb0c1eb5910da64368`](https://github.com/steppsr/0xBASIC/commit/b9411b67e9923549f9355eeb0c1eb5910da64368). The M5 work adds validation, documentation and distribution materials without changing compiler semantics or dependencies.

## Included

- Native `0xbasic` CLI: `check`, `build`, `run`, and `explain`.
- Typed scalar/collection values, functions, contract parameters and solution fields, and explicit Chia condition emission.
- Payment example, public example bindings, usage guide and package provenance.
- Complete application and locked dependency sources in `source.tar.gz`, third-party notices, and offline rebuild/library-modification instructions in `REBUILD.md`.

## Downloads and runtime scope

Choose the Windows MSVC ZIP or Linux GNU tar.gz below, and verify it with its adjacent SHA-256 file. `release-manifest.json` records exact assets, hashes, source revision, test environments and CI runs. Checksums establish integrity, not a publisher signature.

The distributed binaries were built and exercised on Windows Server 2025 (`windows-2025-vs2026`, image `20261021.278.1`) and Ubuntu 24.04.5 with glibc 2.39 (`ubuntu-24.04`, image `20261012.334.1`). These are tested environments, not a claim of minimum-version compatibility. Older Windows/glibc versions, macOS, ARM and musl/static binaries are not certified by this preview. Ordinary host runtime libraries remain prerequisites. Rust is unnecessary for the exercised binary commands; rebuilding requires the toolchains described in `REBUILD.md`.

Keep each archive's source and notice materials with its executable when redistributing. The automatic GitHub source downloads are repository snapshots; the binary archives additionally carry the vendored dependency source bundle.

## Validation

All checks passed on the exact release revision:

- [Compiler CI](https://github.com/steppsr/0xBASIC/actions/runs/40162973936): Windows/Linux format, lint, Rust tests, conformance, 653 generated/regression CLI calls and nine tutorial commands.
- [Simulator/full-node CI](https://github.com/steppsr/0xBASIC/actions/runs/40162973891): isolated payment lifecycle, rejection/replay scenarios, reproducible reports, and confirmed full-node payment on both platforms.
- [Package CI](https://github.com/steppsr/0xBASIC/actions/runs/40162973924): four integrity tests, offline original-source and modified-library rebuilds on both platforms, plus eight CLI checks and 8,970 source-file checks in separate extracted-smoke jobs.

Native Windows and Linux testing also passed. Regression input fingerprints normalize CRLF/LF checkout differences; compiled bytes, puzzle hashes, output and cost expectations remain exact.

## Compatibility and limitations

Artifacts require matching compiler/language/ABI/profile/schema identities. Preserve source and bindings and rebuild when upgrading; do not edit manifest identities to force compatibility. See the [compatibility policy](https://github.com/steppsr/0xBASIC/blob/b9411b67e9923549f9355eeb0c1eb5910da64368/docs/spec/experimental-compatibility.md) and [implemented reference](https://github.com/steppsr/0xBASIC/blob/b9411b67e9923549f9355eeb0c1eb5910da64368/docs/spec/implemented-reference.md).

`run` performs local CLVM execution. It does not sign transactions, connect to wallets/nodes, or establish coin existence or confirmation. The isolated integration tests do not provide wallet/RPC integration, a production audit, or testnet/mainnet deployment certification.

## Project and dependency attribution

Published from the [steppsr/0xBASIC repository](https://github.com/steppsr/0xBASIC), maintained under the GitHub account `steppsr`. Project code is distributed under its existing Apache-2.0 LICENSE; dependencies retain their own licenses and copyright notices. This release does not assign ownership of third-party work or replace its terms. `THIRD-PARTY-NOTICES.txt` and the bundled sources preserve dependency notices, including the pinned Malachite library terms; `REBUILD.md` documents rebuilding with modified libraries.
