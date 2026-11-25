# Read-only SSH worker gate

The approved layout keeps compiler and offline signing work on LANDO and uses
LOBOT's existing Testnet11 node through a lightweight SSH worker. Node TLS keys
stay on LOBOT. No compiler, Python environment, checkout or service is installed
there. Existing node, faucet and harvester services remain untouched.

`integration/ssh_probe.py` implements a read-only probe. The published first gate
checks the node without selecting a coin; the next gate adds explicit coin checks.
It streams the repository's fixed `network_identity.py` and `testnet_probe.py`
modules into `/usr/bin/python3 -I -B` on the remote host. Only the existing public
Testnet11 observation runs; there is no arbitrary RPC method, identity selector,
signing, submission or monitoring option. Remote dispatch and
monitoring are subsequent implementation gates.

## Trust and bounds

SSH requires existing host-key trust and batch authentication. Agent forwarding,
port forwarding, terminal allocation, local commands and connection multiplexing
are disabled. The operator's SSH configuration and both hosts remain trusted;
this is not a sandbox for hostile source code or a compromised host. TLS paths
travel as JSON on stdin, never as shell text. Certificate/key contents are loaded
only by the remote TLS context and are not returned. The existing probe enforces
literal-loopback HTTPS, CA verification, fixed network/version/genesis, synced
state and a stable before/after peak.

The parent uses a monotonic deadline (default 30 seconds, maximum 120), rejects
late/nonzero/malformed replies, and kills/reaps its local SSH process and closes
handles on failure. A temporary local input file avoids an unbounded Windows
stdin-pipe write; it contains source and paths, not TLS key contents. The remote
POSIX alarm independently bounds stdin transfer and RPC work once its interpreter
starts. Alarm expiry exits that dedicated Python process and the OS closes its
sockets; it never stops the node. There are no remote children or retries.

Terminating local SSH does not prove instantaneous remote termination. Remote
startup and OS scheduling are outside the alarm's coverage; local process cleanup
is outside the elapsed-result acceptance deadline. The remote alarm starts later
than the parent deadline. No send/recovery guarantee should be inferred for a
future transaction worker from this read-only implementation.

Replies bind a fresh nonce and streamed source hashes. These detect request mixups,
not a dishonest host. The CLI writes a JSON envelope to stdout only on success;
errors go to stderr with exit 1 (usage errors: 2). The envelope contains an
`observation` and is labelled `ssh-read-only-probe`. The wrapper is not a direct
preparation input; preparation/report export integration is a later gate. Equal
peaks are not an atomic snapshot or chain attestation.

## Next gate: explicit coin observations

The optional `--coin-id`, `--expected-puzzle-hash` and `--expected-amount` flags
must be supplied together. Hashes are normalized 32-byte hex values; amount is
an unsigned 64-bit integer in mojos. Invalid or incomplete expectations fail
before SSH starts. Omitting all three retains the original no-coin behavior.

The worker uses the existing read-only coin observer: fixed public network
identity, exact coin ID derived from parent/puzzle/amount, matching expected
puzzle and amount, unspent state, consistent confirmation metadata and stable
before/after peak. The parent also checks that the returned coin matches its
original expectations. There is no coin discovery, wallet lookup, funding,
signature or submission. A successful observation does not reserve the coin or
prove that it will remain unspent.

Two additional regression tests cover rejection before SSH and actual streamed
worker/parent execution with synthetic RPC replies, including spent and
mismatched coins and reply substitution. Windows passed 152 integration tests
with 21 Linux-only skips. The user confirmed native Linux validation passed on 2026-11-24;
the commands below now expect **152 tests, OK, no skips**. No live coin or funded
wallet is needed, and the live no-coin probe does not need to be repeated.

## Validation and native Linux gate

The user confirmed native Linux testing and the LANDO-to-LOBOT probe passed on
2026-11-24 after configuring SSH key authentication. The commands below retain
the reproducible test procedure; this gate no longer awaits native testing.

Windows: 150 integration tests passed, with 21 Linux-only skips. Five new tests
cover arguments, request/reply binding, real local timeout cleanup, remote stdin
and RPC watchdogs, and remote execution/error sanitization. The two remote tests
run on Linux; fixtures use no live node, keys or transactions. The new client also
passed a read-only live LOBOT probe at 2026-11-14T18:59:00Z: Chia 2.7.5/testnet11,
synced stable height 4,964,971, no coin, zero submissions.

Run on **LANDO** after the Windows share is mounted. The subshell keeps a failure
from closing the SSH login. No Rust build or full-node simulator run is needed
for this slice:

```bash
(
  set -e
  cd ~/sourcecode/0xBASIC
  rsync -a --exclude '__pycache__/' /mnt/artoo/e/DEV/0xBASIC/integration/ integration/
  rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/spec/ docs/spec/
  rsync -a /mnt/artoo/e/DEV/0xBASIC/docs/development.md docs/development.md
  python3 -m unittest discover -s integration -p 'test_*.py'
)
```

Original gate: **150 tests, OK, no skips**, confirmed passed. With the additional
coin checks, expect **152 tests, OK, no skips** before committing that new slice.

With LANDO-to-LOBOT SSH trust and batch authentication already configured, this
additional command exercises the approved topology without installing anything:

```bash
cd ~/sourcecode/0xBASIC
python3 integration/ssh_probe.py \
  --ssh-target steve@LOBOT \
  --endpoint https://127.0.0.1:8555 \
  --ca-cert /home/steve/.chia/mainnet/config/ssl/ca/private_ca.crt \
  --client-cert /home/steve/.chia/mainnet/config/ssl/full_node/private_full_node.crt \
  --client-key /home/steve/.chia/mainnet/config/ssl/full_node/private_full_node.key \
  --duration 30 --timeout 5
```

Expected: exit 0 and the `ssh-read-only-probe` JSON envelope with testnet11,
synced state, `coin: null` and `transactions_submitted: 0`. A moving peak may fail
the observation; an operator can explicitly run a fresh observation. If SSH trust
or authentication is missing, report the failure rather than disabling host-key
checks, copying node TLS keys or changing the node/faucet configuration.
