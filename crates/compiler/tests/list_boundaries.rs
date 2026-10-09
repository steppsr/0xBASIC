use oxbasic_compiler::{abi, check, clvm, compile_template};
fn source(ty: &str, fixed: bool, body: &str) -> String {
    if fixed {
        format!("CONTRACT Demo(value AS {ty})\n{body}END CONTRACT\n")
    } else {
        format!("CONTRACT Demo()\nSOLUTION value AS {ty}\n{body}END CONTRACT\n")
    }
}
#[test]
fn list_json_conversion_is_recursive_strict_and_duplicate_safe() {
    let cases: serde_json::Value = serde_json::from_str(include_str!(
        "../../../docs/spec/m3-list-boundary-cases.json"
    ))
    .unwrap();
    for fixed in [false, true] {
        let t = compile_template(
            "list.bas",
            source(cases["type"].as_str().unwrap(), fixed, "").as_bytes(),
        )
        .unwrap();
        let fields = if fixed {
            &t.contract.fixed
        } else {
            &t.contract.inputs
        };
        for c in cases["cases"].as_array().unwrap() {
            let json = c["json"].as_str().unwrap().as_bytes();
            let result = abi::encode_bindings(fields, json);
            if !c["valid"].as_bool().unwrap() {
                assert_eq!(result.err().unwrap().code, "E0301");
                assert_eq!(
                    abi::encode_solution(fields, json).unwrap_err().code,
                    "E0300"
                );
                continue;
            }
            let encoded = result.unwrap();
            let normalized = serde_json::to_vec(&encoded.normalized).unwrap();
            assert_eq!(
                encoded.bytes,
                abi::encode_solution(fields, &normalized).unwrap()
            );
            if c["id"] == "mixed" {
                assert_eq!(hex::encode(&encoded.bytes), "ffffff018200afffff80808080");
            }
            let (p, s) = if fixed {
                (t.bind(json).unwrap().puzzle, vec![0x80])
            } else {
                (t.bind(b"{}").unwrap().puzzle, encoded.bytes)
            };
            assert_eq!(
                clvm::execute(&p, &s, clvm::DEFAULT_MAX_COST).unwrap().bytes,
                vec![0x80]
            );
        }
    }
}
#[test]
fn raw_lists_check_every_element_and_tail_even_when_unused() {
    use clvmr::{Allocator, ChiaDialect, ClvmFlags, run_program, serde::node_from_bytes};
    for fixed in [false, true] {
        let t = compile_template(
            "raw.bas",
            source(
                "LIST OF BOOLEAN",
                fixed,
                "IF FALSE THEN\nASSERT FALSE\nEND IF\n",
            )
            .as_bytes(),
        )
        .unwrap();
        for (raw, valid) in [
            ("ff8080", true),
            ("ffff01ff808080", true),
            ("ff0180", false),
            ("ffff028080", false),
            ("ffff01ff028080", false),
            ("ffff01ff008080", false),
            ("ffff01ff8200018080", false),
            ("ffffff01808080", false),
            ("ffff010180", false),
            ("ffff010080", false),
            ("80", false),
            ("ff80ff8080", false),
        ] {
            let raw = hex::decode(raw).unwrap();
            let (p, s) = if fixed {
                (clvm::bind_fixed(&t.template, &raw).unwrap(), vec![0x80])
            } else {
                (t.bind(b"{}").unwrap().puzzle, raw)
            };
            let result = clvm::execute(&p, &s, clvm::DEFAULT_MAX_COST);
            assert_eq!(result.is_ok(), valid);
            if !valid {
                assert_eq!(result.err().unwrap().code, "E0500");
            }
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
#[test]
fn lists_and_pairs_mix_through_functions_and_nested_validators() {
    let t = compile_template(
        "example.bas",
        include_bytes!("../../../examples/m3-list-boundaries.bas"),
    )
    .unwrap();
    let b = t
        .bind(include_bytes!(
            "../../../examples/m3-list-boundaries.bindings.json"
        ))
        .unwrap();
    let s = abi::encode_solution(
        &t.contract.inputs,
        include_bytes!("../../../examples/m3-list-boundaries.solution.json"),
    )
    .unwrap();
    assert_eq!(
        hex::encode(
            clvm::execute(&b.puzzle, &s, clvm::DEFAULT_MAX_COST)
                .unwrap()
                .bytes
        ),
        "ffff53ff688080"
    );
    let t = compile_template(
        "nested.bas",
        source(
            "PAIR OF (LIST OF INTEGER, LIST OF LIST OF STRING)",
            false,
            "",
        )
        .as_bytes(),
    )
    .unwrap();
    let json = br#"{"value":{"first":["0","-1"],"rest":[[],["\u0000","\ud83e\udd80"]]}}"#;
    let mut raw = abi::encode_solution(&t.contract.inputs, json).unwrap();
    let p = t.bind(b"{}").unwrap().puzzle;
    clvm::execute(&p, &raw, clvm::DEFAULT_MAX_COST).unwrap();
    let index = raw.iter().position(|b| *b == 0xf0).unwrap();
    raw[index] = 0xff;
    assert_eq!(
        clvm::execute(&p, &raw, clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}
#[test]
fn host_node_budget_is_shared_and_does_not_become_a_runtime_rule() {
    let t = compile_template("budget.bas", source("LIST OF BYTES", false, "").as_bytes()).unwrap();
    let json = |n: usize| {
        serde_json::to_vec(&serde_json::json!({"value":vec![serde_json::json!({"hex":""});n]}))
            .unwrap()
    };
    let accepted = abi::encode_solution(&t.contract.inputs, &json(32766)).unwrap();
    assert!(!accepted.is_empty());
    assert_eq!(
        abi::encode_solution(&t.contract.inputs, &json(32767))
            .unwrap_err()
            .code,
        "E0300"
    );
    // 65537 visited tree nodes: valid on-chain shape, beyond the host conversion budget.
    let mut raw = vec![0xff];
    for _ in 0..32767 {
        raw.extend([0xff, 0x80]);
    }
    raw.extend([0x80, 0x80]);
    clvm::execute(&t.bind(b"{}").unwrap().puzzle, &raw, 100_000_000).unwrap();
    let t=compile_template("shared.bas",b"CONTRACT Demo()\nSOLUTION left AS LIST OF BYTES\nSOLUTION right AS LIST OF BYTES\nEND CONTRACT\n").unwrap();
    for (n, valid) in [(16382, true), (16383, false)] {
        let json=serde_json::to_vec(&serde_json::json!({"left":vec![serde_json::json!({"hex":""});16383],"right":vec![serde_json::json!({"hex":""});n]})).unwrap();
        assert_eq!(
            abi::encode_solution(&t.contract.inputs, &json).is_ok(),
            valid
        );
    }
}
#[test]
fn list_validation_cost_scales_and_nested_codegen_does_not_duplicate_loops() {
    let t = compile_template("cost.bas", source("LIST OF BOOLEAN", false, "").as_bytes()).unwrap();
    let p = t.bind(b"{}").unwrap().puzzle;
    let mut costs = Vec::new();
    for n in [0, 16, 32] {
        let s = abi::encode_solution(
            &t.contract.inputs,
            &serde_json::to_vec(&serde_json::json!({"value":vec![true;n]})).unwrap(),
        )
        .unwrap();
        let r = clvm::execute(&p, &s, clvm::DEFAULT_MAX_COST).unwrap();
        clvm::execute(&p, &s, r.cost).unwrap();
        assert_eq!(
            clvm::execute(&p, &s, r.cost - 1).err().unwrap().code,
            "E0501"
        );
        costs.push(r.cost);
    }
    assert!(costs[0] < costs[1] && costs[1] < costs[2] && costs[2] < costs[1] * 3);
    let mut ty = "BOOLEAN".to_owned();
    let mut v = serde_json::json!(true);
    for _ in 0..32 {
        ty = format!("LIST OF {ty}");
        v = serde_json::json!([v]);
    }
    let t = compile_template("depth.bas", source(&ty, false, "").as_bytes()).unwrap();
    assert!(t.template.len() < 100_000);
    let imported: Vec<abi::Field> =
        abi::decode_json(&serde_json::to_vec(&t.contract.inputs).unwrap()).unwrap();
    abi::validate_fields(&imported).unwrap();
    let too_deep = serde_json::json!([{"name":"value","type":{"kind":"LIST","element":serde_json::to_value(&imported[0].value_type).unwrap()}}]);
    let imported: Vec<abi::Field> =
        abi::decode_json(&serde_json::to_vec(&too_deep).unwrap()).unwrap();
    assert!(abi::validate_fields(&imported).is_err());

    let s = abi::encode_solution(
        &t.contract.inputs,
        &serde_json::to_vec(&serde_json::json!({"value":v})).unwrap(),
    )
    .unwrap();
    clvm::execute(&t.bind(b"{}").unwrap().puzzle, &s, clvm::DEFAULT_MAX_COST).unwrap();
    assert!(
        check(
            "depth.bas",
            source(&format!("LIST OF {ty}"), false, "").as_bytes()
        )
        .is_err()
    );
}
#[test]
fn list_schemas_and_scope_keep_strict_recursive_rules() {
    for json in [
        r#"{"kind":"LIST"}"#,
        r#"{"kind":"LIST","element":null}"#,
        r#"{"kind":"LIST","element":{"kind":"BOOLEAN"},"element":{"kind":"INTEGER"}}"#,
        r#"{"kind":"LIST","element":{"kind":"BOOLEAN"},"first":{"kind":"INTEGER"}}"#,
        r#"{"kind":"INTEGER","element":{"kind":"INTEGER"}}"#,
        r#"{"kind":"LIST","element":{"kind":"PAIR","first":{"kind":"INTEGER"},"rest":{"kind":"CONDITION"}}}"#,
    ] {
        assert!(abi::decode_json::<abi::SchemaType>(json.as_bytes()).is_err());
    }
    for fixed in [false, true] {
        for (body, code) in [
            ("value = [1]\n", "E0203"),
            ("CONST copy = value\n", "E0205"),
            ("DIM VALUE = 1\n", "E0201"),
        ] {
            assert_eq!(
                check(
                    "scope.bas",
                    source("LIST OF INTEGER", fixed, body).as_bytes()
                )
                .unwrap_err()
                .code,
                code
            );
        }
        let error = check(
            "forbidden.bas",
            source("LIST OF PAIR OF (INTEGER, CONDITION)", fixed, "").as_bytes(),
        )
        .unwrap_err();
        assert_eq!(error.code, "E0205");
        assert!(error.message.contains("CONDITION"));
    }
}
