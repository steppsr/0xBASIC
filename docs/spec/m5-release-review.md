# M5-6 experimental release review

Review closed: 2026-10-25. **M5 experimental release approved and published.** [Release `v0.1.0-m3.8b-experimental`](https://github.com/steppsr/0xBASIC/releases/tag/v0.1.0-m3.8b-experimental) points to `b9411b67e9923549f9355eeb0c1eb5910da64368`. Compiler `0.1.0-m3.8b`, ABI 1 and dependency locks are unchanged. The [release record](experimental-release.md) documents scope, runtime baselines and attribution.

## Verified evidence

Update: the [source-inclusive distribution checkpoint](source-distribution.md) now supplies all 134 locked crate sources, authoritative supplemental notices and rebuild instructions. Windows passed four rejection tests, two offline source rebuilds (including a modified Malachite library), 8,969 source-file checks and both eight-command extracted checks. Native Linux verification of this revised layout passed, as confirmed by the user on 2026-10-24. The original M5-5 evidence and dependency findings below describe the earlier binary-only candidate; its missing-material finding is superseded by this implementation, and the final review/publication gates are now complete.

| Gate | Windows | Native Linux |
| --- | --- | --- |
| M5-1 full-node block/payment lifecycle | Passed, local reports | Passed, user confirmed |
| M5-2 compatibility and diagnostic contract | 277 Rust tests; format/lint passed | 278 Rust tests; format/lint passed, user confirmed |
| M5-3 generated inputs and frozen regressions | 653 CLI invocations passed | Passed, user confirmed |
| M5-4 documented payment commands | Nine commands and result assertions passed | Passed, user confirmed |
| M5-6a source-inclusive package | Four rejection tests, two offline rebuilds, source inventory and eight extracted CLI checks passed | All checks passed, user confirmed |
| M5-5 original native package | Three rejection tests; eight extracted CLI checks; standalone verifier passed | All packaging/extracted checks passed, user confirmed |

Linux evidence is explicitly user-confirmed; this Windows review did not independently inspect the Linux report files or archive checksum. Preserve those native outputs for publication review. No Linux suite needs repeating for the present inventory/documentation/CI changes.

## Dependency distribution finding

`tools/audit_release.py` traverses the locked Cargo normal/build dependency graph separately for Windows MSVC and Linux GNU, excluding dev-only edges. Its [inventory](dependency-license-inventory.json) records 124 Windows and 125 Linux third-party packages, declared license expressions, a dependency path, and SHA-256 hashes of available license/copying/notice files. Build-only dependencies are included conservatively. This is neither a linked-symbol analysis nor a legal-compliance determination.

Both graphs include:

```text
oxbasic-cli -> oxbasic-compiler -> clvmr 0.19.0 -> malachite-bigint 0.9.2
malachite-bigint -> malachite-base / malachite-nz 0.9.2
```

All three Malachite packages declare `LGPL-3.0-only` in their installed crate metadata. `clvmr` lists `malachite-bigint` as a normal dependency, and Cargo's active feature graph includes its default/std features. The compiler's runtime profile leaving the MALACHITE dialect flag disabled is not evidence that no Malachite code is present in a binary or that distribution review can be skipped.

The initial registry inspection found missing license/copying/notice-named files for eight packages. The source-inclusive implementation now supplements those files from exact upstream commits, verifies their digests and source revisions, and assembles notices for all 134 locked crates. Every candidate includes complete vendored application/dependency sources and rebuild instructions. Both platforms passed an offline original-source build and a build with a modified local Malachite library.

The engineering distribution-material gate is complete for source-inclusive CI candidates. The earlier binary-only candidates are superseded. This records the tested source/rebuild arrangement and does not constitute an independent legal opinion or authorization for a tagged release. Compiler/runtime dependencies remain unchanged.

Reproduce the metadata inventory from a populated dependency cache with `python tools/audit_release.py`. It uses `cargo metadata --locked --offline` and writes no files outside the project. Missing registry source/cache data is an error, not permission to silently omit a package.

## Hosted verification and release scope

The release targets `b9411b67e9923549f9355eeb0c1eb5910da64368`. All exact-revision hosted workflows passed: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/40162973936), [simulator/full-node](https://github.com/steppsr/0xBASIC/actions/runs/40162973891), and [packages/extraction](https://github.com/steppsr/0xBASIC/actions/runs/40162973924). Both platforms passed two offline source rebuilds, including a modified library. Independent extraction reports verified 8,970 source files and eight CLI commands per platform.

The release contains the unchanged CI archives, their SHA-256 sidecars and a release manifest. GitHub's uploaded digests match the verified files. The tag resolves to the tested source commit. The release is marked prerelease, not latest stable.

Runtime scope remains x86_64 Windows MSVC and Linux GNU on tested hosts. Empty PATH/outside-checkout smoke proves the exercised CLI operations do not need the Rust tools or source checkout; it is not a pristine-OS or broad Windows/glibc compatibility certificate. Record the final supported OS/runtime baseline with the chosen release assets. macOS, ARM, musl/static linking, wallet/RPC integration, testnet deployment and production audit are outside this candidate's claims.

The approved title is “0xBASIC 0.1.0-m3.8b — Experimental preview.” Attribution identifies the verified `steppsr/0xBASIC` repository and maintainer account, retains the project's Apache-2.0 LICENSE and preserves dependencies' own terms/notices. It does not invent a legal copyright owner. The standard Apache appendix remains unchanged. Explicit final publication approval was received on 2026-10-25.

## Completion and next scope

M5 is complete for this experimental scope. No additional native tests are required. Further specifications/documentation work should distinguish the implemented subset from future language features and wallet/network integration; this prerelease does not authorize or claim production deployment.
