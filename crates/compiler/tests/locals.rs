use oxbasic_compiler::{check, clvm, compile};

fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn program(body: &str) -> Vec<u8> {
    compile("locals.bas", source(body).as_bytes())
        .unwrap()
        .puzzle
}
fn run(body: &str) -> Vec<u8> {
    clvm::execute(&program(body), &[0x80], clvm::DEFAULT_MAX_COST)
        .unwrap()
        .bytes
}

#[test]
fn declarations_inference_aliases_and_case_insensitive_references() {
    let body = "DIM Base AS INTEGER = 10\nDIM height = BASE + 5\nDIM alias AS INTEGER = height\nEMIT ASSERT_HEIGHT_ABSOLUTE(ALIAS)\nDIM later = -(-128)\nEMIT ASSERT_HEIGHT_ABSOLUTE(base)\nEMIT ASSERT_HEIGHT_ABSOLUTE(later)\n";
    assert_eq!(
        run(body),
        run(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(15)\nEMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(128)\n"
        )
    );
    assert_eq!(
        run(
            "DIM huge = 18446744073709551616\nDIM small = huge - 18446744073709551615\nEMIT ASSERT_HEIGHT_ABSOLUTE(small)\n"
        ),
        run("EMIT ASSERT_HEIGHT_ABSOLUTE(1)\n")
    );
    assert_eq!(run("DIM unused = -1\n"), [0x80]);
}

#[test]
fn bad_names_and_initializers_have_precise_diagnostics() {
    for (body, code, token) in [
        ("DIM height = height\n", "E0200", "height"),
        ("DIM early = later\nDIM later = 1\n", "E0200", "later"),
        ("EMIT ASSERT_HEIGHT_ABSOLUTE(missing)\n", "E0200", "missing"),
        ("DIM Height = 1\nDIM HEIGHT = 2\n", "E0201", "HEIGHT"),
        ("DIM demo = 1\n", "E0201", "demo"),
        ("DIM SHA256 = 1\n", "E0201", "SHA256"),
        ("DIM INTEGER = 1\n", "E0201", "INTEGER"),
        ("DIM value AS INTEGER = TRUE\n", "E0202", "TRUE"),
        ("DIM value AS INTEGER = FALSE\n", "E0202", "FALSE"),
    ] {
        let text = source(body);
        let error = check("names.bas", text.as_bytes()).unwrap_err();
        assert_eq!(error.code, code, "{body}");
        assert_eq!(error.source.as_deref(), Some("names.bas"));
        let span = error.span.unwrap();
        assert_eq!(&text[span.start_byte..span.end_byte], token);
    }
}

#[test]
fn required_initialization_and_deferred_features_remain_explicit() {
    for body in ["DIM value AS INTEGER\n", "DIM value =\n", "DIM = 1\n"] {
        assert_eq!(
            check("bad.bas", source(body).as_bytes()).unwrap_err().code,
            "E0100"
        );
    }
    for body in [
        "DIM value AS AMOUNT = TRUE\n",
        "CONST value AS AMOUNT = TRUE\n",
    ] {
        assert_eq!(
            check("future.bas", source(body).as_bytes())
                .unwrap_err()
                .code,
            "E0205"
        );
    }
    assert_eq!(
        check("unknown.bas", source("DIM value = Helper(1)\n").as_bytes())
            .unwrap_err()
            .code,
        "E0200"
    );
}

