# Payment and change: selected milestone

Status: direction selected by the user on 2026-11-06. The prior counted-loop release plan is complete. [PC-1 local example and verification](payment-change-local.md) passed Windows and native Linux (LANDO), confirmed on 2026-11-06. [PC-2 SpendSim validation](payment-change-spendsim.md) passed Windows and native Linux (LANDO), confirmed on 2026-11-07. The [PC-4 tutorial and milestone review](payment-change-review.md) passed Windows and native LANDO command verification, confirmed on 2026-11-07. This plan adds no compiler behavior.

## First contract

Use the existing compiler, language 0.2, ABI 1 and condition constructors. A single contract fixes `owner AS PUBLICKEY`, `recipient AS PUZZLEHASH`, `changeRecipient AS PUZZLEHASH`, and `inputAmount AS AMOUNT`. The spender supplies one `SOLUTION paymentAmount AS AMOUNT` value. Both destinations are committed by the funded puzzle; the payment amount is authorized by the signature.

Require a positive input amount, a positive payment no greater than the input, and distinct recipient/change puzzle hashes. The distinct-destination requirement is a deliberate restriction of this first example: it prevents ambiguous same-destination accounting and duplicate identical outputs. It is not a new language rule.

Compute `change = AMOUNT_VALUE(inputAmount) - AMOUNT_VALUE(paymentAmount)` using INTEGER arithmetic after the range assertions. Convert to AMOUNT only when emitting positive change. The ordered result must be:

1. `ASSERT_MY_AMOUNT(inputAmount)`.
2. `AGG_SIG_ME(owner, applicationMessage)`.
3. `CREATE_COIN(recipient, paymentAmount)`.
4. `CREATE_COIN(changeRecipient, AS_AMOUNT(change))` only when change is positive.

An exact payment emits one child, not a zero-valued change child. A partial payment emits two children whose amounts sum exactly to the input amount. This first contract deliberately allocates the entire input to outputs: it provides no fee selection or fee reservation. It does not select coins, discover a wallet, or submit a transaction. Returned change is controlled by the fixed change puzzle; the example does not automatically recreate the original contract.

## Authorization

The proposed application message is SHA-256 of:

```text
UTF8("0xBASIC/payment-change/v1") || 0x00 ||
owner[48] || recipient[32] || changeRecipient[32] ||
U64BE(inputAmount)[8] || U64BE(paymentAmount)[8]
```

The isolated signing harness independently constructs this preimage. AGG_SIG_ME signing appends the actual funded coin ID and the simulator network domain, as in the existing payment checks. A changed payment amount requires a fresh signature. Cross-coin and wrong-domain signatures must fail even when the solution is otherwise valid. No existing payment message domain or fixture is repurposed.

## Acceptance matrix

| Case | Required evidence |
| --- | --- |
| Input 1000, payment 600 | Ordered payment 600 and change 400; exactly two confirmed children |
| Input 1000, payment 1000 | One confirmed payment child; no change child |
| Payment 1 | Payment 1 and remaining 999; canonical boundary handling |
| Maximum AMOUNT input, payment 1 | Local arithmetic and serialization preserve exact values; no narrowing |
| Zero input or payment | Runtime assertion failure; no accepted spend |
| Payment greater than input | Failure before converting negative change to AMOUNT |
| Equal destination hashes | Contract rejection under this example's explicit restriction |
| Missing/wrong-owner/wrong-domain signature | Exact upstream signature rejection; input remains unspent |
| Changed payment with stale signature | Signature rejection, followed by a freshly signed positive control |
| Signature replay on a separately funded coin | Rejection on the second coin, followed by its own valid control |
| Wrong actual coin amount | Amount assertion rejection with otherwise valid authorization |
| Missing/extra/malformed raw solution or noncanonical amount | Boundary rejection; distinguish host conversion from generated puzzle guards |

Do not infer exact upstream error codes from local VM failures: record them when exercising the pinned simulator. After every rejected attempt, check the input and funding change records, absence of contract children and active mempool entries, and unchanged state after farming. Every accepted attempt must check exact removals, child IDs, parent IDs, puzzle hashes, amounts and confirmation/spend heights.

Maximum-value arithmetic belongs in the local execution gate; chain funding need not manufacture unrealistic reward balances to repeat that boundary case. Hosted/native simulator cases use small funded test amounts.

## Implementation slices

| Slice | Deliverable and exit gate |
| --- | --- |
| PC-0 | This contract/message/accounting specification and acceptance matrix; documentation verification only |
| PC-1 | Example and fixed/solution fixtures; standard-library CLI verifier with independent message/condition oracle, host/raw boundary negatives and deterministic artifact checks; Windows then native Linux |
| PC-2 | Dedicated SpendSim scenarios for partial/exact payments and adversarial inputs, fresh-run evidence and rejection-state checks; Windows then native Linux |
| PC-3 | Representative partial and exact payments plus signature/amount rejection through the isolated real full node; exact block additions/removals and cleanup; Windows then native Linux |
| PC-4 | Tutorial and CI integration, evidence review and checkpoint publication; decide packaging/release scope separately |

PC-1 and PC-2 are published with successful CI after Windows and native LANDO validation. [PC-3 full-node validation](payment-change-full-node.md) passed Windows and native LANDO, confirmed on 2026-11-07. Reuse helpers where appropriate while preserving existing payment and loop fixtures and their golden outputs. Keep the initial message and condition oracle independent from the BASIC implementation. Do not add a new generic wallet/signing service merely to run the fixture.

Compiler `0.2.0-alpha.1` can remain the producer for examples and test-only changes. If implementation discovers a compiler correctness issue or requires changed syntax, generated bytes, artifact interpretation or observable CLI behavior, stop treating it as an example-only change: follow the [compatibility policy](experimental-compatibility.md), assign a distinct compiler prerelease identity, and document the migration before activation. No dependency, profile, ABI or schema upgrade is selected here.

Each executable slice gets exact LANDO commands that restore the Cargo environment/target and use a subshell for fail-fast execution without closing SSH. Native confirmation precedes commit/push and exact-revision CI verification. No Linux testing is needed for PC-0. A future release requires a concrete verified candidate and separate publication approval.

Alternative future directions remain additional selected language features, explicit testnet integration, and developer tooling. This proposal does not silently schedule WHILE/DO, recursion, fee handling, new condition constructors or network transactions.
