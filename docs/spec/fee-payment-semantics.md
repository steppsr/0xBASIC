# FP-0: fee semantics and compatibility decision

Status: fee-aware payments selected by the user on 2026-11-07. Design gate complete; [FP-1](reserve-fee-activation.md) implements the selected feature in the local candidate. This design document records the pre-activation decision. See the [milestone plan](fee-payment-plan.md).

## Selected constructor

Add `RESERVE_FEE(value AS AMOUNT) AS CONDITION`. It evaluates its argument once and returns the proper condition list `(52 value)` using canonical AMOUNT encoding. It has no emission side effect: only `EMIT` appends it to the contract output. Zero is valid. INTEGER arguments require explicit `AS_AMOUNT`; other types and incorrect arity fail semantic checking. Calls remain forbidden in CONST, as with existing constructors. Existing host/raw AMOUNT guards and CONDITION restrictions apply unchanged.

The new fee-payment example will emit, in order: `ASSERT_MY_AMOUNT(inputAmount)`, `AGG_SIG_ME(owner, message)`, `RESERVE_FEE(feeAmount)`, the recipient output, then positive change if any. Emit the reserve condition even for zero, keeping the example's output rule simple. The message domain is selected as `0xBASIC/payment-fee/v1`; all fields and encodings follow the plan. Preserve the old payment/change domain and examples.

## Pinned source findings

Chia 2.7.4 defines `RESERVE_FEE` as condition code 52 in [condition_opcodes.py](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/types/condition_opcodes.py). This is returned data, not a CLVM operator.

The selected chia_rs 0.48.0 [condition parser and validator](https://github.com/Chia-Network/chia_rs/blob/e11b3c8aa97af8f5d0915d72d4ac7b3c3da00cc2/crates/chia-consensus/src/conditions.rs) parses a fee amount, adds reservations with checked u64 arithmetic, and rejects a total reservation larger than removals minus additions. Overflow and insufficient fee yield `ReserveFeeConditionFailed`. Reservations are additive, not a maximum. The [amount sanitizer](https://github.com/Chia-Network/chia_rs/blob/e11b3c8aa97af8f5d0915d72d4ac7b3c3da00cc2/crates/chia-consensus/src/condition_sanitizers.rs) accepts unsigned 64-bit amounts; its tests cover rejection of negatives and redundant leading zero bytes. 0xBASIC will emit canonical atoms and exactly one argument, irrespective of looser upstream argument rules under other flags.

Chia's pinned [block-body validator](https://github.com/Chia-Network/chia-blockchain/blob/98aba3d176b24b5814e84a33f9d1c11af67a9cdc/chia/consensus/block_body_validation.py) independently compares total fees with the reservation sum and reports `RESERVE_FEE_CONDITION_FAILED`. These are constraints on the evaluated aggregate, not an exact fee cap or attribution of all fee value to one input.

## Observed aggregation counterexample

On Windows, a design probe used installed `chia_rs==0.48.0`, `validate_clvm_and_signature`, pinned Chia default constants and explicit `MEMPOOL_MODE=34210327`. It used deterministic synthetic coins, quote-only puzzles and empty signatures; there were no signature conditions or signature-bypass flags. It did **not** check coin existence, mempool admission or block confirmation. These observations guide the future funded tests rather than replace them.

| Synthetic prevalidation case | Observation |
| --- | --- |
| A spends 1000 and creates 990; B spends 100 and creates 110; neither reserves | Accepted: removals 1100, additions 1100, fee 0 |
| Same aggregate, A additionally reserves 10 | Rejected: `ReserveFeeConditionFailed`, error 48 |
| A reserves 10; B creates only 100 | Accepted: removals 1100, additions 1090, reservation 10 |
| Input/output both 1000, reservation 0 | Accepted |
| Input 1000, output 990, reservations 6 and 4 | Accepted, reservation sum 10 |
| Negative reservation or individual value 2^64 | Rejected: error 48 |
| Two reservations summing to 2^64, with sufficient total inputs | Rejected: error 48 |

The first case shows why this milestone needs a constructor, not just subtraction in the example. Another spend can offset a contribution when the complete aggregate still conserves value. The reservation constrains the aggregate's minimum fee. It does not prevent aggregation or require its total fee to equal exactly the owner's fee field. Later tests must use funded coins, preserve all involved records after rejection, and confirm a valid aggregate control. Multiple fee-aware inputs must also prove additive reservations.

## Activation identities and migration

The current [target profile](target-profile.md) explicitly allowlists only conditions 50, 51, 73 and 83. Do not silently extend that named profile. Select the following identities for FP-1 activation:

| Identity | Current | Selected successor |
| --- | --- | --- |
| Compiler | `0.2.0-alpha.1` | `0.3.0-alpha.1` |
| Language | `0.2` | `0.3` |
| Target profile | `chia-clvm-0.19-strict-v1` | `chia-clvm-0.19-strict-v2` |
| ABI / manifest schema / CLI envelope | `1` | `1`, unchanged |

The successor profile adds returned condition 52 only; runtime dependencies, VM operators, flags, cost model and default execution limit stay pinned. The language identity changes because the built-in name becomes reserved and expands accepted source. Existing identifiers named `RESERVE_FEE` require renaming. Preserve original artifacts; rebuild into new directories. Old/new compiler and profile metadata must reject mismatches with E0400 rather than accepting edited manifests. CLVM bytes, hashes and local execution costs for unchanged historical examples must remain identical even though producer/profile metadata changes.

Update Cargo package/lock metadata, library identifiers, reserved-name handling, constructor analysis/lowering, artifact/version checks, version-sensitive verifiers, language/profile documentation and package expectations together at activation. Revalidate old examples and tutorial commands. Do not change dependency versions or rewrite frozen golden program bytes to make tests pass. Published release tags and archives stay unchanged.

## FP-1 implementation gate

Cover zero, one, sign-bit boundaries and maximum AMOUNT; typed local/function/branch/loop use; unused calls; condition emission order; wrong type/arity and CONST rejection; invalid host and raw AMOUNT boundaries; reserved-name migration; profile/compiler mismatch rejection; and unchanged historical output baselines. Independently execute generated CLVM and compare the exact `(52 amount)` condition, separating local VM success from fee enforcement.

Run the relevant Windows Rust, CLI, documentation and independent-reference checks, then supply exact native LANDO commands. Native confirmation precedes publication and exact-revision CI. Funded SpendSim and full-node fee acceptance remain FP-3/FP-4 gates. FP-0 changed documentation only, so no native Linux testing is required yet. A release remains a separate approval after package and evidence review.
