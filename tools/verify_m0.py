"""Check M0 reference artifacts, not a 0xBASIC compiler implementation.

Default: offline structure/hash/reference arithmetic checks.
--with-upstream: also use installed clvm/chia_rs as independent references.
--write-vectors --with-upstream: intentionally regenerate the committed vectors.
No network, node, wallet, or package installation is performed.
"""

import argparse
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "spec"
VECTOR_FILE = SPEC / "vectors.json"
GENERATOR = bytes.fromhex("97f1d3a73197d7942695638c4fa9ac0fc3688c4f9774b905a14e3a3f171bac586c55e83ff97a1aeffb3af00adb22c6bb")


def integer_bytes(value):
    if value == 0:
        return b""
    length = max(1, (value.bit_length() + 8) // 8)
    data = value.to_bytes(length, "big", signed=True)
    while len(data) > 1 and ((data[0] == 0 and data[1] < 128) or (data[0] == 255 and data[1] >= 128)):
        data = data[1:]
    return data


def canonical_integer(data):
    return integer_bytes(int.from_bytes(data, "big", signed=True)) == data


def serialize(node):
    """Small reference encoder, intentionally independent of production tooling."""
    if isinstance(node, tuple):
        return b"\xff" + serialize(node[0]) + serialize(node[1])
    if len(node) == 1 and node[0] < 128:
        return node
    length = len(node)
    if length < 64:
        return bytes([0x80 | length]) + node
    if length < 8192:
        return bytes([0xC0 | (length >> 8), length & 255]) + node
    raise ValueError("Reference fixtures intentionally limited to small atoms")


def tree_hash(node):
    preimage = b"\x02" + tree_hash(node[0]) + tree_hash(node[1]) if isinstance(node, tuple) else b"\x01" + node
    return hashlib.sha256(preimage).digest()


def clist(*values):
    result = b""
    for value in reversed(values):
        result = (value, result)
    return result


def binding_fixture():
    # Identity template returns the environment, making the ABI shape observable.
    template = b"\x01"
    fixed = clist(integer_bytes(42))
    solution = clist(bytes.fromhex("dead"))
    bound = clist(b"\x02", (b"\x01", template), clist(b"\x04", (b"\x01", fixed), b"\x01"))
    return template, fixed, solution, bound, (fixed, solution)


def payment_fixture():
    amount, height = 1000, 10
    recipient = bytes.fromhex("11" * 32)
    parent, puzzle_hash = bytes.fromhex("22" * 32), bytes.fromhex("33" * 32)
    domain = bytes.fromhex("aa" * 32)
    preimage = b"0xBASIC/payment/v1\x00" + GENERATOR + recipient + amount.to_bytes(8, "big") + height.to_bytes(4, "big")
    message = hashlib.sha256(preimage).digest()
    coin_id = hashlib.sha256(parent + puzzle_hash + integer_bytes(amount)).digest()
    final_message = message + coin_id + domain
    conditions = clist(clist(b"\x49", integer_bytes(amount)), clist(b"\x53", integer_bytes(height)), clist(b"\x32", GENERATOR, message), clist(b"\x33", recipient, integer_bytes(amount)))
    return {
        "test_secret_scalar": "1",
        "owner_hex": GENERATOR.hex(), "recipient_hex": recipient.hex(),
        "amount": str(amount), "earliest_height": str(height),
        "parent_coin_id_hex": parent.hex(), "synthetic_puzzle_hash_hex": puzzle_hash.hex(),
        "agg_sig_me_additional_data_hex": domain.hex(),
        "preimage_hex": preimage.hex(), "preimage_length": len(preimage),
        "application_message_hex": message.hex(), "coin_id_hex": coin_id.hex(),
        "final_signing_message_hex": final_message.hex(),
        "conditions_serialized_hex": serialize(conditions).hex(),
    }


def generate_vectors():
    from chia_rs import AugSchemeMPL, PrivateKey
    template, fixed, solution, bound, expected = binding_fixture()
    payment = payment_fixture()
    secret = PrivateKey.from_bytes((1).to_bytes(32, "big"))
    assert bytes(secret.get_g1()) == GENERATOR
    payment["augmented_signature_hex"] = bytes(AugSchemeMPL.sign(secret, bytes.fromhex(payment["final_signing_message_hex"]))).hex()
    values = [0, 1, -1, 127, 128, 255, 256, -128, -129, 2**63, 2**64-1, 2**80]
    return {
        "schema_version": 1,
        "provenance": {"generator": "tools/verify_m0.py", "signature_reference": "chia_rs " + importlib.metadata.version("chia_rs"), "warning": "Public test key only; synthetic puzzle hash is not compiled output."},
        "integers": [{"decimal": str(value), "atom_hex": integer_bytes(value).hex(), "serialized_hex": serialize(integer_bytes(value)).hex()} for value in values],
        "noncanonical_integer_atoms": ["00", "0000", "0001", "007f", "ffff", "ff80"],
        "valid_boolean_atoms": ["", "01"],
        "invalid_boolean_atoms": ["00", "02", "ff", "0001"],
        "valid_utf8_atoms": ["", "00", "61", "c2a2", "e282ac", "f09f9880", "f48fbfbf"],
        "invalid_utf8_atoms": ["80", "c080", "c2", "eda080", "f4908080", "ff"],
        "invalid_public_key_atoms": ["00" * 48, "c0" + "00" * 47, "ff" * 48, "01" * 47],
        "serialization": [{"name": name, "serialized_hex": serialize(node).hex(), "tree_hash": tree_hash(node).hex()} for name, node in [("nil", b""), ("one", b"\x01"), ("zero-byte", b"\x00"), ("pair", (b"\x01", b""))]],
        "binding": {"template_hex": serialize(template).hex(), "fixed_values_hex": serialize(fixed).hex(), "solution_hex": serialize(solution).hex(), "bound_program_hex": serialize(bound).hex(), "result_hex": serialize(expected).hex(), "bound_tree_hash": tree_hash(bound).hex()},
        "payment": payment,
        "boundary_cases": [
            {"name": "empty-solution", "schema": [], "serialized_solution_hex": "80", "valid": True},
            {"name": "extra-solution-field", "schema": [], "serialized_solution_hex": "ff0180", "valid": False},
            {"name": "missing-field", "schema": ["INTEGER"], "serialized_solution_hex": "80", "valid": False},
            {"name": "integer-zero", "schema": ["INTEGER"], "serialized_solution_hex": "ff8080", "valid": True},
            {"name": "noncanonical-zero", "schema": ["INTEGER"], "serialized_solution_hex": "ff0080", "valid": False},
            {"name": "improper-solution", "schema": ["INTEGER"], "serialized_solution_hex": "ff0102", "valid": False},
            {"name": "negative-amount", "schema": ["AMOUNT"], "serialized_solution_hex": "ff81ff80", "valid": False},
            {"name": "oversized-amount", "schema": ["AMOUNT"], "serialized_solution_hex": serialize(clist(integer_bytes(2**64))).hex(), "valid": False},
            {"name": "short-hash", "schema": ["PUZZLEHASH"], "serialized_solution_hex": serialize(clist(b"a" * 31)).hex(), "valid": False},
            {"name": "leading-zero-bytes", "schema": ["BYTES"], "serialized_solution_hex": "ff82000180", "valid": True},
        ],
    }


def check_vectors(vectors):
    for case in vectors["integers"]:
        data = bytes.fromhex(case["atom_hex"])
        assert integer_bytes(int(case["decimal"])) == data
        assert serialize(data).hex() == case["serialized_hex"]
    assert all(not canonical_integer(bytes.fromhex(item)) for item in vectors["noncanonical_integer_atoms"])
    assert vectors["valid_boolean_atoms"] == ["", "01"]
    assert all(item not in ("", "01") for item in vectors["invalid_boolean_atoms"])
    for key, valid in [("valid_utf8_atoms", True), ("invalid_utf8_atoms", False)]:
        for item in vectors[key]:
            try:
                bytes.fromhex(item).decode("utf-8", errors="strict")
                actual = True
            except UnicodeDecodeError:
                actual = False
            assert actual == valid
    for key, value in payment_fixture().items():
        assert vectors["payment"][key] == value, key
    assert vectors["payment"]["preimage_length"] == 111
    template, fixed, solution, bound, result = binding_fixture()
    for key, node in [("template_hex", template), ("fixed_values_hex", fixed), ("solution_hex", solution), ("bound_program_hex", bound), ("result_hex", result)]:
        assert serialize(node).hex() == vectors["binding"][key]
    assert tree_hash(bound).hex() == vectors["binding"]["bound_tree_hash"]
    for case, node in zip(vectors["serialization"], [b"", b"\x01", b"\x00", (b"\x01", b"")], strict=True):
        assert serialize(node).hex() == case["serialized_hex"]
        assert tree_hash(node).hex() == case["tree_hash"]


def check_upstream(vectors):
    from chia_rs import AugSchemeMPL, Coin, G1Element, G2Element, PrivateKey, run_chia_program
    from clvm import SExp
    from clvm.casts import int_to_bytes
    from clvm.serialize import sexp_from_stream
    print("Upstream reference versions:", {name: importlib.metadata.version(name) for name in ("chia_rs", "clvm")})
    for case in vectors["integers"]:
        assert int_to_bytes(int(case["decimal"])).hex() == case["atom_hex"]
    template, fixed, solution, bound, expected = binding_fixture()
    assert SExp.to(bound).as_bin() == serialize(bound)
    _, node = run_chia_program(serialize(bound), serialize(solution), 1000000, 0x257)
    def convert(lazy):
        return bytes(lazy.atom) if lazy.atom is not None else (convert(lazy.pair[0]), convert(lazy.pair[1]))
    assert convert(node) == expected
    for case in vectors["boundary_cases"]:
        stream = io.BytesIO(bytes.fromhex(case["serialized_solution_hex"]))
        value = sexp_from_stream(stream, SExp.to)
        valid = stream.read() == b""
        try:
            for typename in case["schema"]:
                atom = value.first().as_atom()
                value = value.rest()
                if typename == "INTEGER":
                    valid &= canonical_integer(atom)
                elif typename == "AMOUNT":
                    valid &= canonical_integer(atom) and 0 <= int.from_bytes(atom, "big", signed=True) < 2**64
                elif typename == "PUZZLEHASH":
                    valid &= len(atom) == 32
                elif typename != "BYTES":
                    raise ValueError("Unexpected fixture type")
            valid &= value.nullp()
        except Exception:
            valid = False
        assert bool(valid) == case["valid"], case["name"]
    payment = vectors["payment"]
    coin = Coin(bytes.fromhex(payment["parent_coin_id_hex"]), bytes.fromhex(payment["synthetic_puzzle_hash_hex"]), int(payment["amount"]))
    assert bytes(coin.name()).hex() == payment["coin_id_hex"]
    secret = PrivateKey.from_bytes((1).to_bytes(32, "big"))
    key = secret.get_g1()
    message = bytes.fromhex(payment["final_signing_message_hex"])
    signature = G2Element.from_bytes(bytes.fromhex(payment["augmented_signature_hex"]))
    assert bytes(AugSchemeMPL.sign(secret, message)) == bytes(signature)
    assert AugSchemeMPL.verify(key, message, signature)
    for index in (0, 32, 64):
        altered = bytearray(message)
        altered[index] ^= 1
        assert not AugSchemeMPL.verify(key, bytes(altered), signature)
    assert not AugSchemeMPL.verify(PrivateKey.from_bytes((2).to_bytes(32, "big")).get_g1(), message, signature)
    for item in vectors["invalid_public_key_atoms"]:
        try:
            decoded = G1Element.from_bytes(bytes.fromhex(item))
            valid = decoded != G1Element()
        except ValueError:
            valid = False
        assert not valid
    print("Reference checks passed: integer encoding, binding execution, malformed ABI cases, coin identity, BLS signature and negative cases.")


def check_documents():
    grammar = (SPEC / "grammar.ebnf").read_text(encoding="utf-8")
    grammar = re.sub(r"\(\*.*?\*\)", "", grammar, flags=re.S)
    grammar = re.sub(r'"[^"]*"', "", grammar)
    definitions = re.findall(r"(?m)^([a-z_]+)\s*=", grammar)
    assert len(definitions) == len(set(definitions))
    references = set(re.findall(r"\b[a-z_]+\b", grammar))
    assert references <= set(definitions), references - set(definitions)
    cases = json.loads((SPEC / "source-cases.json").read_text(encoding="utf-8"))["cases"]
    assert len({case["id"] for case in cases}) == len(cases)
    diagnostics = (SPEC / "cli-v1.md").read_text(encoding="utf-8")
    for case in cases:
        assert ("source" in case) != ("source_file" in case)
        if "source_file" in case:
            assert (SPEC / case["source_file"]).is_file()
        if not case["accept"]:
            assert case["diagnostic"] in diagnostics
    schema = json.loads((SPEC / "manifest.schema.json").read_text(encoding="utf-8"))
    assert schema["required"] == list(schema["properties"])
    for match in re.findall(r'"\$ref":\s*"#/(.*?)"', json.dumps(schema)):
        node = schema
        for component in match.split("/"):
            node = node[component]
    paths = [ROOT / "README.md"] + [p for p in (ROOT / "docs").rglob("*.md") if "archive" not in p.parts]
    for path in paths:
        content = path.read_text(encoding="utf-8")
        for link in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if link.startswith(("http://", "https://", "#")):
                continue
            assert (path.parent / link.split("#")[0]).exists(), f"Broken link in {path}: {link}"
    print(f"Specification structure passed: {len(definitions)} grammar rules, {len(cases)} source fixtures, local links, schema references.")
    print("M0 source fixtures were not parsed/type-checked by this specification verifier; M1 tests cover the implemented subset separately.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-upstream", action="store_true")
    parser.add_argument("--write-vectors", action="store_true")
    args = parser.parse_args()
    if args.write_vectors:
        if not args.with_upstream:
            parser.error("--write-vectors requires --with-upstream")
        VECTOR_FILE.write_text(json.dumps(generate_vectors(), indent=2) + "\n", encoding="utf-8")
    vectors = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    check_vectors(vectors)
    if args.with_upstream:
        check_upstream(vectors)
    check_documents()
    print("M0 artifact checks passed.")


if __name__ == "__main__":
    main()
