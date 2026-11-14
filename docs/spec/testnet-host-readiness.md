# Dedicated testnet host readiness

Status: read-only inventory obtained on 2026-11-13; deployment and public trial are not approved or performed by this record. The user previously selected the LANDO/separate-testnet direction. New evidence of an existing harvester requires confirming the host choice before changing that machine.

## Observed inventory

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

## Proposed layout, pending host decision

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

## Evidence needed before a live probe

Record the chosen host/account and explicit roots; existing service/runtime isolation; dedicated node build/source identity; Python and installed dependency versions; effective network configuration/constants and activation heights; RPC listen address/port and certificate paths; sync state; storage and startup/stop procedure. Compare with the dated [TN-0 baseline](testnet-design.md) and [source audit](testnet-upstream-audit.json). The selected public baseline remains Chia 2.7.5/testnet11; an unreviewed installed version must not be accepted by changing identity checks.

The pinned offline verifier remains Chia 2.7.4/chia_rs 0.48.0. RPC name/genesis/version alone do not attest installed code or all effective constants. Installation and configuration must produce a concrete reviewed baseline before any preparation/signing/submission workflow is treated as ready for public use.

After the host choice, prepare a concrete installation/configuration plan with exact runtime, paths, ports and service commands for review. Only then set up the dedicated node, record its baseline and run an explicitly selected read-only probe. Real owner creation, funding method/destinations/amounts, fee limits, confirmation policy and each public send still need concrete review. Follow the [operator walkthrough](testnet-operator-walkthrough.md) for those later steps.
