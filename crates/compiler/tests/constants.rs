use oxbasic_compiler::{IntegerValueKind, check, clvm, compile};

fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn run(body: &str) -> clvm::Execution {
    let compiled = compile("const.bas", source(body).as_bytes()).unwrap();
    clvm::execute(&compiled.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap()
}

#[test]
fn constants_fold_to_literals_and_mutable_copies_are_independent() {
    let body = "CONST Base AS INTEGER = &H0A\nCONST height = +(BASE * 2)\nDIM mutable = height\nmutable = mutable + 5\nEMIT ASSERT_HEIGHT_ABSOLUTE(height)\nEMIT ASSERT_HEIGHT_ABSOLUTE(mutable)\n";
    assert_eq!(
        run(body).bytes,
        run("EMIT ASSERT_HEIGHT_ABSOLUTE(20)\nEMIT ASSERT_HEIGHT_ABSOLUTE(25)\n").bytes
    );
    let checked = check("const.bas", source(body).as_bytes()).unwrap();
    assert!(!checked.locals[0].mutable);
    assert!(checked.locals[2].mutable);
    assert!(matches!(&checked.values[1].kind, IntegerValueKind::Literal(bytes) if bytes == &[20]));
    let expr =
        "18446744073709551616 * 18446744073709551616 - 340282366920938463463374607431768211455";
    let folded = run(&format!(
        "CONST h = {expr}\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n"
    ));
    let runtime = run(&format!("DIM h = {expr}\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n"));
    assert_eq!(folded.bytes, runtime.bytes);
    assert!(folded.cost < runtime.cost);
}

#[test]
fn invalid_constant_names_types_and_dependencies_have_spans() {
    for (body, code, token) in [
        ("CONST x = x\n", "E0200", "x"),
        ("CONST x = later\nCONST later = 1\n", "E0200", "later"),
        ("DIM x = 1\nCONST y = x\n", "E0205", "x"),
        ("DIM x = 1\nCONST y = 0 * x\n", "E0205", "x"),
        (
            "CONST x = 1\nDIM alias = x\nCONST y = alias\n",
            "E0205",
            "alias",
        ),
        ("CONST x = 1\nX = missing\n", "E0203", "X"),
        ("CONST x = 1\nDIM X = 2\n", "E0201", "X"),
        ("DIM x = 1\nCONST X = 2\n", "E0201", "X"),
        ("CONST x = 1\nCONST X = 2\n", "E0201", "X"),
        ("CONST Demo = 1\n", "E0201", "Demo"),
        ("CONST SHA256 = 1\n", "E0201", "SHA256"),
        ("CONST x AS INTEGER = TRUE\n", "E0202", "TRUE"),
    ] {
        let text = source(body);
        let error = check("const.bas", text.as_bytes()).unwrap_err();
        assert_eq!(error.code, code, "{body}");
        let span = error.span.unwrap();
        assert_eq!(&text[span.start_byte..span.end_byte], token);
    }
    for body in [
        "CONST x = Helper(1)\n",
        "CONST x = 0 * Helper(1)\n",
        "CONST x = TRUE AND Helper(1)\n",
    ] {
        assert_eq!(
            check("const.bas", source(body).as_bytes())
                .unwrap_err()
                .code,
            "E0205"
        );
    }
}

#[test]
fn signed_zero_and_height_range_remain_distinct() {
    assert_eq!(run("CONST n = -(-128)\nCONST z = -0\nEMIT ASSERT_HEIGHT_ABSOLUTE(n)\nEMIT ASSERT_HEIGHT_ABSOLUTE(z)\n").bytes,
        run("EMIT ASSERT_HEIGHT_ABSOLUTE(128)\nEMIT ASSERT_HEIGHT_ABSOLUTE(0)\n").bytes);
    assert_eq!(run("CONST unused = -1\n").bytes, [0x80]);
    for value in ["-1", "4294967296"] {
        let compiled = compile(
            "const.bas",
            source(&format!(
                "CONST h = {value}\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n"
            ))
            .as_bytes(),
        )
        .unwrap();
        assert_eq!(
            clvm::execute(&compiled.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
                .err()
                .unwrap()
                .code,
            "E0500"
        );
    }
}

#[test]
fn every_constant_intermediate_has_a_magnitude_limit() {
    let body = format!(
        "CONST a = &H8{}\nCONST b = a * a\nCONST c = b * 2\n",
        "0".repeat(4095)
    );
    assert!(check("const.bas", source(&body).as_bytes()).is_ok());
    for tail in [
        "CONST d = c * 2\n",
        "CONST d = (c * 2) - c\n",
        "CONST d = -c * 2\n",
    ] {
        let error = check("const.bas", source(&(body.clone() + tail)).as_bytes()).unwrap_err();
        assert_eq!(error.code, "E0205");
        assert!(error.message.contains("32768"));
    }
    let body = format!("CONST a = {}\n", "1".repeat(4097));
    assert!(
        check("const.bas", source(&body).as_bytes())
            .unwrap_err()
            .message
            .contains("4096 digits")
    );
}

#[test]
fn constant_work_and_shared_declarations_are_bounded() {
    let mut body = String::new();
    let expr = ["1"; 17].join(" + ");
    for n in 0..497 {
        body.push_str(&format!("CONST c{n} = {expr}\n"));
    }
    let error = check("const.bas", source(&body).as_bytes()).unwrap_err();
    assert!(error.message.contains("16384"));
    let mut body = "DIM seed = 1\nCONST base = 2\n".to_owned();
    for n in 2..1024 {
        body.push_str(&format!("CONST c{n} = base\n"));
    }
    assert!(check("const.bas", source(&body).as_bytes()).is_ok());
    body.push_str("CONST extra = base\n");
    assert!(
        check("const.bas", source(&body).as_bytes())
            .unwrap_err()
            .message
            .contains("1024")
    );
}
