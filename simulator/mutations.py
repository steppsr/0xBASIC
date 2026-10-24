"""M4-4: replay and payment mutation scenarios using isolated test coins only."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from payment import AMOUNT, HEIGHT, MAX_COST, invoke, coin_json, condition_tree_json
from smoke import BASE, ROOT, WORK, preflight, require, simulator_constants

SCENARIOS = ("cross-coin-replay", "double-spend", "wrong-puzzle-reveal", "wrong-coin-amount",
             "changed-recipient-stale-signature", "changed-recipient-resigned", "malformed-solution", "zero-payment-amount")


def compiled(binary, directory, owner, recipient, amount=AMOUNT):
    from chia.types.blockchain_format.program import Program
    directory.mkdir()
    bindings = {"owner":{"hex":bytes(owner).hex()}, "recipient":{"hex":recipient.hex()},
                "paymentAmount":str(amount), "earliestHeight":str(HEIGHT)}
    path = directory / "bindings.json"
    path.write_text(json.dumps(bindings),encoding="utf-8")
    out = directory / "artifact"
    invoke(binary,"build",ROOT / "examples/height-locked-payment.bas","--bindings",path,"--out",out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    for name in ["template","puzzle"]:
        raw = (out / f"{name}.clvm").read_bytes()
        require(hashlib.sha256(raw).hexdigest()==manifest[name]["program_sha256"],"Byte digest mismatch")
        require(Program.from_bytes(raw).get_tree_hash().hex()==manifest[name]["tree_hash"],"Tree hash mismatch")
    puzzle = Program.from_bytes((out / "puzzle.clvm").read_bytes())
    message = hashlib.sha256(b"0xBASIC/payment/v1\x00"+bytes(owner)+bytes(recipient)+amount.to_bytes(8,"big")+HEIGHT.to_bytes(4,"big")).digest()
    # Zero intentionally fails its contract ASSERT; evaluate through real spend validation below.
    vm_cost = None
    if amount:
        vm_cost, conditions = puzzle.run_with_cost(MAX_COST,Program.to([]))
        expected = Program.to([[73,amount],[83,HEIGHT],[50,bytes(owner),message],[51,recipient,amount]])
        require(bytes(conditions)==bytes(expected),"Independent condition mismatch")
        require(invoke(binary,"run",out / "manifest.json")["tree"]==condition_tree_json(expected),"CLI condition mismatch")
    return {"puzzle":puzzle,"recipient":recipient,"amount":amount,"message":message,
            "manifest":manifest,"bindings":bindings,"vm_cost":vm_cost}


async def scenario(binary, directory, profile, name):
    from chia._tests.util.spend_sim import SpendSim, SimClient
    from chia.types.blockchain_format.program import Program
    from chia.types.coin_spend import make_spend
    from chia.types.mempool_inclusion_status import MempoolInclusionStatus
    from chia.consensus.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
    from chia.util.errors import Err
    from chia_rs import AugSchemeMPL, Coin, G2Element, SpendBundle, MEMPOOL_MODE, DONT_VALIDATE_SIGNATURE, get_flags_for_height_and_constants
    from chia_rs.sized_ints import uint64
    constants = simulator_constants(profile)
    key = AugSchemeMPL.key_gen(hashlib.sha256(b"0xBASIC/M4/public-test-key/v1").digest())
    owner = key.get_g1()
    funding = Program.to(1)
    recipient = Program.to((1,[])).get_tree_hash()
    alternate = Program.to((1,[[83,0]])).get_tree_hash()
    require(recipient!=alternate,"Recipient variant is unchanged")
    original = compiled(binary,directory / "original",owner,recipient)
    fixtures = {"original":original}
    if name in {"wrong-puzzle-reveal","changed-recipient-stale-signature","changed-recipient-resigned","zero-payment-amount"}:
        fixtures["variant"] = compiled(binary,directory / "variant",owner,
                                       recipient if name=="zero-payment-amount" else alternate,
                                       0 if name=="zero-payment-amount" else AMOUNT)
    records = {"scenario":name,"funding":[],"rejections":[],"confirmations":[]}
    async with SpendSim.managed(defaults=constants) as sim:
        client = SimClient(sim)
        await sim.farm_block(funding.get_tree_hash())
        await sim.farm_block(funding.get_tree_hash())

        async def fund(fixture, amount=AMOUNT):
            available = await client.get_coin_records_by_puzzle_hash(funding.get_tree_hash(),include_spent_coins=False)
            parent = min((r.coin for r in available if r.coin.amount>amount),key=lambda c:(c.amount,c.name()))
            coin = Coin(parent.name(),fixture["puzzle"].get_tree_hash(),uint64(amount))
            change = Coin(parent.name(),funding.get_tree_hash(),uint64(parent.amount-amount))
            bundle = SpendBundle([make_spend(parent,funding,Program.to([[51,coin.puzzle_hash,amount],[51,change.puzzle_hash,change.amount]]))],G2Element())
            status,error = await client.push_tx(bundle)
            require(status==MempoolInclusionStatus.SUCCESS and error is None,f"Funding failed: {status} {error}")
            additions,removals = await sim.farm_block()
            require({c.name() for c in additions}=={coin.name(),change.name()} and removals==[parent],"Funding inclusion mismatch")
            require((await client.get_coin_record_by_name(parent.name())).spent,"Funding input remains unspent")
            entry = await client.get_coin_record_by_name(coin.name())
            require(entry is not None and entry.coin==coin and not entry.spent,"Funded coin absent")
            records["funding"].append({"parent":coin_json(parent),"coin":coin_json(coin),"change":coin_json(change)})
            return coin

        def signed(coin, fixture, solution=None, reveal=None, signature=None):
            message = fixture["message"]+bytes(coin.name())+bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA)
            if fixture["amount"]:
                pairs = pkm_pairs_for_conditions_dict(conditions_dict_for_solution(fixture["puzzle"],Program.to([]),MAX_COST),coin,constants.AGG_SIG_ME_ADDITIONAL_DATA)
                require(pairs==[(owner,message)],"Independent signature message mismatch")
            actual_signature = AugSchemeMPL.sign(key,message) if signature is None else signature
            return SpendBundle([make_spend(coin,fixture["puzzle"] if reveal is None else reveal,Program.to([]) if solution is None else solution)],actual_signature)

        async def reject(bundle, coin, expected, spent=False):
            before = await client.get_coin_record_by_name(coin.name())
            children_before = await client.get_coin_records_by_parent_ids([coin.name()])
            require(before is not None and before.spent==spent,"Wrong rejection precondition")
            status,error = await client.push_tx(bundle)
            require(status!=MempoolInclusionStatus.SUCCESS and error==expected,f"{name}: expected {expected}, got {status} {error}")
            require(await client.get_coin_record_by_name(coin.name())==before,"Rejected spend changed coin")
            require(await client.get_coin_records_by_parent_ids([coin.name()])==children_before,"Rejected spend changed children")
            require(not await client.get_all_mempool_tx_ids(),"Rejected spend entered active mempool")
            additions,removals = await sim.farm_block()
            require(not additions and not removals,"Rejected spend was included on next block")
            require(await client.get_coin_record_by_name(coin.name())==before,"Rejected spend changed coin after farm")
            require(await client.get_coin_records_by_parent_ids([coin.name()])==children_before,"Rejected spend created output after farm")
            records["rejections"].append({"error":error.name,"status":status.name,"bundle_id":bundle.name().hex(),
                "coin":coin_json(coin),"spent_before_and_after":spent,"children_before_and_after":len(children_before),
                "state_unchanged_after_farm":True,"submission_peak_height":int(sim.block_height)-1,
                "puzzle_reveal_hex":bytes(bundle.coin_spends[0].puzzle_reveal).hex(),
                "solution_hex":bytes(bundle.coin_spends[0].solution).hex(),"signature":bytes(bundle.aggregated_signature).hex()})

        async def confirm(coin, fixture):
            bundle = signed(coin,fixture)
            before = await client.get_coin_record_by_name(coin.name())
            require(before is not None and not before.spent,"Positive input is spent")
            status,error = await client.push_tx(bundle)
            require(status==MempoolInclusionStatus.SUCCESS and error is None,f"Positive control failed: {status} {error}")
            item = sim.mempool_manager.mempool.get_item_by_id(bundle.name())
            require(item is not None,"Missing positive mempool item")
            cost = int(item.cost)
            expected = Coin(coin.name(),fixture["recipient"],uint64(fixture["amount"]))
            additions,removals = await sim.farm_block()
            require(additions==[expected] and removals==[coin],"Positive inclusion mismatch")
            child = await client.get_coin_record_by_name(expected.name())
            require((await client.get_coin_record_by_name(coin.name())).spent and child is not None and not child.spent,"Positive records invalid")
            children = await client.get_coin_records_by_parent_ids([coin.name()])
            require(len(children)==1 and children[0].coin==expected,"Unexpected positive children")
            require(not await client.get_all_mempool_tx_ids(),"Mempool not empty after positive inclusion")
            records["confirmations"].append({"coin":coin_json(coin),"recipient":coin_json(expected),"bundle_id":bundle.name().hex(),
                "input_spent":True,"recipient_unspent":True,"exactly_one_child":True,
                "simulator_total_spend_cost":str(cost),"confirmed_peak_height":int(sim.block_height)})
            return bundle

        first = await fund(original)
        target,fixture = first,original
        if name=="cross-coin-replay":
            target = await fund(original)
            require(first.parent_coin_info!=target.parent_coin_info and first.name()!=target.name(),"Replay needs distinct parents")
            require(first.puzzle_hash==target.puzzle_hash and first.amount==target.amount,"Replay fixture differs in puzzle/amount")
        elif name=="wrong-coin-amount":
            target = await fund(original,AMOUNT+1)
        elif name in {"changed-recipient-stale-signature","changed-recipient-resigned","zero-payment-amount"}:
            fixture = fixtures["variant"]
            target = await fund(fixture)
        while sim.block_height<HEIGHT:
            await sim.farm_block()
        flags = int(get_flags_for_height_and_constants(sim.block_height,constants)) | int(MEMPOOL_MODE)
        require(not flags & int(DONT_VALIDATE_SIGNATURE),"Signature validation bypass")
        records["validation_flags"] = flags
        records["submission_peak_height"] = int(sim.block_height)
        original_bundle = signed(first,original)
        if name in {"cross-coin-replay","changed-recipient-stale-signature"}:
            require(not (await client.get_coin_record_by_name(first.name())).spent,"Signature source coin already spent")
            await reject(signed(target,fixture,signature=original_bundle.aggregated_signature),target,Err.BAD_AGGREGATE_SIGNATURE)
            await confirm(target,fixture)
            require(not (await client.get_coin_record_by_name(first.name())).spent,"Replay consumed signature-source coin")
            records["signature_source_coin"] = coin_json(first)
            records["signature_source_unspent"] = True
            records["signature_source_message"] = (original["message"]+bytes(first.name())+bytes(constants.AGG_SIG_ME_ADDITIONAL_DATA)).hex()
        elif name=="double-spend":
            accepted = await confirm(first,original)
            await reject(accepted,first,Err.DOUBLE_SPEND,spent=True)
        elif name=="wrong-puzzle-reveal":
            await reject(signed(first,original,reveal=fixtures["variant"]["puzzle"]),first,Err.WRONG_PUZZLE_HASH)
            await confirm(first,original)
        elif name=="wrong-coin-amount":
            await reject(signed(target,original),target,Err.ASSERT_MY_AMOUNT_FAILED)
            await confirm(first,original)
        elif name=="malformed-solution":
            await reject(signed(first,original,solution=Program.to([1])),first,Err.GENERATOR_RUNTIME_ERROR)
            await confirm(first,original)
        elif name=="zero-payment-amount":
            await reject(signed(target,fixture),target,Err.GENERATOR_RUNTIME_ERROR)
            await confirm(first,original)
        elif name=="changed-recipient-resigned":
            await confirm(target,fixture)
        if name in {"wrong-coin-amount","zero-payment-amount"}:
            require(not (await client.get_coin_record_by_name(target.name())).spent,"Positive control consumed rejected coin")
            require(not await client.get_coin_records_by_parent_ids([target.name()]),"Rejected coin gained children")
            records["rejected_coin_remains_unspent_after_control"] = True
        if name=="changed-recipient-resigned":
            require(not (await client.get_coin_record_by_name(first.name())).spent,"Recipient variant consumed original coin")
            require(not await client.get_coin_records_by_parent_ids([first.name()]),"Original coin gained unintended output")
            records["original_coin_remains_unspent"] = True
        records["application_messages"] = {label:f["message"].hex() for label,f in fixtures.items()}
        records["fixtures"] = {label:{k:v for k,v in f.items() if k in {"manifest","bindings","vm_cost"}} for label,f in fixtures.items()}
        records["constants"] = constants.to_json_dict()
    records["resources_closed"] = True
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary",type=Path)
    args = parser.parse_args()
    profile,lock,versions = preflight()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name=="nt" else "0xbasic")).resolve()
    require(binary.is_file(),"Build CLI or supply --binary")
    with tempfile.TemporaryDirectory(prefix="mutations-",dir=WORK) as temp:
        outcomes = []
        for name in SCENARIOS:
            directory = Path(temp) / name
            directory.mkdir()
            outcomes.append(asyncio.run(scenario(binary,directory,profile,name)))
            print(f"PASS: {name}",flush=True)
    report = {"schema_version":1,"validation":"spendsim-replay-mutation-checks","profile":profile["profile"],
              "chia_commit":profile["chia_commit"],"python":platform.python_version(),"platform":sys.platform,
              "packages":versions,"source_hashes":profile["source_hashes"],
              "lock_hashes":{n:hashlib.sha256((BASE / n).read_bytes()).hexdigest() for n in [lock.name,"build-requirements.lock","tools.lock","profile.json"]},
              "outcome":outcomes}
    destination = WORK / ("mutations-windows.json" if sys.platform=="win32" else "mutations-linux.json")
    destination.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"PASS: eight replay/mutation scenarios. Report: {destination}")


if __name__=="__main__":
    main()
