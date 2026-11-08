# Target profile v2

Profile ID: `chia-clvm-0.19-strict-v2`. Activated by development compiler `0.3.0-alpha.1`, language `0.3` for RESERVE_FEE. Native validation status is in [FP-1](reserve-fee-activation.md).

This profile inherits the pinned versions, local runner flags, allowed VM operators, serialization, execution limits and simulator separation from [profile v1](target-profile.md). No dependency or opcode-enablement change is made. The local runner flags remain `0x0257` and default VM limit remains 10,000,000.

The complete returned-condition allowlist is now AGG_SIG_ME=50, CREATE_COIN=51, **RESERVE_FEE=52**, ASSERT_MY_AMOUNT=73 and ASSERT_HEIGHT_ABSOLUTE=83. Condition codes are data, separate from VM operator opcodes. The local runner still does not enforce consensus conditions or fees; funded simulator and full-node validation are separate gates.

ABI 1, manifest schema 1 and CLI envelope schema 1 remain unchanged. Reader compatibility checks require exact compiler, language and profile identities. The historical v1 profile is not retroactively extended. See [fee semantics](fee-payment-semantics.md) for the pinned upstream rules and aggregation counterexample.