#[test]
fn initializers_run_even_when_unused_or_after_the_last_emission() {
    let huge = "9".repeat(500);
    let expensive = [huge.as_str(); 8].join(" * ");
    for body in [
        format!("DIM unused = {expensive}\n"),
        format!("EMIT ASSERT_HEIGHT_ABSOLUTE(1)\nDIM unused = {expensive}\n"),
        format!("DIM old = 1\nDIM unused = {expensive}\nEMIT ASSERT_HEIGHT_ABSOLUTE(old)\n"),
    ] {
        assert_eq!(
            clvm::execute(&program(&body), &[0x80], 10_000)
                .err()
                .unwrap()
                .code,
            "E0501"
        );
    }
    let bad_first = format!("EMIT ASSERT_HEIGHT_ABSOLUTE(-1)\nDIM unused = {expensive}\n");
    assert_eq!(
        clvm::execute(&program(&bad_first), &[0x80], 10_000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}

#[test]
fn repeated_references_reuse_one_computed_value() {
    let expression =
        "18446744073709551616 * 18446744073709551616 - 340282366920938463463374607431768211455";
    let shared = program(&format!(
        "DIM computed = {expression}\nEMIT ASSERT_HEIGHT_ABSOLUTE(computed)\nEMIT ASSERT_HEIGHT_ABSOLUTE(computed)\n"
    ));
    let duplicated = program(&format!(
        "EMIT ASSERT_HEIGHT_ABSOLUTE({expression})\nEMIT ASSERT_HEIGHT_ABSOLUTE({expression})\n"
    ));
    let shared = clvm::execute(&shared, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    let duplicated = clvm::execute(&duplicated, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(shared.bytes, duplicated.bytes);
    assert!(shared.cost < duplicated.cost);
}

#[test]
fn alias_only_declarations_have_an_independent_limit() {
    let mut body = "DIM seed = 1\n".to_owned();
    for n in 1..1024 {
        body.push_str(&format!("DIM local{n} = seed\n"));
    }
    assert!(check("limits.bas", source(&body).as_bytes()).is_ok());
    body.push_str("DIM extra = seed\n");
    assert_eq!(
        check("limits.bas", source(&body).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
}

#[test]
fn reassignment_preserves_earlier_emissions_and_alias_snapshots() {
    let body = "DIM height = 10\nDIM saved = height\nEMIT ASSERT_HEIGHT_ABSOLUTE(height)\nHEIGHT = height + 5\nDIM after = height\nheight = saved\nEMIT ASSERT_HEIGHT_ABSOLUTE(after)\nEMIT ASSERT_HEIGHT_ABSOLUTE(height)\nsaved = saved + 1\nEMIT ASSERT_HEIGHT_ABSOLUTE(saved)\n";
    assert_eq!(
        run(body),
        run(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(15)\nEMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(11)\n"
        )
    );
    assert_eq!(
        run("DIM a = 2\nDIM b = 3\na = a + b\nb = a * b\na = a\nEMIT ASSERT_HEIGHT_ABSOLUTE(b)\n"),
        run("EMIT ASSERT_HEIGHT_ABSOLUTE(15)\n")
    );
}

#[test]
fn invalid_assignment_targets_types_and_syntax_are_rejected() {
    for (body, code, token) in [
        ("missing = 1\n", "E0200", "missing"),
        ("height = 1\nDIM height = 2\n", "E0200", "height"),
        ("Demo = 1\n", "E0203", "Demo"),
        ("SHA256 = 1\n", "E0203", "SHA256"),
        ("DIM height = 1\nheight = TRUE\n", "E0202", "TRUE"),
        ("DIM height = 1\nheight = missing\n", "E0200", "missing"),
    ] {
        let text = source(body);
        let error = check("assignment.bas", text.as_bytes()).unwrap_err();
        assert_eq!(error.code, code, "{body}");
        let span = error.span.unwrap();
        assert_eq!(&text[span.start_byte..span.end_byte], token);
    }
    assert_eq!(
        check("bad.bas", source("DIM height = 1\nheight =\n").as_bytes())
            .unwrap_err()
            .code,
        "E0100"
    );
}

#[test]
fn overwritten_and_trailing_assignments_are_still_evaluated() {
    let huge = "9".repeat(500);
    let expensive = [huge.as_str(); 8].join(" * ");
    for body in [
        format!("DIM h = 1\nh = {expensive}\nh = 2\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n"),
        format!("DIM h = 1\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nh = {expensive}\n"),
        format!("DIM h = 1\nh = {expensive}\n"),
    ] {
        assert_eq!(
            clvm::execute(&program(&body), &[0x80], 10_000)
                .err()
                .unwrap()
                .code,
            "E0501"
        );
    }
    assert_eq!(
        clvm::execute(
            &program(&format!(
                "DIM h = 1\nEMIT ASSERT_HEIGHT_ABSOLUTE(-1)\nh = {expensive}\n"
            )),
            &[0x80],
            10_000
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
}

#[test]
fn self_assignments_create_bounded_fresh_bindings() {
    let text = source("DIM h = 1\nh = h\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n");
    let checked = check("copy.bas", text.as_bytes()).unwrap();
    assert_eq!(checked.values.len(), 3);
    assert!(matches!(
        checked.values[1].kind,
        oxbasic_compiler::IntegerValueKind::Copy { operand: 0 }
    ));
    let text = source(&format!("DIM h = 1\n{}", "h = h\n".repeat(4096)));
    assert_eq!(
        check("limits.bas", text.as_bytes()).unwrap_err().code,
        "E0205"
    );
}
