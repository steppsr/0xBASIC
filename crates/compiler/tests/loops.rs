use oxbasic_compiler::{
    check, clvm,
    explain::{self, Stage},
};

#[test]
fn public_loop_compilation_preserves_cross_platform_goldens() {
    let cases: Vec<serde_json::Value> =
        serde_json::from_str(include_str!("../src/clvm/for_next_golden.json")).unwrap();
    for case in cases {
        let source = case["source"].as_str().unwrap();
        let program = clvm::generate(&check("loops.bas", source.as_bytes()).unwrap()).unwrap();
        assert_eq!(clvm::sha256(&program), case["sha256"]);
        assert_eq!(clvm::tree_hash(&program).unwrap(), case["tree_hash"]);
        let env = hex::decode(case["env_hex"].as_str().unwrap()).unwrap();
        let result = clvm::execute(&program, &env, case["cost"].as_u64().unwrap()).unwrap();
        assert_eq!(hex::encode(result.bytes), case["result_hex"]);
        assert_eq!(result.cost, case["cost"]);
    }
}

#[test]
fn public_simple_loop_contracts_always_receive_semantic_checks() {
    for (body, code) in [
        ("FOR i = TRUE TO 2\nNEXT i", "E0202"),
        ("FOR i = 1 TO 2\ni = 3\nNEXT i", "E0203"),
        ("FOR i = 1 TO 2\nNEXT i\nASSERT i = 3", "E0200"),
        ("IF FALSE THEN\nFOR i = TRUE TO 2\nNEXT i\nEND IF", "E0202"),
        ("DIM step = 1", "E0201"),
    ] {
        let source = format!("CONTRACT Demo()\n{body}\nEND CONTRACT");
        assert_eq!(
            check("loops.bas", source.as_bytes()).unwrap_err().code,
            code
        );
    }
    let source = b"CONTRACT Demo()\nFOR i = TRUE TO 2\nNEXT i\nEND CONTRACT";
    explain::explain("loops.bas", source, Stage::Ast).unwrap();
    assert_eq!(
        explain::explain("loops.bas", source, Stage::Ir)
            .unwrap_err()
            .code,
        "E0202"
    );
}

#[test]
fn aggregate_value_guard_includes_statements_after_the_last_loop() {
    let body = "ASSERT i + 1 > 0\n".repeat(20);
    let loops = format!("FOR i = 1 TO 1\n{body}NEXT i\n").repeat(30);
    let tail = "ASSERT 1 + 1 > 0\n".repeat(200);
    let source = format!("CONTRACT Demo()\n{loops}{tail}END CONTRACT");
    assert_eq!(
        check("loops.bas", source.as_bytes()).unwrap_err().code,
        "E0205"
    );
}
