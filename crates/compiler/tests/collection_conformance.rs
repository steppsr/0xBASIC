use oxbasic_compiler::{analyze, check, clvm, compile};
use serde_json::{Value, json};
fn list(items: impl IntoIterator<Item = Value>) -> Value {
    let items: Vec<_> = items.into_iter().collect();
    items
        .into_iter()
        .rev()
        .fold(json!({"atom":""}), |tail, head| json!({"pair":[head,tail]}))
}
fn expected(conditions: &Value) -> Value {
    list(conditions.as_array().unwrap().iter().map(|condition| list(condition.as_array().unwrap().iter().map(|n| {
        let n = n.as_i64().unwrap();
        json!({"atom": if n == 0 { String::new() } else { hex::encode(num_bigint::BigInt::from(n).to_signed_bytes_be()) }})
    }))))
}
fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn run(text: &str) -> clvm::Execution {
    let p = compile("conformance.bas", text.as_bytes()).unwrap();
    clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap()
}
#[test]
fn all_active_collection_fixtures_have_matching_analysis_and_execution() {
    let data: Value =
        serde_json::from_str(include_str!("../../../docs/spec/m2-collections-cases.json")).unwrap();
    let mut active = 0;
    for case in data["cases"].as_array().unwrap() {
        if !case["superseded_by"].is_null() {
            continue;
        }
        active += 1;
        let text = case["source"].as_str().unwrap();
        if case["check"] == "reject" {
            for error in [
                check("fixture.bas", text.as_bytes()).unwrap_err(),
                analyze("fixture.bas", text.as_bytes()).unwrap_err(),
            ] {
                assert_eq!(error.code, case["diagnostic"], "{}", case["id"]);
                assert!(error.span.is_some());
            }
        } else {
            analyze("fixture.bas", text.as_bytes()).unwrap();
            let p = compile("fixture.bas", text.as_bytes()).unwrap();
            let execution = clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST);
            if case["execution"]["diagnostic"].is_string() {
                assert_eq!(
                    execution.err().unwrap().code,
                    case["execution"]["diagnostic"],
                    "{}",
                    case["id"]
                );
            } else {
                assert_eq!(
                    execution.unwrap().tree,
                    expected(&case["execution"]["conditions"]),
                    "{}",
                    case["id"]
                );
            }
        }
    }
    assert_eq!(active, 31);
}
#[test]
fn original_m0_collection_cases_are_now_executable() {
    let data: Value =
        serde_json::from_str(include_str!("../../../docs/spec/source-cases.json")).unwrap();
    for id in ["short-circuit", "pair-and-list"] {
        let case = data["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == id)
            .unwrap();
        assert_eq!(case["accept"], true);
        let text = case["source"].as_str().unwrap();
        analyze("m0.bas", text.as_bytes()).unwrap();
        assert_eq!(run(text).tree, expected(&case["expected_conditions"]));
    }
    for id in ["empty-list-inference", "contract-return"] {
        let case = data["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == id)
            .unwrap();
        let text = case["source"].as_str().unwrap();
        assert_eq!(case["accept"], false);
        for error in [
            check("m0.bas", text.as_bytes()).unwrap_err(),
            analyze("m0.bas", text.as_bytes()).unwrap_err(),
        ] {
            assert_eq!(error.code, case["diagnostic"]);
        }
    }
}
#[test]
fn mixed_types_reach_the_depth_boundary_and_reject_unreachable_overflow() {
    let mut ty = "INTEGER".to_owned();
    let mut expr = "1".to_owned();
    for depth in 1..=33 {
        if depth % 2 == 0 {
            ty = format!("PAIR OF (BOOLEAN,{ty})");
            expr = format!("PAIR(FALSE,{expr})");
        } else {
            ty = format!("LIST OF {ty}");
            expr = format!("[{expr}]");
        }
        if depth == 32 {
            let text = source(&format!("DIM value AS {ty} = {expr}\n"));
            analyze("boundary.bas", text.as_bytes()).unwrap();
            assert_eq!(run(&text).bytes, vec![0x80]);
        }
    }
    for text in [
        source(&format!("DIM value AS {ty} = {expr}\n")),
        source(&format!("IF FALSE THEN\nDIM value = {expr}\nEND IF\n")),
    ] {
        assert_eq!(
            check("overflow.bas", text.as_bytes()).unwrap_err().code,
            "E0205"
        );
        assert_eq!(
            analyze("overflow.bas", text.as_bytes()).unwrap_err().code,
            "E0205"
        );
    }
}
#[test]
fn collection_snapshots_survive_nested_branch_updates_and_function_returns() {
    for (flag, height) in [("TRUE", 7), ("FALSE", 20)] {
        let text = format!(
            "{}FUNCTION Pick(flag AS BOOLEAN, xs AS LIST OF INTEGER) AS LIST OF PAIR OF (INTEGER, LIST OF INTEGER)\nDIM result = [PAIR(FIRST(xs),xs)]\nIF flag THEN\nIF TRUE THEN\nRETURN result\nEND IF\nELSE\nresult = [PAIR(FIRST(REST(xs)),[])]\nEND IF\nRETURN result\nEND FUNCTION\n",
            source(&format!(
                "CONST seed = [7,20]\nDIM xs = seed\nDIM saved = xs\nDIM result = Pick({flag},xs)\nxs = CONS(99,[])\nASSERT FIRST(saved) = 7\nASSERT LIST_LENGTH(seed) = 2\nEMIT ASSERT_HEIGHT_ABSOLUTE(FIRST(FIRST(result)))\n"
            ))
        );
        assert_eq!(run(&text).tree, expected(&json!([[83, height]])));
    }
}
#[test]
fn collection_example_is_deterministic_and_obeys_exact_execution_cost() {
    let text = include_str!("../../../examples/m2-collections.bas");
    let first = compile("one.bas", text.as_bytes()).unwrap();
    let changed = format!("' same source with BOM and CRLF\n{text}")
        .replace("\r\n", "\n")
        .replace('\n', "\r\n");
    let second = compile("two.bas", format!("\u{feff}{changed}").as_bytes()).unwrap();
    assert_eq!(first.puzzle, second.puzzle);
    assert_eq!(
        clvm::tree_hash(&first.puzzle).unwrap(),
        clvm::tree_hash(&second.puzzle).unwrap()
    );
    let execution = run(text);
    assert_eq!(
        execution.tree,
        expected(&json!([[83, 7], [83, 20], [83, 2]]))
    );
    clvm::execute(&first.puzzle, &[0x80], execution.cost).unwrap();
    assert_eq!(
        clvm::execute(&first.puzzle, &[0x80], execution.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}
