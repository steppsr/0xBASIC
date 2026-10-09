use oxbasic_compiler::{abi, analyze, check, clvm, compile};
fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn execute(text: &str, solution: &[u8]) -> oxbasic_compiler::Result<clvm::Execution> {
    let program = compile("inputs.bas", text.as_bytes())?;
    clvm::execute(&program.puzzle, solution, clvm::DEFAULT_MAX_COST)
}
#[test]
fn solution_declaration_is_case_insensitive_and_replaces_input() {
    for keyword in ["SOLUTION", "solution", "SoLuTiOn"] {
        let text = source(&format!(
            "{keyword} height AS INTEGER\nEMIT ASSERT_HEIGHT_ABSOLUTE(height)\n"
        ));
        assert_eq!(
            hex::encode(execute(&text, &[0xff, 100, 0x80]).unwrap().bytes),
            "ffff53ff648080"
        );
    }
    for keyword in ["INPUT", "input", "InPuT"] {
        let text = source(&format!("{keyword} height AS INTEGER\n"));
        assert!(check("old-keyword.bas", text.as_bytes()).is_err());
        assert!(analyze("old-keyword.bas", text.as_bytes()).is_err());
    }
    // The former keyword is now an ordinary identifier.
    execute(
        &source("DIM input = 100\nEMIT ASSERT_HEIGHT_ABSOLUTE(input)\n"),
        &[0x80],
    )
    .unwrap();
    assert!(check("reserved.bas", source("DIM solution = 1\n").as_bytes()).is_err());
}
#[test]
fn planned_input_cases_execute_or_reject_at_the_correct_boundary() {
    let cases: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/m3-boundary-cases.json")).unwrap();
    for c in cases["cases"].as_array().unwrap() {
        let text = c["source"].as_str().unwrap();
        if c["route"] == "source" {
            assert_eq!(
                check("source.bas", text.as_bytes()).unwrap_err().code,
                c["diagnostic"],
                "{}",
                c["id"]
            );
            assert_eq!(
                analyze("source.bas", text.as_bytes()).unwrap_err().code,
                c["diagnostic"]
            );
            continue;
        }
        let checked = check("source.bas", text.as_bytes()).unwrap();
        let solution = if c["route"] == "raw-solution" {
            Ok(hex::decode(c["solution_hex"].as_str().unwrap()).unwrap())
        } else {
            abi::encode_solution(
                &checked.inputs,
                c["solution_json_text"].as_str().unwrap().as_bytes(),
            )
        };
        let result = solution.and_then(|s| execute(text, &s));
        if c["execution"]["diagnostic"].is_string() {
            assert_eq!(
                result.err().unwrap().code,
                c["execution"]["diagnostic"],
                "{}",
                c["id"]
            );
        } else {
            let expected = if c["id"] == "declaration-order" {
                "ffff53ff078080"
            } else {
                "80"
            };
            assert_eq!(hex::encode(result.unwrap().bytes), expected, "{}", c["id"]);
        }
    }
    let original: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/source-cases.json")).unwrap();
    for id in ["input-shape", "condition-input"] {
        let c = original["cases"]
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["id"] == id)
            .unwrap();
        let text = c["source"].as_str().unwrap();
        if id == "condition-input" {
            assert_eq!(check("m0.bas", text.as_bytes()).unwrap_err().code, "E0205");
        } else {
            let checked = check("m0.bas", text.as_bytes()).unwrap();
            let solution = abi::encode_solution(
                &checked.inputs,
                &serde_json::to_vec(&c["solution"]).unwrap(),
            )
            .unwrap();
            assert_eq!(execute(text, &solution).unwrap().bytes, vec![0x80]);
        }
    }
}
#[test]
fn inputs_are_immutable_scoped_and_explicitly_limited() {
    for (body, code) in [
        ("SOLUTION n AS INTEGER\nDIM N = 1\n", "E0201"),
        ("SOLUTION demo AS INTEGER\n", "E0201"),
        (
            "SOLUTION n AS INTEGER\nIF TRUE THEN\nn = 2\nEND IF\n",
            "E0203",
        ),
        ("SOLUTION n AS DOUBLE\n", "E0205"),
        (
            "SOLUTION n AS PAIR OF (INTEGER,LIST OF CONDITION)\n",
            "E0205",
        ),
    ] {
        let t = source(body);
        assert_eq!(check("bad.bas", t.as_bytes()).unwrap_err().code, code);
    }
    for function in [
        "FUNCTION F() AS INTEGER\nRETURN n\nEND FUNCTION\n",
        "FUNCTION F() AS INTEGER\nSOLUTION n AS INTEGER\nRETURN n\nEND FUNCTION\n",
    ] {
        let text = format!("{}{function}", source("SOLUTION n AS INTEGER\n"));
        assert!(check("scope.bas", text.as_bytes()).is_err());
    }
    let mut body = String::new();
    for i in 0..32 {
        body.push_str(&format!("SOLUTION n{i} AS INTEGER\n"));
    }
    let text = source(&body);
    let checked = check("limit.bas", text.as_bytes()).unwrap();
    let json: serde_json::Value = (0..32)
        .map(|i| (format!("n{i}"), serde_json::json!(i.to_string())))
        .collect();
    let solution =
        abi::encode_solution(&checked.inputs, &serde_json::to_vec(&json).unwrap()).unwrap();
    execute(&text, &solution).unwrap();
    body.push_str("SOLUTION overflow AS INTEGER\n");
    assert_eq!(
        check("limit.bas", source(&body).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
}
#[test]
fn field_slots_survive_functions_branches_and_local_updates() {
    let text = format!(
        "{}FUNCTION Difference(a AS INTEGER,b AS INTEGER) AS INTEGER\nRETURN a-b\nEND FUNCTION\n",
        source(
            "SOLUTION first AS INTEGER\nSOLUTION second AS INTEGER\nDIM saved = first\nDIM n = Difference(first,second)\nIF second > 0 THEN\nn = n + 1\nELSE\nn = 0\nEND IF\nASSERT saved = first\nEMIT ASSERT_HEIGHT_ABSOLUTE(n)\nEMIT ASSERT_HEIGHT_ABSOLUTE(second)\n"
        )
    );
    // FIRST is reserved; use ordinary identifiers in the fixture.
    let text = text
        .replace("first", "leftvalue")
        .replace("second", "rightvalue");
    let c = check("flow.bas", text.as_bytes()).unwrap();
    let bytes = abi::encode_solution(&c.inputs, br#"{"RIGHTVALUE":"2","leftvalue":"9"}"#).unwrap();
    let p = compile("flow.bas", text.as_bytes()).unwrap();
    let result = execute(&text, &bytes).unwrap();
    assert_eq!(hex::encode(result.bytes), "ffff53ff0880ffff53ff028080");
    clvm::execute(&p.puzzle, &bytes, result.cost).unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &bytes, result.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}
#[test]
fn raw_guards_do_not_depend_on_canonical_integer_flags() {
    use clvmr::{Allocator, ChiaDialect, ClvmFlags, run_program, serde::node_from_bytes};
    let p = compile(
        "unused.bas",
        source("SOLUTION n AS INTEGER\nASSERT TRUE\n").as_bytes(),
    )
    .unwrap();
    for (hex, valid) in [
        ("ff8080", true),
        ("ff81ff80", true),
        ("ff82008080", true),
        ("ff0080", false),
        ("ff82000180", false),
        ("ff82ffff80", false),
        ("ffff018080", false),
        ("ff0102", false),
        ("ff01ff0280", false),
        ("80", false),
    ] {
        let mut a = Allocator::new();
        let program = node_from_bytes(&mut a, &p.puzzle).unwrap();
        let env = node_from_bytes(&mut a, &hex::decode(hex).unwrap()).unwrap();
        assert_eq!(
            run_program(
                &mut a,
                &ChiaDialect::new(ClvmFlags::empty()),
                program,
                env,
                clvm::DEFAULT_MAX_COST
            )
            .is_ok(),
            valid,
            "{hex}"
        );
    }
    let work = vec!["9".repeat(500); 8].join(" * ");
    let busy = compile(
        "busy.bas",
        source(&format!("SOLUTION n AS INTEGER\nDIM work = {work}\n")).as_bytes(),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&busy.puzzle, &hex::decode("ff0080").unwrap(), 10000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_eq!(
        clvm::execute(&busy.puzzle, &hex::decode("ff0180").unwrap(), 10000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    // A malformed fixed list also fails when invoking the template directly.
    assert!(
        clvm::execute(
            &p.template,
            &hex::decode("ffff0180ff0180").unwrap(),
            clvm::DEFAULT_MAX_COST
        )
        .is_err()
    );
}
#[test]
fn original_integer_vectors_match_host_and_generated_validation() {
    let v: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/vectors.json")).unwrap();
    let text = source("SOLUTION n AS INTEGER\n");
    let checked = check("vectors.bas", text.as_bytes()).unwrap();
    for integer in v["integers"].as_array().unwrap() {
        let json = serde_json::json!({"n":integer["decimal"]});
        let solution =
            abi::encode_solution(&checked.inputs, &serde_json::to_vec(&json).unwrap()).unwrap();
        let expected = format!("ff{}80", integer["serialized_hex"].as_str().unwrap());
        assert_eq!(hex::encode(&solution), expected);
        execute(&text, &solution).unwrap();
    }
    for atom in v["noncanonical_integer_atoms"].as_array().unwrap() {
        // Each vector stores raw atom contents.
        let encoded = atom.as_str().unwrap();
        let mut a = clvmr::Allocator::new();
        let n = a.new_atom(&hex::decode(encoded).unwrap()).unwrap();
        let list = a.new_pair(n, clvmr::NodePtr::NIL).unwrap();
        let solution = clvmr::serde::node_to_bytes(&a, list).unwrap();
        assert_eq!(execute(&text, &solution).err().unwrap().code, "E0500");
    }
}
#[test]
fn json_conversion_preserves_large_values_and_rejects_wrong_shapes() {
    let c = check("json.bas", source("SOLUTION n AS INTEGER\n").as_bytes()).unwrap();
    for text in [
        r#"{"n":"+1"}"#,
        r#"{"n":"01"}"#,
        r#"{"n":"--1"}"#,
        r#"{"n":true}"#,
        r#"{"n":{}}"#,
        r#"{"n":[]}"#,
        r#"{"n":"1.0"}"#,
        r#"{"n":" 1"}"#,
        r#"{"n":"1"} {}"#,
    ] {
        assert_eq!(
            abi::encode_solution(&c.inputs, text.as_bytes())
                .unwrap_err()
                .code,
            "E0300"
        );
    }
    let large = "9".repeat(5000);
    let text = format!(r#"{{"n":"{large}"}}"#);
    let value = abi::encode_solution(&c.inputs, text.as_bytes()).unwrap();
    execute(&source("SOLUTION n AS INTEGER\n"), &value).unwrap();
    assert_eq!(
        abi::encode_solution(&c.inputs, &vec![b' '; 1048577])
            .unwrap_err()
            .code,
        "E0300"
    );
    assert_eq!(abi::encode_solution(&[], b"{}").unwrap(), vec![0x80]);
}
