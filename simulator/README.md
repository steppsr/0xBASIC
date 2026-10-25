# Isolated M4 simulator environment

M4-1 Windows smoke verified with Python 3.13.7, Chia 2.7.4 and chia_rs 0.48.0. Linux environment setup and smoke passed, as confirmed by the user. Compiler version and the 274 Windows / 275 Linux Rust tests are unchanged.

The environment smoke harness runs in-process SpendSim with an in-memory database. It farms one block, checks two reward records through SimClient, verifies an empty mempool and closes resources. It does not submit or sign a spend and does not prove payment authorization. First farmed block is recorded by this upstream simulator at height 0; coin-store confirmation indexes are recorded separately rather than assumed equal.

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

Windows evidence: dependency check passed, module hashes matched, one-block smoke passed, and a second clean environment installed offline from cache passed the same smoke. Global-Python invocation was correctly rejected. Linux smoke is confirmed. Rust tests need not be rerun for this checkpoint. Simulator CI integration remains a later M4 checkpoint, separate from compiler checks.

M4-2 now implements one authorized payment, described below. See the [M4 plan](../docs/spec/m4-validation-plan.md).

## M4-2: compiled, signed payment

Windows and Linux single-payment validation passed. `payment.py` invokes the Rust CLI to build the existing height-locked payment example with a deterministic public test key, a known recipient puzzle, amount 1000 and height 10. It verifies artifact hashes with upstream Program, independently constructs the expected conditions/message, and checks local CLI output. It farms test rewards, confirms a funding transaction with exact contract and change outputs, then signs using the actual funded coin ID and synthetic domain data. Upstream signature-pair extraction must agree with the independent derivation.

The signed bundle goes through SimClient prevalidation/mempool acceptance with signature checking enabled. A subsequent farm must consume exactly the contract coin and create exactly its expected recipient child, while leaving funding change unspent. Before/after records and empty final mempool are checked. No user keys, wallet RPC or network funds are used.

Refresh the native Linux project copy with the updated `simulator/payment.py` and `simulator/smoke.py`, preserving its `.work` environment. Use the current repository revision containing `payment.py` and `mutations.py`. Then, from that project root:

```sh
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
cargo build --workspace --locked
.work/m4/venv/bin/python simulator/smoke.py
.work/m4/venv/bin/python simulator/payment.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

On Windows:

```powershell
.work/m4/venv/Scripts/python.exe simulator/payment.py --binary target/debug/0xbasic.exe
```

Success begins `PASS: funded compiled puzzle`. Report: `.work/m4/payment-linux.json` or `payment-windows.json`. Builds use a temporary directory under `.work/m4` and are cleaned up; the report retains manifest identities, bindings, condition bytes, coin/message/signature data and state evidence. Windows repeated runs in both isolated environments produced identical reports. Observed VM costs: CLI and upstream Program both 1,487,727; simulator total spend cost 30,347,727. These labels are intentionally distinct. They are observations of this pinned fixture, not a general consensus cost guarantee.

The acceptance height context is `mempool_manager.peak.height = 10`. This pinned MempoolManager passes that height to `check_time_locks`; the block record's separate `prev_transaction_block_height` is 9. The report retains both to prevent off-by-one assumptions. Inclusion/input-spent/recipient-confirmed height is 11 in the observed run.

This proves one accepted test payment in SpendSim. The M4-3 suite below adds height/signature checks; replay cases and full-node block validation remain future work. No Rust test count change; a fresh CLI build is enough for this checkpoint.

## M4-3: height and signature checks

Windows and Linux M4-3 suite passed. `payment.py --suite` runs seven scenarios in separate fresh simulators and independently builds/funds each fixture:

| Scenario | Required observation |
| --- | --- |
| authorized-at-height | Accept at peak 10, confirm exact payment |
| authorized-after-height | Accept at peak 11, confirm exact payment |
| premature-height | Nonacceptance at peak 9 with ASSERT_HEIGHT_ABSOLUTE_FAILED; farm to 10, accept/promote, then confirm |
| missing-signature | Empty aggregate rejected with BAD_AGGREGATE_SIGNATURE |
| wrong-owner | Other deterministic test key rejected with BAD_AGGREGATE_SIGNATURE |
| message-only-signature | Application message without coin/domain suffix rejected with BAD_AGGREGATE_SIGNATURE |
| wrong-network-domain | Correct key and actual coin but different synthetic domain rejected with BAD_AGGREGATE_SIGNATURE |

Every rejection checks unchanged unspent input, no recipient/child records and an empty active mempool. Each signature-negative case then submits a correct signature for the same coin and confirms the exact payment, proving its setup was otherwise valid. All signature negatives run at peak 10. The premature case permits pending status, verifies the height-9 spend was not included while farming to 10, and checks whether upstream automatically promoted it before attempting resubmission. Windows observed PENDING at 9 and automatic promotion at 10. The other four negative attempts were FAILED.

Refresh the native Linux copy with rsync, preserving `.work` and `target` as before. From the native project root:

```sh
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
.work/m4/venv/bin/python simulator/smoke.py
.work/m4/venv/bin/python simulator/payment.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/payment.py --suite --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

