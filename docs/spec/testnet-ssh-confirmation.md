# Read-only SSH confirmation adapter

This gate adds an internal adapter for a single confirmation observation over SSH.
It is a prerequisite for remote monitoring, not an operator monitoring command.
The existing `monitor_fee.py` still uses its local worker. A later gate will connect
its independent historical signature verification and polling to this adapter.

`ssh_confirmation.read_confirmation(target, packet, duration)` accepts the same
spend, children, depth, prior anchor and explicit endpoint/TLS paths used by the
local observation worker. The caller must derive those expectations from verified
original inputs. The adapter validates their shapes and relationships, but does
not itself check signatures, execute CLVM, approve a spend or establish bundle
identity. It has no CLI, polling, retry, signing or submission path.

## Worker and trust boundary

The SSH exchange is shared with the existing probe. It retains strict host-key
checks, batch authentication, disabled forwarding/multiplexing, literal-loopback
TLS, a bounded input packet, source hashes, a fresh nonce and local process cleanup.
The fixed internal operations are `probe` and `confirmation`; no arbitrary RPC
method or identity selector is exposed. Probe mode still streams only its original
two modules. Confirmation mode additionally streams `confirmation.py` and
`confirmation_transport.py`, in dependency order, and runs the existing fixed
public Testnet11 observation algorithm.

Confirmation transport adds only `get_block_record_by_height` and
`get_puzzle_and_solution` to the existing read routes. It cannot submit a spend.
Remote code has no compiler, signer, keyring access or child process. TLS keys stay
on LOBOT; no remote installation, file output or node/faucet change occurs.

The parent validates the returned public identity, input ID, requested depth,
status, prior anchor and explicit no-chain-proof/no-submission scope. A correct
reply reports one of `unspent`, `confirming`, `confirmed`, `reorged` or
`conflicting-spend`. Existing checks compare exact puzzle/solution bytes, children,
inclusive confirmation depth and stable peaks. RPC observations remain claims by
a trusted node, not independent chain proofs or atomic snapshots.

Each read accepts a duration in `(0, 120]` seconds and the existing socket timeout
in `(0, 30]`. The parent rejects late replies and reaps its local SSH process. The
remote POSIX alarm bounds work after interpreter startup; local SSH termination
does not prove instantaneous remote termination. Cleanup and OS scheduling are
outside a hard whole-command wall-clock guarantee. Packet size remains capped at
256 KiB including streamed source and expectations; larger spends fail before SSH.
The future monitor must account for these per-read bounds and conservative errors.

## Validation and native gate

Three new tests cover invalid expectations before SSH, parent reply binding and
the actual streamed worker/exchange using synthetic RPC data. The latter preserves
the confirmation transport's route validation while replacing network I/O. It
exercises all five states and wrong-version rejection. Existing real TLS tests
continue covering authentication, route limits and RPC response handling. The
fixture does not claim live LOBOT confirmation or independent spend verification.

Windows: **158 tests passed, with 21 Linux-only skips**. Native Linux validation passed, confirmed by the user on 2026-11-24. Run on **LANDO**; this uses disposable fixtures only, with no real coin,
funding, wallet or repeat LOBOT probe:

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

Expected: **158 tests, OK, no skips**. After the native pass, publish this adapter
and verify exact-revision CI before integrating it into the operator monitor.
Remote submission remains a separate later gate.
