use oxbasic_compiler::{analyze, check, clvm, compile};
fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn execute(text: &str) -> Vec<u8> {
    let p = compile("constants.bas", text.as_bytes()).unwrap();
    clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
        .unwrap()
        .bytes
}
fn reject(body: &str, code: &str) {
    let text = source(body);
    for error in [
        check("bad.bas", text.as_bytes()).unwrap_err(),
        analyze("bad.bas", text.as_bytes()).unwrap_err(),
    ] {
        assert_eq!(error.code, code, "{body}: {}", error.message);
        assert!(error.span.is_some());
    }
}
#[test]
fn planned_constants_and_example_execute() {
    let cases: serde_json::Value =
        serde_json::from_str(include_str!("../../../docs/spec/m2-collections-cases.json")).unwrap();
    for case in cases["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["requires"] == "M2-7b5")
    {
        let text = case["source"].as_str().unwrap();
        if case["check"] == "reject" {
            assert_eq!(
                check("fixture.bas", text.as_bytes()).unwrap_err().code,
                case["diagnostic"]
            );
            assert_eq!(
                analyze("fixture.bas", text.as_bytes()).unwrap_err().code,
                case["diagnostic"]
            );
        } else {
            analyze("fixture.bas", text.as_bytes()).unwrap();
            assert_eq!(hex::encode(execute(text)), "ffff53ff078080");
        }
    }
    assert_eq!(
        hex::encode(execute(include_str!(
            "../../../examples/m2-list-constants.bas"
        ))),
        "ffff53ff0780ffff53ff028080"
    );
}
#[test]
fn constants_quote_exact_trees_and_preserve_atom_types() {
    for (ty, literal) in [
        ("INTEGER", "[0,-1,128]"),
        ("BOOLEAN", "[TRUE,FALSE]"),
        ("BYTES", "[0x,0x0001,0xff]"),
        ("STRING", "[\"\",\"é\",\"a\"\"b\"]"),
        ("LIST OF INTEGER", "[[],[1,128],[]]"),
        ("PAIR OF (INTEGER,BOOLEAN)", "[]"),
    ] {
        let observe = |keyword| {
            let text = source(&format!("{keyword} xs AS LIST OF {ty} = {literal}\n"));
            let mut c = check("observe.bas", text.as_bytes()).unwrap();
            c.emissions.push(oxbasic_compiler::syntax::HeightEmission {
                condition: c.locals.last().unwrap().value,
                values_before: c.values.len(),
                span: c.span,
                spread: false,
            });
            let p = clvm::generate(&c).unwrap();
            clvm::execute(&p, &[0xff, 0x80, 0x80], clvm::DEFAULT_MAX_COST)
                .unwrap()
                .bytes
        };
        assert_eq!(observe("CONST"), observe("DIM"), "{ty}");
    }
    execute(&source(
        "CONST xs AS LIST OF LIST OF STRING = ([[],[\"é\"]])\nCONST alias = (xs)\nASSERT UTF8(FIRST(FIRST(REST(alias)))) = 0xc3a9\nCONST bs = [0x0001]\nASSERT FIRST(bs) = 0x0001\n",
    ));
}
#[test]
fn constants_keep_strict_typing_dependencies_and_call_restrictions() {
    for (body, code) in [
        ("CONST xs = []\n", "E0202"),
        ("CONST xs = [[1],[]]\n", "E0202"),
        ("CONST xs = [1,TRUE]\n", "E0202"),
        ("CONST xs AS LIST OF BYTES = [\"a\"]\n", "E0202"),
        (
            "CONST xs = [1]\nCONST ys = [TRUE]\nCONST bad = xs = ys\n",
            "E0202",
        ),
        ("CONST xs = [1]\nxs = [2]\n", "E0203"),
        ("DIM n = 1\nCONST xs = [n]\n", "E0205"),
        ("CONST xs = [missing]\n", "E0200"),
        ("CONST xs = [CONS(1,[])]\n", "E0205"),
        ("CONST xs = [TRUE OR FIRST([TRUE])]\n", "E0205"),
        ("CONST xs = [LIST_LENGTH([1])]\n", "E0205"),
        ("IF FALSE THEN\nCONST xs = [FIRST([1])]\nEND IF\n", "E0205"),
    ] {
        reject(body, code);
    }
    let text = format!(
        "{}FUNCTION Pick(flag AS BOOLEAN) AS LIST OF INTEGER\nCONST empty AS LIST OF INTEGER = []\nIF flag THEN\nRETURN empty\nEND IF\nCONST xs = [7]\nRETURN xs\nEND FUNCTION\n",
        source("ASSERT LIST_LENGTH(Pick(TRUE)) = 0\nASSERT FIRST(Pick(FALSE)) = 7\n")
    );
    execute(&text);
}
fn expansion(depth: usize) -> String {
    let mut body = "CONST x0 = [1]\n".to_owned();
    for n in 1..=depth {
        body.push_str(&format!("CONST x{n} = [x{},x{}]\n", n - 1, n - 1));
    }
    body
}
#[test]
fn nested_alias_expansion_and_cumulative_work_are_bounded() {
    let body = expansion(13);
    // Largest tree here has 49149 expanded nodes; the next doubling has 98301.
    execute(&source(&body));
    let error = check("large.bas", source(&expansion(14)).as_bytes()).unwrap_err();
    assert_eq!(error.code, "E0205");
    assert!(error.message.contains("Expanded constant trees"));
    let mut repeated = body;
    for n in 0..20 {
        repeated.push_str(&format!("CONST alias{n} = (x13)\n"));
    }
    let error = check("work.bas", source(&repeated).as_bytes()).unwrap_err();
    assert_eq!(error.code, "E0205");
    assert!(error.message.contains("structural work"));
    let blob = "ab".repeat(2048);
    let mut bytes = format!(
        "CONST b = 0x{blob}\nCONST xs = [{}]\n",
        vec!["b"; 256].join(",")
    );
    for n in 0..14 {
        bytes.push_str(&format!("CONST alias{n} = xs\n"));
    }
    let error = check("bytes.bas", source(&bytes).as_bytes()).unwrap_err();
    assert_eq!(error.code, "E0205");
    assert!(error.message.contains("byte work"), "{}", error.message);
    let wide = format!(
        "CONST b = 0x{}\nCONST xs = [{}]\n",
        "00".repeat(8192),
        vec!["b"; 128].join(",")
    );
    let error = check("size.bas", source(&wide).as_bytes()).unwrap_err();
    assert!(
        error.message.contains("Expanded constant trees"),
        "{}",
        error.message
    );
}
#[test]
fn list_constant_programs_are_reproducible_and_eager_at_execution() {
    let a = compile(
        "a.bas",
        source("CONST xs = [1+2,4]\nEMIT ASSERT_HEIGHT_ABSOLUTE(FIRST(xs))\n").as_bytes(),
    )
    .unwrap();
    let b = compile(
        "b.bas",
        source("const XS = [ 3, 4 ] ' comment\nemit assert_height_absolute(first(XS))\n")
            .as_bytes(),
    )
    .unwrap();
    assert_eq!(a.puzzle, b.puzzle);
    let p = compile(
        "empty.bas",
        source("CONST xs AS LIST OF INTEGER = []\nDIM unused = FIRST(xs)\n").as_bytes(),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    execute(&source(
        "CONST xs AS LIST OF INTEGER = []\nASSERT TRUE OR FIRST(xs) = 1\n",
    ));
}
