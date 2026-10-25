# Build and inspect a height-locked payment

This tutorial uses the working [payment source](../../examples/height-locked-payment.bas) and its [public fixture bindings](../../examples/height-locked-payment.bindings.json). The fixed terms are an owner public key, recipient puzzle hash, amount of 1000 mojos and earliest height 10. The solution is empty. The fixture values are test data; local execution does not require a private key or a running node.

Use compiler `0.1.0-m3.8b`. Build the repository with `cargo build --workspace --locked` using the pinned Rust toolchain, or use an already-built executable. In the command blocks below, `0xbasic` means that executable: replace it with `./target/debug/0xbasic` on Linux or `./target/debug/0xbasic.exe` in PowerShell. If using a native `CARGO_TARGET_DIR`, use its `debug/0xbasic` path instead. Run from the repository root. `payment-tutorial-build` must not already exist; choose a new output name rather than deleting an existing artifact.

The nine marked command blocks below are read and executed verbatim as argument lists by `tools/verify_tutorial.py`, substituting only the executable path. Verification uses an isolated working directory with copied example files; it will not overwrite your own tutorial build.

## Understand the program

The contract checks that the fixed amount is positive and the height is within the unsigned 32-bit range. It emits these four conditions in order:

1. `ASSERT_MY_AMOUNT`: the spent coin's amount must equal the fixed amount.
2. `ASSERT_HEIGHT_ABSOLUTE`: the chain must satisfy the fixed height lock.
3. `AGG_SIG_ME`: a signature from the owner must authorize the application message in the actual coin/network context.
4. `CREATE_COIN`: create an output of exactly the fixed amount at the recipient puzzle hash.

`EMIT` constructs the returned condition list; it does not contact a blockchain. The `PaymentMessage` helper hashes a versioned UTF-8 prefix plus a zero byte, owner bytes, recipient bytes, the 8-byte unsigned amount and 4-byte unsigned height. The signing layer then uses that application message, the actual spent coin ID and the simulator/network's additional signing data. Do not sign only the application hash or substitute a fixture coin ID for a funded coin.

## Check and inspect

<!-- tutorial:version -->
```text
0xbasic --version
```

Expect identifiers for compiler `0.1.0-m3.8b`, language `0.1`, ABI `1` and target `chia-clvm-0.19-strict-v1`.

<!-- tutorial:check -->
```text
0xbasic check examples/height-locked-payment.bas --json
```

Expect `ok: true`. Checking requires no actual fixed values.

<!-- tutorial:ast -->
```text
0xbasic explain examples/height-locked-payment.bas --stage ast --json
```

<!-- tutorial:ir -->
```text
0xbasic explain examples/height-locked-payment.bas --stage ir --json
```

AST is parsed syntax; IR is the checked, lowered representation. Both retain source references and write no artifacts. These debug representations are compiler-versioned.

<!-- tutorial:clvm -->
```text
0xbasic explain examples/height-locked-payment.bas --stage clvm --bindings examples/height-locked-payment.bindings.json --json
```

This binds the fixed values and shows template/puzzle bytes and hashes without executing them. The bound puzzle hash identifies the puzzle a contract coin must use.

## Build and execute locally

<!-- tutorial:build -->
```text
0xbasic build examples/height-locked-payment.bas --bindings examples/height-locked-payment.bindings.json --out payment-tutorial-build --json
```

The new directory contains `manifest.json` and binary/hex forms of the template and bound puzzle. The manifest records versions, source identity, normalized bindings, schemas and hashes. Byte SHA-256 and CLVM tree hash are different values. Preserve the whole directory; see the [compatibility policy](experimental-compatibility.md) before changing compiler versions.

<!-- tutorial:run -->
```text
0xbasic run payment-tutorial-build/manifest.json --json
```

No `--solution` argument is necessary: the default empty object encodes the empty solution. Expect `ok: true`, `validation: "clvm-execution-only"`, local cost `"1487727"`, and a raw CLVM tree containing the four conditions described above. The key, recipient and application message match the committed fixtures. This succeeds locally regardless of current chain height because returning a height condition is not checking that condition against a blockchain. No signature is generated or verified by this command.

## Observe deliberate failures

The next two commands intentionally fail. Run them separately if your shell stops on nonzero exit status.

<!-- tutorial:cost-failure -->
```text
0xbasic run payment-tutorial-build/manifest.json --max-cost 1 --json
```

Expect exit 3, `ok: false`, E0501 and a null result: the local execution budget is too small. It is not a consensus-fee estimate.

<!-- tutorial:overwrite-failure -->
```text
0xbasic build examples/height-locked-payment.bas --bindings examples/height-locked-payment.bindings.json --out payment-tutorial-build --json
```

Expect exit 4 and E0600 because the output directory already exists. Its original artifacts must remain unchanged.

## From local execution to a confirmed test payment

The optional [simulator guide](../../simulator/README.md#m5-1b-compiled-payment-through-the-full-node) supplies the separate environment and commands for a confirmed spend. Its M5-1b harness builds with deterministic test-key bindings, farms real rewards, confirms funding, rejects a missing signature, signs using the funded coin and effective domain, then farms the payment block. It verifies the spent input, exactly one recipient child of the promised amount, and untouched funding change. The harness's recipient/key bindings differ from this tutorial's historical condition fixtures, so their puzzle hashes need not match.

Native Windows/Linux SpendSim and full-node payment gates have passed. This tutorial verifier checks the offline compiler commands only; it does not reinstall or rerun those simulators. Wallet coin selection, real-key management, fees, RPC submission and testnet/mainnet deployment are separate work.

## Verify this tutorial on native Linux

M5-4 Windows verification passed all nine documented commands and their result assertions. From the native checkout used for earlier tests, refresh the local changes and run:

```bash
set -e
test -f Cargo.toml
rsync -a /mnt/artoo/e/DEV/0xBASIC/tools/verify_tutorial.py tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/payment-tutorial.md docs/spec/
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
if [ ! -x "$CARGO_TARGET_DIR/debug/0xbasic" ]; then
    cargo build --workspace --locked
fi
python3 tools/verify_tutorial.py --binary "$CARGO_TARGET_DIR/debug/0xbasic"
```

Expected: nine individual PASS lines followed by `PASS: all 9 documented payment commands and expected results verified.` The aggregate is `.work/m5/tutorial-linux.json`; command outputs and copied fixtures remain in a unique `.work/m5/tutorial-*` directory. Each CLI process has a 20-second timeout. Prior success is invalidated before verification; only a fully successful run publishes the new aggregate. Run one verifier at a time per checkout.

No package installation, simulator run or Rust-suite rerun is needed. Compiler code and existing fixtures are unchanged. The verifier checks the marked CLI blocks, not repository cloning, toolchain installation or these shell setup commands. Compiler CI now includes the verifier on Windows/Linux; a hosted result is pending publication. The user subsequently confirmed native Linux M5-4 passed; the tutorial gate is complete on both platforms.
