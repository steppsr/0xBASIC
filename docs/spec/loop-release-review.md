# Experimental counted-loop release review

Prepared 2026-11-05; explicitly approved and published 2026-11-06. [Download the prerelease](https://github.com/steppsr/0xBASIC/releases/tag/v0.2.0-alpha.1-experimental). Remote tag resolution and all five uploaded SHA-256 digests/sizes match the reviewed candidate.

Published tag: `v0.2.0-alpha.1-experimental`. Title: **0xBASIC 0.2.0-alpha.1 — Experimental counted loops**. Published as a prerelease, not latest stable, targeting exactly [`5f68dab6e415bc700efc41ff3269e0e378b1ed22`](https://github.com/steppsr/0xBASIC/commit/5f68dab6e415bc700efc41ff3269e0e378b1ed22), the tested package checkpoint. This review document is subsequent documentation and does not change the selected source revision. Compiler `0.2.0-alpha.1`, language `0.2`, ABI 1. The existing [0.1 release](experimental-release.md) remains unchanged.

## Candidate assets

Use the original CI archives, not locally rebuilt replacements. They were downloaded from [package run 42061731179](https://github.com/steppsr/0xBASIC/actions/runs/42061731179), and are staged with their checksum sidecars and `release-manifest.json` under `.work/releases/v0.2.0-alpha.1-experimental/assets/`. Draft publication text is the adjacent `release-notes.md`.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `0xbasic-0.2.0-alpha.1-experimental-x86_64-pc-windows-msvc.zip` | 23,793,351 | `b578351ee2f8b09762c78d33746dc499155a7542d9c6e1bcbb18f0f48bf5c32d` |
| `0xbasic-0.2.0-alpha.1-experimental-x86_64-unknown-linux-gnu.tar.gz` | 23,943,607 | `70f986bd695c0d0c058b5ee06ad23f94aa0636dcb81e92a9235d35e43c169c3a` |

The release has five uploaded assets: both archives, their two SHA-256 sidecars and the release manifest. Each archive carries complete application and 134 locked crate sources, notices and rebuild instructions, plus the packaged payment/loop examples and `LOOPS.md`.

## Evidence

All three workflows passed on the selected revision: [compiler](https://github.com/steppsr/0xBASIC/actions/runs/42061731159), [simulator/full-node](https://github.com/steppsr/0xBASIC/actions/runs/42061731137), and [packages/extraction](https://github.com/steppsr/0xBASIC/actions/runs/42061731179). Native Windows and LANDO Linux checks passed before publication of that source checkpoint.

Downloaded archives were checked against their sidecars, all internal payload hashes, all 9,031 source inventory entries and the selected Git revision's compiler-source hashes. Build and independent extraction reports identify the same archive digests. Both offline rebuilds' loop hashes, cost and output match the packaged binary. Each platform passed six archive rejection tests and 17 extracted CLI checks. The exact downloaded Windows archive was additionally verified locally with empty PATH and outside the checkout. Linux executable behavior is supported by the hosted Linux reports; it was not executed on this Windows review host.

Downloaded simulator reports confirm two identical SpendSim runs, the original 15-scenario suite and the additional loop payment with six rejections and exactly three children. The full-node reports confirm the corresponding loop result and resource cleanup on both platforms. These are isolated test-chain results.

## Tested runtime scope

| Platform | Build environment | Separate extracted smoke |
| --- | --- | --- |
| Windows x86_64 MSVC | Windows Server 2025, `windows-2025-vs2026` image `20261030.294.1` | Same OS/image family, image `20261103.298.1` |
| Linux x86_64 GNU | Ubuntu 26.04.1, glibc 2.43, `ubuntu-26.04` image `20261025.179.1` | Same OS/glibc, image `20261101.186.1` |

Linux simulator CI uses Ubuntu 24.04 separately because of its pinned Python 3.13.7 setup. It does not establish compatibility of the packaged release binary with Ubuntu 24.04. This candidate makes no older-glibc, macOS, ARM, musl/static or pristine-OS certification claim. LANDO source-build success is additional native evidence, not proof that every downloaded binary runs on older hosts.

## Migration and release scope

FOR, TO, STEP and NEXT are reserved case-insensitively. Rename old identifiers and corresponding binding/solution JSON fields, and rebuild source into a fresh directory. Preserve old artifacts with the old compiler. Old/new compiler and language identities intentionally reject one another's manifests; editing manifest versions is not migration. See the [compatibility policy](experimental-compatibility.md) and [loop tutorial](loops-tutorial.md).

Loops add inclusive/snapshotted headers, scoped immutable counters, carried state, nested loops, ordered emissions and function returns through loops. Zero STEP fails when executed; VM cost and existing limits bound execution. WHILE/DO, EXIT/CONTINUE, wallet/RPC integration and network deployment remain outside the implemented scope. Local `run` still means `clvm-execution-only`.

Attribution retains the existing Apache-2.0 project LICENSE and dependencies' own notices, including Malachite source and modification/rebuild instructions. The review verifies engineering distribution materials, not an independent legal opinion or production audit.

## Publication decision

The separate publication approval required by the [activation plan](for-next-activation.md#integration-and-release-gates-after-activation) was received on 2026-11-06. The release was published with the reviewed five assets and exact source revision. GitHub reports prerelease status; remote tag resolution and uploaded digests were verified. No additional user testing is required for publication or these documentation updates. The older release remains unchanged.
