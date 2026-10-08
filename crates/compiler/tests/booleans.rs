use oxbasic_compiler::{ValueType, check, clvm, compile};

fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn execute(body: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let compiled = compile("bool.bas", source(body).as_bytes())?;
    clvm::execute(&compiled.puzzle, &[0x80], cost)
}
fn passes(body: &str) {
    assert_eq!(execute(body, clvm::DEFAULT_MAX_COST).unwrap().bytes, [0x80]);
}

#[test]
fn comparisons_agree_for_constants_and_runtime_signed_integers() {
    for (left, right, ordering) in [
        ("-2", "-1", -1),
        ("-1", "0", -1),
        ("0", "-1", 1),
        ("0", "0", 0),
        ("128", "127", 1),
        ("&H80", "128", 0),
        ("18446744073709551616", "18446744073709551615", 1),
        ("-18446744073709551616", "-18446744073709551615", -1),
    ] {
        for (op, expected) in [
            ("=", ordering == 0),
            ("<>", ordering != 0),
            ("<", ordering < 0),
            ("<=", ordering <= 0),
            (">", ordering > 0),
            (">=", ordering >= 0),
        ] {
            let comparison = format!("{left} {op} {right}");
            let assertion = if expected { "result" } else { "NOT result" };
            for declaration in ["DIM", "CONST"] {
                passes(&format!(
                    "{declaration} result AS BOOLEAN = {comparison}\nASSERT {assertion}\n"
                ));
                let error = execute(
                    &format!("{declaration} result = {comparison}\nASSERT NOT ({assertion})\n"),
                    clvm::DEFAULT_MAX_COST,
                )
                .err()
                .unwrap();
                assert_eq!(error.code, "E0500", "{comparison}");
            }
        }
    }
}

#[test]
fn boolean_locals_constants_assignment_and_snapshots_are_typed() {
    let body = "CONST yes AS BOOLEAN = NOT FALSE\nCONST no = NOT yes\nDIM flag = yes\nDIM saved AS BOOLEAN = FLAG\nASSERT flag\nflag = no\nASSERT NOT flag\nASSERT saved\nASSERT yes = TRUE\nASSERT no <> yes\nASSERT NOT 1 = 2\nASSERT (1 < 2) = TRUE\nASSERT NOT NOT TRUE\n";
    passes(body);
    let checked = check("bool.bas", source(body).as_bytes()).unwrap();
    for local in &checked.locals {
        assert_eq!(checked.values[local.value].value_type, ValueType::Boolean);
    }
    passes("CONST zero = -0\nCONST equal = zero = 0\nASSERT equal\n");
}

#[test]
fn strict_types_reject_truthiness_arithmetic_ordering_and_changes() {
    for (body, token) in [
        ("ASSERT 1\n", "1"),
        ("ASSERT 0\n", "0"),
        ("DIM b AS BOOLEAN = 1\n", "1"),
        ("CONST b AS BOOLEAN = 0\n", "0"),
        ("DIM b = TRUE\nb = 1\n", "1"),
        ("DIM n = 1\nn = FALSE\n", "FALSE"),
        ("DIM b = NOT 0\n", "0"),
        ("CONST b = NOT 0\n", "0"),
        ("DIM n = +TRUE\n", "TRUE"),
        ("CONST n = -TRUE\n", "TRUE"),
        ("DIM n = TRUE + 1\n", "TRUE"),
        ("CONST n = 1 * FALSE\n", "FALSE"),
        ("ASSERT TRUE < FALSE\n", "TRUE"),
        ("CONST b = TRUE >= FALSE\n", "TRUE"),
        ("ASSERT TRUE = 1\n", "1"),
        ("CONST b = 0 <> FALSE\n", "FALSE"),
        ("EMIT ASSERT_HEIGHT_ABSOLUTE(1 < 2)\n", "1 < 2"),
    ] {
        let text = source(body);
        let err = check("bool.bas", text.as_bytes()).unwrap_err();
        assert_eq!(err.code, "E0202", "{body}");
        let span = err.span.unwrap();
        assert_eq!(&text[span.start_byte..span.end_byte], token, "{body}");
    }
}

#[test]
fn assertions_preserve_statement_order_and_emit_no_conditions() {
    let body = "ASSERT TRUE\nEMIT ASSERT_HEIGHT_ABSOLUTE(10)\nASSERT NOT FALSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(20)\nASSERT 3 > 2\n";
    let expected = execute(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(20)\n",
        clvm::DEFAULT_MAX_COST,
    )
    .unwrap();
    assert_eq!(
        execute(body, clvm::DEFAULT_MAX_COST).unwrap().bytes,
        expected.bytes
    );
    for body in [
        "ASSERT FALSE\n",
        "EMIT ASSERT_HEIGHT_ABSOLUTE(1)\nASSERT FALSE\n",
        "CONST bad = FALSE\nASSERT bad\n",
    ] {
        assert!(check("bool.bas", source(body).as_bytes()).is_ok());
        assert_eq!(
            execute(body, clvm::DEFAULT_MAX_COST).err().unwrap().code,
            "E0500"
        );
    }
    let huge = "9".repeat(500);
    let expensive = [huge.as_str(); 8].join(" * ");
    for (body, code) in [
        (format!("ASSERT FALSE\nDIM unused = {expensive}\n"), "E0500"),
        (format!("DIM unused = {expensive}\nASSERT FALSE\n"), "E0501"),
        (format!("ASSERT TRUE\nDIM unused = {expensive}\n"), "E0501"),
        (
            format!("EMIT ASSERT_HEIGHT_ABSOLUTE(-1)\nASSERT {expensive} > 0\n"),
            "E0500",
        ),
        (format!("DIM unused = {expensive} > 0\n"), "E0501"),
    ] {
        assert_eq!(execute(&body, 10_000).err().unwrap().code, code);
    }
}

#[test]
fn unreachable_source_and_constant_dependencies_are_still_checked() {
    for (body, code) in [
        ("ASSERT FALSE\nDIM b AS BOOLEAN = 1\n", "E0202"),
        ("ASSERT FALSE\nASSERT missing\n", "E0200"),
        ("DIM b = TRUE\nCONST c = NOT b\n", "E0205"),
        ("CONST b = TRUE\nb = FALSE\n", "E0203"),
        ("ASSERT\n", "E0100"),
        ("ASSERT 1 < 2 < 3\n", "E0100"),
        ("ASSERT TRUE AND 0\n", "E0202"),
        ("CONST b = TRUE OR 0\n", "E0202"),
    ] {
        assert_eq!(
            check("bool.bas", source(body).as_bytes()).unwrap_err().code,
            code,
            "{body}"
        );
    }
}

#[test]
fn assertion_bindings_have_a_shared_resource_limit() {
    let body = format!("DIM b = TRUE\n{}", "ASSERT b\n".repeat(4095));
    assert!(check("bool.bas", source(&body).as_bytes()).is_ok());
    assert_eq!(
        check("bool.bas", source(&(body + "ASSERT b\n")).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
}
