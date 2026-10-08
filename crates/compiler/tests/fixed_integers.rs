use oxbasic_compiler::{abi, analyze, check, clvm, compile, compile_template};
fn source(parameters: &str, body: &str) -> String {
    format!("CONTRACT Demo({parameters})\n{body}END CONTRACT\n")
}
#[test]
fn template_compilation_and_binding_have_distinct_requirements_and_identities() {
    let text = source("height AS INTEGER", "EMIT ASSERT_HEIGHT_ABSOLUTE(height)\n");
    analyze("fixed.bas", text.as_bytes()).unwrap();
    check("fixed.bas", text.as_bytes()).unwrap();
    assert_eq!(
        compile("fixed.bas", text.as_bytes()).err().unwrap().code,
        "E0301"
    );
    let t = compile_template("fixed.bas", text.as_bytes()).unwrap();
    let a = t.bind(br#"{"HEIGHT":"7"}"#).unwrap();
    let b = t.bind(br#"{"height":"8"}"#).unwrap();
    assert_ne!(
        clvm::tree_hash(&a.puzzle).unwrap(),
        clvm::tree_hash(&b.puzzle).unwrap()
    );
    assert_eq!(a.puzzle, t.bind(br#"{"height":"7"}"#).unwrap().puzzle);
    assert_eq!(
        serde_json::to_string(&a.bindings).unwrap(),
        r#"{"height":"7"}"#
    );
    assert_eq!(
        hex::encode(
            clvm::execute(&a.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
                .unwrap()
                .bytes
        ),
        "ffff53ff078080"
    );
    let vector: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/vectors.json")).unwrap();
    let v = &vector["binding"];
    assert_eq!(
        hex::encode(
            clvm::bind_fixed(
                &hex::decode(v["template_hex"].as_str().unwrap()).unwrap(),
                &hex::decode(v["fixed_values_hex"].as_str().unwrap()).unwrap()
            )
            .unwrap()
        ),
        v["bound_program_hex"]
    );
}
#[test]
fn fixed_names_are_immutable_isolated_and_not_constants() {
    for (parameters, body, code) in [
        ("n AS INTEGER", "n = 2\n", "E0203"),
        ("n AS INTEGER", "IF TRUE THEN\nn = 2\nEND IF\n", "E0203"),
        ("n AS INTEGER,N AS INTEGER", "", "E0201"),
        ("n AS INTEGER", "INPUT N AS INTEGER\n", "E0201"),
        ("demo AS INTEGER", "", "E0201"),
        ("n AS INTEGER", "DIM N = 3\n", "E0201"),
        ("n AS INTEGER", "CONST x = n\n", "E0205"),
        ("n AS LIST OF CONDITION", "", "E0205"),
        ("n AS BOOLEAN", "", "E0205"),
    ] {
        let text = source(parameters, body);
        for e in [
            check("bad.bas", text.as_bytes()).unwrap_err(),
            analyze("bad.bas", text.as_bytes()).unwrap_err(),
        ] {
            assert_eq!(e.code, code);
            assert!(e.span.is_some());
        }
    }
    let text = format!(
        "{}FUNCTION F() AS INTEGER\nRETURN n\nEND FUNCTION\n",
        source("n AS INTEGER", "")
    );
    assert_eq!(
        check("scope.bas", text.as_bytes()).unwrap_err().code,
        "E0200"
    );
    let original: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/source-cases.json")).unwrap();
    let c = original["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == "immutable-binding")
        .unwrap();
    assert_eq!(
        check("m0.bas", c["source"].as_str().unwrap().as_bytes())
            .unwrap_err()
            .code,
        c["diagnostic"]
    );
}
#[test]
fn fixed_and_input_slots_keep_order_through_functions_and_branches() {
    let text = format!(
        "{}FUNCTION Sum(a AS INTEGER,b AS INTEGER) AS INTEGER\nRETURN a+b\nEND FUNCTION\n",
        source(
            "base AS INTEGER, step AS INTEGER",
            "INPUT offset AS INTEGER\nINPUT flag AS INTEGER\nDIM saved = base\nDIM n = Sum(base,offset)\nIF flag = 1 THEN\nn = n + step\nELSE\nn = 0\nEND IF\nASSERT saved = base\nEMIT ASSERT_HEIGHT_ABSOLUTE(n)\nEMIT ASSERT_HEIGHT_ABSOLUTE(offset)\n"
        )
    );
    let t = compile_template("slots.bas", text.as_bytes()).unwrap();
    let b = t.bind(br#"{"STEP":"2","BASE":"100"}"#).unwrap();
    let s = abi::encode_solution(&t.contract.inputs, br#"{"flag":"1","OFFSET":"7"}"#).unwrap();
    assert_eq!(
        serde_json::to_string(&b.bindings).unwrap(),
        r#"{"base":"100","step":"2"}"#
    );
    let execution = clvm::execute(&b.puzzle, &s, clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(hex::encode(&execution.bytes), "ffff53ff6d80ffff53ff078080");
    clvm::execute(&b.puzzle, &s, execution.cost).unwrap();
    assert_eq!(
        clvm::execute(&b.puzzle, &s, execution.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    assert!(
        clvm::execute(
            &b.puzzle,
            &hex::decode("ff64ff07ff0180").unwrap(),
            clvm::DEFAULT_MAX_COST
        )
        .is_err()
    );
}
#[test]
fn malformed_unused_fixed_values_fail_before_body_without_runner_flags() {
    use clvmr::{Allocator, ChiaDialect, ClvmFlags, run_program, serde::node_from_bytes};
    let t = compile_template(
        "unused.bas",
        source("n AS INTEGER", "INPUT value AS INTEGER\n").as_bytes(),
    )
    .unwrap();
    for raw in [
        "80",
        "ff0080",
        "ff82000180",
        "ff82ffff80",
        "ffff018080",
        "ff0102",
        "ff01ff0280",
    ] {
        let puzzle = clvm::bind_fixed(&t.template, &hex::decode(raw).unwrap()).unwrap();
        let mut a = Allocator::new();
        let p = node_from_bytes(&mut a, &puzzle).unwrap();
        let s = node_from_bytes(&mut a, &hex::decode("ff0180").unwrap()).unwrap();
        assert!(
            run_program(
                &mut a,
                &ChiaDialect::new(ClvmFlags::empty()),
                p,
                s,
                clvm::DEFAULT_MAX_COST
            )
            .is_err(),
            "{raw}"
        );
    }
    let work = vec!["9".repeat(500); 8].join(" * ");
    let t = compile_template(
        "work.bas",
        source("n AS INTEGER", &format!("DIM work = {work}\n")).as_bytes(),
    )
    .unwrap();
    let bad = clvm::bind_fixed(&t.template, &hex::decode("ff0080").unwrap()).unwrap();
    assert_eq!(
        clvm::execute(&bad, &[0x80], 10000).err().unwrap().code,
        "E0500"
    );
    assert_eq!(
        clvm::execute(&t.bind(br#"{"n":"1"}"#).unwrap().puzzle, &[0x80], 10000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}
#[test]
fn binding_json_and_combined_field_limits_are_bounded() {
    let t = compile_template("json.bas", source("n AS INTEGER", "").as_bytes()).unwrap();
    for json in [
        r#"{}"#,
        r#"{"n":1}"#,
        r#"{"n":"+1"}"#,
        r#"{"n":"-0"}"#,
        r#"{"n":"01"}"#,
        r#"{"n":"1","N":"2"}"#,
        r#"{"n":"1","\u006e":"2"}"#,
        r#"{"n":"1","extra":"2"}"#,
    ] {
        assert_eq!(t.bind(json.as_bytes()).err().unwrap().code, "E0301");
    }
    let fixed = (0..32)
        .map(|i| format!("f{i} AS INTEGER"))
        .collect::<Vec<_>>()
        .join(",");
    let mut body = (0..32)
        .map(|i| format!("INPUT s{i} AS INTEGER\n"))
        .collect::<String>();
    body.push_str("EMIT ASSERT_HEIGHT_ABSOLUTE(f0+f31+s0+s31)\n");
    let t = compile_template("max.bas", source(&fixed, &body).as_bytes()).unwrap();
    let f: serde_json::Value = (0..32)
        .map(|i| (format!("f{i}"), serde_json::json!(i.to_string())))
        .collect();
    let s: serde_json::Value = (0..32)
        .map(|i| (format!("s{i}"), serde_json::json!(i.to_string())))
        .collect();
    let b = t.bind(&serde_json::to_vec(&f).unwrap()).unwrap();
    let solution =
        abi::encode_solution(&t.contract.inputs, &serde_json::to_vec(&s).unwrap()).unwrap();
    assert_eq!(
        hex::encode(
            clvm::execute(&b.puzzle, &solution, clvm::DEFAULT_MAX_COST)
                .unwrap()
                .bytes
        ),
        "ffff53ff3e8080"
    );
    assert_eq!(
        check(
            "limit.bas",
            source(&format!("{fixed},overflow AS INTEGER"), "").as_bytes()
        )
        .unwrap_err()
        .code,
        "E0205"
    );
    let large = format!(r#"{{"n":"{}"}}"#, "9".repeat(5000));
    let b = compile_template("big.bas", source("n AS INTEGER", "").as_bytes())
        .unwrap()
        .bind(large.as_bytes())
        .unwrap();
    clvm::execute(&b.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
}
