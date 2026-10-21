use oxbasic_compiler::{abi, analyze, check, clvm, compile, compile_template};
use serde_json::Value;
fn key() -> String {
    serde_json::from_str::<Value>(include_str!("../../../docs/spec/vectors.json")).unwrap()["payment"]["owner_hex"].as_str().unwrap().into()
}
fn run(body: &str) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile(
        "sig.bas",
        format!("CONTRACT Demo()\n{body}\nEND CONTRACT\n").as_bytes(),
    )?;
    clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
}
#[test]
fn signature_vectors_have_exact_messages_and_diagnostics() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../docs/spec/m3-signature-condition-cases.json"
    ))
    .unwrap();
    for c in fixture["cases"].as_array().unwrap() {
        let s = c["source"].as_str().unwrap().as_bytes();
        if let Some(code) = c["check_diagnostic"].as_str() {
            for e in [
                analyze("sig.bas", s).unwrap_err(),
                check("sig.bas", s).unwrap_err(),
            ] {
                assert_eq!(e.code, code);
                assert!(e.span.is_some());
            }
        } else {
            let p = compile("sig.bas", s).unwrap();
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
}
#[test]
fn message_limit_applies_at_call_for_json_and_raw_fixed_and_solution_values() {
    for fixed in [false, true] {
        let source = if fixed {
            "CONTRACT Demo(owner AS PUBLICKEY, message AS BYTES)\n"
        } else {
            "CONTRACT Demo()\nSOLUTION owner AS PUBLICKEY\nSOLUTION message AS BYTES\n"
        };
        let t = compile_template(
            "boundary.bas",
            format!("{source}DIM unused = AGG_SIG_ME(owner,message)\nEND CONTRACT\n").as_bytes(),
        )
        .unwrap();
        for n in [0, 1023, 1024, 1025] {
            let j = format!(
                r#"{{"owner":{{"hex":"{}"}},"message":{{"hex":"{}"}}}}"#,
                key(),
                "00".repeat(n)
            );
            let fields = if fixed {
                &t.contract.fixed
            } else {
                &t.contract.inputs
            };
            // BYTES itself is unrestricted by the signature constructor's message cap.
            let raw = abi::encode_solution(fields, j.as_bytes()).unwrap();
            let (p, s) = if fixed {
                (t.bind(j.as_bytes()).unwrap().puzzle, vec![0x80])
            } else {
                (t.bind(b"{}").unwrap().puzzle, raw.clone())
            };
            assert_eq!(
                clvm::execute(&p, &s, clvm::DEFAULT_MAX_COST).is_ok(),
                n <= 1024
            );
            let (p, s) = if fixed {
                (clvm::bind_fixed(&t.template, &raw).unwrap(), vec![0x80])
            } else {
                (p, raw)
            };
            use clvmr::{Allocator, ChiaDialect, ClvmFlags, run_program, serde::node_from_bytes};
            let mut a = Allocator::new();
            let p = node_from_bytes(&mut a, &p).unwrap();
            let s = node_from_bytes(&mut a, &s).unwrap();
            assert_eq!(
                run_program(
                    &mut a,
                    &ChiaDialect::new(ClvmFlags::empty()),
                    p,
                    s,
                    clvm::DEFAULT_MAX_COST
                )
                .is_ok(),
                n <= 1024
            );
        }
    }
    let s = format!("DIM bytesOnly = 0x{}", "00".repeat(1025));
    run(&s).unwrap();
}
#[test]
fn signature_validation_is_eager_but_skipped_in_unselected_control_flow() {
    let k = format!("AS_PUBLICKEY(0x{})", key());
    let long = "00".repeat(1025);
    assert_eq!(
        run(&format!(
            "DIM c = AGG_SIG_ME({k},0x{long})\nc = AGG_SIG_ME({k},0x)"
        ))
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    let s = format!(
        "CONTRACT Demo()\nASSERT TRUE OR F()\nEND CONTRACT\nFUNCTION F() AS BOOLEAN\nDIM c = AGG_SIG_ME({k},0x{long})\nRETURN TRUE\nEND FUNCTION\n"
    );
    let p = compile("lazy.bas", s.as_bytes()).unwrap();
    clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    let p = compile("eager.bas", s.replace("TRUE OR", "FALSE OR").as_bytes()).unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    let slow = format!("UTF8(STRING_FROM_UTF8(0x{}))", "61".repeat(256));
    let p = compile(
        "order.bas",
        format!("CONTRACT Demo()\nDIM c = AGG_SIG_ME(AS_PUBLICKEY(0x),{slow})\nEND CONTRACT\n")
            .as_bytes(),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], 1500000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}
#[test]
fn invalid_keys_cannot_reach_signature_conditions() {
    let fixture: Value =
        serde_json::from_str(include_str!("../../../docs/spec/m3-publickey-cases.json")).unwrap();
    for c in fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["valid"] == false)
    {
        let body = format!(
            "DIM c = AGG_SIG_ME(AS_PUBLICKEY(0x{}),0x)",
            c["hex"].as_str().unwrap()
        );
        assert_eq!(run(&body).err().unwrap().code, "E0500", "{}", c["id"]);
    }
}
#[test]
fn signature_conditions_flow_through_functions_collections_and_exact_cost() {
    let s = format!(
        "CONTRACT Demo()\nDIM items AS LIST OF CONDITION = [Signature(AS_PUBLICKEY(0x{}),0x00ff)]\nEMIT FIRST(items)\nEMIT FIRST(items)\nEND CONTRACT\nFUNCTION Signature(owner AS PUBLICKEY,message AS BYTES) AS CONDITION\nRETURN AGG_SIG_ME(owner,message)\nEND FUNCTION\n",
        key()
    );
    let p = compile("function.bas", s.as_bytes()).unwrap();
    let r = clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    let one = format!("ff32ffb0{}ff8200ff80", key());
    assert_eq!(hex::encode(&r.bytes), format!("ff{one}ff{one}80"));
    clvm::execute(&p.puzzle, &[0x80], r.cost).unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], r.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    let text = s.replace(
        "RETURN AGG_SIG_ME(owner,message)",
        "RETURN AGG_SIG_ME(owner,message)\nRETURN AGG_SIG_ME(owner,1)",
    );
    assert_eq!(
        analyze("bad.bas", text.as_bytes()).unwrap_err().code,
        "E0202"
    );
}
#[test]
fn full_payment_example_matches_original_m0_condition_vector_without_signing() {
    let v: Value = serde_json::from_str(include_str!("../../../docs/spec/vectors.json")).unwrap();
    let t = compile_template(
        "payment.bas",
        include_bytes!("../../../examples/height-locked-payment.bas"),
    )
    .unwrap();
    let b = t
        .bind(include_bytes!(
            "../../../examples/height-locked-payment.bindings.json"
        ))
        .unwrap();
    let r = clvm::execute(&b.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(
        hex::encode(&r.bytes),
        v["payment"]["conditions_serialized_hex"]
    );
}
