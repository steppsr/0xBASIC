use oxbasic_compiler::{analyze, check, clvm, compile};
fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn run(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("lists.bas", source(body, functions).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}
// Test-only observation of a checked local's CLVM tree. Source EMIT still rejects lists.
fn observe(body: &str, functions: &str) -> Vec<u8> {
    let mut c = check("observe.bas", source(body, functions).as_bytes()).unwrap();
    let id = c.locals.last().unwrap().value;
    c.emissions.push(oxbasic_compiler::syntax::HeightEmission {
        condition: id,
        values_before: c.values.len(),
        span: c.span,
        spread: false,
    });
    let p = clvm::generate(&c).unwrap();
    clvm::execute(&p, &[0xff, 0x80, 0x80], clvm::DEFAULT_MAX_COST)
        .unwrap()
        .bytes
}
#[test]
fn planned_list_literal_cases_are_checked_and_executed() {
    let cases: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/m2-collections-cases.json")).unwrap();
    for c in cases["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["requires"] == "M2-7b3" && c["superseded_by"].is_null())
    {
        let text = c["source"].as_str().unwrap();
        if c["check"] == "reject" {
            assert_eq!(
                check("fixture.bas", text.as_bytes()).unwrap_err().code,
                c["diagnostic"],
                "{}",
                c["id"]
            );
            assert_eq!(
                analyze("fixture.bas", text.as_bytes()).unwrap_err().code,
                c["diagnostic"]
            );
        } else {
            analyze("fixture.bas", text.as_bytes()).unwrap();
            let p = compile("fixture.bas", text.as_bytes()).unwrap();
            let result = clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST);
            if c["execution"]["diagnostic"].is_string() {
                assert_eq!(result.err().unwrap().code, c["execution"]["diagnostic"]);
            } else {
                assert_eq!(result.unwrap().bytes, vec![0x80]);
            }
        }
    }
}
#[test]
fn proper_list_encoding_and_contextual_returns_are_preserved() {
    assert_eq!(
        hex::encode(observe("DIM xs = [1,128]\n", "")),
        "ffff01ff8200808080"
    );
    assert_eq!(
        hex::encode(observe("DIM xs AS LIST OF INTEGER = []\n", "")),
        "ff8080"
    );
    assert_eq!(
        hex::encode(observe("DIM xs AS LIST OF LIST OF INTEGER = [[],[]]\n", "")),
        "ffff80ff808080"
    );
    let functions = "FUNCTION Empty() AS LIST OF INTEGER\nRETURN ([])\nEND FUNCTION\nFUNCTION Branch(flag AS BOOLEAN) AS LIST OF INTEGER\nIF flag THEN\nRETURN []\nEND IF\nRETURN [1,128]\nEND FUNCTION\n";
    assert_eq!(
        hex::encode(observe("DIM xs = Branch(FALSE)\n", functions)),
        "ffff01ff8200808080"
    );
    assert_eq!(
        hex::encode(observe("DIM xs = Branch(TRUE)\n", functions)),
        "ff8080"
    );
    assert_eq!(
        hex::encode(observe("DIM xs = Empty()\n", functions)),
        "ff8080"
    );
    assert_eq!(
        hex::encode(observe(
            "DIM xs = [1]\nIF TRUE THEN\nxs = []\nEND IF\nDIM seen = xs\n",
            ""
        )),
        "ff8080"
    );
    run("DIM p AS PAIR OF (LIST OF INTEGER,LIST OF BOOLEAN) = PAIR(([]),[])\nDIM xs AS LIST OF PAIR OF (LIST OF INTEGER,STRING) = [PAIR([],\"a\")]\n","",clvm::DEFAULT_MAX_COST).unwrap();
}
#[test]
fn list_typing_syntax_and_deferred_operations_are_explicit() {
    for (body, code) in [
        ("DIM xs = [1,]\n", "E0100"),
        ("DIM xs = [,1]\n", "E0100"),
        ("DIM xs = [[1],[]]\n", "E0202"),
        ("DIM xs AS INTEGER = []\n", "E0202"),
        ("DIM xs AS LIST OF INTEGER = []\nxs = [TRUE]\n", "E0202"),
        (
            "DIM xs AS LIST OF INTEGER = []\nDIM n = FIRST(1)\n",
            "E0202",
        ),
        ("DIM n = LIST_LENGTH(1)\n", "E0202"),
        ("IF FALSE THEN\nDIM xs = []\nEND IF\n", "E0202"),
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
fn list_elements_evaluate_once_left_to_right_even_when_unused() {
    let functions = format!(
        "FUNCTION Fail() AS BYTES\nASSERT FALSE\nRETURN 0x\nEND FUNCTION\nFUNCTION Work() AS BYTES\nDIM b = 0x{}\nRETURN CONCAT(b,b)\nEND FUNCTION\n",
        "ff".repeat(8192)
    );
    assert_eq!(
        run("DIM xs = [Fail(),Work()]\n", &functions, 20000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_eq!(
        run("DIM xs = [Work(),Fail()]\n", &functions, 20000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    run(
        "IF FALSE THEN\nDIM xs = [Fail(),Work()]\nEND IF\n",
        &functions,
        clvm::DEFAULT_MAX_COST,
    )
    .unwrap();
    let a = compile(
        "a.bas",
        source("DIM xs = [Work(),0x]\n", &functions).as_bytes(),
    )
    .unwrap();
    let b = compile(
        "b.bas",
        source("DIM b = Work()\nDIM xs = [b,0x]\n", &functions).as_bytes(),
    )
    .unwrap();
    assert_eq!(a.puzzle, b.puzzle);
    let result = clvm::execute(&a.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    clvm::execute(&a.puzzle, &[0x80], result.cost).unwrap();
    assert_eq!(
        clvm::execute(&a.puzzle, &[0x80], result.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}
#[test]
fn list_type_and_expression_limits_are_bounded() {
    let mut ty = "INTEGER".to_owned();
    for _ in 0..32 {
        ty = format!("LIST OF {ty}");
    }
    check(
        "depth.bas",
        source(&format!("DIM xs AS {ty} = []\n"), "").as_bytes(),
    )
    .unwrap();
    assert_eq!(
        check(
            "depth.bas",
            source(&format!("DIM xs AS LIST OF {ty} = []\n"), "").as_bytes()
        )
        .unwrap_err()
        .code,
        "E0205"
    );
    let items = vec!["1"; 1024].join(",");
    assert_eq!(
        check(
            "wide.bas",
            source(&format!("DIM xs = [{items}]\n"), "").as_bytes()
        )
        .unwrap_err()
        .code,
        "E0205"
    );
    let p = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-lists.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        run(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(12)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}
