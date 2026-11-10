# Experimental fee-payment release review

Prepared and explicitly approved/published 2026-11-09. [Download the prerelease](https://github.com/steppsr/0xBASIC/releases/tag/v0.3.0-alpha.1-experimental). Remote tag and all five uploaded sizes/SHA-256 digests match the reviewed candidate. Published tag: `v0.3.0-alpha.1-experimental`. Title: **0xBASIC 0.3.0-alpha.1 — Experimental fee-aware payments**. Published as a prerelease, not latest stable, targeting exactly [`e7e97b3c03b983250bd352579b04a5384578a9ea`](https://github.com/steppsr/0xBASIC/commit/e7e97b3c03b983250bd352579b04a5384578a9ea). Subsequent review documentation does not change the selected revision. Compiler 0.3.0-alpha.1, language 0.3, ABI/schema 1, profile chia-clvm-0.19-strict-v2.

## Candidate assets

Original CI archives from [package run 42736695743](https://github.com/steppsr/0xBASIC/actions/runs/42736695743), with no local rebuilding or repacking. Staged under `.work/releases/v0.3.0-alpha.1-experimental/assets/`; published release text is the adjacent `release-notes.md`.

| Archive | Bytes | SHA-256 |
| --- | ---: | --- |
| `0xbasic-0.3.0-alpha.1-experimental-x86_64-pc-windows-msvc.zip` | 23,859,344 | `0094eb96018c167e295edb122f7888b4ed276e0987d83a6819f3687774fca1d3` |
| `0xbasic-0.3.0-alpha.1-experimental-x86_64-unknown-linux-gnu.tar.gz` | 24,008,550 | `63f41ed9ddc53642fc7c790c1185068ed97e5ab0d46dfb2da0be7eb4abc5e726` |

Five published assets: two archives, their two SHA-256 sidecars, and `release-manifest.json`. Each archive includes full application and 134 locked crate sources, notices/rebuild instructions, payment/loop/fee examples, `LOOPS.md` and `FEES.md`. The source archive includes the language 0.3 specification and complete fee tutorial.

## Verification

[Compiler](https://github.com/steppsr/0xBASIC/actions/runs/42736695887), [simulator/full-node](https://github.com/steppsr/0xBASIC/actions/runs/42736695978) and [package/extracted-smoke](https://github.com/steppsr/0xBASIC/actions/runs/42736695743) CI passed on the selected revision. Windows and native LANDO gates passed, confirmed on 2026-11-09. The [milestone review](fee-payment-review.md) explains the validation layers.

Downloaded archives match their sidecars, every internal payload hash, all embedded source inventory hashes and the selected Git revision's compiler-source hashes. Both build and independent extraction reports identify these exact archive digests. Each source archive has 9,073 verified inventory entries. Both offline rebuilds' fee and loop hashes, costs and outputs match the packaged binary. Each platform passed nine package tests and 30 extracted CLI checks. The exact downloaded Windows archive additionally passed all 30 checks locally with empty PATH outside the checkout. The Linux executable was not run on this Windows host; hosted Linux evidence covers it.

Downloaded fee SpendSim reports confirm 20 scenarios/14 rejections/20 controls per run and two identical fresh runs. Full-node reports confirm four fee rejections, three fee control bundles, exact fees 11/10/30, preserved rejected coins and outputs, closed resources and no network services. Combined full-node coverage is 14 rejections/seven controls. Candidate audit evidence is retained alongside the staged assets.

## Runtime scope and migration

Windows build and extracted smoke used Windows Server 2025, image windows-2025-vs2026 version 20261103.298.1. Linux used Ubuntu 26.04.1/glibc 2.43, image ubuntu-26.04 version 20261101.186.1. LANDO source builds and Ubuntu 24.04 simulator jobs do not establish that the distributed Linux binary runs on older glibc. No older-runtime, macOS, ARM or static/musl certification is claimed.

RESERVE_FEE is reserved case-insensitively. Rename conflicting identifiers/JSON fields and rebuild sources with the selected compiler. Older compiler/language/profile artifacts fail E0400; preserve them with the old compiler rather than editing identities. Fee reservation is an additive aggregate minimum, not an exact cap or per-input guarantee. Local execution remains clvm-execution-only; no wallet, production-key or public-network integration is included.

Existing project/dependency attribution, notices and modified-library rebuild provisions are preserved. This is an engineering distribution review, not a production audit. Existing 0.1 and 0.2 releases remain unchanged.

## Publication decision

Explicit publication approval was received on 2026-11-09. The release was published with the reviewed tag, exact source revision and five assets. GitHub confirms prerelease status; remote tag resolution, release notes, asset inventory and every uploaded size/SHA-256 digest were verified. No additional native testing is required. Existing older releases remain unchanged.
