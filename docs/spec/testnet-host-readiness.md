# Testnet host readiness: reuse LOBOT without disruption

Status: the user selected **LOBOT**, an existing Testnet11 node serving a TXCH faucet, and explicitly requires that node and faucet remain running. Read-only baseline checks passed on 2026-11-14. LANDO is no longer the proposed node host. The older LANDO inventory and proposed new-node layout below are historical and must not be used as deployment instructions.

## LOBOT baseline and existing services

The node remains rooted at `/home/steve/.chia/mainnet`. Its directory name does not override the verified configuration or RPC identity. No relocation, initialization, upgrade, restart, service edit, key import or faucet/wallet transaction is required or performed for these checks.

Existing SSH trust reached `steve@LOBOT`, running Ubuntu 22.04.5 LTS. Both installed package metadata and the Chia CLI report 2.7.5. The running full-node executable resolves to `/opt/chia/resources/app.asar.unpacked/daemon/start_full_node`. Existing daemon, full-node and wallet processes remained present after the checks. No faucet transaction or application-level availability test was performed; the checks did not modify its services.

Authenticated read-only RPC used `https://127.0.0.1:8555` with the existing CA certificate and full-node client certificate/key under the explicit root. TLS keys were used only on LOBOT for the handshake, never printed or copied. The request allowlist was limited to version, network, blockchain state and effective constants. No wallet, faucet or mutating RPC method was invoked.

| Check | Result |
| --- | --- |
| Live RPC identity | Chia 2.7.5 / testnet11 / txch / reviewed genesis |
| Baseline snapshot | Synced, not in sync mode; stable peak 4,964,268 during the constants check |
| Effective consensus constants | Exact match to reviewed upstream Testnet11 configuration applied to the pinned defaults |
| Configured Testnet11 overrides | Exact match to reviewed upstream configuration |
| Height-dependent offline flags | Expected mempool flags 50,987,607 at that observed height |
| Bundled `chia_rs` library | SHA-256 exactly matches the shared-library member of the official 0.48.0 CPython 3.12 Linux x86_64 wheel |
| Repository read-only probe | Unchanged probe source ran in memory on LOBOT; passed at stable peak 4,964,290 with no selected coin and zero submissions |