Use the existing compiled CLI; rebuild only if it is missing. No dependency reinstall or full Rust retest is needed. On Windows add `--suite` to the existing payment command. Report: `.work/m4/payment-checks-linux.json` or `payment-checks-windows.json`. It contains seven outcomes, five rejected attempts and seven confirmed positive controls, with actual errors/statuses, signature inputs, peak contexts, state checks and costs. Failure exits nonzero; a previously written report is not evidence that a later failed invocation passed.

Windows smoke and single-payment regression passed. The suite passed twice in the two isolated environments with identical reports. No compiler, lock or Rust test-count change. M4-4 now adds the replay/mutation suite below. This harness does not establish full-node consensus behavior or production safety.

## M4-4: replay, double-spend and payment mutations

Windows and Linux mutation checks passed; Linux success was confirmed by the user. `mutations.py` runs eight independent fresh simulators with real funding transactions and no direct coin-store insertion:

| Scenario | Observed pinned-upstream result |
| --- | --- |
| cross-coin-replay | BAD_AGGREGATE_SIGNATURE for a signature reused on a second coin with identical puzzle/amount and a different parent |
| double-spend | DOUBLE_SPEND after the original payment was confirmed |
| wrong-puzzle-reveal | WRONG_PUZZLE_HASH for a differently bound recipient reveal on the original coin |
| wrong-coin-amount | ASSERT_MY_AMOUNT_FAILED for an actual amount of 1001 against a fixed payment amount of 1000, signed for the actual coin |
| changed-recipient-stale-signature | BAD_AGGREGATE_SIGNATURE on a correctly funded new recipient puzzle using the original coin's signature |
| changed-recipient-resigned | Correctly signed recipient variant accepted and confirmed with exactly its intended child |
| malformed-solution | GENERATOR_RUNTIME_ERROR for a nonempty raw solution where the compiled schema is empty |
| zero-payment-amount | GENERATOR_RUNTIME_ERROR from the contract assertion on fixed zero; not an isolated amount-condition test |

Each rejection verifies unchanged input/child records and an empty active mempool, then farms another block and repeats the state checks. A confirmed double-spend attempt retains its one existing recipient output, rather than expecting zero children. Replay cases retain the signature-source coin unspent and then confirm the target using its own correct signature. Wrong-amount and zero-bound coins cannot be repaired by changing a signature: their positive controls use separately funded valid coins, and the rejected coins remain unspent. All submission contexts are at valid heights. Fixture artifact hashes, independent messages, flags, manifests, actual errors and before/after state invariants are recorded.

Refresh the native Linux project copy with rsync as before, then run:

```sh
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
.work/m4/venv/bin/python simulator/smoke.py
.work/m4/venv/bin/python simulator/payment.py --suite --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/mutations.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

Expected mutation output: eight scenario PASS lines and `PASS: eight replay/mutation scenarios`. Report: `.work/m4/mutations-linux.json` (Windows uses `mutations-windows.json`). Eight confirmed payments and seven rejected attempts are required. Windows runs in both isolated environments produced identical reports; smoke and the seven-scenario M4-3 regression also passed. No lock/compiler changes, package reinstall or full Rust retest are needed. Existing Rust totals remain 274 Windows / 275 Linux.

All 15 planned scenarios and the M4-5 verification gates below have passed on Windows and Linux. M4 is complete. Full-node validation remains a separate pre-release requirement.

## M4-5: complete evidence and reproducible runs

`verify.py` runs smoke, the seven height/signature scenarios and the eight mutation scenarios twice in fresh subprocesses/simulators. It requires exact scenario coverage, expected rejection reasons, confirmed positive controls, closed resources, matching environment identities and the current compiler version. The existing scenario harnesses assert actual coin state and artifact/message correctness. The complete reports from both runs must compare equal; timestamps and temporary paths are not added to this comparison.

The aggregate embeds all three detailed reports, a per-scenario summary, the CLI binary digest and hashes of compiler sources, harnesses, locks, profile, payment source and scenario matrix. Each run must contain 15 confirmed payments and 12 rejected attempts. The runner invalidates its previous aggregate before preflight, removes each old component report before invoking its producer, stops on a failed command and publishes the aggregate only after the second successful audit. Component reports alone are not proof of a complete run. Run only one verification process per checkout at a time because component report names are shared.

Use the existing locked environment; no dependency change or Rust test rerun is required. Build the CLI if it is absent or its sources changed. Windows:

```powershell
.work/m4/venv/Scripts/python.exe -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/Scripts/python.exe simulator/verify.py --binary target/debug/0xbasic.exe
```

Linux, after refreshing the native checkout while preserving `.work`:

```sh
set -e
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/verify.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

