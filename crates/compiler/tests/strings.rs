use oxbasic_compiler::{analyze, check, clvm, compile};
fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn literal(s: &str) -> String {
    format!("\"{}\"", s.replace('"', "\"\""))
}
fn run(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("strings.bas", source(body, functions).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}
#[test]
fn literals_preserve_exact_utf8_quotes_backslashes_and_comment_text() {
    for text in [
        "",
        "Hello, Chia!",
        "REM ' () []",
        "a\"b",
        "\\n\\t",
        "é",
        "e\u{301}",
        "你好",
        "🦀",
        "\t",
        "\u{10ffff}",
    ] {
        run(
            &format!(
                "DIM s AS STRING = {}\nASSERT UTF8(s) = 0x{}\nASSERT BYTE_LENGTH(utf8(s)) = {}\n",
                literal(text),
                hex::encode(text.as_bytes()),
                text.len()
            ),
            "",
            clvm::DEFAULT_MAX_COST,
        )
        .unwrap();
    }
    run(
        "ASSERT \"é\" <> \"é\"\nASSERT \"Chia\" <> \"chia\"\nASSERT UTF8(\"\") = 0x\n",
        "",
        clvm::DEFAULT_MAX_COST,
    )
    .unwrap();
    let text = "\u{feff}CONTRACT Demo()\r\nDIM s = \"é\" ' comment\r\nASSERT UTF8(s) = 0xc3a9\r\nEND CONTRACT";
    let p = compile("bom.bas", text.as_bytes()).unwrap();
    clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
}
#[test]
fn strings_are_distinct_from_bytes_and_other_types() {
    for (body, code) in [
        ("DIM s AS STRING = 0x\n", "E0202"),
        ("DIM b AS BYTES = \"\"\n", "E0202"),
        ("ASSERT \"a\" = 0x61\n", "E0202"),
        ("ASSERT \"a\" < \"b\"\n", "E0202"),
        ("ASSERT \"\"\n", "E0202"),
        ("DIM s = \"a\" + \"b\"\n", "E0202"),
        ("DIM n = BYTE_LENGTH(\"a\")\n", "E0202"),
        ("DIM b = SHA256(\"a\")\n", "E0202"),
        ("DIM b = UTF8(0x)\n", "E0202"),
        ("DIM b = UTF8(TRUE)\n", "E0202"),
        ("DIM b = UTF8()\n", "E0202"),
        ("DIM b = UTF8(\"a\",\"b\")\n", "E0202"),
        ("DIM b = UTF8\n", "E0100"),
        ("DIM UTF8 = 0\n", "E0201"),
        ("CONST b = UTF8(\"a\")\n", "E0205"),
        ("CONST b = TRUE OR (UTF8(\"a\") = 0x61)\n", "E0205"),
        ("DIM s = \"a\"\ns = 0x61\n", "E0202"),
        ("IF FALSE THEN\nDIM b = UTF8(1)\nEND IF\n", "E0202"),
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
fn string_constants_and_scoped_values_flow_through_functions() {
    let functions = "FUNCTION Echo(s AS STRING, flag AS BOOLEAN) AS STRING\nCONST suffix = \"é\"\nIF flag THEN\nRETURN s\nEND IF\nRETURN suffix\nEND FUNCTION\nFUNCTION Proven() AS STRING\nCONST a = \"a\"\nIF a <> \"b\" THEN\nRETURN a\nEND IF\nEND FUNCTION\n";
    run("CONST original AS STRING = \"Hi\"\nCONST alias = original\nCONST same = alias = \"Hi\"\nASSERT same\nDIM s = Echo(alias,TRUE)\nIF TRUE THEN\ns = Echo(s,FALSE)\nEND IF\nASSERT s = \"é\"\nASSERT original = \"Hi\"\nASSERT Proven() = \"a\"\n",functions,clvm::DEFAULT_MAX_COST).unwrap();
    for body in [
        "CONST s = \"a\"\ns = \"b\"\n",
        "DIM s = \"a\"\nCONST c = s\n",
    ] {
        assert!(check("bad.bas", source(body, "").as_bytes()).is_err());
    }
}
#[test]
fn utf8_keeps_eager_once_and_lazy_execution_rules() {
    let functions = "FUNCTION Fail() AS STRING\nASSERT FALSE\nRETURN \"\"\nEND FUNCTION\nFUNCTION Work() AS STRING\nRETURN \"é\"\nEND FUNCTION\n";
    assert_eq!(
        run("DIM b = UTF8(Fail())\n", functions, clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    run(
        "ASSERT TRUE OR (UTF8(Fail()) = 0x)\nIF FALSE THEN\nDIM b = UTF8(Fail())\nEND IF\n",
        functions,
        clvm::DEFAULT_MAX_COST,
    )
    .unwrap();
    let direct = compile(
        "direct.bas",
        source("DIM b = UTF8(Work())\n", functions).as_bytes(),
    )
    .unwrap();
    let named = compile(
        "named.bas",
        source("DIM s = Work()\nDIM b = UTF8(s)\n", functions).as_bytes(),
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
    let p = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-strings.bas"),
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
#[test]
fn malformed_strings_and_source_diagnostics_remain_precise() {
    for body in [
        "DIM s = \"unterminated\n",
        "DIM s = \"a\nb\"\n",
        "DIM s = \"a\r\nb\"\n",
    ] {
        assert_eq!(
            check("bad.bas", source(body, "").as_bytes())
                .unwrap_err()
                .code,
            "E0002"
        );
    }
    for bytes in [
        b"CONTRACT Demo()\nDIM s = \"\xff\"\nEND CONTRACT\n".as_slice(),
        b"CONTRACT Demo()\nDIM s = \"\0\"\nEND CONTRACT\n",
    ] {
        assert!(check("bad.bas", bytes).is_err());
    }
    let text = "\u{feff}CONTRACT Demo()\r\nDIM s = \"é\"\r\nASSERT s = 0xc3a9\r\nEND CONTRACT\r\n";
    let error = check("span.bas", text.as_bytes()).unwrap_err();
    assert_eq!(error.code, "E0202");
    let span = error.span.unwrap();
    assert_eq!(&text[span.start_byte..span.end_byte], "0xc3a9");
    assert_eq!(span.line, 3);
}
#[test]
fn string_constants_share_the_existing_byte_work_budget() {
    // 256 values of 32768 UTF-8 bytes reach 8 MiB; aliases still cost work.
    let mut body = format!("CONST s0 = {}\n", literal(&"é".repeat(16384)));
    for n in 1..256 {
        body.push_str(&format!("CONST s{n} = s0\n"));
    }
    check("budget.bas", source(&body, "").as_bytes()).unwrap();
    body.push_str("CONST extra = s0\n");
    assert_eq!(
        check("budget.bas", source(&body, "").as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
}
