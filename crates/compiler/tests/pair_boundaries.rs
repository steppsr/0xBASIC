use oxbasic_compiler::{abi, check, clvm, compile_template};
fn source(ty: &str, fixed: bool, body: &str) -> String {
    if fixed {
        format!("CONTRACT Demo(value AS {ty})\n{body}END CONTRACT\n")
    } else {
        format!("CONTRACT Demo()\nSOLUTION value AS {ty}\n{body}END CONTRACT\n")
    }
}
#[test]
fn recursive_json_has_strict_members_types_and_normalization() {
    let cases: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/m3-pair-cases.json")).unwrap();
    for fixed in [false, true] {
        let t = compile_template(
            "pairs.bas",
            source(cases["type"].as_str().unwrap(), fixed, "").as_bytes(),
        )
        .unwrap();
        for c in cases["cases"].as_array().unwrap() {
            let fields = if fixed {
                &t.contract.fixed
            } else {
                &t.contract.inputs
            };
            let json = c["json"].as_str().unwrap().as_bytes();
            let result = abi::encode_bindings(fields, json);
            if !c["valid"].as_bool().unwrap() {
                assert_eq!(result.err().unwrap().code, "E0301", "{}", c["id"]);
                assert_eq!(
                    abi::encode_solution(fields, json).unwrap_err().code,
                    "E0300"
                );
                continue;
            }
            let encoded = result.unwrap();
            let normalized = serde_json::to_vec(&encoded.normalized).unwrap();
            assert_eq!(
                abi::encode_solution(fields, &normalized).unwrap(),
                encoded.bytes
            );
            if c["id"] == "valid" {
                assert_eq!(hex::encode(&encoded.bytes), "ffff01ff008200af80");
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
fn raw_pairs_validate_both_children_before_unused_body_under_all_flags() {
    use clvmr::{Allocator, ChiaDialect, ClvmFlags, run_program, serde::node_from_bytes};
    for fixed in [false, true] {
        let t = compile_template(
            "raw.bas",
            source(
                "PAIR OF (INTEGER, PAIR OF (BOOLEAN, STRING))",
                fixed,
                "IF FALSE THEN\nASSERT FALSE\nEND IF\n",
            )
            .as_bytes(),
        )
        .unwrap();
        // S/F contains one dotted pair (7 . (true . "a")).
        for (raw, valid) in [
            ("ffff07ff016180", true),
            ("ffff80ff808080", true),
            ("ffff00ff016180", false),
            ("ffff07ff026180", false),
            ("ffff07ff0181ff80", false),
            ("ff0780", false),
            ("ffff078080", false),
            ("ffff07ff01ff618080", false),
            ("80", false),
            ("ffff07ff016101", false),
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
fn pairs_flow_through_functions_and_bindings_keep_distinct_identities() {
    let t = compile_template(
        "example.bas",
        include_bytes!("../../../examples/m3-pair-boundaries.bas"),
    )
    .unwrap();
    let b = t
        .bind(include_bytes!(
            "../../../examples/m3-pair-boundaries.bindings.json"
        ))
        .unwrap();
    let s = abi::encode_solution(
        &t.contract.inputs,
        include_bytes!("../../../examples/m3-pair-boundaries.solution.json"),
    )
    .unwrap();
    let result = clvm::execute(&b.puzzle, &s, clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(hex::encode(result.bytes), "ffff53ff688080");
    assert!(clvm::execute(&b.puzzle, &s, result.cost).is_ok());
    assert_eq!(
        clvm::execute(&b.puzzle, &s, result.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    let other = t
        .bind(br#"{"CONFIG":{"rest":false,"first":"100"}}"#)
        .unwrap();
    assert_ne!(b.puzzle, other.puzzle);
    assert_eq!(
        clvm::execute(&other.puzzle, &s, clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        vec![0x80]
    );
}
#[test]
fn pair_schema_depth_size_and_json_recursion_are_bounded() {
    fn leaf() -> serde_json::Value {
        serde_json::json!({"kind":"INTEGER"})
    }
    fn pair(a: serde_json::Value, b: serde_json::Value) -> serde_json::Value {
        serde_json::json!({"kind":"PAIR","first":a,"rest":b})
    }
    let mut ty = "INTEGER".to_owned();
    let mut schema = leaf();
    let mut value = serde_json::json!("7");
    for _ in 0..32 {
        ty = format!("PAIR OF (INTEGER,{ty})");
        schema = pair(leaf(), schema);
        value = serde_json::json!({"first":"0","rest":value});
    }
    let t = compile_template("depth.bas", source(&ty, false, "").as_bytes()).unwrap();
    let fields: Vec<abi::Field> = abi::decode_json(
        &serde_json::to_vec(&serde_json::json!([{"name":"value","type":schema}])).unwrap(),
    )
    .unwrap();
    abi::validate_fields(&fields).unwrap();
    let raw = abi::encode_solution(
        &fields,
        &serde_json::to_vec(&serde_json::json!({"value":value})).unwrap(),
    )
    .unwrap();
    clvm::execute(&t.bind(b"{}").unwrap().puzzle, &raw, clvm::DEFAULT_MAX_COST).unwrap();
    let bad = pair(leaf(), serde_json::to_value(&fields[0].value_type).unwrap());
    let fields: Vec<abi::Field> = abi::decode_json(
        &serde_json::to_vec(&serde_json::json!([{"name":"value","type":bad}])).unwrap(),
    )
    .unwrap();
    assert!(abi::validate_fields(&fields).is_err());
    assert!(
        check(
            "too-deep.bas",
            source(&format!("PAIR OF (INTEGER,{ty})"), false, "").as_bytes()
        )
        .is_err()
    );
    let mut wide = leaf();
    for _ in 0..9 {
        wide = pair(wide.clone(), wide);
    }
    for (schema, valid) in [(wide.clone(), true), (pair(leaf(), wide), false)] {
        let fields: Vec<abi::Field> = abi::decode_json(
            &serde_json::to_vec(&serde_json::json!([{"name":"value","type":schema}])).unwrap(),
        )
        .unwrap();
        assert_eq!(abi::validate_fields(&fields).is_ok(), valid);
    }
    for (depth, valid) in [(96, true), (97, false)] {
        let json = format!("{}0{}", "[".repeat(depth), "]".repeat(depth));
        assert_eq!(
            abi::decode_json::<serde_json::Value>(json.as_bytes()).is_ok(),
            valid
        );
    }
    let quoted = serde_json::to_vec(&"[\\\"".repeat(100)).unwrap();
    assert!(abi::decode_json::<String>(&quoted).is_ok());
}
#[test]
fn imported_pair_schemas_reject_missing_duplicate_and_irrelevant_members() {
    for json in [
        r#"{"kind":"PAIR","first":{"kind":"INTEGER"}}"#,
        r#"{"kind":"PAIR","first":null,"rest":{"kind":"INTEGER"}}"#,
        r#"{"kind":"INTEGER","first":null}"#,
        r#"{"kind":"INTEGER","first":{"kind":"INTEGER"}}"#,
        r#"{"kind":"PAIR","first":{"kind":"INTEGER"},"first":{"kind":"BYTES"},"rest":{"kind":"INTEGER"}}"#,
        r#"{"kind":"PAIR","first":{"kind":"CONDITION"},"rest":{"kind":"INTEGER"}}"#,
        r#"{"kind":"INTEGER","kind":"BYTES"}"#,
    ] {
        assert!(
            abi::decode_json::<abi::SchemaType>(json.as_bytes()).is_err(),
            "{json}"
        );
    }
}
#[test]
fn pair_fields_remain_immutable_and_nested_condition_is_forbidden() {
    for fixed in [false, true] {
        for (body, code) in [
            ("value = PAIR(1,TRUE)\n", "E0203"),
            ("CONST copy = value\n", "E0205"),
            ("DIM VALUE = 1\n", "E0201"),
            ("DIM n AS INTEGER = value\n", "E0202"),
        ] {
            assert_eq!(
                check(
                    "bad.bas",
                    source("PAIR OF (INTEGER,BOOLEAN)", fixed, body).as_bytes()
                )
                .unwrap_err()
                .code,
                code
            );
        }
        let error = check(
            "condition.bas",
            source("PAIR OF (INTEGER,PAIR OF (BYTES,CONDITION))", fixed, "").as_bytes(),
        )
        .unwrap_err();
        assert_eq!(error.code, "E0205");
        assert!(error.message.contains("CONDITION"));
        assert!(
            check(
                "list.bas",
                source("PAIR OF (INTEGER,DOUBLE)", fixed, "").as_bytes()
            )
            .is_err()
        );
    }
}
