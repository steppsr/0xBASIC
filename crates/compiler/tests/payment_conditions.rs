use oxbasic_compiler::{abi, analyze, check, clvm, compile, compile_template};
use serde_json::Value;
fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}\nEND CONTRACT\n")
}
fn run(body: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("payment.bas", source(body).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}
#[test]
fn payment_vectors_match_types_execution_and_original_emission_order() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../docs/spec/m3-payment-condition-cases.json"
    ))
    .unwrap();
    for c in fixture["cases"].as_array().unwrap() {
        let s = c["source"].as_str().unwrap().as_bytes();
        if let Some(code) = c["check_diagnostic"].as_str() {
            for e in [
                analyze("fixture.bas", s).unwrap_err(),
                check("fixture.bas", s).unwrap_err(),
            ] {
                assert_eq!(e.code, code, "{}", c["id"]);
                assert!(e.span.is_some());
            }
        } else {
            let p = compile("fixture.bas", s).unwrap();
            let r = clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST);
            if let Some(code) = c["runtime_diagnostic"].as_str() {
                assert_eq!(r.err().unwrap().code, code);
            } else {
                assert_eq!(
                    hex::encode(r.unwrap().bytes),
                    c["expected_hex"],
                    "{}",
                    c["id"]
                );
            }
        }
    }
    let original: Value =
        serde_json::from_str(include_str!("../../../docs/spec/source-cases.json")).unwrap();
    let old = original["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "emission-order")
        .unwrap();
    let activated = fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "m0-emission-order")
        .unwrap();
    assert_eq!(old["source"], activated["source"]);
    assert_eq!(old["expected_conditions"], activated["conditions"]);
}
#[test]
fn condition_functions_collections_and_exact_cost_work_with_bound_values() {
    let t = compile_template(
        "example.bas",
        include_bytes!("../../../examples/m3-payment-conditions.bas"),
    )
    .unwrap();
    let b = t
        .bind(include_bytes!(
            "../../../examples/m3-payment-conditions.bindings.json"
        ))
        .unwrap();
    let r = clvm::execute(&b.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(
        hex::encode(&r.bytes),
        format!(
            "ffff49ff8203e880ffff53ff6480ffff33ffa0{}afff8203e88080",
            "00".repeat(31)
        )
    );
    clvm::execute(&b.puzzle, &[0x80], r.cost).unwrap();
    assert_eq!(
        clvm::execute(&b.puzzle, &[0x80], r.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}
#[test]
fn payment_calls_are_eager_left_to_right_and_do_not_emit_implicitly() {
    let h = format!("AS_PUZZLEHASH(0x{})", "00".repeat(32));
    assert_eq!(
        run(
            &format!("DIM unused = CREATE_COIN({h},AS_AMOUNT(1))"),
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes,
        [0x80]
    );
    assert_eq!(
        run(
            "DIM c = ASSERT_MY_AMOUNT(AS_AMOUNT(-1))\nc = ASSERT_MY_AMOUNT(AS_AMOUNT(1))",
            clvm::DEFAULT_MAX_COST
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    let slow = format!("STRING_FROM_UTF8(0x{})", "61".repeat(256));
    let left_fails =
        format!("DIM c = CREATE_COIN(AS_PUZZLEHASH(0x),AS_AMOUNT(BYTE_LENGTH(UTF8({slow}))))");
    assert_eq!(run(&left_fails, 50000).err().unwrap().code, "E0500");
    let right_fails =
        format!("DIM c = CREATE_COIN(AS_PUZZLEHASH(SHA256(UTF8({slow}))),AS_AMOUNT(-1))");
    assert_eq!(run(&right_fails, 50000).err().unwrap().code, "E0501");
    assert_eq!(
        run(&right_fails, clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}
#[test]
fn payment_results_remain_condition_values_with_no_implicit_conversions() {
    for body in [
        "DIM n AS INTEGER = ASSERT_MY_AMOUNT(AS_AMOUNT(1))",
        "ASSERT ASSERT_MY_AMOUNT(AS_AMOUNT(1))",
        "DIM equal = ASSERT_MY_AMOUNT(AS_AMOUNT(1)) = ASSERT_MY_AMOUNT(AS_AMOUNT(1))",
        "IF FALSE THEN\nEMIT CREATE_COIN(1,2)\nEND IF",
    ] {
        assert_eq!(
            check("bad.bas", source(body).as_bytes()).unwrap_err().code,
            "E0202"
        );
    }
    let s = "CONTRACT Demo()\nEND CONTRACT\nFUNCTION F() AS CONDITION\nRETURN ASSERT_MY_AMOUNT(AS_AMOUNT(1))\nRETURN CREATE_COIN(1,2)\nEND FUNCTION\n";
    assert_eq!(
        analyze("unreachable.bas", s.as_bytes()).unwrap_err().code,
        "E0202"
    );
    assert_eq!(
        run("EMIT AGG_SIG_ME(0x,0x)", clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0202"
    );
}
#[test]
fn solution_domain_guards_protect_payment_operands_before_emission() {
    let t=compile_template("raw.bas",b"CONTRACT Demo()\nSOLUTION recipient AS PUZZLEHASH\nSOLUTION paymentAmount AS AMOUNT\nEMIT CREATE_COIN(recipient,paymentAmount)\nEMIT ASSERT_MY_AMOUNT(paymentAmount)\nEND CONTRACT\n").unwrap();
    let p = t.bind(b"{}").unwrap();
    for (raw, valid) in [
        (format!("ffa0{}ff8080", "00".repeat(32)), true),
        (format!("ffa0{}ff0080", "00".repeat(32)), false),
        (format!("ffa0{}ff81ff80", "00".repeat(32)), false),
        (format!("ff9f{}ff0180", "00".repeat(31)), false),
    ] {
        assert_eq!(
            clvm::execute(
                &p.puzzle,
                &hex::decode(raw).unwrap(),
                clvm::DEFAULT_MAX_COST
            )
            .is_ok(),
            valid
        );
    }
    let json = format!(
        r#"{{"recipient":{{"hex":"{}"}},"paymentAmount":"18446744073709551615"}}"#,
        "ff".repeat(32)
    );
    let s = abi::encode_solution(&t.contract.inputs, json.as_bytes()).unwrap();
    clvm::execute(&p.puzzle, &s, clvm::DEFAULT_MAX_COST).unwrap();
}
#[test]
fn locals_reassignment_and_duplicate_payments_preserve_order() {
    let body = "DIM c = ASSERT_MY_AMOUNT(AS_AMOUNT(1))\nDIM saved = c\nc = ASSERT_MY_AMOUNT(AS_AMOUNT(2))\nEMIT saved\nEMIT c\nEMIT saved";
    assert_eq!(
        hex::encode(run(body, clvm::DEFAULT_MAX_COST).unwrap().bytes),
        "ffff49ff0180ffff49ff0280ffff49ff018080"
    );
}