The [dated baseline evidence](testnet-lobot-baseline.json) records timestamps, hashes, comparison results and the probe output. The [official PyPI metadata](https://pypi.org/pypi/chia_rs/0.48.0/json) supplied the wheel URL/hash; the download was verified and compared locally in memory, with no installation. The upstream configuration's hash was checked against the existing [source audit](testnet-upstream-audit.json).

These observations establish the reviewed baseline checks, not independent attestation of the entire running process or continuing chain state. Fresh observations remain mandatory before any eventual signing/submission. No owner, funded contract coin, destination or transaction budget has been selected.

## Next: separate tools, retain the existing node

Reuse the existing node and its explicit loopback endpoint. The next setup concerns only an isolated compiler/integration workspace and pinned offline runtime, separate from `/opt/chia`, the running node's root and the faucet. The offline tools retain their reviewed Chia 2.7.4/chia_rs 0.48.0 runtime; they must not upgrade or activate the node's bundled environment. No new node runtime, blockchain database or node service is needed.

Prepare a concrete workspace/runtime plan before creating it. Keep any owner key in the protected native-home signer vault, outside node data, the checkout, shared mounts and reports. Do not reuse the faucet wallet or its keys. Preserve the existing root, ports, service supervisor and start/stop behavior. No configuration edits or restarts are included in workspace setup.

Additional read-only workspace inventory found Git on LOBOT's SSH PATH, but no Cargo, Rust or uv there, no `~/.cargo/env`, and no `~/sourcecode/0xBASIC` checkout. Native storage had about 1.2 TiB available; RAM was 7.6 GiB total/4.2 GiB available, with 1.8 GiB of 2 GiB swap in use. These are snapshots, not a diagnosis of service performance.

The recommended next design keeps the existing compiler/offline signing environment on LANDO and adds a small SSH-executed RPC worker on LOBOT, keeping node TLS credentials on LOBOT. That remote-worker mode is **not implemented yet** and needs its own design, Windows/native fixture tests, timeout/cleanup and identity checks before use. The alternative is a separate tools runtime on LOBOT with resource limits. The operator-host choice is pending; do not install either option or copy TLS keys merely from this recommendation.

After workspace validation, review a test-only owner, recipient/change destinations, funding method, separate funding/spend fee limits and confirmation policy. Each concrete funding or spend remains a separate reviewed transaction. Use the [operator walkthrough](testnet-operator-walkthrough.md); the read-only baseline does not grant permission to send funds or create/import wallet keys.

## Historical LANDO inventory (not the selected node host)

Existing SSH trust and batch authentication reached `steve@LANDO`. Only OS/memory/disk information, executable availability, process/service names and top-level directory names were queried. No configuration contents, keys or RPC certificates were read; no service or file was changed and no Chia RPC request was made.

| Item | Observation |
| --- | --- |
| Host/account | LANDO / steve |
| OS | Ubuntu 24.04.4 LTS, x86_64; kernel reported 7.0.0-34-generic |
| Memory | 31 GiB total, approximately 29 GiB available at inventory time |
| Native home filesystem | `/dev/sda2`, approximately 440 GiB total / 385 GiB available |
| SSH-session PATH | `/usr/bin/python3` and `/usr/bin/git` found; `chia` and `uv` not found on that PATH |
| Existing Chia state | `~/.chia/mainnet` directory; running process names include `chia_daemon` and `chia_harvester` |
| Proposed dedicated directory | `~/.local/share/0xbasic-testnet` was not present |
| Signer directory | `~/.local/share/0xbasic-signer` was not present |

PATH absence does not establish that Chia is uninstalled: running Chia processes were observed. Process-name inspection does not identify their runtime, data root, service supervisor or credentials. The filtered running-service list produced no Chia-named matches; this is not proof of no managed service. Disk/memory observations are a dated snapshot, not a capacity guarantee.

## Superseded new-node layout (do not execute)

If LANDO remains selected, use a dedicated installation and explicit roots; preserve existing mainnet/harvester processes and configuration. Do not activate or upgrade the existing runtime, use the default `~/.chia`, reuse keyrings, modify existing units or run broad `chia stop all` commands.

| Purpose | Proposed location or policy |
| --- | --- |
| Dedicated node/runtime parent | `/home/steve/.local/share/0xbasic-testnet/` on native storage |
| Dedicated runtime | `runtime/` beneath that parent; separate from the repository's pinned offline environment and existing Chia processes |
| Node root | `node/` beneath that parent, always explicit |
| Node keyring boundary | Dedicated explicit root beneath that parent if required by the selected startup method; no imported wallet/owner keys |
| RPC | Explicit unused loopback port, selected after checking listeners; no public RPC binding |
| Owner signer | Existing protected-file design under `/home/steve/.local/share/0xbasic-signer/`, separate from the node/runtime |
| Trial evidence | Native local directory with explicit paths; no secret material in checkout/reports/share |

These are proposed paths, not directories already created. An alternate host needs its own inventory and layout. No install/init/start/service command is authorized merely by this document.

## Original baseline checklist (now supplemented by LOBOT results)

Record the chosen host/account and explicit roots; existing service/runtime isolation; dedicated node build/source identity; Python and installed dependency versions; effective network configuration/constants and activation heights; RPC listen address/port and certificate paths; sync state; storage and startup/stop procedure. Compare with the dated [TN-0 baseline](testnet-design.md) and [source audit](testnet-upstream-audit.json). The selected public baseline remains Chia 2.7.5/testnet11; an unreviewed installed version must not be accepted by changing identity checks.

The pinned offline verifier remains Chia 2.7.4/chia_rs 0.48.0. RPC name/genesis/version alone do not attest installed code or all effective constants. Installation and configuration must produce a concrete reviewed baseline before any preparation/signing/submission workflow is treated as ready for public use.

The original new-node installation proposal is superseded by the existing LOBOT node and successful read-only baseline above. Real owner creation, funding method/destinations/amounts, fee limits, confirmation policy and each public send still need concrete review. Follow the [operator walkthrough](testnet-operator-walkthrough.md) for those later steps.
