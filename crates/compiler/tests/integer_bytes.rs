use num_bigint::BigInt;
use oxbasic_compiler::{analyze, check, clvm, compile};

fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn run(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("conversion.bas", source(body, functions).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}

#[test]
fn canonical_encoding_preserves_zero_sign_boundaries_and_large_integers() {
    for (number, bytes) in [
        (0, ""),
        (1, "01"),
        (-1, "ff"),
        (127, "7f"),
        (128, "0080"),
        (255, "00ff"),
        (256, "0100"),
        (-128, "80"),
        (-129, "ff7f"),
        (-256, "ff00"),
        (32768, "008000"),
        (-32769, "ff7fff"),
    ] {
        run(&format!("ASSERT int_bytes({number}) = 0x{bytes}\nASSERT int_from_bytes(0x{bytes}) = {number}\n"),"",clvm::DEFAULT_MAX_COST).unwrap();
    }
    for bits in [64usize, 128, 1024, 8192] {
        let value = BigInt::from(1) << bits;
        for n in [value.clone(), -value] {
            let bytes = hex::encode(n.to_signed_bytes_be());
            run(&format!("DIM n = {n}\nASSERT INT_BYTES(n) = 0x{bytes}\nASSERT INT_FROM_BYTES(INT_BYTES(n)) = n\n"),"",clvm::DEFAULT_MAX_COST).unwrap();
        }
    }
    run(
        "ASSERT INT_BYTES(128 - 128) = 0x\nASSERT INT_BYTES(-128 - 1) = 0xff7f\n",
        "",
        clvm::DEFAULT_MAX_COST,
    )
    .unwrap();
}

#[test]
fn strict_decoding_rejects_noncanonical_atoms_including_unused_results() {
    for bytes in [
        "00", "0000", "0001", "007f", "ffff", "ff80", "ff81", "000080", "ffff7f",
    ] {
        let text = source(&format!("DIM unused = INT_FROM_BYTES(0x{bytes})\n"), "");
        check("bad.bas", text.as_bytes()).unwrap();
        analyze("bad.bas", text.as_bytes()).unwrap();
        assert_eq!(
            run(
                &format!("DIM unused = INT_FROM_BYTES(0x{bytes})\n"),
                "",
                clvm::DEFAULT_MAX_COST
            )
            .err()
            .unwrap()
            .code,
            "E0500",
            "{bytes}"
        );
    }
    // Every nonzero one-byte atom is a canonical signed integer.
    for byte in 1u16..=255 {
        let n = if byte < 128 {
            i32::from(byte)
        } else {
            i32::from(byte) - 256
        };
        run(
            &format!("ASSERT INT_FROM_BYTES(0x{byte:02x}) = {n}\n"),
            "",
            clvm::DEFAULT_MAX_COST,
        )
        .unwrap();
    }
}

#[test]
fn conversion_types_arity_and_const_rules_are_shared() {
    for (body, code) in [
        ("DIM b = INT_BYTES()\n", "E0202"),
        ("DIM b = INT_BYTES(1,2)\n", "E0202"),
        ("DIM b = INT_BYTES(0x)\n", "E0202"),
        ("DIM b = INT_BYTES(TRUE)\n", "E0202"),
        ("DIM n = INT_FROM_BYTES()\n", "E0202"),
        ("DIM n = INT_FROM_BYTES(0x,0x)\n", "E0202"),
        ("DIM n = INT_FROM_BYTES(0)\n", "E0202"),
        ("DIM n = INT_FROM_BYTES(FALSE)\n", "E0202"),
        ("DIM n AS BYTES = INT_FROM_BYTES(0x)\n", "E0202"),
        ("DIM n AS INTEGER = INT_BYTES(0)\n", "E0202"),
        ("DIM b = INT_BYTES\n", "E0100"),
        ("DIM INT_FROM_BYTES = 1\n", "E0201"),
        ("CONST b = INT_BYTES(0)\n", "E0205"),
        ("CONST n = INT_FROM_BYTES(0x)\n", "E0205"),
        ("CONST b = TRUE OR (INT_FROM_BYTES(0x00) = 0)\n", "E0205"),
        ("IF FALSE THEN\nDIM b = INT_BYTES(FALSE)\nEND IF\n", "E0202"),
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
fn conversion_evaluation_is_once_ordered_and_lazy_only_when_selected() {
    let functions = "FUNCTION Fail() AS INTEGER\nASSERT FALSE\nRETURN 0\nEND FUNCTION\nFUNCTION Work() AS BYTES\nRETURN CONCAT(0x00,0x80)\nEND FUNCTION\n";
    assert_eq!(
        run(
            "DIM b = INT_BYTES(Fail())\n",
            functions,
            clvm::DEFAULT_MAX_COST
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    run("ASSERT TRUE OR (INT_FROM_BYTES(0x00) = 0)\nASSERT NOT (FALSE AND (INT_FROM_BYTES(0xffff) = -1))\nIF FALSE THEN\nDIM b = INT_BYTES(Fail())\nEND IF\n",functions,clvm::DEFAULT_MAX_COST).unwrap();
    let direct = compile(
        "direct.bas",
        source("DIM n = INT_FROM_BYTES(Work())\n", functions).as_bytes(),
    )
    .unwrap();
    let named = compile(
        "named.bas",
        source("DIM b = Work()\nDIM n = INT_FROM_BYTES(b)\n", functions).as_bytes(),
    )
    .unwrap();
    assert_eq!(direct.puzzle, named.puzzle);
    clvm::execute(&direct.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    let expensive = format!(
        "FUNCTION Work() AS BYTES\nDIM b = 0x{}\nRETURN CONCAT(b,b)\nEND FUNCTION\n",
        "ff".repeat(8192)
    );
    assert_eq!(
        run(
            "DIM b = CONCAT(INT_BYTES(INT_FROM_BYTES(0x00)),Work())\n",
            &expensive,
            20_000
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    assert_eq!(
        run(
            "DIM b = CONCAT(Work(),INT_BYTES(INT_FROM_BYTES(0x00)))\n",
            &expensive,
            20_000
        )
        .err()
        .unwrap()
        .code,
        "E0501"
    );
}

#[test]
fn conversions_flow_through_functions_branches_and_cost_limits() {
    let functions = "FUNCTION Decode(b AS BYTES) AS INTEGER\nIF BYTE_LENGTH(b) = 0 THEN\nRETURN INT_FROM_BYTES(b)\nEND IF\nRETURN INT_FROM_BYTES(b) + 1\nEND FUNCTION\n";
    let body = "DIM n = Decode(0x)\nIF TRUE THEN\nn = Decode(INT_BYTES(127))\nEND IF\nASSERT n = 128\nASSERT INT_BYTES(n) = 0x0080\n";
    let result = run(body, functions, clvm::DEFAULT_MAX_COST).unwrap();
    run(body, functions, result.cost).unwrap();
    assert_eq!(
        run(body, functions, result.cost - 1).err().unwrap().code,
        "E0501"
    );
    let p = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-integer-bytes.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        run(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(128)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}
