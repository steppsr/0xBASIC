# TN-1: read-only testnet RPC observation

Status: Windows passed all 18 integration tests and package verification (30 extracted CLI checks and two offline rebuilds) on 2026-11-09. Native LANDO passed, confirmed by the user on 2026-11-09. This implements the read-only portion of the [TN-0 design](testnet-design.md), using a separate Python standard-library tool. No live host, endpoint, certificate set or testnet coin has been selected or contacted.

`integration/testnet_probe.py` accepts only explicit loopback HTTPS with mutual TLS, private CA and client credentials. Four read-only POST routes are allowed. It requires reviewed node 2.7.5, testnet11/txch/genesis identity, a non-null synced peak and unchanged before/after peak observations. Optional coin inspection recomputes Chia coin ID using canonical amount encoding, validates uint64 amount and unspent/confirmation fields, and compares expected puzzle/amount when supplied. It does not attest effective node constants or validate a spend.

[Usage and limits](../../integration/README.md) describe the explicit arguments, socket timeouts, 1 MiB response bound, exact JSON handling, noninteractive credential loading and report semantics. A failed run invalidates stale success. The output is rpc-observation-only, with no claim of atomic snapshot or spend validation. Live-host connection remains a later operator-selected action.

## Isolated validation

Eighteen unittest methods exercise positive connection/coin observations, independent coin-ID boundary vectors, wrong network/version/genesis, unsynced/missing peaks, spent/malformed/mismatched coins, structured missing-coin errors, changed peaks, JSON bounds/duplicate keys and invalid endpoint forms. Reporting tests cover stale success on setup and observation failure and credential/report overlap.

The suite also starts a fake RPC server bound only to 127.0.0.1 with public test certificates and runs the actual CLI through mutual TLS. It verifies successful coin observation with poisoned proxy environment variables, untrusted server rejection, missing client-certificate rejection, no redirects, response-size limits, socket timeout and mutating-route rejection before network I/O. The server shuts down after tests. No actual Chia node or wallet is involved.

Compiler CI runs this suite on Windows and Linux. The complete source archive now includes `integration/`, its tests, usage and public TLS fixtures so the archived workflow is reproducible. No Rust code, compiler identity, dependency lock, signing code or release asset changes are part of TN-1. Packaging remains local/CI candidate creation only.

## Native LANDO gate

This gate tests isolated fixtures only; it does not set up or contact a live testnet node. Use the existing native checkout. No Chia environment or simulator rerun is needed. Packaging checks the source-inclusive archive and retains existing offline rebuild checks.

```bash
(
set -e
cd ~/sourcecode/0xBASIC
source "$HOME/.cargo/env"
export CARGO_TARGET_DIR="$HOME/.cache/0xbasic/target"
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
rsync -a /mnt/artoo/e/DEV/0xBASIC/.github/ .github/
rsync -a --exclude='__pycache__/' /mnt/artoo/e/DEV/0xBASIC/tools/ tools/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/
python3 tools/verify_m0.py
python3 -m unittest discover -s integration -p 'test_*.py'
python3 tools/package_experimental.py
)
```

Expected: specification checks, 18 integration tests and package creation pass. Package verification retains 30 extracted CLI checks and two offline rebuilds. This package gate is needed because the source archive's inventory now includes the new integration tool and fixtures. Allow several minutes for rebuilds. Preserve `.work/packages/package-linux.json`.

Native confirmation is complete. Commit/push the TN-0/TN-1 changes and verify exact-revision CI, then continue automatically to TN-2 work that does not depend on a live host. A real connection needs explicit host/endpoint/certificate choices. No funding or submission is part of this gate.
