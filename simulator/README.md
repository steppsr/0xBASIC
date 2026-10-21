# Isolated M4 simulator environment

M4-1 Windows smoke verified with Python 3.13.7, Chia 2.7.4 and chia_rs 0.48.0. Linux x86_64/glibc lock is resolved but execution is pending user confirmation. Compiler version and the 274 Windows / 275 Linux Rust tests are unchanged.

The harness runs in-process SpendSim with an in-memory database. It farms one block, checks two reward records through SimClient, verifies an empty mempool and closes resources. It does not submit or sign a spend and does not prove payment authorization. First farmed block is recorded by this upstream simulator at height 0; coin-store confirmation indexes are recorded separately rather than assumed equal.

## Locked inputs

- `requirements.in`: selected simulator versions; platform `.lock` files contain complete runtime pins and permitted package SHA-256 hashes (71 Windows, 72 Linux packages).
- `build-requirements.lock`: pinned and hashed build-tool dependency set, supplied as uv build constraints. Source-only dependencies include chia-base, chialisp-loader and chialisp-puzzles. Runtime archives are hash-verified; build constraints pin build-tool versions. This is not a claim of byte-identical rebuilt wheels across operating systems.
- `tools.lock`: hash-locked uv 0.9.4 bootstrap, separate from runtime packages.
- `profile.json`: selected source-reference commit and hashes of the reviewed SpendSim, mempool manager and constants modules. Install the hash-locked release distribution, whose three module files match the reviewed commit; no checkout/editable install is required. This refines the initial plan's checkout-based recipe without changing selected upstream code.

Do not regenerate locks during ordinary installation. A lock change needs review and a fresh smoke on both platforms. `uv pip check` checks dependency consistency; `smoke.py` checks locked runtime versions and source files before importing simulator code. Reports include the actual Python patch version; Python 3.13.7 is the reproducible setup choice, although the smoke accepts and records other 3.13 patches.

## Windows setup (PowerShell, project root)

The existing development machine has Python 3.13.7. Use a fresh `.work/m4/tools` bootstrap environment; keep installer and package caches under the project.

```powershell
New-Item -ItemType Directory -Force .work/m4/tmp | Out-Null
$env:TEMP = "$PWD/.work/m4/tmp"
$env:TMP = $env:TEMP
$env:UV_CACHE_DIR = "$PWD/.work/m4/uv-cache"
python -m venv .work/m4/tools
.work/m4/tools/Scripts/python.exe -m pip --isolated install --cache-dir .work/m4/pip-cache --require-hashes -r simulator/tools.lock
.work/m4/tools/Scripts/uv.exe venv --python 3.13.7 --no-python-downloads .work/m4/venv
.work/m4/tools/Scripts/uv.exe pip install --python .work/m4/venv/Scripts/python.exe --require-hashes -r simulator/requirements-windows.lock --build-constraints simulator/build-requirements.lock
.work/m4/tools/Scripts/uv.exe pip check --python .work/m4/venv/Scripts/python.exe
.work/m4/venv/Scripts/python.exe simulator/smoke.py
```

Stop on any failed setup command. If the environment already exists, skip its creation rather than replacing it; reinstall from the locks and run checks. Existing project `.work/m4/venv` and `.work/m4/verification-venv` both passed. No global Python packages or existing Chia configurations were changed.

## Linux setup (project root on a native Linux filesystem)

Use a native Linux copy of the project containing these current local files, not the Samba working tree. Use the current repository revision containing the `simulator` directory. Copy source and tracked inputs; do not copy Windows `.work` or `target` directories. Choose the Linux project directory yourself; the commands below write only inside that copy. Existing Linux Cargo target configuration can remain separate.

Python 3 with venv support bootstraps the installer. If system Python is 3.12, it is sufficient for this bootstrap; uv installs the selected 3.13.7 interpreter locally. No system Python replacement or sudo is required by this recipe.

```sh
set -e
mkdir -p .work/m4/tmp
export TMPDIR="$PWD/.work/m4/tmp"
export UV_CACHE_DIR="$PWD/.work/m4/uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.work/m4/python"
python3 -m venv .work/m4/tools
.work/m4/tools/bin/python -m pip --isolated install --cache-dir .work/m4/pip-cache --require-hashes -r simulator/tools.lock
.work/m4/tools/bin/uv python install 3.13.7 --install-dir "$UV_PYTHON_INSTALL_DIR" --no-bin
.work/m4/tools/bin/uv venv --python 3.13.7 --managed-python --no-python-downloads .work/m4/venv
.work/m4/tools/bin/uv pip install --python .work/m4/venv/bin/python --require-hashes -r simulator/requirements-linux.lock --build-constraints simulator/build-requirements.lock
.work/m4/tools/bin/uv pip check --python .work/m4/venv/bin/python
.work/m4/venv/bin/python simulator/smoke.py
```

Initial installation needs internet; the smoke itself uses no RPC/node service. If system venv support or a compatible package is unavailable, report the failing command rather than changing pins. Do not run a global `pip install`, initialize Chia roots, or import production keys.

## Results and next step

Successful output begins `PASS: isolated SpendSim farmed one block`. Upstream may emit a mempool slow-path informational log; it is not a failure. Reports are `.work/m4/smoke-windows.json` or `.work/m4/smoke-linux.json`. They record observed coin IDs, heights, constants, base flags, derived mempool prevalidation flags, runtime versions and lock/source digests. Signature validation has not been exercised because this smoke submits no bundle.

Windows evidence: dependency check passed, module hashes matched, one-block smoke passed, and a second clean environment installed offline from cache passed the same smoke. Global-Python invocation was correctly rejected. Linux still needs the setup/smoke above. Rust tests need not be rerun for this checkpoint. No simulator CI job is added until both platform setups are confirmed; later M4 integration will add it separately from compiler checks.

After Linux confirmation proceed to M4-2: fund a real simulator coin for the compiled payment puzzle, independently derive/sign its message, and confirm one authorized payment. See the [M4 plan](../docs/spec/m4-validation-plan.md).
