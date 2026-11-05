# Loop-generated payment validation

Status: Windows and native Linux (LANDO) passed; the tester confirmed Linux success on 2026-11-04. This follows public FOR/NEXT activation at `75072a6b04170bbe03162e4de5713458a71fefd5`. Compiler `0.2.0-alpha.1`, language `0.2`, ABI 1 and compiler output rules are unchanged. No release or tag is created by this checkpoint.

## Fixture and independent expectations

[LoopPayment](../../examples/loop-payment.bas) fixes an owner public key and total amount into the puzzle, and accepts a recipient puzzle hash and integer count in the solution. The fixture binds total to six mojos. It bounds count to 1 through 3 before entering the loop, emits amounts 1 through count, and asserts that their sum equals the fixed total. With this binding, only count 3 completes successfully. Different amounts give the three children distinct coin IDs even though they share a recipient hash.

The ordered condition oracle is `ASSERT_MY_AMOUNT(6)`, `AGG_SIG_ME(owner, message)`, then three `CREATE_COIN` conditions for amounts 1, 2 and 3. The application message is SHA-256 of the concatenation of UTF-8 `0xBASIC/loop-payment/v1`, one zero byte, the 48 owner bytes, 32 recipient bytes, total as U64BE and count as U32BE. Signing appends the actual funded coin ID and the pinned simulator's AGG_SIG_ME domain. Python constructs the expected message and condition tree independently of compiler output, then cross-checks upstream signature-pair extraction.

[The shared harness](../../simulator/loop_payment.py) verifies artifact digests/tree hashes, local CLI and upstream condition parity, exact funding outputs, and positive signature validity. It uses deterministic public test keys. SpendSim and the isolated real full node run the same oracle through separate backend adapters. Full-node validation additionally checks accepted block hashes, stored blocks, exact non-reward additions/removals and a transaction generator for inclusion.

## Rejections and confirmed state

Each rejected attempt targets the same initially unspent contract. Both backends verify that it leaves the input record unchanged, creates no children, enters no active mempool and leaves funding change unspent, including after farming another block.

| Attempt | Expected rejection |
| --- | --- |
| Missing signature | `BAD_AGGREGATE_SIGNATURE` |
| Changed recipient with the original signature | `BAD_AGGREGATE_SIGNATURE` |
| Count zero | `GENERATOR_RUNTIME_ERROR` |
| Count four, above the bound | `GENERATOR_RUNTIME_ERROR` |
| Count two, whose outputs do not sum to six | `GENERATOR_RUNTIME_ERROR` |
| Missing count in the raw solution | `GENERATOR_RUNTIME_ERROR` |

The incomplete-total case checks that a failure after loop emission cannot create partial outputs. A subsequent valid signature/solution must consume the contract and create exactly the three expected children, totaling six mojos, at the input's spend height. Funding change remains unspent and the final mempool is empty.

SpendSim runs twice from fresh environments and requires identical complete results. Its old success report is removed before preflight; failures or differing reruns cannot publish success. The full-node worker publishes only after both legacy and loop payments pass and node/keyring resources close. `--payment` now includes both scenarios; the existing no-payment smoke is unchanged. The full-node offline sync-readiness bypass remains recorded, while signature and consensus validation stay enabled. These are isolated test-chain results, not network or wallet integration.

## Windows evidence

- New SpendSim gate: two identical fresh runs, six rejected attempts and one confirmed three-output payment per run.
- Full-node gate: legacy payment plus loop payment passed; seven total rejected attempts and both valid payments included.
- Fourteen reporting/isolation unit tests passed, including preflight failure, scenario failure and differing-rerun publication checks.
- The existing 15-scenario SpendSim regression gate also passes twice unchanged.
- Loop CLI and upstream VM cost: 1,535,188. SpendSim and full-node mempool spend cost: 50,111,188. These are observed fixture costs, not general cost guarantees.

Reports: `.work/m4/loop-payment-windows.json`, `.work/m4/verification-windows.json` and `.work/m5/full-node-payment-windows.json`. The full-node report adds `outcome.loop_payment` and hashes the new fixture/harness. [Simulator CI](../../.github/workflows/simulator.yml) runs and uploads the new SpendSim report on both platforms and exercises loops through its existing full-node payment step.

Hosted simulator CI pins Ubuntu 24.04: the Ubuntu 26.04 runner selected by `ubuntu-latest` lacks the required setup-python 3.13.7 build. The Python and dependency pins remain the same.

## Native Linux commands

Run from the existing native checkout, preserving its isolated Python 3.13.7 environment and native Cargo target. If that environment is missing, first follow the [locked Linux setup](../../simulator/README.md#linux-setup-project-root-on-a-native-linux-filesystem); do not copy the Windows virtual environment.

```bash
set -e
test -f Cargo.toml
test -x .work/m4/venv/bin/python
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/simulator/ simulator/
rsync -a /mnt/artoo/e/DEV/0xBASIC/examples/ examples/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
cargo build --workspace --locked
python3 tools/verify_m0.py
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python simulator/verify.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/loop_payment.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/full_node_smoke.py --payment --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

Expected: 14 unit tests, the existing 15-scenario gate, the new six-rejection/three-child gate with two identical runs, and the combined full-node gate all pass. Full-node setup creates three isolated k19 plots and may take several minutes. Reports use `-linux.json`; preserve them for the checkpoint. Compiler sources are unchanged, so another Rust test suite run is not required here.

After native confirmation, commit/push this checkpoint and verify hosted CI. Next: source-inclusive packages, offline original/modified-library rebuilds and extracted loop tutorial checks on both platforms, then release documentation and separate release review.
