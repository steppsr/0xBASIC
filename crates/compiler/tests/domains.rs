use oxbasic_compiler::{abi, analyze, check, clvm, compile, compile_template};
fn source(ty: &str, fixed: bool, body: &str) -> String {
    if fixed {
        format!("CONTRACT Demo(value AS {ty})\n{body}END CONTRACT\n")
    } else {
        format!("CONTRACT Demo()\nSOLUTION value AS {ty}\n{body}END CONTRACT\n")
    }
}
fn run(body: &str) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile(
        "domain.bas",
        format!("CONTRACT Demo()\n{body}END CONTRACT\n").as_bytes(),
    )?;
    clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
}
#[test]
fn domain_json_is_exact_and_normalized() {
    for fixed in [false, true] {
        for ty in ["AMOUNT", "PUZZLEHASH"] {
            let c = check("host.bas", source(ty, fixed, "").as_bytes()).unwrap();
            let fields = if fixed { &c.fixed } else { &c.inputs };
            let cases = if ty == "AMOUNT" {
                vec![
                    ("\"0\"".into(), Some("ff8080".into())),
                    (
                        "\"18446744073709551615\"".into(),
                        Some("ff8900ffffffffffffffff80".into()),
                    ),
                    ("\"-1\"".into(), None),
                    ("\"18446744073709551616\"".into(), None),
                    ("\"-0\"".into(), None),
                    ("\"01\"".into(), None),
                    ("\"+1\"".into(), None),
                    ("1".into(), None),
                ]
            } else {
                vec![
                    (
                        format!("{{\"hex\":\"{}\"}}", "Af".repeat(32)),
                        Some(format!("ffa0{}80", "af".repeat(32))),
                    ),
                    (
                        format!("{{\"hex\":\"{}\"}}", "00".repeat(32)),
                        Some(format!("ffa0{}80", "00".repeat(32))),
                    ),
                    (format!("{{\"hex\":\"{}\"}}", "00".repeat(31)), None),
                    (format!("{{\"hex\":\"{}\"}}", "00".repeat(33)), None),
                    ("{\"hex\":\"\",\"h\\u0065x\":\"\"}".into(), None),
                    ("\"00\"".into(), None),
                ]
            };
            for (value, expected) in cases {
                let json = format!("{{\"VALUE\":{value}}}");
                let encoded = abi::encode_bindings(fields, json.as_bytes());
                if let Some(expected) = expected {
                    let encoded = encoded.unwrap();
                    assert_eq!(hex::encode(&encoded.bytes), expected);
                    let normalized = serde_json::to_vec(&encoded.normalized).unwrap();
                    assert_eq!(
                        encoded.bytes,
                        abi::encode_solution(fields, &normalized).unwrap()
                    );
                    assert!(!String::from_utf8(normalized).unwrap().contains("Af"));
                } else {
                    assert_eq!(encoded.err().unwrap().code, "E0301");
                    assert_eq!(
                        abi::encode_solution(fields, json.as_bytes())
                            .err()
                            .unwrap()
                            .code,
                        "E0300"
                    );
                }
            }
        }
    }
}
#[test]
fn raw_unused_domains_are_checked_with_and_without_vm_flags() {
    use clvmr::{Allocator, ChiaDialect, ClvmFlags, run_program, serde::node_from_bytes};
    for fixed in [false, true] {
        for ty in ["AMOUNT", "PUZZLEHASH"] {
            let t = compile_template("raw.bas", source(ty, fixed, "").as_bytes()).unwrap();
            let cases = if ty == "AMOUNT" {
                vec![
                    ("ff8080".into(), true),
                    ("ff7f80".into(), true),
                    ("ff82008080".into(), true),
                    ("ff8900ffffffffffffffff80".into(), true),
                    ("ff0080".into(), false),
                    ("ff82000180".into(), false),
                    ("ff81ff80".into(), false),
                    ("ff8901000000000000000080".into(), false),
                ]
            } else {
                vec![
                    (format!("ffa0{}80", "00".repeat(32)), true),
                    (format!("ffa0{}80", "ff".repeat(32)), true),
                    (format!("ff9f{}80", "00".repeat(31)), false),
                    (format!("ffa1{}80", "00".repeat(33)), false),
                    ("ff8080".into(), false),
                ]
            };
            for (raw, valid) in cases.into_iter().chain([
                ("ffff018080".into(), false),
                ("80".into(), false),
                ("ff0102".into(), false),
            ]) {
                let raw = hex::decode(raw).unwrap();
                let (p, s) = if fixed {
                    (clvm::bind_fixed(&t.template, &raw).unwrap(), vec![0x80])
                } else {
                    (t.bind(b"{}").unwrap().puzzle, raw)
                };
                assert_eq!(
                    clvm::execute(&p, &s, clvm::DEFAULT_MAX_COST).is_ok(),
                    valid,
                    "{ty}"
                );
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
                    valid
                );
            }
        }
    }
}
#[test]
fn explicit_conversions_roundtrip_and_fail_eagerly() {
    for n in [0u64, 1, 127, 128, u64::MAX / 2, u64::MAX] {
        run(&format!("DIM a AS AMOUNT = AS_AMOUNT({n})\nASSERT AMOUNT_VALUE(a) = {n}\nASSERT a = AS_AMOUNT({n})\n")).unwrap();
    }
    for bytes in ["00".repeat(32), "ff".repeat(32)] {
        run(&format!(
            "DIM h AS PUZZLEHASH = AS_PUZZLEHASH(0x{bytes})\nASSERT HASH_BYTES(h) = 0x{bytes}\n"
        ))
        .unwrap();
    }
    for bad in [
        "AS_AMOUNT(-1)",
        "AS_AMOUNT(18446744073709551616)",
        "AS_PUZZLEHASH(0x)",
        "AS_PUZZLEHASH(0x00)",
    ] {
        assert_eq!(
            run(&format!("DIM unused = {bad}\n")).err().unwrap().code,
            "E0500"
        );
        run(&format!("IF FALSE THEN\nDIM unused = {bad}\nEND IF\n")).unwrap();
    }
    assert_eq!(
        run("DIM a = AS_AMOUNT(-1)\na = AS_AMOUNT(0)\n")
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}
#[test]
fn domain_types_never_convert_implicitly() {
    for body in [
        "DIM a AS AMOUNT = 1",
        "DIM h AS PUZZLEHASH = 0x",
        "DIM a = AS_AMOUNT(TRUE)",
        "DIM h = AS_PUZZLEHASH(1)",
        "DIM n = AMOUNT_VALUE(1)",
        "DIM b = HASH_BYTES(0x)",
        "DIM a = AS_AMOUNT()",
        "DIM h = AS_PUZZLEHASH(0x,0x)",
        "DIM b = AS_AMOUNT(1) = 1",
        "DIM b = AS_AMOUNT(1) < AS_AMOUNT(2)",
        "DIM n = AS_AMOUNT(1) + AS_AMOUNT(2)",
        "DIM b = HASH_BYTES(AS_PUZZLEHASH(SHA256(0x))) = AS_PUZZLEHASH(SHA256(0x))",
    ] {
        let s = format!("CONTRACT Demo()\n{body}\nEND CONTRACT\n");
        assert_eq!(
            analyze("type.bas", s.as_bytes()).err().unwrap().code,
            "E0202",
            "{body}"
        );
        assert_eq!(
            check("type.bas", s.as_bytes()).err().unwrap().code,
            "E0202",
            "{body}"
        );
    }
    for (ty, expr) in [
        ("AMOUNT", "AS_AMOUNT(0)"),
        ("PUZZLEHASH", "AS_PUZZLEHASH(SHA256(0x))"),
    ] {
        assert_eq!(
            run(&format!("CONST a = {expr}\n")).err().unwrap().code,
            "E0205"
        );
        for fixed in [false, true] {
            for (body, code) in [
                (format!("value = {expr}\n"), "E0203"),
                ("CONST copied = value\n".into(), "E0205"),
            ] {
                assert_eq!(
                    check("immutable.bas", source(ty, fixed, &body).as_bytes())
                        .err()
                        .unwrap()
                        .code,
                    code
                );
            }
        }
    }
}
#[test]
fn domains_flow_through_collections_functions_and_cost_limits() {
    let t = compile_template(
        "example.bas",
        include_bytes!("../../../examples/m3-domain-boundaries.bas"),
    )
    .unwrap();
    let p = t
        .bind(include_bytes!(
            "../../../examples/m3-domain-boundaries.bindings.json"
        ))
        .unwrap();
    let s = abi::encode_solution(
        &t.contract.inputs,
        include_bytes!("../../../examples/m3-domain-boundaries.solution.json"),
    )
    .unwrap();
    let result = clvm::execute(&p.puzzle, &s, clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(hex::encode(&result.bytes), "ffff53ff648080");
    clvm::execute(&p.puzzle, &s, result.cost).unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &s, result.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    let mut hostile = s.clone();
    // Final list element is canonical zero; atom 00 must fail even though unread.
    let index = hostile.len() - 3;
    assert_eq!(hostile[index], 0x80);
    hostile[index] = 0;
    assert!(clvm::execute(&p.puzzle, &hostile, clvm::DEFAULT_MAX_COST).is_err());
}
#[test]
fn domain_schemas_remain_strict() {
    for ty in ["AMOUNT", "PUZZLEHASH"] {
        let good = format!(r#"{{"kind":"{ty}"}}"#);
        let schema: abi::SchemaType = serde_json::from_str(&good).unwrap();
        assert_eq!(serde_json::to_string(&schema).unwrap(), good);
        for bad in [
            format!(r#"{{"kind":"{ty}","kind":"BYTES"}}"#),
            format!(r#"{{"kind":"{ty}","element":{{"kind":"INTEGER"}}}}"#),
        ] {
            assert!(serde_json::from_str::<abi::SchemaType>(&bad).is_err());
        }
    }
}
