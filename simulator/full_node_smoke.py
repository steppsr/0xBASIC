"""Isolated real-full-block smoke. No wallet, RPC server, peers or payment claim."""
import argparse
import asyncio
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
import uuid
from unittest.mock import patch

from smoke import ROOT, BASE, preflight, require

WORK = ROOT / ".work/m5"


def contained(path, root=WORK):
    result = Path(path).resolve()
    require(result.is_relative_to(root.resolve()), f"Path outside isolated root: {result}")
    return result


def source_check():
    evidence = json.loads((BASE / "full_node_sources.json").read_text(encoding="utf-8"))
    distribution = metadata.distribution("chia-blockchain")
    for relative, expected in evidence["source_hashes"].items():
        actual = hashlib.sha256(Path(distribution.locate_file(relative)).read_bytes()).hexdigest()
        require(actual == expected, f"Full-node source mismatch: {relative}")
    return evidence


def guard_network(event, args):
    if event in {"socket.connect", "socket.bind"}:
        address = args[1]
        if isinstance(address, tuple):
            require(address[0] in {"127.0.0.1", "::1", "localhost"},
                    f"Non-loopback socket forbidden: {address}")


def loopback_port(_name):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def run_node(run, binary=None):
    from chia.simulator.block_tools import BlockTools, test_constants
    from chia.simulator.keyring import TempKeyring
    from chia.simulator.start_simulator import create_full_node_simulator_service
    from chia.simulator.simulator_protocol import FarmNewBlockProtocol
    from chia.util.default_root import DEFAULT_ROOT_PATH, DEFAULT_KEYS_ROOT_PATH, SIMULATOR_ROOT_PATH
    from chia_rs.sized_bytes import bytes32

    node_root, keys, plots = run / "node", run / "keys", run / "plots"
    require(DEFAULT_ROOT_PATH == node_root and DEFAULT_KEYS_ROOT_PATH == keys
            and SIMULATOR_ROOT_PATH == run / "simulator", "Import-time root mismatch")
    for path in (node_root, keys, plots):
        contained(path, run).mkdir(parents=True, exist_ok=True)
    keyring = TempKeyring(existing_keyring_path=str(keys / "keyring.yaml"), use_os_credential_store=False)
    bt = None
    try:
        with keyring as keychain, patch("chia.simulator.block_tools.find_available_listen_port", loopback_port):
            require(contained(keychain.keyring_wrapper.keys_root_path, run) == keys, "Wrong key root")
            require(not keychain.get_all_private_keys(), "Expected fresh test keychain")
            bt = BlockTools(test_constants, root_path=node_root, keychain=keychain,
                            automated_testing=True, plot_dir=str(plots), config_overrides={
                "self_hostname": "127.0.0.1", "full_node.port": 0, "full_node.rpc_port": 0,
                "full_node.enable_upnp": False, "full_node.introducer_peer": None,
                "full_node.dns_servers": [], "full_node.full_node_peers": [],
                "full_node.target_outbound_peer_count": 0, "full_node.send_uncompact_interval": 0,
                "full_node.single_threaded": True, "simulator.auto_farm": False,
                "simulator.use_current_time": False,
            })
            contained(bt.plot_dir, run)
            contained(bt.temp_dir, run)
            await bt.setup_keys()
            print("Creating/loading three isolated k19 plots", flush=True)
            await bt.setup_plots(num_og_plots=3, num_pool_plots=0,
                                 num_non_keychain_plots=0, num_v2_plots=0, plot_size=19)
            service = await create_full_node_simulator_service(node_root, bt.config, bt, connect_to_daemon=False)
            node = service._node
            # Construct the real server/API wiring but do not start transport services.
            # Disable discovery only; consensus, signatures and block validation are unchanged.
            node.full_node_peers = None
            contained(node.db_path, run)
            api = service._api
            recipient = bytes32(bytes.fromhex("11" * 32))
            try:
                async with node.manage():
                    require(node.blockchain.get_peak() is None, "Expected empty full-node chain")
                    require(await node.coin_store.is_empty(), "Expected empty coin store")
                    blocks = []
                    for _ in range(3):
                        block = await api.farm_new_transaction_block(FarmNewBlockProtocol(recipient))
                        peak = node.blockchain.get_peak()
                        require(peak is not None and peak.header_hash == block.header_hash,
                                "Farmed block did not become validated peak")
                        require(await node.block_store.get_full_block(block.header_hash) == block,
                                "Full block missing from store")
                        require(block.is_transaction_block(), "Expected transaction block")
                        blocks.append({"height": int(block.height), "header_hash": block.header_hash.hex()})
                    records = await node.coin_store.get_coin_records_by_puzzle_hash(True, recipient)
                    expected = {coin.name(): coin for block in await api.get_all_full_blocks()
                                for coin in block.get_included_reward_coins() if coin.puzzle_hash == recipient}
                    require(len(expected) >= 4 and {r.coin.name() for r in records} == set(expected),
                            "Confirmed rewards differ from full-block reward claims")
                    for record in records:
                        require(record.coin == expected[record.coin.name()] and record.coinbase
                                and not record.spent and record.coin.amount > 0, "Invalid reward record")
                        require(await node.coin_store.get_coin_record(record.coin.name()) == record,
                                "Reward lookup mismatch")
                    require(not node.mempool_manager.mempool.all_item_ids(), "Unexpected mempool spends")
                    require(service._server.webserver is None and service.rpc_server is None
                            and not service._server.all_connections, "Unexpected network service")
                    outcome = {"blocks": blocks, "peak_height": int(peak.height),
                               "reward_records": [r.to_json_dict() for r in sorted(records, key=lambda r: r.coin.name())],
                               "constants": bt.constants.to_json_dict(), "plot_count": len(bt.plot_manager.plots),
                               "plot_size": 19, "v2_plot_count": 0, "network_services_started": False}
                    if binary is not None:
                        from full_node_payment import payment
                        outcome["payment"] = await payment(node, api, binary, run)
                        outcome["peak_height"] = int(node.blockchain.get_peak().height)
                        require(service._server.webserver is None and service.rpc_server is None
                                and not service._server.all_connections, "Unexpected payment network service")
                require(node._shut_down, "Full node did not shut down")
            finally:
                service._server.close_all()
                await service._server.await_closed()
    finally:
        if bt is not None:
            bt.plot_manager.stop_refreshing()
    require(keyring.cleaned_up and not keys.exists(), "Test keyring not cleaned up")
    outcome["resources_closed"] = True
    return outcome


