# TN-4b6: fixed identities and shared confirmation checks

Status: Windows passed 53 integration tests, 49 simulator tests, the real RPC lifecycle, 10 positive/21 negative preparation cases and seven positive/26 negative signing cases. Native LANDO passed, confirmed on 2026-11-11. TN-4b5 is published at `22ba936aac22b5cdd21ca651a1d168358d542cbf`; [compiler](https://github.com/steppsr/0xBASIC/actions/runs/43057612327), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/43057612347) and [package](https://github.com/steppsr/0xBASIC/actions/runs/43057612325) CI passed.

This is the observation side of the remaining isolated-identity integration. The rehearsal now exercises the same confirmation algorithm as the public-testnet observer, with an explicit fixed simulator identity. Offline preparation/signature integration remains a separate next slice.

## Identity selection

`integration/network_identity.py` defines two frozen, reviewed objects:

| Purpose | Node version | Network | Prefix | Genesis |
| --- | --- | --- | --- | --- |
| Public-testnet observation | 2.7.5 | testnet11 | txch | `37a90eb5185a9c4439a91ddc98bbadce7b4feba060d50116a067de66bf236615` |
| Isolated rehearsal | 2.7.4 | 0xbasic-simulator | txch | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The public `observe` and `observe_confirmation` functions bind the public object internally. Their signatures have no identity selector, and the public probe CLI gains no network/version override. RPC replies and input documents do not select a policy.

Private shared helpers require one of the two exact reviewed identity objects; arbitrary dictionaries, newly constructed copies and unreviewed objects are rejected. The separate `simulator/isolated_observation.py` adapters bind only the isolated object. This is an application API boundary, not a sandbox against arbitrary Python code running in the same process.

Both paths require an exact version/name/prefix/genesis match. They share existing checks for synchronized unchanged peaks, recomputed coin IDs, strict types/heights, exact puzzle/solution and child records, confirmation depth and prior anchors. Public labels remain unchanged. Isolated results use `isolated-rpc-observation-only` or `isolated-rpc-confirmation-observation-only`, retain the real simulator version/network, and continue to mark chain proof false and transactions submitted zero.

The public TN-2 observation validator is unchanged and rejects isolated observations, including a test that renames only their validation label. TN-3a and public CLI behavior remain strict. No testnet version, network, genesis, signing domain or RPC response is rewritten to make a simulator result look public.

## Real node coverage

The full-node rehearsal passes the original independently checked partial-payment spend and its two expected children to the isolated adapter. The adapter calls the shared confirmation core over the actual mutual-TLS transport at four checkpoints:

1. Original inclusion below the selected target depth: `confirming`.
2. Original inclusion after another block: `confirmed`, preserving the prior anchor.
3. Replacement chain after actual rollback: `reorged`, clearing current confirmation evidence.
4. Recreated exact spend after unchanged-bundle resubmission: `confirmed` at the new depth-two anchor.

The original full-node fee/block/store oracle remains independent. The parent compares shared-observer scope, identity, input ID, statuses, depth and anchor against that evidence. Missing or changed shared observations fail the report audit. Other aggregate inputs retain the existing direct RPC/block/store checks; this slice exercises the shared single-input confirmation interface with the partial-payment control.

The shared observations are saved in `reorg.shared_observations` and `reconfirmation.shared_confirmed` within `.work/m5/full-node-rpc-<platform>.json`. The nine journal checkpoints retain their existing meanings. Source hashes now include the identity definition and isolated adapter; preparation/signing matrix reports also include the identity source hash.

## Boundary tests and remaining work

Five new integration tests cover frozen reviewed identity objects, bidirectional identity rejection, mixed version/name/prefix/genesis rejection, shared confirmation scope and child checks, and public preparation rejecting an isolated coin observation. Existing TLS/public confirmation tests continue unchanged. The real-node run checks all four shared-confirmation transitions, while existing preparation and signature matrices verify that the public offline path retains its previous behavior.

The next remaining TN-4 work is an explicit isolated policy for the offline preparation/signature path, including actual consensus constants and signing domains. This change does not yet submit a bundle produced by the strict TN-2/TN-3a pipeline to the simulator. No new runtime, dependency, key custody, host or public transaction is selected.

## Native LANDO gate

Because the shared observation code changed, run both public regression matrices as well as the real rehearsal:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/simulator/ simulator/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
cargo build --workspace --locked
python3 tools/verify_m0.py
python3 -m unittest discover -s integration -p 'test_*.py'
.work/m4/venv/bin/python -m unittest discover -s simulator -p 'test_*.py'
.work/m4/venv/bin/python integration/verify_preparation.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python integration/verify_signing.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
.work/m4/venv/bin/python simulator/full_node_smoke.py --rpc --binary "$CARGO_TARGET_DIR/debug/0xbasic"
)
```

Expected: **53 integration tests**, **49 simulator tests**, preparation **10 positive/21 negative**, signing **7 positive/26 negative**, then the full RPC lifecycle PASS with resources closed. Preserve the three generated reports. No live credentials/node, dependency upgrade or separate original-payment rerun is needed. After native confirmation, commit/push, verify exact CI and continue the offline pipeline bridge.
