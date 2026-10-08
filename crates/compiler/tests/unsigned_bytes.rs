use oxbasic_compiler::{analyze, check, clvm, compile};
fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn run(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("unsigned.bas", source(body, functions).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}
#[test]
fn exact_unsigned_widths_preserve_zeros_and_high_bits() {
    for width in [4usize, 8] {
        let max = if width == 4 {
            u64::from(u32::MAX)
        } else {
            u64::MAX
        };
        for n in [
            0,
            1,
            127,
            128,
            255,
            256,
            32767,
            32768,
            65535,
            65536,
            max / 2,
            max / 2 + 1,
            max - 1,
            max,
        ] {
            let encoded = hex::encode(&n.to_be_bytes()[8 - width..]);
            run(&format!("DIM b AS BYTES = u{}be({n})\nASSERT b = 0x{encoded}\nASSERT BYTE_LENGTH(b) = {width}\n",width*8),"",clvm::DEFAULT_MAX_COST).unwrap();
        }
    }
    run("ASSERT U32BE(127 + 1) = 0x00000080\nASSERT U64BE(1 - 1) = 0x0000000000000000\nASSERT U32BE(128) <> INT_BYTES(128)\n","",clvm::DEFAULT_MAX_COST).unwrap();
}
#[test]
fn ranges_fail_at_runtime_even_when_unused_or_overwritten() {
    for (name, values) in [
        (
            "U32BE",
            ["-1", "-4294967296", "4294967296", "18446744073709551615"],
        ),
        (
            "U64BE",
            [
                "-1",
                "-18446744073709551616",
                "18446744073709551616",
                "9999999999999999999999999999999999999999",
            ],
        ),
    ] {
        for n in values {
            let body = format!("DIM unused = {name}({n})\nunused = 0x\n");
            let text = source(&body, "");
            check("bad.bas", text.as_bytes()).unwrap();
            analyze("bad.bas", text.as_bytes()).unwrap();
            assert_eq!(
                run(&body, "", clvm::DEFAULT_MAX_COST).err().unwrap().code,
                "E0500",
                "{name}({n})"
            );
        }
    }
}
#[test]
fn signatures_and_constant_restrictions_are_shared() {
    for name in ["U32BE", "U64BE"] {
        for (body, code) in [
            (format!("DIM b = {name}()\n"), "E0202"),
            (format!("DIM b = {name}(1,2)\n"), "E0202"),
            (format!("DIM b = {name}(TRUE)\n"), "E0202"),
            (format!("DIM b = {name}(0x)\n"), "E0202"),
            (format!("DIM b AS INTEGER = {name}(0)\n"), "E0202"),
            (format!("DIM b = {name}\n"), "E0100"),
            (format!("DIM {name} = 0\n"), "E0201"),
            (format!("CONST b = {name}(0)\n"), "E0205"),
            (format!("CONST b = TRUE OR ({name}(-1) = 0x)\n"), "E0205"),
            (
                format!("IF FALSE THEN\nDIM b = {name}(FALSE)\nEND IF\n"),
                "E0202",
            ),
        ] {
            let text = source(&body, "");
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
}
#[test]
fn unsigned_calls_evaluate_once_in_order_with_lazy_branches() {
    let functions = "FUNCTION Fail() AS INTEGER\nASSERT FALSE\nRETURN 0\nEND FUNCTION\nFUNCTION Work() AS INTEGER\nRETURN 127 + 1\nEND FUNCTION\n";
    for name in ["U32BE", "U64BE"] {
        assert_eq!(
            run(
                &format!("DIM unused = {name}(Fail())\n"),
                functions,
                clvm::DEFAULT_MAX_COST
            )
            .err()
            .unwrap()
            .code,
            "E0500"
        );
        run(&format!("ASSERT TRUE OR ({name}(-1) = 0x)\nASSERT NOT (FALSE AND ({name}(-1) = 0x))\nIF FALSE THEN\nDIM b = {name}(Fail())\nEND IF\n"),functions,clvm::DEFAULT_MAX_COST).unwrap();
        let direct = compile(
            "direct.bas",
            source(&format!("DIM b = {name}(Work())\n"), functions).as_bytes(),
        )
        .unwrap();
        let named = compile(
            "named.bas",
            source(&format!("DIM n = Work()\nDIM b = {name}(n)\n"), functions).as_bytes(),
        )
        .unwrap();
        assert_eq!(direct.puzzle, named.puzzle);
        clvm::execute(&direct.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    }
    let expensive = format!(
        "FUNCTION Work() AS BYTES\nDIM b = 0x{}\nRETURN CONCAT(b,b)\nEND FUNCTION\n",
        "ff".repeat(8192)
    );
    assert_eq!(
        run("DIM b = CONCAT(U32BE(-1),Work())\n", &expensive, 20_000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_eq!(
        run("DIM b = CONCAT(Work(),U64BE(-1))\n", &expensive, 20_000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}
#[test]
fn unsigned_bytes_flow_through_functions_branches_and_cost_limits() {
    let functions = "FUNCTION Encode(n AS INTEGER, short AS BOOLEAN) AS BYTES\nIF short THEN\nRETURN U32BE(n)\nEND IF\nRETURN U64BE(n)\nEND FUNCTION\n";
    let body = "CONST n = 128\nDIM b = Encode(n,TRUE)\nASSERT b = 0x00000080\nIF TRUE THEN\nb = Encode(n,FALSE)\nEND IF\nASSERT b = 0x0000000000000080\n";
    let result = run(body, functions, clvm::DEFAULT_MAX_COST).unwrap();
    run(body, functions, result.cost).unwrap();
    assert_eq!(
        run(body, functions, result.cost - 1).err().unwrap().code,
        "E0501"
    );
    let p = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-unsigned-bytes.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        run(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(12)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}
