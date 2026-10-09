use oxbasic_compiler::{abi, check, clvm, compile, compile_template};

fn source(fixed: bool, body: &str) -> String {
    if fixed {
        format!("CONTRACT Demo(value AS STRING)\n{body}END CONTRACT\n")
    } else {
        format!("CONTRACT Demo()\nSOLUTION value AS STRING\n{body}END CONTRACT\n")
    }
}
fn raw_list(bytes: &[u8]) -> Vec<u8> {
    let mut a = clvmr::Allocator::new();
    let atom = a.new_atom(bytes).unwrap();
    let list = a.new_pair(atom, clvmr::NodePtr::NIL).unwrap();
    clvmr::serde::node_to_bytes(&a, list).unwrap()
}

#[test]
fn json_strings_preserve_unicode_scalars_and_reject_invalid_encodings() {
    for fixed in [false, true] {
        let c = check("text.bas", source(fixed, "").as_bytes()).unwrap();
        let fields = if fixed { &c.fixed } else { &c.inputs };
        for text in [
            "",
            "\0",
            "\u{feff}",
            "\u{ffff}",
            "\u{10ffff}",
            "é",
            "e\u{301}",
            "\0🦀",
        ] {
            let json = serde_json::to_vec(&serde_json::json!({"VALUE":text})).unwrap();
            let encoded = abi::encode_bindings(fields, &json).unwrap();
            assert_eq!(encoded.bytes, raw_list(text.as_bytes()));
            assert_eq!(
                serde_json::to_value(encoded.normalized).unwrap(),
                serde_json::json!({"value":text})
            );
        }
        for json in [
            r#"{"value":"\ud800"}"#,
            r#"{"value":"\udc00"}"#,
            r#"{"value":"\ud800x"}"#,
            r#"{"value":null}"#,
            r#"{"value":1}"#,
            r#"{"value":false}"#,
            r#"{"value":{"hex":"61"}}"#,
            r#"{"value":"a","VALUE":"b"}"#,
            r#"{"value":"a","v\u0061lue":"b"}"#,
            r#"{"value":[]}"#,
        ] {
            let code = if fixed {
                abi::encode_bindings(fields, json.as_bytes())
                    .err()
                    .unwrap()
                    .code
            } else {
                abi::encode_solution(fields, json.as_bytes())
                    .unwrap_err()
                    .code
            };
            assert_eq!(code, if fixed { "E0301" } else { "E0300" });
        }
        assert!(abi::encode_solution(fields, b"{\"value\":\"\xff\"}").is_err());
        assert_eq!(
            abi::encode_solution(fields, br#"{"value":"\ud83e\udd80"}"#).unwrap(),
            raw_list("🦀".as_bytes())
        );
    }
}

#[test]
fn generated_string_guards_check_unused_raw_values_with_and_without_flags() {
    use clvmr::{Allocator, ChiaDialect, ClvmFlags, run_program, serde::node_from_bytes};
    let cases: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/m3-string-cases.json")).unwrap();
    for fixed in [false, true] {
        let template = compile_template(
            "text.bas",
            source(fixed, "IF FALSE THEN\nASSERT FALSE\nEND IF\n").as_bytes(),
        )
        .unwrap();
        let mut values = Vec::new();
        for case in cases["cases"].as_array().unwrap() {
            let bytes = hex::decode(case["hex"].as_str().unwrap()).unwrap();
            let valid = case["valid"].as_bool().unwrap();
            assert_eq!(std::str::from_utf8(&bytes).is_ok(), valid);
            values.push((raw_list(&bytes), valid));
        }
        for raw in ["ffff018080", "80", "ff6101", "ff61ff6280"] {
            values.push((hex::decode(raw).unwrap(), false));
        }
        for (raw, valid) in values {
            let (program, env) = if fixed {
                (
                    clvm::bind_fixed(&template.template, &raw).unwrap(),
                    vec![0x80],
                )
            } else {
                (template.bind(b"{}").unwrap().puzzle, raw)
            };
            let result = clvm::execute(&program, &env, clvm::DEFAULT_MAX_COST);
            assert_eq!(result.is_ok(), valid);
            if !valid {
                assert_eq!(result.err().unwrap().code, "E0500");
            }
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
                valid
            );
        }
    }
}

