# Build a payment with optional change

This walkthrough uses compiler `0.2.0-alpha.1`, language 0.2 and ABI 1. Start with the [beginner walkthrough](first-program.md) for compiler setup and the [implemented reference](implemented-reference.md) for the full supported language. The source and JSON fixtures below are in the current repository; older downloadable archives may not include these newer examples.

## Understand the source and inputs

Open [payment-change.bas](../../examples/payment-change.bas). Its `CONTRACT` fixes an owner public key, recipient puzzle hash, change puzzle hash and input amount. `SOLUTION paymentAmount AS AMOUNT` supplies the requested payment when spending. Fixed values determine the bound puzzle; the solution can change without rebuilding that puzzle.

The program uses these already implemented features:

| Feature | Purpose here |
| --- | --- |
| `CONTRACT`, `SOLUTION`, `AS`, `END CONTRACT` | Declare fixed terms and the spend-time amount |
| `AMOUNT`, `PUBLICKEY`, `PUZZLEHASH`, `INTEGER`, `BYTES` | Type amounts, destinations, arithmetic and messages |
| `ASSERT`, comparisons `>`, `<=`, `<>` | Require positive input/payment, sufficient value and distinct destinations |
| `DIM`, assignment, subtraction | Compute change as an INTEGER |
| `IF … THEN … END IF` | Emit change only when positive |
| `FUNCTION`, `RETURN`, `END FUNCTION` | Build the authorization message |
| `AMOUNT_VALUE`, `AS_AMOUNT`, `U64BE` | Convert amounts for arithmetic, conditions and eight-byte message encoding |
| `UTF8`, `CONCAT`, `KEY_BYTES`, `HASH_BYTES`, `SHA256` | Hash the domain, owner, destinations and both amounts |
| `EMIT`, `ASSERT_MY_AMOUNT`, `AGG_SIG_ME`, `CREATE_COIN` | Return the ordered spend conditions |

The [bindings](../../examples/payment-change.bindings.json) set input amount 1000. The [partial solution](../../examples/payment-change.partial.json) is `{"paymentAmount":"600"}`; the [exact solution](../../examples/payment-change.exact.json) is `{"paymentAmount":"1000"}`. Decimal strings preserve exact AMOUNT values. The key and hashes are public fixtures, not configured wallet destinations.

## Check, inspect and build

Build with `cargo build --workspace --locked`. Run from the repository root. Replace `0xbasic` below with `./target/debug/0xbasic` on Linux or `./target/debug/0xbasic.exe` in PowerShell. With a custom Cargo target directory, use its `debug/0xbasic` executable. Choose a new output directory if `payment-change-tutorial-build` already exists.

<!-- payment-change:check -->
```text
0xbasic check examples/payment-change.bas --json
```

Expect `ok: true`. Checking needs no fixed bindings and does not execute the program.

<!-- payment-change:clvm -->
```text
0xbasic explain examples/payment-change.bas --stage clvm --bindings examples/payment-change.bindings.json --json
```

Yes, you can inspect the compiled CLVM: this shows the template and bound puzzle representations, serialized hex and tree hashes. It writes no artifacts and does not execute a spend. `--stage ast` and `--stage ir` offer syntax and lowered-code views. These inspection formats are compiler-versioned.

<!-- payment-change:build -->
```text
0xbasic build examples/payment-change.bas --bindings examples/payment-change.bindings.json --out payment-change-tutorial-build --json
```

Preserve all five files: `manifest.json`, `template.clvm`, `template.hex`, `puzzle.clvm` and `puzzle.hex`. The `.clvm` files are serialized binary programs; `.hex` files encode those bytes as text. The manifest records schemas, bindings and identities. A puzzle's byte SHA-256 differs from its CLVM tree hash; the latter identifies the puzzle used by a contract coin.

## Run partial and exact payments

<!-- payment-change:partial -->
```text
0xbasic run payment-change-tutorial-build/manifest.json --solution examples/payment-change.partial.json --json
```

The returned tree represents four ordered conditions: `ASSERT_MY_AMOUNT(1000)`, `AGG_SIG_ME(owner, message)`, `CREATE_COIN(recipient, 600)`, and `CREATE_COIN(changeRecipient, 400)`. Atom values in the JSON tree are hex, not decimal display amounts.

<!-- payment-change:exact -->
```text
0xbasic run payment-change-tutorial-build/manifest.json --solution examples/payment-change.exact.json --json
```

This returns three conditions: the amount assertion, a signature requirement with a different application message, and `CREATE_COIN(recipient, 1000)`. There is no zero-valued change output. Both commands use the same puzzle and leave its artifacts unchanged.

Try a different positive payment no greater than 1000 in your own solution file. Zero or overspending fails the contract. Changing the input amount, owner or destinations requires rebuilding with new bindings and produces a different bound puzzle. Changing the solution payment changes the authorization message and requires a fresh signature for an actual spend.

## What the result proves

`run` reports `clvm-execution-only`: it evaluates conditions and VM cost. It does not establish that the input coin exists, verify an owner signature, submit a transaction or confirm outputs. `AGG_SIG_ME` requires signing the application message together with the actual coin ID and network signing domain. The isolated harness handles that separately using public test keys.

The example allocates the entire input value, with no fee reserve. Change is controlled by the fixed change puzzle; it does not automatically recreate this contract. Wallet discovery, real key management, fee selection and network submission remain separate work.

The [milestone review](payment-change-review.md) connects the local oracle, signed SpendSim cases and real isolated full-node evidence. `tools/verify_payment_change_tutorial.py` executes the five marked commands directly from this document in a fresh directory, checks the independent expected conditions and inspection/build identities, and preserves a success report only after all checks pass.
