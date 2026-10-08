use oxbasic_compiler::{analyze, check, clvm, compile};
use sha2::{Digest, Sha256};

fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn run(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("hash.bas", source(body, functions).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}

#[test]
fn hashes_exact_bytes_and_known_vectors() {
    for (input, expected) in [
        (
            "",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ),
        (
            "616263",
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        ),
    ] {
        run(
            &format!("ASSERT sHa256(0x{input}) = 0x{expected}\n"),
            "",
            clvm::DEFAULT_MAX_COST,
        )
        .unwrap();
    }
    for bytes in [
        vec![0],
        vec![0, 0, 1],
        vec![1],
        (0..=255).collect(),
        vec![0x61; 55],
        vec![0x61; 56],
        vec![0x61; 64],
        vec![0xff; 8192],
    ] {
        let digest = hex::encode(Sha256::digest(&bytes));
        run(&format!("DIM hash AS BYTES = SHA256(0x{})\nASSERT hash = 0x{digest}\nASSERT BYTE_LENGTH(hash) = 32\n",hex::encode(bytes)), "", clvm::DEFAULT_MAX_COST).unwrap();
    }
}

#[test]
fn hash_signature_and_constant_restrictions_are_checked() {
    for (body, code) in [
        ("DIM h = SHA256()\n", "E0202"),
        ("DIM h = SHA256(0x,0x)\n", "E0202"),
        ("DIM h = SHA256(1)\n", "E0202"),
        ("DIM h = SHA256(FALSE)\n", "E0202"),
        ("DIM h = SHA256(ASSERT_HEIGHT_ABSOLUTE(0))\n", "E0202"),
        ("DIM h AS INTEGER = SHA256(0x)\n", "E0202"),
        ("ASSERT SHA256(0x)\n", "E0202"),
        ("DIM h = SHA256\n", "E0100"),
        ("DIM SHA256 = 0x\n", "E0201"),
        ("CONST h = SHA256(0x)\n", "E0205"),
        ("CONST b = TRUE OR (SHA256(0x) = 0x)\n", "E0205"),
        ("IF FALSE THEN\nDIM h = SHA256(1)\nEND IF\n", "E0202"),
    ] {
        let text = source(body, "");
        assert_eq!(
            check("bad.bas", text.as_bytes()).unwrap_err().code,
            code,
            "{body}"
        );
        assert_eq!(
            analyze("bad.bas", text.as_bytes()).unwrap_err().code,
            code,
            "{body}"
        );
    }
}

#[test]
fn hashing_is_eager_once_and_obeys_lazy_control_flow() {
    let functions = "FUNCTION Fail() AS BYTES\nASSERT FALSE\nRETURN 0x\nEND FUNCTION\nFUNCTION Work() AS BYTES\nRETURN CONCAT(0x00,0xff)\nEND FUNCTION\n";
    assert_eq!(
        run(
            "DIM unused = SHA256(Fail())\n",
            functions,
            clvm::DEFAULT_MAX_COST
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    run("ASSERT TRUE OR (SHA256(Fail()) = 0x)\nASSERT NOT (FALSE AND (SHA256(Fail()) = 0x))\nIF FALSE THEN\nDIM h = SHA256(Fail())\nEND IF\n", functions, clvm::DEFAULT_MAX_COST).unwrap();
    let direct = compile(
        "direct.bas",
        source("DIM h = SHA256(Work())\n", functions).as_bytes(),
    )
    .unwrap();
    let named = compile(
        "named.bas",
        source("DIM b = Work()\nDIM h = SHA256(b)\n", functions).as_bytes(),
    )
    .unwrap();
    assert_eq!(direct.puzzle, named.puzzle);
    clvm::execute(&direct.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
}

#[test]
fn hashes_flow_through_functions_branches_and_have_bounded_cost() {
    let functions = "FUNCTION Hash(b AS BYTES, flag AS BOOLEAN) AS BYTES\nIF flag THEN\nRETURN SHA256(b)\nEND IF\nRETURN SHA256(CONCAT(b,0x00))\nEND FUNCTION\n";
    let body = "CONST b = 0x0001\nDIM h = Hash(b,TRUE)\nIF TRUE THEN\nh = Hash(b,FALSE)\nEND IF\nASSERT h = SHA256(0x000100)\nASSERT SHA256(SHA256(b)) = SHA256(Hash(b,TRUE))\n";
    let result = run(body, functions, clvm::DEFAULT_MAX_COST).unwrap();
    run(body, functions, result.cost).unwrap();
    assert_eq!(
        run(body, functions, result.cost - 1).err().unwrap().code,
        "E0501"
    );
    let example = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-sha256.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&example.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        run(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(32)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}
