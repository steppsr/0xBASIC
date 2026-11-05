# Loop package and offline rebuild validation

Status: Windows and native Linux (LANDO) passed. The tester confirmed Linux success on 2026-11-05. This follows the published loop-payment checkpoint and CI runner correction at `00005d0ef9af6bf84788e0bcde3717d5972f9166`. Compiler `0.2.0-alpha.1`, language `0.2`, ABI 1 and dependency versions are unchanged. These are development package checks; they do not publish a release or tag.

## Package coverage

New candidate archives include `examples/counted-heights.bas` and `LOOPS.md`, the [packaged loop walkthrough](package-loops.md). The standalone verifier uses only extracted files, an empty PATH and unavailable Cargo/Rustup homes. It checks the original payment baseline plus the loop example through check, all three explain stages, build and run. Loop results must equal the independently constructed condition tree `((83 5) (83 3) (83 1))`. Inspection hashes must agree with the built bytes; execution at the exact observed cost must succeed and one less must fail with E0501. Rebuilding into the same directory must fail with E0600 and preserve every artifact byte.

The resulting 17 extracted CLI commands include the existing eight payment/version/help commands and nine loop commands. The verifier records loop program SHA-256, tree hash, cost and result. It retains the legacy path for existing `0.1.0-m3.8b` archives; old release assets are unchanged.

The source archive explicitly requires the four FOR/NEXT implementation modules, public loop integration tests, counted-height and payment fixtures, language 0.2 specification and source tutorial. It also includes the root language/architecture/development documentation and the supporting README, workflow and simulator files referenced by the curated docs. Python simulator sources and locks are reference inputs; an offline Cargo rebuild does not provide an offline Python installation.

Both offline rebuilds execute the loop checks: first original sources with an empty Cargo cache, then a locally modified Malachite source override. Their loop byte hashes, tree hashes, costs and results must match the packaged executable. Legacy payment tree/result/cost checks and verification of the actual local library override remain required. Source/package inventories and hashes are checked before execution; regression tests reject archives missing the new loop materials.

## Validation and reports

Package construction calls the full verifier with both offline rebuilds. A separate standalone verifier run checks the resulting archive again without rebuilding sources, matching the extracted-smoke CI job. Report fields include `commands_passed`, `offline_rebuilds`, `rebuilt_loops` and `packaged_loop`. The two rebuilt-loop entries must equal the packaged-loop entry. In the standalone report, `offline_rebuilds` is zero because that run only exercises the archived executable.

Windows validation passed all six rejection tests, all 17 extracted CLI commands, both offline rebuilds and the independent standalone verification. Bundled curated documentation links were checked against the source inventory with no missing targets. The loop fixture cost is `43832`, program SHA-256 is `a2c1eb0f5fa4775b1e245975be846763fe83530e13b4825d3ffacda7a3f49172`, and tree hash is `51b586eaa58af4e0764cc27c6798002df5329b06f873a523290cbff51d5d31f0`. These observations matched across the archive executable and both rebuilds. Windows evidence is `.work/packages/package-windows.json` and `.work/packages/extracted-loops-windows.json`.

## Native Linux commands

Run from LANDO's existing native checkout. The subshell restores the Cargo environment and stops on failure without closing SSH. No simulator environment or Rust test-suite rerun is needed for these packaging-only changes. The offline source rebuilds may take several minutes; toolchain installation and initial package assembly can use the network, but both extracted-source builds run with Cargo offline.

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a /mnt/artoo/e/DEV/0xBASIC/tools/ tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
python3 tools/verify_m0.py
python3 -m unittest discover -s tools -p test_package.py
python3 tools/package_experimental.py
python3 tools/verify_package.py \
  .work/packages/0xbasic-0.2.0-alpha.1-experimental-x86_64-unknown-linux-gnu.tar.gz \
  --report .work/packages/extracted-loops-linux.json
)
```

Expected: six package rejection tests pass, construction reports 17 extracted CLI commands and succeeds after both offline rebuilds, and standalone verification reports 17 commands with empty PATH. Preserve `.work/packages/package-linux.json` and `.work/packages/extracted-loops-linux.json` as evidence.

After native confirmation, publish this checkpoint and verify exact-revision CI. Next is release documentation and a concrete candidate review, with separate approval before publishing a new release.