Expected: eight reporting tests (12 total with the M5-1a isolation tests) and `PASS: all 15 scenarios, 12 rejections and 15 confirmed payments per run; two identical fresh runs.` Reports are `.work/m4/verification-windows.json` and `verification-linux.json`. Binary/package/environment hashes differ across platforms; equality is required between fresh runs on the same platform, not between Windows and Linux executables.

The separate [simulator workflow](../.github/workflows/simulator.yml) builds the pinned compiler, installs Python 3.13.7 and the existing hash-locked tools/runtime, checks dependencies, runs reporting tests and executes this gate on Windows/Linux. Successful jobs upload their aggregate as `spendsim-evidence-windows` or `spendsim-evidence-linux` for 30 days. Installation uses package registries; scenario execution uses only the in-process simulator. The compiler workflow remains separate.

Platform verification (2026-10-24): the user confirmed all Windows and Linux testing passed, including the eight reporting tests and complete reproducibility runner. This supersedes the earlier restricted Windows temporary-directory failure; both native aggregate gates are closed. Hosted simulator and compiler CI subsequently passed on `75002bb` after correcting the Windows interpreter path. Both evidence artifacts were uploaded; M4 is complete. See the [M5 work plan](../docs/spec/m5-release-plan.md) for CI links and next steps. No compiler, dependency, ABI or Rust test-count change.

SpendSim covers the selected in-process mempool/coin-store lifecycle. A full-node simulator smoke remains required before release. Testnet, wallet/key management and deployment are separate future work.

## M5-1a: full-node environment and block smoke

`full_node_smoke.py` uses the same locked Python 3.13.7 environment, with eight additional upstream source hashes verified against the pinned Chia commit in `full_node_sources.json`. No package installation, compiler rebuild or Rust retest is needed. `tools/inspect_m5_upstream.py` is the networked maintenance verifier used to establish those hashes; ordinary smoke runs check installed bytes locally and do not download sources.

The launcher starts a fresh worker with project-local roots before Chia imports. Each run uses a unique `.work/m5/run-*` directory for config, databases, public test keys/certificates, three k19 plots, temporary files and `output.log`. It constructs FullNode/FullNodeSimulator and manages the actual node database/validation lifecycle without starting peer or RPC listeners, a daemon or wallet. Peer discovery is disabled, a socket guard rejects non-loopback binds/connections, and the upstream unused-port probe is replaced with a loopback-only probe. These are transport/setup adaptations; full-block consensus validation is unchanged. The test keyring uses upstream's file-backed test helper with OS credential storage disabled and is removed on shutdown. Logs, plots and node data remain in the ignored run directory for diagnosis.

The test farms three transaction blocks after genesis and requires each full block to become the validated peak and be retrievable from BlockStore. Confirmed coin records must exactly match the recipient rewards claimed by the full blocks, remain unspent and be retrievable by coin ID. It verifies an empty mempool, no network service or peer connection, and node/keyring cleanup. It does not submit a compiled payment; M5-1b adds that lifecycle after Linux confirmation.

The launcher invalidates old success before startup, enforces a ten-minute worker timeout and publishes the aggregate atomically only after a successful worker exit. Failure leaves the run log for diagnosis and no successful aggregate. Run one smoke per checkout at a time. Full-node hashes/timing may differ across fresh runs; this checkpoint requires semantic assertions, not whole-report equality.

Windows:

```powershell
.work/m4/venv/Scripts/python.exe -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/Scripts/python.exe simulator/full_node_smoke.py
```

Linux: refresh the **native local checkout from these local Windows changes**, preserving its `.work` environment and native build directory. These changes are not yet on GitHub. From the native checkout root:

```sh
set -e
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/full_node_smoke.py
```

