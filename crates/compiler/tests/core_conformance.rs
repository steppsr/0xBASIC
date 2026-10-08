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

fn m0() -> Value {
    serde_json::from_str(include_str!("../../../docs/spec/source-cases.json")).unwrap()
}
fn scope() -> Value {
    serde_json::from_str(include_str!("../../../docs/spec/m2-conformance-scope.json")).unwrap()
}
fn verify(case: &Value, original: bool) {
    let text = case["source"].as_str().unwrap();
    let accept = if original {
        case["accept"] == true
    } else {
        case["check"] == "accept"
    };
    if !accept {
        for error in [
            analyze("fixture.bas", text.as_bytes()).unwrap_err(),
            check("fixture.bas", text.as_bytes()).unwrap_err(),
            compile("fixture.bas", text.as_bytes()).err().unwrap(),
        ] {
            assert_eq!(
                error.code, case["diagnostic"],
                "{}: {}",
                case["id"], error.message
            );
            assert!(error.span.is_some(), "{}", case["id"]);
        }
        return;
    }
    analyze("fixture.bas", text.as_bytes()).unwrap();
    let program = compile("fixture.bas", text.as_bytes()).unwrap();
    let result = clvm::execute(&program.puzzle, &[0x80], clvm::DEFAULT_MAX_COST);
    if case["execution"]["diagnostic"].is_string() {
        assert_eq!(result.err().unwrap().code, case["execution"]["diagnostic"]);
    } else {
        let conditions = if original {
            &case["expected_conditions"]
        } else {
            &case["execution"]["conditions"]
        };
        assert_eq!(result.unwrap().tree, expected(conditions), "{}", case["id"]);
    }
}
#[test]
fn scope_accounts_for_every_original_case_without_silent_exclusions() {
    let original = m0();
    let audit = scope();
    let cases = original["cases"].as_array().unwrap();
    let entries = audit["m0"].as_array().unwrap();
    assert_eq!(cases.len(), entries.len());
    let mut ids = std::collections::BTreeSet::new();
    let mut deferred = 0;
    for entry in entries {
        let id = entry["id"].as_str().unwrap();
        assert!(ids.insert(id));
        assert!(cases.iter().any(|case| case["id"] == id));
        match entry["status"].as_str().unwrap() {
            "active" => assert!(entry["reason"].is_null()),
            "deferred" => {
                deferred += 1;
                assert!(!entry["reason"].as_str().unwrap().is_empty());
            }
            unknown => panic!("Unknown scope classification: {unknown}"),
        }
    }
    assert_eq!(deferred, 5);
}
#[test]
fn all_24_applicable_m0_cases_match_the_original_specification() {
    let original = m0();
    let audit = scope();
    let mut count = 0;
    for entry in audit["m0"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|e| e["status"] == "active")
    {
        let case = original["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == entry["id"])
            .unwrap();
        verify(case, true);
        count += 1;
    }
    assert_eq!(count, 24);
}
#[test]
fn all_14_m2_acceptance_cases_match_analysis_compilation_and_execution() {
    let data: Value =
        serde_json::from_str(include_str!("../../../docs/spec/m2-source-cases.json")).unwrap();
    let cases = data["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 14);
    for case in cases {
        verify(case, false);
    }
}
