# TN-4a: confirmation observation contract

Status: Windows passed all 40 integration tests, including 14 new confirmation tests. Native LANDO passed, confirmed on 2026-11-10. TN-3a is published at `9eace1192e21aaf95238034985859d5c8e71fad3`; [compiler](https://github.com/steppsr/0xBASIC/actions/runs/42838332390), [simulator](https://github.com/steppsr/0xBASIC/actions/runs/42838332424) and [package](https://github.com/steppsr/0xBASIC/actions/runs/42838332428) CI passed.

This is the first slice of [TN-4](testnet-integration-plan.md), not the completed end-to-end rehearsal. It implements the observation rules needed after submission, independently of submission and transport. Live host and TN-3b operator signer/key-custody choices remain open.

## Inputs and boundary

`integration/confirmation.py` exposes `observe_confirmation(call, expected_spend, expected_children, depth, previous_anchor=None)`. There is no CLI or network transport in this slice. Its injected callable receives an RPC route and request dictionary and returns the decoded RPC envelope. Tests supply synthetic responses; no node, keys, funding or submission is used.

The expected spend must come from the independently revalidated [TN-3a](testnet-signing.md) result. Expected children must come from that same verified preparation, converted to upstream coin objects with integer amounts. This function does not load or authenticate an arbitrary saved report, verify a signature, execute CLVM or derive expected outputs. The caller must preserve exact integer amounts and must not treat caller-supplied expectations as verification evidence.

The scope is the existing single-input fee payment with one or two positive children. Validate child parent IDs, unique child IDs and output sum no greater than input before RPC calls. Byte normalization accepts RPC `0x` prefixes and hex case without changing puzzle/solution bytes. Coin amounts must be uint64 integers, excluding booleans. Serialized program validation here is encoding validation, not CLVM evaluation.

## Read sequence

First use the existing TN-1 identity/state checks: exact reviewed Chia 2.7.5, testnet11/prefix/genesis, synced non-null peak, unchanged initial state. Then:

1. If supplied, check the prior confirmation anchor against the current canonical block at its height. A shorter chain or different block hash reports `reorged` and clears current confirmation evidence.
2. Read the expected input coin record by its independently recomputed ID. Compare the full coin, strict spent flag, creation/spend heights, timestamp and coinbase type.
3. If spent, request `get_puzzle_and_solution` with the exact input ID and reported spend height. Compare the full coin, puzzle reveal and solution bytes.
4. Read the canonical block record at that height and every expected child coin record. Each child must match its full expected identity, be non-coinbase and have been created at the input spend height.
5. Re-read chain state and require the same height/hash/sync state as at the start. A changing peak invalidates the result, including unspent, conflict and reorg observations.

The additional route shapes were checked against the already audited `chia/full_node/full_node_rpc_api.py` from the [TN-0 source audit](testnet-upstream-audit.json): `get_block_record_by_height` takes `height` and returns `block_record`; `get_puzzle_and_solution` takes `coin_id`/`height` and returns `coin_solution`. The TN-1 transport allowlist remains unchanged. Wiring these reads into authenticated transport belongs to TN-4b.

Equal surrounding peak observations do not create an atomic snapshot or independent chain proof. A contradictory response fails rather than weakening these checks. A missing coin, missing block, malformed envelope or transport error is an error; it is not converted to success, unspent or reorged.

## Status and confirmation policy

| Status | Meaning |
| --- | --- |
| `unspent` | The expected input is currently reported unspent. This says nothing about submission or mempool membership. |
| `conflicting-spend` | The expected input is reported spent with different puzzle or solution bytes. No expected-spend confirmation is claimed. |
| `confirming` | Exact spend and expected children were observed, but the requested depth has not been reached. |
| `confirmed` | Exact spend and expected children were observed at the explicitly requested depth on this node's reported chain. |
| `reorged` | The supplied previous anchor is no longer at its canonical height, or the current chain is shorter. Current confirmation count is zero; the old anchor is preserved separately. |

Depth is an explicit integer from 1 through 10000, counted inclusively: `peak_height - spend_height + 1`. At the inclusion block, depth is 1. No default public-trial depth is selected. Subsequent spending of a child does not undo its creation confirmation; the report preserves its spent state and height.

A prior anchor contains the input ID, spend height and block hash. It is caller-provided historical observation, not chain proof. An unchanged anchor combined with a now-unspent input, changed spend height or changed puzzle/solution is inconsistent and fails. After a reported reorg, obtaining a fresh observation without the old anchor can establish a new inclusion; this function does not automatically discard history or resubmit anything.

The result identifies `rpc-confirmation-observation-only`, network/version, observation time, before/after peaks, input/child records, requested and observed depth, and confirmation anchor. `atomic_snapshot` and `chain_proof` remain false; `transactions_submitted` is zero. Matching coin spends does not identify a particular aggregate bundle or its signature in a block. No bundle-confirmation claim is made.

Submission success, mempool status, retry policy, durable evidence publication, bounded polling and full-node validation remain TN-4b work. In particular, a timeout here raises an error; a later polling driver must report a bounded observation timeout explicitly rather than reuse a previous confirmed result.

## Native LANDO gate

The 14 new standard-library tests cover exact spend/children, inclusive depth, single child, unspent, conflicts, both anchor reorg forms, anchor continuity/contradictions, changed peaks, wrong network/version/sync, malformed coin types/heights, child creation and later spending, missing records/errors, pre-RPC input rejection, hex normalization and transport timeout. They use RPC-shaped fixtures and no sockets. The complete suite also reruns existing isolated TLS and offline input/publication tests.

Run on LANDO:

```bash
(
set -e
cd ~/sourcecode/0xBASIC
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
python3 tools/verify_m0.py
python3 -m unittest discover -s integration -p 'test_*.py'
)
```

Expected: specification checks and **40 integration tests** pass. No Cargo build, pinned Chia environment, signing matrix, package build or full-node rerun is needed for this standard-library observation slice. Compiler, signing and preparation code are unchanged.

After native confirmation, commit/push and verify exact-revision CI, then continue with TN-4b authenticated RPC wiring and the isolated full-node rehearsal. Neither this gate nor passing fixtures completes TN-4, selects live key custody or authorizes a public-network transaction.
