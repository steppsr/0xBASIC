"""M4-2 payment and M4-3 height/signature scenarios through pinned SpendSim."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from smoke import BASE, ROOT, WORK, preflight, require, simulator_constants

AMOUNT = 1000
HEIGHT = 10
MAX_COST = 10_000_000


def invoke(binary, *args):
    process = subprocess.run([str(binary), *map(str, args), "--json"], capture_output=True, text=True, check=False)
    require(process.returncode == 0, f"CLI failure: {process.stdout} {process.stderr}")
    result = json.loads(process.stdout)
    require(result["ok"] is True, "CLI returned a diagnostic")
    return result["result"]


def condition_tree_json(program):
    # Only the small independently constructed condition tree is passed here.
    if program.pair is None:
        return {"atom": program.as_atom().hex()}
    return {"pair": [condition_tree_json(program.first()), condition_tree_json(program.rest())]}


def coin_json(coin):
    return {"id": coin.name().hex(), "parent": coin.parent_coin_info.hex(),
            "puzzle_hash": coin.puzzle_hash.hex(), "amount": str(coin.amount)}


SCENARIOS = ("authorized-at-height", "authorized-after-height", "premature-height",
             "missing-signature", "wrong-owner", "message-only-signature", "wrong-network-domain")


async def payment(binary, directory, profile, scenario="authorized-at-height"):
    require(scenario in SCENARIOS, "Unknown payment scenario")
    from chia._tests.util.spend_sim import SpendSim, SimClient
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia.util.errors import Err
    from chia_rs import AugSchemeMPL, Coin, G2Element, SpendBundle, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_ints import uint64

    constants = simulator_constants(profile)
    # Public deterministic TEST seed, never a wallet/user key.
    key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/M4/public-test-key/v1").digest())
    owner = key.get_g1()
    funding = Program.to(1)  # Anyone-can-spend, isolated test funding only.
    recipient = Program.to((1, []))  # Known test recipient reveal, distinct from funding.
    recipient_hash = recipient.get_tree_hash()
    bindings = {"owner": {"hex": bytes(owner).hex()}, "recipient": {"hex": recipient_hash.hex()},
                "paymentAmount": str(AMOUNT), "earliestHeight": str(HEIGHT)}
    binding_file = directory / "bindings.json"
    binding_file.write_text(json.dumps(bindings), encoding="utf-8")
    out = directory / "payment"
    source = ROOT / "examples/height-locked-payment.bas"
    invoke(binary, "build", source, "--bindings", binding_file, "--out", out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name in ["template", "puzzle"]:
        blob = (out / f"{name}.clvm").read_bytes()
        require(hashlib.sha256(blob).hexdigest() == manifest[name]["program_sha256"], "Artifact byte digest mismatch")
        require(Program.from_bytes(blob).get_tree_hash().hex() == manifest[name]["tree_hash"], "Upstream tree hash mismatch")
    puzzle = Program.from_bytes((out / "puzzle.clvm").read_bytes())
    solution = Program.to([])
    application_message = hashlib.sha256(b"0xBASIC/payment/v1\x00" + bytes(owner) + bytes(recipient_hash)
                                         + AMOUNT.to_bytes(8,"big") + HEIGHT.to_bytes(4,"big")).digest()
    expected = Program.to([[73, AMOUNT], [83, HEIGHT], [50, bytes(owner), application_message], [51, recipient_hash, AMOUNT]])
    upstream_cost, conditions = puzzle.run_with_cost(MAX_COST, solution)
    require(bytes(conditions) == bytes(expected), "Payment conditions differ from independent specification")
    local = invoke(binary, "run", out / "manifest.json")
    require(local["validation"] == "clvm-execution-only", "Unexpected CLI validation label")
    require(local["tree"] == condition_tree_json(expected), "Local CLI condition tree mismatch")

    async with SpendSim.managed(defaults=constants) as sim:
        client = SimClient(sim)
        await sim.farm_block(funding.get_tree_hash())
        await sim.farm_block(funding.get_tree_hash())
        rewards = await client.get_coin_records_by_puzzle_hash(funding.get_tree_hash(), include_spent_coins=False)
        funding_coin = min((r.coin for r in rewards if r.coin.amount > AMOUNT), key=lambda c:(c.amount,c.name()))
        contract_coin = Coin(funding_coin.name(), puzzle.get_tree_hash(), uint64(AMOUNT))
        change_coin = Coin(funding_coin.name(), funding.get_tree_hash(), uint64(funding_coin.amount - AMOUNT))
        funding_bundle = SpendBundle([make_spend(funding_coin, funding, Program.to([
            [51, puzzle.get_tree_hash(), AMOUNT], [51, funding.get_tree_hash(), funding_coin.amount - AMOUNT]
        ]))], G2Element())
        funding_status, funding_error = await client.push_tx(funding_bundle)
        require(funding_status == MempoolInclusionStatus.SUCCESS and funding_error is None, f"Funding rejected: {funding_status} {funding_error}")
        additions, removals = await sim.farm_block()
        require({c.name() for c in additions} == {contract_coin.name(), change_coin.name()}, "Funding outputs mismatch")
        require([c.name() for c in removals] == [funding_coin.name()], "Funding removal mismatch")
        require((await client.get_coin_record_by_name(funding_coin.name())).spent, "Funding coin not spent")
        before = await client.get_coin_record_by_name(contract_coin.name())
        require(before is not None and not before.spent and before.coin == contract_coin, "Contract coin not funded")
        submission_height = HEIGHT + (1 if scenario == "authorized-after-height" else -1 if scenario == "premature-height" else 0)
        while sim.block_height < submission_height:
            await sim.farm_block()
        require(sim.mempool_manager.peak is not None and sim.mempool_manager.peak.height == submission_height, "Unexpected validation height")
        flags = int(get_flags_for_height_and_constants(sim.mempool_manager.peak.height, constants)) | int(MEMPOOL_MODE)
        require(not flags & int(DONT_VALIDATE_SIGNATURE), "Signature validation bypass")
        final_message = application_message + bytes(contract_coin.name()) + bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA)
        pairs = pkm_pairs_for_conditions_dict(conditions_dict_for_solution(puzzle, solution, MAX_COST), contract_coin, constants.AGG_SIG_ME_ADDITIONAL_DATA)
        require(pairs == [(owner, final_message)], "Upstream signature-pair derivation disagrees")
        signature = AugSchemeMPL.sign(key, final_message)
        require(AugSchemeMPL.verify(owner, final_message, signature), "Signature self-check failed")
        bundle = SpendBundle([make_spend(contract_coin, puzzle, solution)], signature)
        expected_child = Coin(contract_coin.name(), recipient_hash, uint64(AMOUNT))
        rejected_attempts = []
        if scenario not in {"authorized-at-height", "authorized-after-height"}:
            bad_signature = signature
            attempted_message = final_message
            attempted_owner = owner
            expected_error = Err.ASSERT_HEIGHT_ABSOLUTE_FAILED if scenario == "premature-height" else Err.BAD_AGGREGATE_SIGNATURE
            if scenario == "missing-signature":
                bad_signature = G2Element()
                attempted_message = None
            elif scenario == "wrong-owner":
                other_key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/M4/other-public-test-key/v1").digest())
                require(other_key.get_g1() != owner, "Wrong-owner fixture uses owner key")
                attempted_owner = other_key.get_g1()
                bad_signature = AugSchemeMPL.sign(other_key, final_message)
            elif scenario == "message-only-signature":
                attempted_message = application_message
                bad_signature = AugSchemeMPL.sign(key, attempted_message)
            elif scenario == "wrong-network-domain":
                attempted_message = application_message + bytes(contract_coin.name()) + bytes.fromhex("bb" * 32)
                bad_signature = AugSchemeMPL.sign(key, attempted_message)
            if scenario != "premature-height":
                require(not AugSchemeMPL.verify(owner, final_message, bad_signature), "Negative signature is valid")
            rejected_bundle = SpendBundle([make_spend(contract_coin, puzzle, solution)], bad_signature)
            bad_status, bad_error = await client.push_tx(rejected_bundle)
            require(bad_status != MempoolInclusionStatus.SUCCESS and bad_error == expected_error,
                    f"{scenario}: expected {expected_error}, got {bad_status} {bad_error}")
            unchanged = await client.get_coin_record_by_name(contract_coin.name())
            require(unchanged == before and not unchanged.spent, "Rejected spend changed input state")
            require(not await client.get_coin_records_by_parent_ids([contract_coin.name()]), "Rejected spend created children")
            require(await client.get_coin_record_by_name(expected_child.name()) is None, "Rejected spend created recipient")
            require(not await client.get_all_mempool_tx_ids(), "Rejected spend entered active mempool")
            rejected_attempts.append({"scenario": scenario, "status": bad_status.name, "error": bad_error.name,
                                      "mempool_peak_height": int(sim.block_height), "bundle_id": rejected_bundle.name().hex(),
                                      "signature": bytes(bad_signature).hex(),
                                      "signer_public_key": None if attempted_message is None else bytes(attempted_owner).hex(),
                                      "signed_message": None if attempted_message is None else attempted_message.hex(),
                                      "input_unspent": True,
                                      "recipient_absent": True, "children_count": 0, "active_mempool_empty": True})
            if scenario == "premature-height":
                additions, removals = await sim.farm_block()
                require(not additions and not removals, "Premature spend was included before acceptance height")
                require(sim.block_height == HEIGHT, "Height boundary was skipped")
                require(not (await client.get_coin_record_by_name(contract_coin.name())).spent, "Premature input consumed")
        context = {"mempool_peak_height": int(sim.mempool_manager.peak.height),
                   "record_previous_transaction_block_height": int(sim.block_records[-1].prev_transaction_block_height),
                   "mempool_prevalidation_flags": int(get_flags_for_height_and_constants(sim.mempool_manager.peak.height, constants)) | int(MEMPOOL_MODE)}
        # A premature bundle may have been promoted automatically after farming H.
        promoted = sim.mempool_manager.mempool.get_item_by_id(bundle.name()) is not None
        if promoted:
            require(scenario == "premature-height", "Unexpected existing payment")
            status, error = MempoolInclusionStatus.SUCCESS, None
        else:
            status, error = await client.push_tx(bundle)
        require(status == MempoolInclusionStatus.SUCCESS and error is None, f"Positive control rejected: {status} {error}")
        item = sim.mempool_manager.mempool.get_item_by_id(bundle.name())
        require(item is not None, "Accepted payment missing from mempool")
        simulator_cost = int(item.cost)
        expected_child = Coin(contract_coin.name(), recipient_hash, uint64(AMOUNT))
        require(await client.get_coin_record_by_name(expected_child.name()) is None, "Recipient exists before inclusion")
        additions, removals = await sim.farm_block()
        require(additions == [expected_child] and removals == [contract_coin], "Payment inclusion differs from exact output/removal")
        after = await client.get_coin_record_by_name(contract_coin.name())
        child = await client.get_coin_record_by_name(expected_child.name())
        require(after is not None and after.spent, "Contract coin not marked spent")
        require(child is not None and not child.spent and child.coin == expected_child, "Recipient record missing or invalid")
        children = await client.get_coin_records_by_parent_ids([contract_coin.name()])
        require(len(children) == 1 and children[0].coin == expected_child, "Unexpected additional contract child")
        change = await client.get_coin_record_by_name(change_coin.name())
        require(change is not None and not change.spent, "Funding change was consumed by payment")
        require(not await client.get_all_mempool_tx_ids(), "Mempool not empty after inclusion")
        result = {"scenario": scenario, "rejected_attempts": rejected_attempts, "promoted_after_farming": promoted,
                  "manifest": manifest, "bindings": bindings, "constants": constants.to_json_dict(),
                  "application_message": application_message.hex(), "final_signing_message": final_message.hex(),
                  "signature": bytes(signature).hex(), "conditions_hex": bytes(conditions).hex(),
                  "funding_coin": coin_json(funding_coin), "contract_coin": coin_json(contract_coin),
                  "recipient_coin": coin_json(expected_child), "change_coin": coin_json(change_coin),
                  "context": context, "payment_status": status.name, "payment_error": None,
                  "bundle_id": bundle.name().hex(), "local_cli_vm_cost": local["cost"],
                  "upstream_program_vm_cost": str(upstream_cost), "simulator_total_spend_cost": str(simulator_cost),
                  "input_spent_before": before.spent, "input_spent_after": after.spent,
                  "input_spent_block_index": int(after.spent_block_index),
                  "recipient_confirmed_block_index": int(child.confirmed_block_index),
                  "recipient_unspent": not child.spent, "exactly_one_child": True,
                  "confirmation_peak_height": int(sim.block_height)}
    result["resources_closed"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--suite", action="store_true", help="Run all seven M4-3 height/signature scenarios in fresh simulators")
    args = parser.parse_args()
    profile, lock, versions = preflight()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    require(binary.is_file(), "Build the CLI first or pass --binary")
    with tempfile.TemporaryDirectory(prefix="payment-", dir=WORK) as temp:
        if args.suite:
            outcome = []
            for scenario in SCENARIOS:
                directory = Path(temp) / scenario
                directory.mkdir()
                outcome.append(asyncio.run(payment(binary, directory, profile, scenario)))
                print(f"PASS: {scenario} (confirmed positive control)", flush=True)
        else:
            outcome = asyncio.run(payment(binary, Path(temp), profile))
    report = {"schema_version": 1, "validation": "spendsim-height-signature-checks" if args.suite else "spendsim-confirmed-test-payment",
              "scenario": "height-signature-suite" if args.suite else "authorized-at-height", "profile": profile["profile"],
              "chia_commit": profile["chia_commit"], "python": platform.python_version(), "platform": sys.platform,
              "packages": versions, "source_hashes": profile["source_hashes"],
              "requirements_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
              "lock_hashes": {name: hashlib.sha256((BASE / name).read_bytes()).hexdigest()
                              for name in [lock.name, "build-requirements.lock", "tools.lock", "profile.json"]},
              "outcome": outcome}
    stem = "payment-checks" if args.suite else "payment"
    destination = WORK / (f"{stem}-windows.json" if sys.platform == "win32" else f"{stem}-linux.json")
    destination.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"PASS: funded compiled puzzle, validated test-key signature, confirmed exact payment and spent input. Report: {destination}")


if __name__ == "__main__":
    main()
