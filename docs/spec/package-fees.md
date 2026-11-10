# Fee-payment example in this experimental package

This candidate uses compiler 0.3.0-alpha.1, language 0.3, ABI 1 and target profile chia-clvm-0.19-strict-v2. Earlier published packages do not support RESERVE_FEE. Existing artifacts with older compiler/language/profile identities must be rebuilt from source for this compiler.

Run from the extracted package root. Use `./bin/0xbasic` on Linux or `./bin/0xbasic.exe` in PowerShell in place of `0xbasic` below. The public test key and hashes are fixtures, not configured wallet destinations. Choose a fresh build directory.

```text
0xbasic check examples/payment-fee.bas --json
0xbasic explain examples/payment-fee.bas --stage clvm --bindings examples/payment-fee.bindings.json --json
0xbasic build examples/payment-fee.bas --bindings examples/payment-fee.bindings.json --out fee-build --json
0xbasic run fee-build/manifest.json --solution examples/payment-fee.partial.json --json
0xbasic run fee-build/manifest.json --solution examples/payment-fee.exact.json --json
0xbasic run fee-build/manifest.json --solution examples/payment-fee.zero-fee.json --json
```

Input is 1000 mojos. Partial produces recipient600/change390/reserve10; exact produces recipient990/nochange/reserve10; zero-fee produces recipient1000/nochange/reserve0. Each result begins with ASSERT_MY_AMOUNT and AGG_SIG_ME, followed by RESERVE_FEE and recipient/change CREATE_COIN conditions. Amount atoms are hex in the JSON tree. Solution order is paymentAmount then feeAmount; both use decimal strings in JSON. Payment must be positive and payment plus fee cannot exceed input.

The CLVM inspection shows template/puzzle representations, hex and tree hashes. Build writes a manifest and binary/hex pairs for template and puzzle. Keep all five files. Execution leaves them unchanged and reports clvm-execution-only: no signature verification, funding or transaction submission. Actual signatures include the coin ID and network domain. Reservations add across a bundle and enforce a minimum aggregate fee, not an exact fee cap. VM cost is not a fee.

The complete walkthrough, reference and evidence review are in the embedded source archive under docs/spec/fee-payment-tutorial.md, implemented-reference.md and fee-payment-review.md. The source archive includes language-v0.3.md. REBUILD.md explains offline builds and modified-library rebuilds. Package verification compares these three fee cases between the packaged binary and both offline rebuilds. No public-network or wallet integration is claimed.
