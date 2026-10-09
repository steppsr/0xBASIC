use oxbasic_compiler::{analyze, check, clvm, compile};

fn source(body: &str) -> String {
    format!("CONTRACT BytesFixture()\n{body}END CONTRACT\n")
}
fn run(text: &str) {
    let program = compile("bytes.bas", text.as_bytes()).unwrap();
    clvm::execute(&program.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
}
fn error(body: &str, code: &str) {
    let text = source(body);
    assert_eq!(
        check("bytes.bas", text.as_bytes()).unwrap_err().code,
        code,
        "{body}"
    );
    assert_eq!(
        analyze("bytes.bas", text.as_bytes()).unwrap_err().code,
        code,
        "{body}"
    );
}

#[test]
fn byte_literals_preserve_empty_zero_prefixes_and_every_byte() {
    run(&source(
        "ASSERT 0x = 0X\nASSERT 0x00 <> 0x\nASSERT 0x0001 <> 0x01\nASSERT 0xaBff = 0XABFF\n",
    ));
    let bytes: Vec<_> = (0..=255).collect();
    let text = source(&format!("DIM value AS BYTES = 0x{}\n", hex::encode(&bytes)));
    let contract = check("all.bas", text.as_bytes()).unwrap();
    assert!(
        matches!(&contract.values[0].kind, oxbasic_compiler::IntegerValueKind::Literal(value) if value == &bytes)
    );
    assert_eq!(
        contract.values[0].value_type,
        oxbasic_compiler::ValueType::Bytes
    );
    run(&text);
    let lower = compile("a.bas", source("ASSERT 0xab = 0XAB\n").as_bytes()).unwrap();
    let upper = compile("b.bas", source("ASSERT 0XAB = 0xab\n").as_bytes()).unwrap();
    assert_eq!(lower.puzzle, upper.puzzle);
}

#[test]
fn bytes_flow_through_locals_branches_and_function_returns() {
    run(include_str!("../../../examples/m2-bytes.bas"));
    run(&source(
        "DIM value AS BYTES = 0x00\nDIM saved = value\nIF TRUE THEN\nvalue = 0x0001\nELSE\nvalue = 0xff\nEND IF\nASSERT value = 0x0001\nASSERT saved = 0x00\n",
    ));
    run(
        "CONTRACT Demo()\nASSERT Echo(0x, TRUE) = 0x\nASSERT Echo(0x0001, FALSE) = 0x0001\nEND CONTRACT\nFUNCTION Echo(value AS BYTES, b AS BOOLEAN) AS BYTES\nIF b THEN\nRETURN value\nELSEIF value = 0x0001 THEN\nRETURN value\nEND IF\nRETURN 0xff\nEND FUNCTION\n",
    );
}

#[test]
fn bytes_have_strict_types_and_no_implicit_numeric_interpretation() {
    for body in [
        "ASSERT 0x\n",
        "ASSERT 0x01 = 1\n",
        "ASSERT 0x = FALSE\n",
        "DIM n = 0x01 + 0x02\n",
        "ASSERT 0x01 < 0x02\n",
        "DIM n = -0x01\n",
        "ASSERT NOT 0x\n",
        "DIM b AS BYTES = TRUE\n",
        "DIM b = 0x\nb = 1\n",
        "EMIT 0x53\n",
        "EMIT ASSERT_HEIGHT_ABSOLUTE(0x64)\n",
    ] {
        error(body, "E0202");
    }
    for literal in ["0x0", "0xgg", "0x01zz", "0x00_01", "0x00.01"] {
        error(&format!("DIM value = {literal}\n"), "E0002");
    }
}

#[test]
fn conversions_require_correct_types_and_unreachable_returns_are_checked() {
    error("DIM value = AS_PUBLICKEY(0)\n", "E0202");
    let text =
        "CONTRACT Demo()\nEND CONTRACT\nFUNCTION F() AS BYTES\nRETURN 0x\nRETURN 0\nEND FUNCTION\n";
    assert_eq!(
        check("unreachable.bas", text.as_bytes()).unwrap_err().code,
        "E0202"
    );
}

#[test]
fn byte_literal_size_uses_existing_source_and_artifact_limits() {
    let literal = "00ff".repeat(8192);
    run(&source(&format!(
        "DIM value = 0x{literal}\nASSERT value = 0x{literal}\n"
    )));
    let text = source(&format!("DIM value = 0x{}\n", "00".repeat(524288)));
    assert_eq!(
        check("large.bas", text.as_bytes()).unwrap_err().code,
        "E0205"
    );
}