#[test]
fn strings_flow_through_functions_collections_and_keep_normalization_forms_distinct() {
    let t = compile_template(
        "example.bas",
        include_bytes!("../../../examples/m3-string-boundaries.bas"),
    )
    .unwrap();
    let p = t
        .bind(include_bytes!(
            "../../../examples/m3-string-boundaries.bindings.json"
        ))
        .unwrap();
    let s = abi::encode_solution(
        &t.contract.inputs,
        include_bytes!("../../../examples/m3-string-boundaries.solution.json"),
    )
    .unwrap();
    let result = clvm::execute(&p.puzzle, &s, clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(hex::encode(result.bytes), "ffff53ff6b8080");
    let a = t.bind(br#"{"prefix":"\u00e9","base":"100"}"#).unwrap();
    let equivalent = t
        .bind("{\"prefix\":\"é\",\"base\":\"100\"}".as_bytes())
        .unwrap();
    let decomposed = t.bind(br#"{"prefix":"e\u0301","base":"100"}"#).unwrap();
    assert_eq!(a.puzzle, equivalent.puzzle);
    assert_ne!(a.puzzle, decomposed.puzzle);
}

#[test]
fn string_boundaries_remain_immutable_typed_and_not_constants() {
    for fixed in [false, true] {
        for (body, code) in [
            ("value = \"x\"\n", "E0203"),
            ("CONST copy = value\n", "E0205"),
            ("DIM VALUE = 1\n", "E0201"),
            ("DIM blob AS BYTES = value\n", "E0202"),
        ] {
            assert_eq!(
                check("bad.bas", source(fixed, body).as_bytes())
                    .unwrap_err()
                    .code,
                code
            );
        }
    }
}

#[test]
fn validation_cost_and_maximum_string_field_counts_are_bounded() {
    let p = compile("cost.bas", source(false, "").as_bytes()).unwrap();
    let mut costs = Vec::new();
    for text in ["".to_owned(), "a".repeat(16), "a".repeat(32)] {
        let raw = raw_list(text.as_bytes());
        let result = clvm::execute(&p.puzzle, &raw, clvm::DEFAULT_MAX_COST).unwrap();
        assert!(clvm::execute(&p.puzzle, &raw, result.cost).is_ok());
        assert_eq!(
            clvm::execute(&p.puzzle, &raw, result.cost - 1)
                .err()
                .unwrap()
                .code,
            "E0501"
        );
        costs.push(result.cost);
    }
    assert!(costs[0] < costs[1] && costs[1] < costs[2] && costs[2] < costs[1] * 3);
    let fixed = (0..32)
        .map(|i| format!("f{i} AS STRING"))
        .collect::<Vec<_>>()
        .join(",");
    let fields = (0..32)
        .map(|i| format!("SOLUTION s{i} AS STRING\n"))
        .collect::<String>();
    let t = compile_template(
        "max.bas",
        format!("CONTRACT Demo({fixed})\n{fields}END CONTRACT\n").as_bytes(),
    )
    .unwrap();
    assert!(t.template.len() < clvm::MAX_PROGRAM_BYTES);
    let f: serde_json::Value = (0..32)
        .map(|i| (format!("f{i}"), serde_json::json!("")))
        .collect();
    let s: serde_json::Value = (0..32)
        .map(|i| (format!("s{i}"), serde_json::json!("\0")))
        .collect();
    let bound = t.bind(&serde_json::to_vec(&f).unwrap()).unwrap();
    let raw = abi::encode_solution(&t.contract.inputs, &serde_json::to_vec(&s).unwrap()).unwrap();
    clvm::execute(&bound.puzzle, &raw, clvm::DEFAULT_MAX_COST).unwrap();
    assert!(abi::encode_solution(&t.contract.inputs, &vec![b' '; 1048577]).is_err());
}
