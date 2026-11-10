# Build a payment with an authorized fee

This walkthrough uses compiler `0.3.0-alpha.1`, language 0.3, ABI 1 and target profile `chia-clvm-0.19-strict-v2`. Start with the [beginner walkthrough](first-program.md) for setup and the [implemented reference](implemented-reference.md) for all currently supported features. The published `v0.2.0-alpha.1-experimental` archive predates fee support; use the current source checkout for this walkthrough.

## Read the program

Open [payment-fee.bas](../../examples/payment-fee.bas). Its fixed terms are an owner public key, recipient and change puzzle hashes, and input amount. Two ordered `SOLUTION` declarations supply `paymentAmount` followed by `feeAmount`. Changing either solution value leaves the bound puzzle unchanged; changing a fixed term requires rebuilding.

| Supported feature used here | Purpose |
| --- | --- |
| `CONTRACT`, `SOLUTION`, `AS`, `END CONTRACT` | Declare fixed and spend-time inputs |
| `PUBLICKEY`, `PUZZLEHASH`, `AMOUNT`, `INTEGER`, `BYTES` | Type keys, destinations, amounts, arithmetic and messages |
| `ASSERT`, `>`, `<=`, `<>` | Require positive input/payment, sufficient funds and distinct destinations |
| `DIM`, assignment, `+`, `-` | Calculate payment plus fee and remaining change using INTEGER arithmetic |
| `IF … THEN … END IF` | Create change only when positive |
| `FUNCTION`, `RETURN`, `END FUNCTION` | Construct the authorization message |
| `AMOUNT_VALUE`, `AS_AMOUNT`, `U64BE` | Convert amounts and encode eight-byte unsigned values |
| `UTF8`, `CONCAT`, `KEY_BYTES`, `HASH_BYTES`, `SHA256` | Hash a domain, owner, destinations, input, payment and fee |
| `EMIT`, `ASSERT_MY_AMOUNT`, `AGG_SIG_ME`, `RESERVE_FEE`, `CREATE_COIN` | Return the ordered conditions |

The [bindings](../../examples/payment-fee.bindings.json) use input amount 1000. Public fixture keys and destination hashes are test inputs. Amounts in the JSON solutions are decimal strings:

| Solution | Payment | Fee | Change |
| --- | --- | --- | --- |
| `payment-fee.partial.json` | 600 | 10 | 390 |
| `payment-fee.exact.json` | 990 | 10 | none |
| `payment-fee.zero-fee.json` | 1000 | 0 | none |

All amounts are mojos. The source requires payment greater than zero and payment plus fee no greater than input. Zero fee is allowed. INTEGER arithmetic prevents an overflowing AMOUNT sum or conversion of negative change.

## Check, inspect and compile

Run `cargo build --workspace --locked` from the repository root. Replace `0xbasic` in the commands below with `./target/debug/0xbasic` on Linux or `./target/debug/0xbasic.exe` in PowerShell. If `CARGO_TARGET_DIR` is set, use its `debug` executable. Choose a fresh output directory if `payment-fee-tutorial-build` already exists.

<!-- payment-fee:check -->
```text
0xbasic check examples/payment-fee.bas --json
```

Expect `ok: true`. Checking validates the source without bindings or execution.

<!-- payment-fee:clvm -->
```text
0xbasic explain examples/payment-fee.bas --stage clvm --bindings examples/payment-fee.bindings.json --json
```

This displays the compiled template and bound CLVM puzzle, serialized hex and tree hashes without writing files. Syntax and lowered representations are also available through `--stage ast` and `--stage ir`.

<!-- payment-fee:build -->
```text
0xbasic build examples/payment-fee.bas --bindings examples/payment-fee.bindings.json --out payment-fee-tutorial-build --json
```

Keep all five files: `manifest.json`, `template.clvm`, `template.hex`, `puzzle.clvm`, `puzzle.hex`. The `.clvm` files are serialized binary CLVM; `.hex` files encode those bytes as text. The manifest records bindings, solution layout and compiler/profile identities. Byte SHA-256 and CLVM tree hash serve different purposes; the tree hash identifies the puzzle for a coin.

## Execute three solutions

<!-- payment-fee:partial -->
```text
0xbasic run payment-fee-tutorial-build/manifest.json --solution examples/payment-fee.partial.json --json
```

Expect five ordered conditions: `ASSERT_MY_AMOUNT(1000)`, `AGG_SIG_ME(owner, message)`, `RESERVE_FEE(10)`, `CREATE_COIN(recipient, 600)`, and `CREATE_COIN(changeRecipient, 390)`. The JSON tree encodes atoms in hex, not decimal display amounts.

<!-- payment-fee:exact -->
```text
0xbasic run payment-fee-tutorial-build/manifest.json --solution examples/payment-fee.exact.json --json
```

Expect four conditions: amount assertion, signature requirement, fee reservation 10, and recipient output 990. No zero-valued change output is created.

<!-- payment-fee:zero-fee -->
```text
0xbasic run payment-fee-tutorial-build/manifest.json --solution examples/payment-fee.zero-fee.json --json
```

This also returns four conditions, including an explicit `RESERVE_FEE(0)` and recipient output 1000. All three commands use the same puzzle without modifying its artifacts, and each produces a different authorization message.

Try a separate solution file containing `{"paymentAmount":"600","feeAmount":"11"}`. It should produce change 389 and a different message. An actual spend needs a fresh signature when either payment or fee changes. Zero payment or a payment-plus-fee total above 1000 fails this contract.

## Understand what you have built

`run` reports `clvm-execution-only`: returned conditions and VM execution cost. Cost units are separate from fees. This command does not prove that a coin exists, verify a signature, submit a spend or confirm a block. `AGG_SIG_ME` requires signing the application message together with the actual coin ID and effective network domain. The isolated simulator and full-node harnesses do this separately with public test keys.

`RESERVE_FEE` enforces an aggregate minimum. Reservations add across all spends in a bundle; total inputs minus total outputs must cover their sum. Other spends can contribute additional fees, so reservation is neither an exact fee cap nor a per-coin guarantee. The example's single-input accounting is `input = payment + change + fee`.

Change goes to the fixed change puzzle; it does not automatically recreate this contract. Wallet discovery, production keys, coin selection, fee estimation and public-network submission are outside this walkthrough. See the [milestone review](fee-payment-review.md) for local, SpendSim, full-node and package evidence.

`tools/verify_fee_payment_tutorial.py` executes all six marked command blocks in a fresh directory, checks independent expected conditions and artifact identities, and publishes success only when all checks pass.
