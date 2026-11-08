# Payment/change milestone review

Status: PC-1 through PC-3 passed Windows, native Linux (LANDO) and exact-revision GitHub CI. PC-4 tutorial commands passed Windows and native LANDO, confirmed by the user on 2026-11-07. PC-4 is published and its exact-revision CI passed; the payment/change milestone is complete. This milestone uses compiler `0.2.0-alpha.1`, language 0.2 and ABI 1 without compiler or dependency changes.

Start with the [payment/change tutorial](payment-change-tutorial.md). The [selected plan](payment-change-plan.md) defines the contract and authorization message. Coverage is intentionally split by validation layer:

| Gate | Evidence and limits |
| --- | --- |
| [PC-1 local](payment-change-local.md) | Eight positives and 25 negatives across 72 CLI calls; independent message/condition oracle, maximum AMOUNT arithmetic, host/raw boundary errors, deterministic artifacts and cost limits. No signature or chain validation. |
| [PC-2 SpendSim](payment-change-spendsim.md) | Twelve scenarios, ten rejections and twelve confirmed controls per run; two identical fresh runs. Missing/wrong-owner/wrong-domain/stale-payment/cross-coin signatures, incorrect actual amount and invalid solutions. Rejection state and exact confirmed coins checked. |
| [PC-3 full node](payment-change-full-node.md) | Three representative rejections and two confirmed payments for this example, plus preserved legacy/loop coverage. Combined run: ten rejections and four confirmed payments. Exact block/store/coin changes and resource cleanup checked. Twenty-one reporting/isolation tests pass. |
| PC-4 tutorial | Five actual documentation command blocks executed in a fresh directory. Independent partial/exact condition oracle, different payment messages, unchanged artifacts, inspection/build bytes and hashes, and explicit local-only validation. Windows and native LANDO passed, confirmed on 2026-11-07. |

PC-3's published revision is `c73f9cda1418706e248a1ccfd5810a65009689b5`. [Compiler CI](https://github.com/steppsr/0xBASIC/actions/runs/42396043661), [simulator CI](https://github.com/steppsr/0xBASIC/actions/runs/42396043714) and [package CI](https://github.com/steppsr/0xBASIC/actions/runs/42396043663) passed for that exact revision on both platforms, including both extracted-package smoke tests. Those results certify PC-3. PC-4 was subsequently published at `c29ff9b4879092c41364e3627a7071a46d97917c`; its [compiler CI](https://github.com/steppsr/0xBASIC/actions/runs/42403903368), [simulator CI](https://github.com/steppsr/0xBASIC/actions/runs/42403903325) and [package CI](https://github.com/steppsr/0xBASIC/actions/runs/42403903318) all passed on Windows and Linux, including both extracted-package smoke tests.

Compiler CI now invokes `verify_payment_change_tutorial.py` alongside the existing local verifier. Simulator CI already runs the full SpendSim matrix and extended full-node payment command, uploading both platforms' evidence. No additional simulator scenario or workflow is needed for PC-4. Local evidence paths are `.work/payment-change/local-<platform>.json`, `.work/payment-change/tutorial-<platform>.json`, `.work/m4/payment-change-<platform>.json`, and `.work/m5/full-node-payment-<platform>.json`. A report belongs to its recorded source/binary hashes; hosted artifacts have finite retention.

## Native PC-4 gate

Only documentation and a standard-library command verifier changed. No simulator environment or full-node rerun is needed. Run on LANDO:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/tools/ tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 tools/verify_payment_change_tutorial.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
python3 tools/verify_tutorial.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: specification verification, all five payment/change commands and all nine existing payment commands pass. The existing payment tutorial's version prose is corrected to match its already-current executable checks. Preserve `.work/payment-change/tutorial-linux.json` and `.work/m5/tutorial-linux.json`.

Native confirmation, publication and exact-revision CI are complete. These commands are retained for reproduction; no additional native testing is required for the completed milestone. The published `v0.2.0-alpha.1-experimental` release and its assets remain unchanged. This example-only milestone does not require a compiler version bump; a refreshed package or another release is a separate scope decision with its own validation and publication approval.

## Remaining boundaries

The contract reserves no fee and does not recreate itself with change. Its fixed destinations must differ. Public fixture keys and hashes are test inputs. There is no wallet integration, production key management, coin selection, public-network submission or testnet acceptance claim. Maximum-value arithmetic is tested locally rather than by manufacturing a chain balance. The broader SpendSim rejection matrix is not claimed as full-node coverage. Further language features, fee handling, wallet tooling and testnet integration remain separately selected work.
