use oxbasic_compiler::{abi, check, clvm, compile, compile_template};

fn source(ty: &str, fixed: bool, body: &str) -> String {
    if fixed {
        format!("CONTRACT Demo(value AS {ty})\n{body}END CONTRACT\n")
    } else {
        format!("CONTRACT Demo()\nSOLUTION value AS {ty}\n{body}END CONTRACT\n")
    }
}

#[test]
fn scalar_json_is_strict_duplicate_safe_and_normalized() {
    for fixed in [false, true] {
        for (ty, accepted, rejected) in [
            (
                "BOOLEAN",
                vec![
                    (r#"{"VALUE":true}"#, "ff0180"),
                    (r#"{"value":false}"#, "ff8080"),
                ],
                vec![
                    r#"{"value":1}"#,
                    r#"{"value":"true"}"#,
                    r#"{"value":null}"#,
                    r#"{"value":{"hex":"01"}}"#,
                ],
            ),
            (
                "BYTES",
                vec![
                    (r#"{"VALUE":{"hex":"00Af"}}"#, "ff8200af80"),
                    (r#"{"value":{"hex":""}}"#, "ff8080"),
                ],
                vec![
                    r#"{"value":"00"}"#,
                    r#"{"value":true}"#,
                    r#"{"value":{"hex":"0"}}"#,
                    r#"{"value":{"hex":"0x00"}}"#,
                    r#"{"value":{"hex":"gg"}}"#,
                    r#"{"value":{"hex":"00","hex":"01"}}"#,
                    r#"{"value":{"hex":"00","h\u0065x":"01"}}"#,
                    r#"{"value":{"HEX":"00"}}"#,
                    r#"{"value":{"hex":null}}"#,
                    r#"{"value":{"hex":"00","extra":""}}"#,
                    r#"{"value":{}}"#,
                    r#"{"value":[]}"#,
                ],
            ),
        ] {
            let c = check("scalar.bas", source(ty, fixed, "").as_bytes()).unwrap();
            let fields = if fixed { &c.fixed } else { &c.inputs };
            for (json, expected) in accepted {
                let encoded = abi::encode_bindings(fields, json.as_bytes()).unwrap();
                assert_eq!(hex::encode(&encoded.bytes), expected);
                let normalized = serde_json::to_vec(&encoded.normalized).unwrap();
                assert_eq!(
                    encoded.bytes,
                    abi::encode_solution(fields, &normalized).unwrap()
                );
                if ty == "BYTES" {
                    assert!(!String::from_utf8(normalized).unwrap().contains("Af"));
                }
            }
            for json in rejected.into_iter().chain([
                r#"{}"#,
                r#"{"value":true,"VALUE":false}"#,
                r#"{"value":true,"v\u0061lue":false}"#,
                r#"{"value":true,"extra":false}"#,
            ]) {
                let err = if fixed {
                    abi::encode_bindings(fields, json.as_bytes()).err().unwrap()
                } else {
                    abi::encode_solution(fields, json.as_bytes()).err().unwrap()
                };
                assert_eq!(
                    err.code,
                    if fixed { "E0301" } else { "E0300" },
                    "{ty}: {json}"
                );
            }
        }
    }
}

#[test]
fn unused_scalar_fields_are_guarded_for_raw_fixed_and_solution_routes() {
    use clvmr::{Allocator, ChiaDialect, ClvmFlags, run_program, serde::node_from_bytes};
    for ty in ["BOOLEAN", "BYTES"] {
        for fixed in [false, true] {
            let template = compile_template(
                "raw.bas",
                source(ty, fixed, "IF FALSE THEN\nASSERT FALSE\nEND IF\n").as_bytes(),
            )
            .unwrap();
            for (raw, boolean_ok, bytes_ok) in [
                ("ff8080", true, true),
                ("ff0180", true, true),
                ("ff0080", false, true),
                ("ff0280", false, true),
                ("ff81ff80", false, true),
                ("ff82000180", false, true),
                ("ffff018080", false, false),
                ("80", false, false),
                ("ff0102", false, false),
                ("ff01ff0180", false, false),
            ] {
                let raw = hex::decode(raw).unwrap();
                let (program, env) = if fixed {
                    (
                        clvm::bind_fixed(&template.template, &raw).unwrap(),
                        vec![0x80],
                    )
                } else {
                    (template.bind(b"{}").unwrap().puzzle, raw)
                };
                let expected = if ty == "BOOLEAN" {
                    boolean_ok
                } else {
                    bytes_ok
                };
                assert_eq!(
                    clvm::execute(&program, &env, clvm::DEFAULT_MAX_COST).is_ok(),
                    expected
                );
                let mut a = Allocator::new();
                let p = node_from_bytes(&mut a, &program).unwrap();
                let s = node_from_bytes(&mut a, &env).unwrap();
                assert_eq!(
                    run_program(
                        &mut a,
                        &ChiaDialect::new(ClvmFlags::empty()),
                        p,
                        s,
                        clvm::DEFAULT_MAX_COST
                    )
                    .is_ok(),
                    expected
                );
            }
        }
    }
}

#[test]
fn mixed_boundaries_flow_through_functions_branches_and_collections() {
    let source = include_bytes!("../../../examples/m3-scalar-boundaries.bas");
    let template = compile_template("mixed.bas", source).unwrap();
    let bound = template
        .bind(include_bytes!(
            "../../../examples/m3-scalar-boundaries.bindings.json"
        ))
        .unwrap();
    let solution = abi::encode_solution(
        &template.contract.inputs,
        include_bytes!("../../../examples/m3-scalar-boundaries.solution.json"),
    )
    .unwrap();
    let result = clvm::execute(&bound.puzzle, &solution, clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(hex::encode(&result.bytes), "ffff53ff678080"); // 100 + 3 preserved bytes
    assert!(clvm::execute(&bound.puzzle, &solution, result.cost).is_ok());
    assert_eq!(
        clvm::execute(&bound.puzzle, &solution, result.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    let changed = template
        .bind(br#"{"enabled":false,"prefix":{"hex":"00"},"base":"100"}"#)
        .unwrap();
    assert_ne!(changed.puzzle, bound.puzzle);
    assert_eq!(
        clvm::execute(&changed.puzzle, &solution, clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        vec![0x80]
    );
}

#[test]
fn new_boundary_types_remain_immutable_and_cannot_feed_constants() {
    for (ty, literal) in [("BOOLEAN", "TRUE"), ("BYTES", "0x00")] {
        for fixed in [false, true] {
            for (body, code) in [
                (format!("value = {literal}\n"), "E0203"),
                ("CONST copy = value\n".to_owned(), "E0205"),
                ("DIM VALUE = 1\n".to_owned(), "E0201"),
            ] {
                assert_eq!(
                    check("invalid.bas", source(ty, fixed, &body).as_bytes())
                        .unwrap_err()
                        .code,
                    code
                );
            }
        }
    }
    let text = source("BOOLEAN", false, "EMIT ASSERT_HEIGHT_ABSOLUTE(value)\n");
    assert_eq!(
        check("no-coercion.bas", text.as_bytes()).unwrap_err().code,
        "E0202"
    );
}

#[test]
fn host_limits_and_large_byte_values_preserve_runtime_semantics() {
    let text = source(
        "BYTES",
        false,
        "EMIT ASSERT_HEIGHT_ABSOLUTE(BYTE_LENGTH(value))\n",
    );
    let compiled = compile("large.bas", text.as_bytes()).unwrap();
    let json = format!(r#"{{"value":{{"hex":"{}"}}}}"#, "00ff".repeat(8192));
    let s = abi::encode_solution(&compiled.contract.inputs, json.as_bytes()).unwrap();
    assert!(clvm::execute(&compiled.puzzle, &s, clvm::DEFAULT_MAX_COST).is_ok());
    let too_large = vec![b' '; 1048577];
    assert_eq!(
        abi::encode_solution(&compiled.contract.inputs, &too_large)
            .unwrap_err()
            .code,
        "E0300"
    );
    let nested = format!(
        r#"{{"value":{{"hex":{}0{}}}}}"#,
        "[".repeat(1000),
        "]".repeat(1000)
    );
    assert!(abi::encode_solution(&compiled.contract.inputs, nested.as_bytes()).is_err());
}

#[test]
fn maximum_boolean_fields_do_not_duplicate_the_contract_body() {
    let fixed = (0..32)
        .map(|i| format!("f{i} AS BOOLEAN"))
        .collect::<Vec<_>>()
        .join(",");
    let inputs = (0..32)
        .map(|i| format!("SOLUTION s{i} AS BOOLEAN\n"))
        .collect::<String>();
    let text = format!("CONTRACT Demo({fixed})\n{inputs}END CONTRACT\n");
    let template = compile_template("limit.bas", text.as_bytes()).unwrap();
    assert!(template.template.len() < 100_000);
    let fixed: serde_json::Value = (0..32)
        .map(|i| (format!("f{i}"), serde_json::json!(i % 2 == 0)))
        .collect();
    let inputs: serde_json::Value = (0..32)
        .map(|i| (format!("s{i}"), serde_json::json!(i % 2 != 0)))
        .collect();
    let bound = template.bind(&serde_json::to_vec(&fixed).unwrap()).unwrap();
    let solution = abi::encode_solution(
        &template.contract.inputs,
        &serde_json::to_vec(&inputs).unwrap(),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&bound.puzzle, &solution, clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        vec![0x80]
    );
}
