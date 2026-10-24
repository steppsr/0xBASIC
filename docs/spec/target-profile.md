# Initial target and dependency profile

Profile ID: `chia-clvm-0.19-strict-v1`. Source assessment date: 2026-10-04. This is a reproducible local compiler/runner profile, not a declaration that every network height uses identical flags/costs.

## Selected versions

| Component | Selection | Evidence/status |
| --- | --- | --- |
| Rust | `1.95.0`, edition 2024 | Pinned in rust-toolchain.toml; Windows M1 build verified |
| CLVM runtime/serialization | `clvmr = "=0.19.0"`, no optional features | Registry archive checksum verified; source inspected; matches chia_rs 0.48.0 dependency series |
| Arbitrary-precision arithmetic | `num-bigint = "=0.4.6"` | Also used by the inspected runtime |
| Fixed-binding G1 validation | `chia-bls = "=0.38.2"` | Same series as the selected CLVM runtime; use checked decoding and reject infinity |
| Simulator | Chia source release `2.7.4`, commit `98aba3d176b24b5814e84a33f9d1c11af67a9cdc` | Source-level validation-path review; not installed or run during M0 |
| Simulator Rust bindings | `chia_rs==0.48.0`, commit `e11b3c8aa97af8f5d0915d72d4ac7b3c3da00cc2` | Satisfies inspected Chia source constraint `>=0.48.0,<0.49`; references CLVM 0.19 |
| Simulator Python | 3.13 | Local Python 3.13.7; selected Chia source permits this major/minor |

Pin all transitive dependencies in Cargo.lock when M1 creates the workspace. Pin the simulator environment separately before M4. CLI/JSON/hash helper crates are implementation choices to resolve and lock in M1; they do not define the ABI. No automatic latest-version fallback. Do not enable optional OpenSSL features initially; native crypto dependencies still require the Windows C/C++ build tools and Linux compiler toolchain.

M1 pins transitive dependencies in Cargo.lock, including num-bigint 0.4.6 and chia-bls 0.38.2. Windows and Linux build/runtime compatibility is verified, with Linux test evidence supplied by the user on 2026-10-05. See [verification status](../development.md). Installed reference libraries used for M0 vectors are separately reported (`chia_rs 0.42.1`, `clvm 0.9.15`); these independent encoding/signature checks do not certify the selected simulator.

## Local runner rules

Use clvmr 0.19.0 `ChiaDialect` with the explicit flag set:

```text
CANONICAL_INTS | NO_UNKNOWN_OPS | LIMIT_HEAP |
LIMIT_SOFTFORK | LIMITS | DISABLE_OP = 0x0257
```

This is that release's MEMPOOL_MODE plus LIMITS. Disable NEW_COST_MODEL, RELAXED_BLS, ENABLE_GC, MALACHITE, and new opcode-enablement flags. Use old/traditional uncompressed serialization and a cost limit, default 10,000,000. Record numeric flags and runtime version with reports; never silently inherit a changed MEMPOOL_MODE from another release.

The compiler may emit only core operators needed by this language: quote/apply/if/cons/first/rest/listp/raise/equality, sha256, substr/strlen/concat, integer add/subtract/multiply/greater-than, arithmetic shift/bitwise-and for generated conversions/validators, strict point_add, and boolean not. Opcode numbers are `1,2,3,4,5,6,7,8,9,11,12,13,14,16,17,18,21,22,24,29,32`. Environment selectors are paths, not operator calls. No raw user opcodes, softfork guards, Keccak, or new cost-model-dependent primitives.

Returned conditions are separately allowlisted: AGG_SIG_ME=50, CREATE_COIN=51, ASSERT_MY_AMOUNT=73, ASSERT_HEIGHT_ABSOLUTE=83. Operators and condition codes are different namespaces. The local runner does not perform consensus spend validation.

## Simulator choice and coverage

Use `chia._tests.util.spend_sim.SpendSim` with `SimClient` from the pinned Chia checkout for fast M4 lifecycle tests. It uses actual MempoolManager/CoinStore components but simplified block records. `SimClient.push_tx` calls `pre_validate_spendbundle`, which invokes `validate_clvm_and_signature`, then adds the spend to the mempool. Farm blocks and verify resulting coin records; do not equate successful CLVM evaluation with spend acceptance.

Do not use `CostLogger` as a signature-validation oracle: its source explicitly passes DONT_VALIDATE_SIGNATURE. Do not pass that flag in authorization acceptance tests.

For deterministic low-height tests, use pinned DEFAULT_CONSTANTS with an explicitly recorded synthetic `AGG_SIG_ME_ADDITIONAL_DATA` of 32 bytes `aa`, and the six other AGG_SIG domain constants derived from this same base using upstream rules, although those conditions are not emitted by 0.1. Leave activation heights otherwise unchanged and record the actual constants and computed flags with results. This isolated profile is not mainnet or testnet. Advance actual simulator blocks, not just a counter, when exercising height boundaries.

Use H=10 for the example scenario: push with mempool peak height 9 and require nonacceptance; advance to mempool peak height 10 and require acceptance; farm the next block and verify the output. A mempool may classify a premature spend as pending rather than permanently invalid; assert nonacceptance and the height-lock reason, not one generic status spelling. Signature-negative scenarios must run at an otherwise valid height.

The simulator does not prove full network/block-consensus behavior or RPC integration. Before M5 release, add a full-node simulator smoke test for the same contract; testnet remains a later integration phase. Runtime costs and simulator total spend costs are separately labeled.

## Pinned source evidence

- [clvmr 0.19 source commit](https://github.com/Chia-Network/clvm_rs/tree/f00ad6c1549e89a153c634b38d2832a2fb039478), [dialect flags](https://github.com/Chia-Network/clvm_rs/blob/f00ad6c1549e89a153c634b38d2832a2fb039478/src/chia_dialect.rs).
- [Chia dependency manifest](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/pyproject.toml), [SpendSim](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/_tests/util/spend_sim.py), [mempool validation](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/full_node/mempool_manager.py).
- [Coin identity](https://github.com/Chia-Network/chia_rs/blob/e11b3c8aa97af8f5d0915d72d4ac7b3c3da00cc2/crates/chia-protocol/src/coin.rs), [signature-message tests](https://github.com/Chia-Network/chia_rs/blob/e11b3c8aa97af8f5d0915d72d4ac7b3c3da00cc2/crates/chia-consensus/src/spendbundle_validation.rs), [timelocks](https://github.com/Chia-Network/chia_rs/blob/e11b3c8aa97af8f5d0915d72d4ac7b3c3da00cc2/crates/chia-consensus/src/check_time_locks.rs).

`tools/inspect_m0_upstream.py` fetches public references into ignored `.work/m0-upstream`; it installs/executes none of them. [upstream-evidence.json](upstream-evidence.json) records hashes of inspected references. Registry metadata is date-sensitive; the archived runtime checksum and source commit are the reproducibility anchors.


M4-2 source/execution clarification: the pinned MempoolManager passes `self.peak.height` to `check_time_locks`. This is the acceptance context for the next transaction block, not the separate `prev_transaction_block_height` field of that peak's simplified block record. At the successful Windows payment submission these are 10 and 9 respectively; inclusion occurs at 11. M4-3 verified the peak9 rejection and peak10 promotion on Windows and Linux. M4-1 environment smoke and M4-2 signed payment have passed on Windows/Linux.