def worker(run, binary=None):
    profile, lock, versions = preflight()
    require(platform.python_version() == "3.13.7", "Full-node profile requires Python 3.13.7")
    evidence = source_check()
    require(evidence["chia_commit"] == profile["chia_commit"], "Source profile commit mismatch")
    require(not any(name == "chia" or name.startswith("chia.") for name in sys.modules),
            "Chia imported before isolation")
    run = contained(run)
    require(run.is_dir(), "Missing worker directory")
    for key, name in [("CHIA_ROOT", "node"), ("CHIA_KEYS_ROOT", "keys"), ("CHIA_SIMULATOR_ROOT", "simulator")]:
        os.environ[key] = str(contained(run / name, run))
    tmp = contained(run / "tmp", run)
    tmp.mkdir()
    tempfile.tempdir = str(tmp)
    for key in ("TMP", "TEMP", "TMPDIR"):
        os.environ[key] = str(tmp)
    sys.addaudithook(guard_network)
    if binary is not None:
        require(binary.is_file(), "Build CLI first or pass --binary")
    outcome = asyncio.run(run_node(run, binary))
    report = {"schema_version": 1, "validation": "full-node-confirmed-test-payment" if binary else "full-node-environment-block-smoke-only",
              "python": platform.python_version(), "platform": sys.platform,
              "packages": versions, "chia_commit": profile["chia_commit"],
              "source_hashes": evidence["source_hashes"],
              "requirements_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "outcome": outcome}
    if binary is not None:
        report["binary_sha256"] = hashlib.sha256(binary.read_bytes()).hexdigest()
        report["payment_source_hashes"] = {str(path.relative_to(ROOT)).replace("\\", "/"):
            hashlib.sha256(path.read_bytes()).hexdigest() for path in
            [BASE / "full_node_payment.py", BASE / "payment.py", ROOT / "examples/height-locked-payment.bas"]}
    (run / "result.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payment", action="store_true", help="Also confirm a compiled payment after a signature rejection")
    parser.add_argument("--binary", type=Path, help="CLI executable for --payment")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.binary and not args.payment:
        parser.error("--binary requires --payment")
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve() if args.payment else None
    if args.worker:
        worker(args.worker, binary)
        return
    WORK.mkdir(parents=True, exist_ok=True)
    platform_name = "windows" if sys.platform == "win32" else "linux"
    stem = "full-node-payment" if args.payment else "full-node-smoke"
    destination = WORK / f"{stem}-{platform_name}.json"
    destination.unlink(missing_ok=True)
    run = contained(WORK / ("run-" + uuid.uuid4().hex))
    run.mkdir()
    log = run / "output.log"
    print(f"Full-node smoke (10 minute timeout); log: {log}", flush=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", str(run)]
    if binary is not None:
        command.extend(["--payment", "--binary", str(binary)])
    with log.open("w", encoding="utf-8") as output:
        subprocess.run(command,
                       cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=600)
    report = json.loads((run / "result.json").read_text(encoding="utf-8"))
    require(report["outcome"]["resources_closed"], "Incomplete worker result")
    (run / "result.json").replace(destination)
    message = "full-node funding, missing-signature rejection and exact payment verified" if args.payment else "full-node blocks and reward records verified"
    print(f"PASS: {message}; resources closed. Report: {destination}")


if __name__ == "__main__":
    main()
