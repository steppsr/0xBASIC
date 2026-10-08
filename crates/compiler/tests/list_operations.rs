use oxbasic_compiler::{analyze, check, clvm, compile};
fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn run(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("lists.bas", source(body, functions).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}
#[test]
fn planned_list_operation_cases_execute() {
    let cases: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/m2-collections-cases.json")).unwrap();
    for c in cases["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["requires"] == "M2-7b4")
    {
        let text = c["source"].as_str().unwrap();
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
fn nested_values_context_and_function_returns_keep_exact_types() {
    let functions = "FUNCTION Add(xs AS LIST OF INTEGER) AS LIST OF INTEGER\nRETURN CONS(7,xs)\nEND FUNCTION\nFUNCTION Nested() AS LIST OF LIST OF INTEGER\nIF TRUE THEN\nRETURN CONS([],[])\nEND IF\nRETURN []\nEND FUNCTION\n";
    run("DIM xs = Add([])\nASSERT FIRST(xs) = 7\nASSERT LIST_LENGTH(REST(xs)) = 0\nASSERT LIST_LENGTH(Nested()) = 1\nASSERT LIST_LENGTH(FIRST(Nested())) = 0\nDIM bs = CONS(0x0001, [0xff])\nASSERT FIRST(bs) = 0x0001\nASSERT FIRST(REST(bs)) = 0xff\nDIM ps = [PAIR(1,\"a\"),PAIR(2,\"b\")]\nASSERT REST(FIRST(ps)) = \"a\"\nDIM cs = [ASSERT_HEIGHT_ABSOLUTE(5)]\nEMIT FIRST(cs)\nDIM p = PAIR(1,2)\nASSERT FIRST(p) = 1\nASSERT REST(p) = 2\n",functions,clvm::DEFAULT_MAX_COST).unwrap();
    let p = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-list-operations.bas"),
    )
    .unwrap();
    assert_eq!(clvm::execute(&p.puzzle,&[0x80],clvm::DEFAULT_MAX_COST).unwrap().bytes,run("EMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(20)\nEMIT ASSERT_HEIGHT_ABSOLUTE(3)\n","",clvm::DEFAULT_MAX_COST).unwrap().bytes);
}
#[test]
fn arity_invariance_and_constant_rules_are_shared() {
    for (body, code) in [
        ("DIM xs = CONS()\n", "E0202"),
        ("DIM xs = CONS(1)\n", "E0202"),
        ("DIM xs = CONS(1,[],[])\n", "E0202"),
        ("DIM xs = CONS(1,TRUE)\n", "E0202"),
        ("DIM xs = CONS(1,[TRUE])\n", "E0202"),
        ("DIM xs AS LIST OF BOOLEAN = CONS(1,[])\n", "E0202"),
        ("DIM xs = CONS([],[[]])\n", "E0202"),
        ("DIM n = LIST_LENGTH()\n", "E0202"),
        ("DIM n = LIST_LENGTH([1],[2])\n", "E0202"),
        ("DIM n = LIST_LENGTH(PAIR(1,2))\n", "E0202"),
        ("DIM n = FIRST([])\n", "E0202"),
        ("DIM n = LIST_LENGTH([])\n", "E0202"),
        ("CONST n = LIST_LENGTH([1])\n", "E0205"),
        ("CONST b = TRUE OR FIRST([1]) = 1\n", "E0205"),
        ("DIM CONS = 1\n", "E0201"),
        ("DIM n = LIST_LENGTH\n", "E0100"),
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
fn empty_access_and_argument_evaluation_preserve_failures_and_order() {
    for op in ["FIRST", "REST"] {
        assert_eq!(
            run(
                &format!("DIM xs AS LIST OF INTEGER = []\nDIM unused = {op}(xs)\n"),
                "",
                clvm::DEFAULT_MAX_COST
            )
            .err()
            .unwrap()
            .code,
            "E0500"
        );
    }
    let functions = format!(
        "FUNCTION Fail() AS BYTES\nASSERT FALSE\nRETURN 0x\nEND FUNCTION\nFUNCTION Work() AS LIST OF BYTES\nDIM b = 0x{}\nRETURN [CONCAT(b,b)]\nEND FUNCTION\n",
        "ff".repeat(8192)
    );
    assert_eq!(
        run("DIM xs = CONS(Fail(),Work())\n", &functions, 20000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_eq!(
        run("DIM xs = CONS(FIRST(Work()),[Fail()])\n", &functions, 20000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    assert_eq!(
        run(
            "DIM n = LIST_LENGTH([Fail()])\n",
            &functions,
            clvm::DEFAULT_MAX_COST
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    run("DIM xs AS LIST OF INTEGER = []\nASSERT TRUE OR FIRST(xs) = 0\nIF FALSE THEN\nDIM tail = REST(xs)\nEND IF\n",&functions,clvm::DEFAULT_MAX_COST).unwrap();
    let direct = compile(
        "direct.bas",
        source("DIM n = LIST_LENGTH(Work())\n", &functions).as_bytes(),
    )
    .unwrap();
    let named = compile(
        "named.bas",
        source("DIM xs = Work()\nDIM n = LIST_LENGTH(xs)\n", &functions).as_bytes(),
    )
    .unwrap();
    assert_eq!(direct.puzzle, named.puzzle);
}
#[test]
fn length_scales_with_elements_and_respects_exact_cost_budget() {
    let mut costs = Vec::new();
    for n in [0, 1, 16, 32, 64, 256] {
        let body = format!(
            "DIM xs AS LIST OF INTEGER = [{}]\nASSERT LIST_LENGTH(xs) = {n}\n",
            vec!["1"; n].join(",")
        );
        let result = run(&body, "", clvm::DEFAULT_MAX_COST).unwrap();
        run(&body, "", result.cost).unwrap();
        assert_eq!(run(&body, "", result.cost - 1).err().unwrap().code, "E0501");
        costs.push(result.cost);
    }
    assert!(costs[4] - costs[3] < 3 * (costs[3] - costs[2]));
    // Compact source grows a runtime list through function calls, not literal width.
    let mut body = "DIM xs AS LIST OF INTEGER = []\n".to_owned();
    for _ in 0..128 {
        body.push_str("xs = CONS(1,xs)\n");
    }
    body.push_str("DIM n = LIST_LENGTH(xs)\n");
    assert_eq!(run(&body, "", 10000).err().unwrap().code, "E0501");
}
