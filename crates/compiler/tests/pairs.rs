use oxbasic_compiler::{analyze, check, clvm, compile};
fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn run(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("pairs.bas", source(body, functions).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}
#[test]
fn planned_pair_acceptance_cases_execute_or_reject() {
    let cases: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/m2-collections-cases.json")).unwrap();
    for c in cases["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["requires"] == "M2-7b2")
    {
        let text = c["source"].as_str().unwrap();
        if c["check"] == "reject" {
            assert_eq!(
                check("fixture.bas", text.as_bytes()).unwrap_err().code,
                c["diagnostic"]
            );
            assert_eq!(
                analyze("fixture.bas", text.as_bytes()).unwrap_err().code,
                c["diagnostic"]
            );
            continue;
        }
        analyze("fixture.bas", text.as_bytes()).unwrap();
        let p = compile("fixture.bas", text.as_bytes()).unwrap();
        let result = clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST);
        if c["execution"]["diagnostic"].is_string() {
            assert_eq!(result.err().unwrap().code, c["execution"]["diagnostic"]);
        } else {
            let mut body = String::new();
            for condition in c["execution"]["conditions"].as_array().unwrap() {
                body.push_str(&format!("EMIT ASSERT_HEIGHT_ABSOLUTE({})\n", condition[1]));
            }
            assert_eq!(
                result.unwrap().bytes,
                run(&body, "", clvm::DEFAULT_MAX_COST).unwrap().bytes
            );
        }
    }
}
#[test]
fn pair_types_arity_and_annotations_are_strict() {
    for (body, code) in [
        ("DIM p = PAIR()\n", "E0202"),
        ("DIM p = PAIR(1)\n", "E0202"),
        ("DIM p = PAIR(1,2,3)\n", "E0202"),
        ("DIM n = FIRST(1)\n", "E0202"),
        ("DIM n = REST(0x)\n", "E0202"),
        ("DIM n = FIRST()\n", "E0202"),
        (
            "DIM p AS PAIR OF (INTEGER, BYTES) = PAIR(TRUE,0x)\n",
            "E0202",
        ),
        ("DIM p = PAIR(1,0x)\np = PAIR(1,\"\")\n", "E0202"),
        ("ASSERT PAIR(1,2)\n", "E0202"),
        ("DIM p AS PAIR(INTEGER,INTEGER) = PAIR(1,2)\n", "E0100"),
        ("DIM p = PAIR\n", "E0100"),
        ("DIM FIRST = 1\n", "E0201"),
        ("IF FALSE THEN\nDIM p = FIRST(1)\nEND IF\n", "E0202"),
        ("CONST p = PAIR(1,2)\n", "E0205"),
    ] {
        let text = source(body, "");
        assert_eq!(
            check("bad.bas", text.as_bytes()).unwrap_err().code,
            code,
            "{body}"
        );
        assert_eq!(
            analyze("bad.bas", text.as_bytes()).unwrap_err().code,
            code,
            "{body}"
        );
    }
}
#[test]
fn nested_pair_returns_and_branch_merges_preserve_values() {
    let functions = "FUNCTION SelectPair(flag AS BOOLEAN) AS PAIR OF (INTEGER, PAIR OF (BOOLEAN, STRING))\nIF flag THEN\nRETURN PAIR(0,PAIR(FALSE,\"\"))\nEND IF\nRETURN PAIR(7,PAIR(TRUE,\"hi\"))\nEND FUNCTION\n";
    run("DIM p = SelectPair(TRUE)\nASSERT FIRST(p) = 0\nASSERT NOT FIRST(REST(p))\nIF TRUE THEN\np = SelectPair(FALSE)\nEND IF\nASSERT FIRST(p) = 7\nASSERT REST(REST(p)) = \"hi\"\n",functions,clvm::DEFAULT_MAX_COST).unwrap();
    let p = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-pairs.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        run(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(128)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}
#[test]
fn pair_operands_are_eager_once_and_in_source_order() {
    let functions = format!(
        "FUNCTION Fail() AS INTEGER\nASSERT FALSE\nRETURN 0\nEND FUNCTION\nFUNCTION Work() AS BYTES\nDIM b = 0x{}\nRETURN CONCAT(b,b)\nEND FUNCTION\n",
        "ff".repeat(8192)
    );
    assert_eq!(
        run("DIM p = PAIR(Fail(),Work())\n", &functions, 20000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_eq!(
        run("DIM p = PAIR(Work(),Fail())\n", &functions, 20000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    run("ASSERT TRUE OR FIRST(PAIR(Fail(),1)) = 0\nIF FALSE THEN\nDIM p = PAIR(Work(),Fail())\nEND IF\n",&functions,clvm::DEFAULT_MAX_COST).unwrap();
    let direct = compile(
        "direct.bas",
        source("DIM p = PAIR(Work(),1)\n", &functions).as_bytes(),
    )
    .unwrap();
    let named = compile(
        "named.bas",
        source("DIM b = Work()\nDIM p = PAIR(b,1)\n", &functions).as_bytes(),
    )
    .unwrap();
    assert_eq!(direct.puzzle, named.puzzle);
    let result = clvm::execute(&direct.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    clvm::execute(&direct.puzzle, &[0x80], result.cost).unwrap();
    assert_eq!(
        clvm::execute(&direct.puzzle, &[0x80], result.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}
#[test]
fn parsed_and_inferred_types_enforce_depth_size_and_module_budget() {
    let mut ty = "INTEGER".to_owned();
    let mut expr = "1".to_owned();
    for _ in 0..32 {
        ty = format!("PAIR OF (INTEGER,{ty})");
        expr = format!("PAIR(1,{expr})");
    }
    check(
        "depth.bas",
        source(&format!("DIM p AS {ty} = {expr}\n"), "").as_bytes(),
    )
    .unwrap();
    let bad = source(
        &format!("DIM p AS PAIR OF (INTEGER,{ty}) = PAIR(1,{expr})\n"),
        "",
    );
    assert_eq!(check("bad.bas", bad.as_bytes()).unwrap_err().code, "E0205");
    let mut body = "DIM p0 = 1\n".to_owned();
    for n in 1..=9 {
        body.push_str(&format!("DIM p{n} = PAIR(p{},p{})\n", n - 1, n - 1));
    }
    check("size.bas", source(&body, "").as_bytes()).unwrap();
    body.push_str("DIM p10 = PAIR(p9,p9)\n");
    assert_eq!(
        check("size.bas", source(&body, "").as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
    // Each p9 has 1023 nodes. Repeated independent constructions share one module budget.
    let mut body = "DIM p0 = 1\n".to_owned();
    for n in 1..=8 {
        body.push_str(&format!("DIM p{n} = PAIR(p{},p{})\n", n - 1, n - 1));
    }
    for n in 0..65 {
        body.push_str(&format!("DIM big{n} = PAIR(p8,p8)\n"));
    }
    let text = source(&body, "");
    assert_eq!(
        check("budget.bas", text.as_bytes()).unwrap_err().code,
        "E0205"
    );
    assert_eq!(
        analyze("budget.bas", text.as_bytes()).unwrap_err().code,
        "E0205"
    );
    let mut annotation = "INTEGER".to_owned();
    for _ in 0..7 {
        annotation = format!("PAIR OF ({annotation},{annotation})");
    }
    let functions: String = (0..40)
        .map(|i| format!("FUNCTION F{i}(p AS {annotation}) AS INTEGER\nRETURN 0\nEND FUNCTION\n"))
        .collect();
    let text = source("", &functions);
    assert_eq!(
        check("annotations.bas", text.as_bytes()).unwrap_err().code,
        "E0205"
    );
    assert_eq!(
        analyze("annotations.bas", text.as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
}
