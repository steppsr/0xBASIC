# Fee-aware payments: selected milestone

Status: selected by the user on 2026-11-07 after completion of payment/change. The [FP-0 semantics and compatibility decision](fee-payment-semantics.md) resolves fee reservation, aggregate accounting and activation identities. [FP-1](reserve-fee-activation.md) passed Windows and native LANDO, confirmed on 2026-11-07. This document adds no implemented keyword, condition constructor or compiler behavior. The existing payment/change fixtures and published releases retain their current meanings.

## Objective and scope

Extend the demonstrated single-input payment with an explicitly authorized fee amount, preserving exact recipient/change accounting. Start with a specification and pinned-upstream investigation before choosing whether a new condition constructor is needed. Do not describe an unallocated balance as an enforced bundle-level fee until that distinction has been verified.

The proposed contract fixes `owner AS PUBLICKEY`, `recipient AS PUZZLEHASH`, `changeRecipient AS PUZZLEHASH` and `inputAmount AS AMOUNT`. Its proposed solution has `paymentAmount AS AMOUNT` and `feeAmount AS AMOUNT`.

Require positive input/payment, distinct destinations, and `payment + fee <= input`. Perform the sum and subtraction as INTEGER after explicit AMOUNT extraction. Zero fee is allowed. Change is `input - payment - fee`; emit it only when positive. The intended isolated single-spend accounting invariant is:

```text
inputAmount = paymentAmount + changeAmount + feeAmount
```

The fixture baseline is input 1000, payment 600, fee 10, change 390. A no-change case is payment 990, fee 10. Payment 1000 with fee 0 remains valid; payment 1000 with fee 1 fails. These are proposed example rules, not language-wide restrictions.

## Authorization and fee semantics gate

Use a new application-message domain, proposed as `0xBASIC/payment-fee/v1`, followed by NUL, owner bytes, recipient bytes, change-recipient bytes, and U64BE encodings of input, payment and fee amounts in that order. Independently construct the message oracle. Bind signatures to the actual coin and effective network domain in the signing harness. A fee mutation must invalidate the previous signature even if all other fields are unchanged.

Before implementation, inspect the pinned upstream condition and bundle-validation rules and record concrete source references. Resolve:

- Whether the intended contract requires an explicit fee-reservation condition in addition to leaving input value unallocated.
- Its exact opcode, argument encoding, range, zero-value behavior, additive behavior and failure codes.
- The difference between this contract's input/output contribution and the effective fee of an aggregate containing other spends.
- A concrete adversarial aggregate that distinguishes those meanings, with a valid control and measurable total additions/removals.
- Whether the existing target profile permits the chosen condition and what compiler/language/artifact identity changes are required.

If a new constructor is selected, specify its signature and validation behavior before implementation. Follow the [compatibility policy](experimental-compatibility.md); do not introduce it under the unchanged `0.2.0-alpha.1` identity. FP-0 selects compiler `0.3.0-alpha.1`, language `0.3`, and profile `chia-clvm-0.19-strict-v2` for future activation; ABI and schemas remain 1.

## Acceptance matrix

| Case | Required evidence |
| --- | --- |
| 1000 input, 600 payment, 10 fee | Recipient 600, change 390; intended fee accounting and authorization |
| 1000 input, 990 payment, 10 fee | One recipient child, no change child |
| Zero fee | Partial and exact cases retain valid accounting |
| Payment plus fee exceeds input | Rejection before converting negative change to AMOUNT |
| Zero payment or input | Contract rejection |
| Maximum AMOUNT values | Exact local INTEGER arithmetic and fixed-width encodings, including sums above AMOUNT range |
| Missing, malformed or out-of-range fee | Host/raw boundary rejection with distinct observed diagnostics |
| Changed fee with stale signature | Signature rejection, then freshly signed control |
| Wrong owner/domain/coin or actual amount | Rejection without changes to contract or funding records |
| Aggregate changes net fee | Explicit adversarial case and control based on the resolved upstream fee rule |
| Confirmed payment | Exact children, parents, amounts, confirmation/spend heights and measured aggregate accounting |

Every rejected chain attempt must preserve inputs, funding change and absence of children before and after farming. Valid controls must confirm exact expected state. Record CLVM execution cost separately from mempool/consensus cost and fees; cost units are not fee amounts.

## Implementation slices

| Slice | Deliverable and exit gate |
| --- | --- |
| FP-0 | Select direction; resolve pinned-upstream fee semantics, aggregation counterexample, constructor scope and compatibility identities; documentation checks |
| FP-1 | Implement and independently verify the selected constructor through analysis, lowering, CLI and boundary paths; Windows then native LANDO |
| FP-2 | Separate fee-aware example/fixtures and independent local message/accounting verifier; Windows then native LANDO |
| FP-3 | SpendSim acceptance/rejection matrix and aggregate fee controls with reproducible fresh runs; Windows then native LANDO |
| FP-4 | Representative isolated real full-node inclusion/rejection and exact fee/coin accounting; Windows then native LANDO |
| FP-5 | Tutorial command verification, CI integration, evidence review and compatibility/package validation as required by the actual changes |

Supply exact native Linux commands for every executable slice. Native confirmation precedes commit/push and exact-revision CI. Documentation-only planning requires no native test. A release remains a separate reviewed and explicitly approved action.

## Exclusions and alternatives

No wallet discovery, real key management, fee estimation, automatic coin selection, public-network submission or changes to existing payment/change fixtures. Testnet integration, additional language features and developer tooling remain future directions outside this selected milestone.
