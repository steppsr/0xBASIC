"""Verify pure function execution and eager/lazy boundaries; optional Python CLVM oracle."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile

from verify_m2b import invoke
from verify_m2_branches import expected_tree, upstream

ROOT = Path(__file__).resolve().parents[1]


def module(body, functions):
    return f"CONTRACT FunctionFixture()\n{body}END CONTRACT\n{functions}"


def cases():
    for flag, truth in [("TRUE", 1), ("FALSE", 0)]:
        functions = "FUNCTION Branch(b AS BOOLEAN) AS INTEGER\nIF b THEN\nRETURN 0\nEND IF\nRETURN 4\nEND FUNCTION\n"
        reference = f"(a (i (q . {truth}) (q . (q . ((83 0)))) (q . (q . ((83 4))))) 1)"
        yield module(f"EMIT ASSERT_HEIGHT_ABSOLUTE(Branch({flag}))\n", functions), reference, [0 if truth else 4]
        functions = "FUNCTION Branch(b AS BOOLEAN) AS CONDITION\nIF b THEN\nIF TRUE THEN\nRETURN ASSERT_HEIGHT_ABSOLUTE(7)\nEND IF\nELSE\nRETURN ASSERT_HEIGHT_ABSOLUTE(0)\nEND IF\nASSERT FALSE\nEND FUNCTION\n"
        reference = f"(a (i (q . {truth}) (q . (q . ((83 7)))) (q . (q . ((83 0))))) 1)"
        yield module(f"EMIT Branch({flag})\n", functions), reference, [7 if truth else 0]
        functions = "FUNCTION Branch(b AS BOOLEAN) AS BOOLEAN\nIF b THEN\nRETURN FALSE\nELSE\nRETURN TRUE\nEND IF\nASSERT FALSE\nEND FUNCTION\n"
        yield module(f"ASSERT Branch({flag}) = (NOT {flag})\n", functions), "(q . ())", []
        functions = "FUNCTION Branch(b AS BOOLEAN) AS INTEGER\nIF b THEN\nRETURN 1\nEND IF\nASSERT FALSE\nRETURN 2\nEND FUNCTION\n"
        reference = f"(a (i (q . {truth}) (q . (q . ((83 1)))) (q . (x))) 1)"
        yield module(f"EMIT ASSERT_HEIGHT_ABSOLUTE(Branch({flag}))\n", functions), reference, [1] if truth else None
    yield module("DIM n = Fail()\n", "FUNCTION Fail() AS INTEGER\nASSERT FALSE\nEND FUNCTION\n"), "(x)", None
    for body, functions, reference, expected in [
        ("EMIT ASSERT_HEIGHT_ABSOLUTE(Early())\n", "FUNCTION Early() AS INTEGER\nRETURN 17\nASSERT FALSE\nRETURN 99\nEND FUNCTION\n", "(q . ((83 17)))", [17]),
        ("ASSERT Early()\n", "FUNCTION Early() AS BOOLEAN\nRETURN TRUE\nASSERT FALSE\nEND FUNCTION\n", "(q . ())", []),
        ("EMIT Early()\n", "FUNCTION Early() AS CONDITION\nRETURN ASSERT_HEIGHT_ABSOLUTE(100)\nRETURN ASSERT_HEIGHT_ABSOLUTE(-1)\nEND FUNCTION\n", "(q . ((83 100)))", [100]),
        ("EMIT Early()\n", "FUNCTION Early() AS CONDITION\nASSERT FALSE\nRETURN ASSERT_HEIGHT_ABSOLUTE(100)\nASSERT TRUE\nEND FUNCTION\n", "(x)", None),
    ]:
        yield module(body, functions), reference, expected
    functions = "FUNCTION Difference(a AS INTEGER, b AS INTEGER) AS INTEGER\nRETURN a - b\nEND FUNCTION\n"
    # Independent reference applies an explicitly ordered argument list and
    # constructs the condition from the result; it is not compiler output.
    yield module("EMIT ASSERT_HEIGHT_ABSOLUTE(Difference(200, 50))\n", functions), "(c (c (q . 83) (c (a (q . (- 2 5)) (q . (200 50))) (q . ()))) (q . ()))", [150]
    functions = "FUNCTION Twice(n AS INTEGER) AS INTEGER\nRETURN n + n\nEND FUNCTION\nFUNCTION Outer(n AS INTEGER) AS INTEGER\nRETURN Twice(n) + 1\nEND FUNCTION\n"
    yield module("EMIT ASSERT_HEIGHT_ABSOLUTE(Outer(7))\n", functions), "(c (c (q . 83) (c (+ (a (q . (+ 2 2)) (q . (7))) (q . 1)) (q . ()))) (q . ()))", [15]
    functions = "FUNCTION Height(n AS INTEGER) AS CONDITION\nRETURN ASSERT_HEIGHT_ABSOLUTE(n)\nEND FUNCTION\nFUNCTION Echo(c AS CONDITION) AS CONDITION\nRETURN c\nEND FUNCTION\n"
    yield module("EMIT Echo(Height(7))\n", functions), "(c (a (q . 2) (q . ((83 7)))) (q . ()))", [7]
    functions = "FUNCTION Fail() AS BOOLEAN\nASSERT FALSE\nRETURN TRUE\nEND FUNCTION\n"
    for body, expected in [("ASSERT TRUE OR Fail()\n", []), ("ASSERT NOT (FALSE AND Fail())\n", []), ("ASSERT TRUE AND Fail()\n", None), ("DIM unused = Fail()\n", None)]:
        yield module(body, functions), "(q . ())" if expected == [] else "(x)", expected
    functions = "FUNCTION Ignore(c AS CONDITION) AS INTEGER\nRETURN 1\nEND FUNCTION\n"
    yield module("DIM unused = Ignore(ASSERT_HEIGHT_ABSOLUTE(-1))\n", functions), "(x)", None
    for flag, expected in [("TRUE", [10]), ("FALSE", [20])]:
        functions = "FUNCTION SelectHeight(flag AS BOOLEAN) AS INTEGER\nDIM n = 20\nIF flag THEN\nn = 10\nEND IF\nRETURN n\nEND FUNCTION\n"
        reference = f"(a (i (q . {1 if flag == 'TRUE' else 0}) (q . (q . ((83 10)))) (q . (q . ((83 20))))) 1)"
        yield module(f"EMIT ASSERT_HEIGHT_ABSOLUTE(SelectHeight({flag}))\n", functions), reference, expected


def byte_cases():
    functions = "FUNCTION Identity(value AS BYTES, flag AS BOOLEAN) AS BYTES\nIF flag THEN\nRETURN value\nEND IF\nRETURN 0x\nEND FUNCTION\n"
    for left, right in [("", ""), ("", "00"), ("00", "00"), ("0001", "01"), ("00ff", "00FF"), ("ff", "80")]:
        for operator in ["=", "<>"]:
            equal = bytes.fromhex(left) == bytes.fromhex(right)
            expected = [] if equal == (operator == "=") else None
            lhs, rhs = ("0x" + left if left else "()"), ("0x" + right if right else "()")
            predicate = f"(= (q . {lhs}) (q . {rhs}))"
            if operator == "<>":
                predicate = f"(not {predicate})"
            reference = f"(a (i {predicate} (q . (q . ())) (q . (x))) 1)"
            yield module(f"DIM value AS BYTES = Identity(0x{left}, TRUE)\nASSERT value {operator} 0x{right}\n", functions), reference, expected
    yield (ROOT / "examples/m2-bytes.bas").read_text(encoding="utf-8"), "(q . ((83 100)))", [100]


def byte_constant_cases():
    for left, right in [("", ""), ("", "00"), ("00", "00"), ("0001", "01"), ("00ff", "00FF"), ("ff", "80")]:
        for operator in ["=", "<>"]:
            expected = [] if (bytes.fromhex(left) == bytes.fromhex(right)) == (operator == "=") else None
            lhs, rhs = ("0x" + left if left else "()"), ("0x" + right if right else "()")
            predicate = f"(= (q . {lhs}) (q . {rhs}))"
            if operator == "<>":
                predicate = f"(not {predicate})"
            reference = f"(a (i {predicate} (q . (q . ())) (q . (x))) 1)"
            body = f"CONST original AS BYTES = 0x{left}\nCONST alias = original\nCONST answer AS BOOLEAN = alias {operator} 0x{right}\nASSERT answer\n"
            yield module(body, ""), reference, expected
    yield (ROOT / "examples/m2-byte-constants.bas").read_text(encoding="utf-8"), "(q . ((83 100)))", [100]
    functions = "FUNCTION F() AS BYTES\nCONST tag = 0x0001\nIF tag = 0x0001 THEN\nRETURN tag\nEND IF\nEND FUNCTION\n"
    yield module("ASSERT F() = 0x0001\n", functions), "(q . ())", []
    functions = "FUNCTION F() AS BYTES\nCONST tag = 0x00\nASSERT tag = 0x\nEND FUNCTION\n"
    yield module("DIM value = F()\n", functions), "(x)", None


def byte_operation_cases():
    for left, right in [("", ""), ("", "00"), ("00", ""), ("0001", "80ff"), ("ff", "00"), (bytes(range(256)).hex(), "00")]:
        lhs, rhs = ("0x" + left if left else "()"), ("0x" + right if right else "()")
        expression = f"(concat (q . {lhs}) (q . {rhs}))"
        reference = f"(c (c (q . 83) (c (strlen {expression}) (q . ()))) (q . ()))"
        body = f"DIM b = CONCAT(0x{left}, 0x{right})\nASSERT b = 0x{left}{right}\nEMIT ASSERT_HEIGHT_ABSOLUTE(BYTE_LENGTH(b))\n"
        yield module(body, ""), reference, [len(bytes.fromhex(left + right))]
    yield (ROOT / "examples/m2-byte-operations.bas").read_text(encoding="utf-8"), "(q . ((83 4)))", [4]
    functions = "FUNCTION Fail() AS BYTES\nASSERT FALSE\nRETURN 0x\nEND FUNCTION\n"
    for body, expected in [("DIM n = BYTE_LENGTH(Fail())\n", None), ("DIM b = CONCAT(0x,Fail())\n", None), ("ASSERT TRUE OR (BYTE_LENGTH(Fail()) = 0)\n", [])]:
        yield module(body, functions), "(x)" if expected is None else "(q . ())", expected


def hash_cases():
    for data in [b"", b"abc", b"\x00", b"\x00\x00\x01", b"\x01", bytes(range(256)), b"a" * 55, b"a" * 56, b"a" * 64, b"\xff" * 8192]:
        digest = hashlib.sha256(data).hexdigest()
        atom = "0x" + data.hex() if data else "()"
        predicate = f"(= (sha256 (q . {atom})) (q . 0x{digest}))"
        reference = f"(a (i {predicate} (q . (q . ((83 32)))) (q . (x))) 1)"
        body = f"DIM h = SHA256(0x{data.hex()})\nASSERT h = 0x{digest}\nEMIT ASSERT_HEIGHT_ABSOLUTE(BYTE_LENGTH(h))\n"
        yield module(body, ""), reference, [32]
    yield (ROOT / "examples/m2-sha256.bas").read_text(encoding="utf-8"), "(q . ((83 32)))", [32]
    functions = "FUNCTION Fail() AS BYTES\nASSERT FALSE\nRETURN 0x\nEND FUNCTION\n"
    for body, expected in [("DIM h = SHA256(Fail())\n", None), ("ASSERT TRUE OR (SHA256(Fail()) = 0x)\n", []), ("IF FALSE THEN\nDIM h = SHA256(Fail())\nEND IF\n", [])]:
        yield module(body, functions), "(x)" if expected is None else "(q . ())", expected


def integer_byte_cases():
    # Independent Python signed encoding; never obtain expected atoms from compiler output.
    for n in [0, 1, -1, 127, 128, 255, 256, -128, -129, -256, 32768, -32769, 2**128, -(2**128), 2**1024]:
        if n == 0:
            data = b""
        else:
            width = 1
            while not -(1 << (8 * width - 1)) <= n < (1 << (8 * width - 1)):
                width += 1
            data = n.to_bytes(width, "big", signed=True)
        atom = "0x" + data.hex() if data else "()"
        reference = f"(a (i (= (+ (q . {atom})) (q . {n})) (q . (q . ())) (q . (x))) 1)"
        body = f"ASSERT INT_BYTES({n}) = 0x{data.hex()}\nASSERT INT_FROM_BYTES(0x{data.hex()}) = {n}\n"
        yield module(body, ""), reference, []
    for encoded in ["00", "0000", "0001", "007f", "ffff", "ff80", "ff81", "000080", "ffff7f"]:
        data = bytes.fromhex(encoded)
        # ABI rejection rules independently checked by byte prefix, not arithmetic normalization.
        assert data == b"\x00" or len(data) > 1 and (data[0] == 0 and data[1] < 128 or data[0] == 255 and data[1] >= 128)
        yield module(f"DIM unused = INT_FROM_BYTES(0x{encoded})\n", ""), "(x)", None
    yield (ROOT / "examples/m2-integer-bytes.bas").read_text(encoding="utf-8"), "(q . ((83 128)))", [128]
    yield module("ASSERT TRUE OR (INT_FROM_BYTES(0x00) = 0)\n", ""), "(q . ())", []
    yield module("IF FALSE THEN\nDIM n = INT_FROM_BYTES(0xffff)\nEND IF\n", ""), "(q . ())", []


def unsigned_byte_cases():
    for width in [4, 8]:
        bits = width * 8
        maximum = 2**bits - 1
        for n in [0, 1, 127, 128, 255, 256, 32768, 65536, maximum // 2, maximum // 2 + 1, maximum - 1, maximum]:
            encoded = n.to_bytes(width, "big").hex()
            # Independent reference constructs the width by zero-prefixing and
            # selecting the last bytes of a signed atom (no sentinel addition).
            atom = n.to_bytes((n.bit_length() + 8) // 8 or 1, "big").hex()
            padded = f"(concat (q . 0x{'00' * width}) (q . 0x{atom}))"
            start = len(bytes.fromhex(atom))
            expr = f"(substr {padded} (q . {start}))"
            reference = f"(a (i (= {expr} (q . 0x{encoded})) (q . (q . ((83 {width})))) (q . (x))) 1)"
            yield module(f"DIM b = U{bits}BE({n})\nASSERT b = 0x{encoded}\nEMIT ASSERT_HEIGHT_ABSOLUTE(BYTE_LENGTH(b))\n", ""), reference, [width]
        for n in [-1, -(2**bits), 2**bits, 2**128]:
            yield module(f"DIM unused = U{bits}BE({n})\n", ""), "(x)", None
        yield module(f"ASSERT TRUE OR (U{bits}BE(-1) = 0x)\n", ""), "(q . ())", []
    yield (ROOT / "examples/m2-unsigned-bytes.bas").read_text(encoding="utf-8"), "(q . ((83 12)))", [12]


def string_cases():
    for text in ["", "Hello, Chia!", "REM ' () []", 'a"b', r"\n\t", "é", "e\u0301", "你好", "🦀", "\t", "\U0010ffff"]:
        literal = '"' + text.replace('"', '""') + '"'
        data = text.encode("utf-8")
        atom = "0x" + data.hex() if data else "()"
        reference = f"(c (c (q . 83) (c (strlen (q . {atom})) (q . ()))) (q . ()))"
        body = f"CONST original AS STRING = {literal}\nDIM s = original\nASSERT UTF8(s) = 0x{data.hex()}\nEMIT ASSERT_HEIGHT_ABSOLUTE(BYTE_LENGTH(UTF8(s)))\n"
        yield module(body, ""), reference, [len(data)]
    for left, right in [("é", "e\u0301"), ("a", "A"), ("", ""), ("你好", "你好")]:
        lhs = "0x" + left.encode().hex() if left else "()"
        rhs = "0x" + right.encode().hex() if right else "()"
        reference = f"(a (i (= (q . {lhs}) (q . {rhs})) (q . (q . ())) (q . (x))) 1)"
        yield module(f'ASSERT "{left}" = "{right}"\n', ""), reference, [] if left == right else None
    yield (ROOT / "examples/m2-strings.bas").read_text(encoding="utf-8"), "(q . ((83 12)))", [12]
    functions = 'FUNCTION Fail() AS STRING\nASSERT FALSE\nRETURN ""\nEND FUNCTION\n'
    for body, expected in [("DIM b = UTF8(Fail())\n", None), ("ASSERT TRUE OR (UTF8(Fail()) = 0x)\n", [])]:
        yield module(body, functions), "(x)" if expected is None else "(q . ())", expected


def utf8_validation_cases():
    vectors = ["", "00", "7f", "c280", "dfbf", "e0a080", "ed9fbf", "ee8080", "efbfbf", "f0908080", "f48fbfbf", "efbbbf", "61cc81", "c3a9", "48656c6c6f00f09fa680",
               "80", "bf", "c0af", "c180", "c2", "c241", "e08080", "e09fbf", "eda080", "edbfbf", "e180", "e18041", "f0808080", "f08fbfbf", "f4908080", "f5808080", "fe", "ff", "f18080", "f1808041", "61c280ff"]
    for encoded in vectors:
        data = bytes.fromhex(encoded)
        try:
            data.decode("utf-8", errors="strict")
            expected = [len(data)]
        except UnicodeDecodeError:
            expected = None
        body = f"DIM s = STRING_FROM_UTF8(0x{encoded})\nASSERT UTF8(s) = 0x{encoded}\nEMIT ASSERT_HEIGHT_ABSOLUTE(BYTE_LENGTH(UTF8(s)))\n"
        reference = "(x)" if expected is None else f"(q . ((83 {len(data)})))"
        yield module(body, ""), reference, expected
    yield (ROOT / "examples/m2-utf8-validation.bas").read_text(encoding="utf-8"), "(q . ((83 10)))", [10]
    yield module('ASSERT TRUE OR (STRING_FROM_UTF8(0xff) = "")\n', ""), "(q . ())", []
    yield module('IF FALSE THEN\nDIM s = STRING_FROM_UTF8(0xff)\nEND IF\n', ""), "(q . ())", []


def pair_cases():
    for n in [0, 1, 127, 128, 1000]:
        pair = f"(c (q . {n}) (q . 0x0001))"
        reference = f"(c (c (q . 83) (c (f {pair}) (q . ()))) (q . ()))"
        yield module(f"DIM p = PAIR({n},0x0001)\nASSERT REST(p) = 0x0001\nEMIT ASSERT_HEIGHT_ABSOLUTE(FIRST(p))\n", ""), reference, [n]
    yield (ROOT / "examples/m2-pairs.bas").read_text(encoding="utf-8"), "(q . ((83 128)))", [128]
    yield module("DIM p = PAIR(PAIR(7,TRUE),0x)\nEMIT ASSERT_HEIGHT_ABSOLUTE(FIRST(FIRST(p)))\n", ""), "(c (c (q . 83) (c (f (f (c (c (q . 7) (q . 1)) (q . ())))) (q . ()))) (q . ()))", [7]
    yield module("DIM p = PAIR(FALSE,0x)\nASSERT NOT FIRST(p)\nASSERT REST(p) = 0x\n", ""), "(q . ())", []
    yield module("DIM p = PAIR(1,ASSERT_HEIGHT_ABSOLUTE(-1))\n", ""), "(x)", None
    yield module("ASSERT TRUE OR REST(PAIR(ASSERT_HEIGHT_ABSOLUTE(-1),1)) = 1\n", ""), "(q . ())", []


def list_literal_cases():
    for ty, literal in [("INTEGER", "[]"), ("INTEGER", "[1,128]"), ("BOOLEAN", "[TRUE,FALSE]"), ("BYTES", "[0x,0x0001]"), ("STRING", '["", "hi"]'), ("LIST OF INTEGER", "[[],[1]]")]:
        yield module(f"DIM xs AS LIST OF {ty} = {literal}\n", ""), "(q . ())", []
    functions = "FUNCTION Empty() AS LIST OF INTEGER\nRETURN []\nEND FUNCTION\nFUNCTION Ignore(xs AS LIST OF INTEGER) AS INTEGER\nRETURN 7\nEND FUNCTION\n"
    yield module("DIM xs = Empty()\nEMIT ASSERT_HEIGHT_ABSOLUTE(Ignore([]))\n", functions), "(q . ((83 7)))", [7]
    yield module("DIM p AS PAIR OF (LIST OF INTEGER,INTEGER) = PAIR([],7)\nEMIT ASSERT_HEIGHT_ABSOLUTE(REST(p))\n", ""), "(c (c (q . 83) (c (r (c (q . ()) (q . 7))) (q . ()))) (q . ()))", [7]
    yield (ROOT / "examples/m2-lists.bas").read_text(encoding="utf-8"), "(q . ((83 12)))", [12]
    yield module("DIM xs = [ASSERT_HEIGHT_ABSOLUTE(-1)]\n", ""), "(x)", None
    yield module("IF FALSE THEN\nDIM xs = [ASSERT_HEIGHT_ABSOLUTE(-1)]\nEND IF\n", ""), "(q . ())", []


def list_operation_cases():
    for count in [0, 1, 2, 16, 32, 128]:
        items = ",".join(str(n) for n in range(count))
        yield module(f"DIM xs AS LIST OF INTEGER = [{items}]\nEMIT ASSERT_HEIGHT_ABSOLUTE(LIST_LENGTH(xs))\n", ""), f"(q . ((83 {count})))", [count]
    for head in [0, 7, 128]:
        reference = f"(c (c (q . 83) (c (f (c (q . {head}) (q . (2 3)))) (q . ()))) (q . ()))"
        yield module(f"DIM xs = CONS({head},[2,3])\nASSERT FIRST(REST(xs)) = 2\nEMIT ASSERT_HEIGHT_ABSOLUTE(FIRST(xs))\n", ""), reference, [head]
    yield (ROOT / "examples/m2-list-operations.bas").read_text(encoding="utf-8"), "(q . ((83 10) (83 20) (83 3)))", [10,20,3]
    for op, clvm_op in [("FIRST", "f"), ("REST", "r")]:
        yield module(f"DIM xs AS LIST OF INTEGER = []\nDIM unused = {op}(xs)\n", ""), f"({clvm_op} (q . ()))", None
    yield module("DIM xs AS LIST OF INTEGER = []\nASSERT TRUE OR FIRST(xs) = 1\n", ""), "(q . ())", []
    yield module("DIM xs AS LIST OF LIST OF INTEGER = CONS([],[])\nASSERT LIST_LENGTH(FIRST(xs)) = 0\nEMIT ASSERT_HEIGHT_ABSOLUTE(LIST_LENGTH(xs))\n", ""), "(q . ((83 1)))", [1]


def list_constant_cases():
    for n in [0, 1, 127, 128, 65536]:
        body = f"CONST xs = [{n},2]\nCONST saved = (xs)\nASSERT LIST_LENGTH(saved) = 2\nEMIT ASSERT_HEIGHT_ABSOLUTE(FIRST(saved))\n"
        reference = f"(c (c (q . 83) (c (f (q . ({n} 2))) (q . ()))) (q . ()))"
        yield module(body, ""), reference, [n]
    for ty, literal, assertion in [("BYTES", "[0x,0x0001]", "FIRST(REST(xs)) = 0x0001"), ("STRING", '["", "é"]', "UTF8(FIRST(REST(xs))) = 0xc3a9"), ("BOOLEAN", "[TRUE,FALSE]", "FIRST(xs) AND NOT FIRST(REST(xs))")]:
        yield module(f"CONST xs AS LIST OF {ty} = {literal}\nASSERT {assertion}\n", ""), "(q . ())", []
    for op in ["FIRST", "REST"]:
        yield module(f"CONST xs AS LIST OF INTEGER = []\nDIM unused = {op}(xs)\n", ""), "(x)", None
    yield module("CONST xs AS LIST OF INTEGER = []\nASSERT TRUE OR FIRST(xs) = 1\n", ""), "(q . ())", []
    yield (ROOT / "examples/m2-list-constants.bas").read_text(encoding="utf-8"), "(q . ((83 7) (83 2)))", [7, 2]


def budget_cases(binary, directory):
    work = " * ".join(["9" * 500] * 8)
    functions = f"FUNCTION Expensive() AS INTEGER\nRETURN {work}\nEND FUNCTION\nFUNCTION Fail() AS INTEGER\nASSERT FALSE\nRETURN 1\nEND FUNCTION\nFUNCTION Ignore(a AS INTEGER, b AS INTEGER) AS INTEGER\nRETURN 1\nEND FUNCTION\n"
    for index, (arguments, code) in enumerate([("Fail(), Expensive()", "E0500"), ("Expensive(), Fail()", "E0501")]):
        source = directory / f"budget{index}.bas"
        source.write_text(module(f"DIM n = Ignore({arguments})\n", functions), encoding="utf-8", newline="\n")
        out = directory / f"budget{index}"
        invoke(binary, ["build", source, "--out", out])
        result = invoke(binary, ["run", out / "manifest.json", "--max-cost", "10000"], 3)
        assert result["diagnostics"][0]["code"] == code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--with-upstream", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--bytes", action="store_true", help="Verify byte literals, equality and typed function flow")
    modes.add_argument("--byte-constants", action="store_true", help="Verify exact-byte constants, folding and return analysis")
    modes.add_argument("--byte-operations", action="store_true", help="Verify BYTE_LENGTH and CONCAT")
    modes.add_argument("--sha256", action="store_true", help="Verify exact-byte SHA256 hashing")
    modes.add_argument("--integer-bytes", action="store_true", help="Verify canonical integer byte conversions")
    modes.add_argument("--unsigned-bytes", action="store_true", help="Verify U32BE and U64BE")
    modes.add_argument("--strings", action="store_true", help="Verify STRING literals, values and UTF8")
    modes.add_argument("--utf8-validation", action="store_true", help="Verify strict runtime STRING_FROM_UTF8")
    modes.add_argument("--pairs", action="store_true", help="Verify pair construction and projections")
    modes.add_argument("--list-literals", action="store_true", help="Verify runtime list literals and contextual typing")
    modes.add_argument("--list-operations", action="store_true", help="Verify list FIRST/REST, CONS and LIST_LENGTH")
    modes.add_argument("--list-constants", action="store_true", help="Verify list constants and quoted trees")
    args = parser.parse_args()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    if not binary.is_file():
        parser.error("Build the CLI first or supply --binary PATH")
    with tempfile.TemporaryDirectory(prefix="0xbasic functions ") as directory:
        directory = Path(directory)
        selected = list_constant_cases() if args.list_constants else list_operation_cases() if args.list_operations else list_literal_cases() if args.list_literals else pair_cases() if args.pairs else utf8_validation_cases() if args.utf8_validation else string_cases() if args.strings else unsigned_byte_cases() if args.unsigned_bytes else integer_byte_cases() if args.integer_bytes else hash_cases() if args.sha256 else byte_operation_cases() if args.byte_operations else byte_constant_cases() if args.byte_constants else byte_cases() if args.bytes else cases()
        for count, (text, reference, expected) in enumerate(selected, start=1):
            source = directory / "function.bas"
            source.write_text(text, encoding="utf-8", newline="\n")
            out = directory / str(count)
            invoke(binary, ["check", source])
            invoke(binary, ["build", source, "--out", out])
            result = invoke(binary, ["run", out / "manifest.json"], 3 if expected is None else 0)
            if expected is None:
                assert result["diagnostics"][0]["code"] == "E0500"
            else:
                assert result["result"]["tree"] == expected_tree(expected)
            if args.with_upstream:
                upstream((out / "puzzle.clvm").read_bytes(), reference, expected, result)
        if not (args.bytes or args.byte_constants or args.byte_operations or args.sha256 or args.integer_bytes or args.unsigned_bytes or args.strings or args.utf8_validation or args.pairs or args.list_literals or args.list_operations or args.list_constants):
            budget_cases(binary, directory)
    mode = "LIST constant cases" if args.list_constants else "LIST operation cases" if args.list_operations else "LIST literal cases" if args.list_literals else "PAIR cases" if args.pairs else "UTF-8 validation cases" if args.utf8_validation else "STRING cases" if args.strings else "unsigned byte cases" if args.unsigned_bytes else "integer byte cases" if args.integer_bytes else "SHA256 cases" if args.sha256 else "byte operation cases" if args.byte_operations else "byte constant cases" if args.byte_constants else "byte cases" if args.bytes else "function cases and 2 evaluation-order budget cases"
    print(f"{count} {mode} passed" + ("; reference cases also matched independent Python CLVM references and generated-program costs." if args.with_upstream else "."))


if __name__ == "__main__":
    main()