Expected: **12 tests** (eight reporting and four full-node isolation/publication checks), then `PASS: full-node blocks and reward records verified; resources closed.` Aggregate: `.work/m5/full-node-smoke-linux.json` (Windows: `full-node-smoke-windows.json`). The fresh chain ends at height 3 with four confirmed recipient reward records and three k19 plots; `resources_closed` is true and `network_services_started` is false. This test does not invoke the Rust CLI, so no binary path or `CARGO_TARGET_DIR` setting is needed.

Windows verification (2026-10-24): all 12 tests passed; the final harness passed with height 3, four reward records, no started network services and successful cleanup. The report's harness digest matches the final source. Restricted execution initially blocked upstream temporary config writes; the final run used normal Windows permissions. The user subsequently confirmed native Linux M5-1a passed. M4 evidence remains valid; do not rerun its scenarios for this checkpoint. No compiler, ABI, dependency or Rust test-count change.

## M5-1b: compiled payment through the full node

M5-1a native Linux testing was confirmed successful by the user. Both platforms now pass the environment/block smoke. `full_node_smoke.py --payment` extends that same isolated run with `full_node_payment.py`; it still runs the M5-1a block/reward assertions before exercising payment.

The harness builds the existing height-locked payment using a deterministic public test key and independently checks artifact byte/tree hashes, compiler version, condition output and signing-message derivation. It funds the contract via a confirmed spend of a real farmed reward, preserving separate change. At a valid height, a missing-signature attempt must fail with `BAD_AGGREGATE_SIGNATURE`; input, recipient/children and mempool state must remain unchanged immediately and after another real block. The correctly signed positive control must then enter the mempool and be included in a real full block. CoinStore additions/removals at that block must match exactly one recipient output and the contract input, excluding reward additions; change must remain unspent.

Signatures bind the actual contract coin and the full node's effective `AGG_SIG_ME_ADDITIONAL_DATA`, not M4's synthetic domain. Submission uses upstream `FullNode.add_transaction(..., test=True)`: this skips only wall-clock/peer synchronization readiness for the isolated historical chain. Signature/condition prevalidation, mempool acceptance and full-block consensus validation remain enabled. No network listener, RPC connection, wallet or daemon is started. This checkpoint covers an invalid-signature rejection and a valid payment after the height lock; it does not repeat every M4 negative case through the full node.

The aggregate records the compiler manifest, CLI binary and payment-source digests, actual coins, signing domain/message/signature, block hashes/heights, rejection state and confirmed records. Local VM cost is recorded separately from full-node mempool cost. Prior payment success is invalidated before startup and publication requires successful worker exit and resource cleanup. Block-smoke reports use a separate filename.

Windows:

```powershell
.work/m4/venv/Scripts/python.exe -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/Scripts/python.exe simulator/full_node_smoke.py --payment --binary target/debug/0xbasic.exe
```

Native Linux: run the following **from the same native checkout where M5-1a passed**. The first two checks confirm that this checkout and its isolated environment exist. The rsync command refreshes only the simulator code from the known Windows share; it preserves `.work` and native binaries and does not copy artwork. These changes are not yet on GitHub.

```bash
set -e
test -f Cargo.toml
test -x .work/m4/venv/bin/python
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/simulator/ simulator/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
if [ ! -x "$CARGO_TARGET_DIR/debug/0xbasic" ]; then
    cargo build --workspace --locked
fi
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/full_node_smoke.py --payment --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

No dependency installation or Rust test rerun is needed. The existing CLI is unchanged; the conditional build is only for a missing native executable. The combined payment command includes the block smoke, so no separate M5-1a rerun is necessary.

Expected: **12 tests pass**, followed by `PASS: full-node funding, missing-signature rejection and exact payment verified; resources closed.` Report: `.work/m5/full-node-payment-linux.json` (Windows: `full-node-payment-windows.json`). Windows observed funding at height 6, `FAILED/BAD_AGGREGATE_SIGNATURE` at peak 10, unchanged state after farming 11, acceptance at peak 11 and confirmation at height 12. Exactly one recipient child is confirmed, change remains unspent, resources close and network services remain unstarted. Local CLI/upstream VM cost: 1,487,727; full-node mempool cost: 30,347,727.

Windows M5-1b passed on 2026-10-24, including all 12 reporting/isolation tests and the payment-mode stale-success check. Native Linux M5-1b subsequently passed, as confirmed by the user. The full-node payment gate is complete on both platforms. Compiler, ABI, locks and Rust counts remain unchanged. Next after Linux confirmation: M5-2 experimental compatibility and diagnostic policy.
