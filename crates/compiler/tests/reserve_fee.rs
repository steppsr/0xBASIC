use oxbasic_compiler::{analyze, check, clvm, compile};

fn run(body: &str) -> oxbasic_compiler::Result<clvm::Execution> {
    let source = format!("CONTRACT Fees()\n{body}\nEND CONTRACT\n");
    let p = compile("fees.bas", source.as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
}

#[test]
fn reserve_fee_encodes_boundaries_without_implicit_emission() {
    for (amount, atom) in [
        ("0", "80"),
        ("1", "01"),
        ("127", "7f"),
        ("128", "820080"),
        ("18446744073709551615", "8900ffffffffffffffff"),
    ] {
        let result = run(&format!("EMIT RESERVE_FEE(AS_AMOUNT({amount}))")).unwrap();
        assert_eq!(hex::encode(result.bytes), format!("ffff34ff{atom}8080"));
    }
    assert_eq!(
        run("DIM unused = RESERVE_FEE(AS_AMOUNT(10))")
            .unwrap()
            .bytes,
        [0x80]
    );
    assert_eq!(
        run("DIM unused = RESERVE_FEE(AS_AMOUNT(-1))")
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}

#[test]
fn reserve_fee_functions_branches_loops_and_saved_conditions_keep_order() {
    let source = b"CONTRACT Fees()\nDIM saved AS CONDITION = Fee(AS_AMOUNT(4))\nFOR i = 1 TO 2\nIF i = 1 THEN\nEMIT saved\nELSE\nEMIT RESERVE_FEE(AS_AMOUNT(i))\nEND IF\nNEXT i\nEMIT saved\nEND CONTRACT\nFUNCTION Fee(value AS AMOUNT) AS CONDITION\nRETURN RESERVE_FEE(value)\nEND FUNCTION\n";
    let p = compile("fees.bas", source).unwrap();
    let r = clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(
        hex::encode(&r.bytes),
        "ffff34ff0480ffff34ff0280ffff34ff048080"
    );
    clvm::execute(&p.puzzle, &[0x80], r.cost).unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], r.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}

#[test]
fn reserve_fee_rejects_wrong_types_arity_constants_and_shadowing() {
    for body in [
        "EMIT RESERVE_FEE(1)",
        "EMIT RESERVE_FEE(TRUE)",
        "EMIT RESERVE_FEE(0x)",
        "EMIT RESERVE_FEE()",
        "EMIT RESERVE_FEE(AS_AMOUNT(1),AS_AMOUNT(2))",
        "CONST c = RESERVE_FEE(AS_AMOUNT(1))",
        "DIM reserve_fee = 1",
    ] {
        let source = format!("CONTRACT Fees()\n{body}\nEND CONTRACT\n");
        assert!(analyze("fees.bas", source.as_bytes()).is_err(), "{body}");
        assert!(check("fees.bas", source.as_bytes()).is_err(), "{body}");
        assert!(compile("fees.bas", source.as_bytes()).is_err(), "{body}");
    }
    assert!(
        compile(
            "fees.bas",
            b"CONTRACT Fees(reserve_fee AS AMOUNT)\nEND CONTRACT\n"
        )
        .is_err()
    );
}
