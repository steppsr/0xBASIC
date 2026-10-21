use oxbasic_compiler::{ValueType, check, clvm, compile};

fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn run(body: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let compiled = compile("condition.bas", source(body).as_bytes())?;
    clvm::execute(&compiled.puzzle, &[0x80], cost)
}

#[test]
fn condition_locals_copy_reassign_and_emit_in_order() {
    let body = "DIM h = 10\nDIM pending AS CONDITION = ASSERT_HEIGHT_ABSOLUTE(h)\nDIM saved = PENDING\nh = 20\nEMIT (pending)\npending = ASSERT_HEIGHT_ABSOLUTE(h + 5)\nEMIT pending\nEMIT saved\npending = saved\nEMIT (pending)\nEMIT (ASSERT_HEIGHT_ABSOLUTE(h))\n";
    let expected = "EMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(25)\nEMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(20)\n";
    assert_eq!(
        run(body, clvm::DEFAULT_MAX_COST).unwrap().bytes,
        run(expected, clvm::DEFAULT_MAX_COST).unwrap().bytes
    );
    let checked = check("condition.bas", source(body).as_bytes()).unwrap();
    assert_eq!(
        checked.values[checked.locals[1].value].value_type,
        ValueType::Condition
    );
    assert_eq!(
        run(
            "DIM unused = ASSERT_HEIGHT_ABSOLUTE(100)\n",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes,
        [0x80]
    );
}

#[test]
fn invalid_constructors_fail_when_unused_overwritten_or_trailing() {
    for body in [
        "DIM unused AS CONDITION = ASSERT_HEIGHT_ABSOLUTE(-1)\n",
        "DIM unused = ASSERT_HEIGHT_ABSOLUTE(4294967296)\n",
        "DIM c = ASSERT_HEIGHT_ABSOLUTE(-1)\nc = ASSERT_HEIGHT_ABSOLUTE(1)\n",
        "DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nc = ASSERT_HEIGHT_ABSOLUTE(-1)\nc = ASSERT_HEIGHT_ABSOLUTE(1)\n",
        "EMIT ASSERT_HEIGHT_ABSOLUTE(1)\nDIM unused = ASSERT_HEIGHT_ABSOLUTE(-1)\n",
    ] {
        assert!(check("condition.bas", source(body).as_bytes()).is_ok());
        assert_eq!(
            run(body, clvm::DEFAULT_MAX_COST).err().unwrap().code,
            "E0500",
            "{body}"
        );
    }
    let big = "9".repeat(500);
    let work = [big.as_str(); 8].join(" * ");
    for (body, code) in [
        (
            format!("DIM c = ASSERT_HEIGHT_ABSOLUTE(-1)\nDIM n = {work}\n"),
            "E0500",
        ),
        (
            format!("DIM n = {work}\nDIM c = ASSERT_HEIGHT_ABSOLUTE(-1)\n"),
            "E0501",
        ),
        (
            format!("ASSERT FALSE\nDIM c = ASSERT_HEIGHT_ABSOLUTE({work})\n"),
            "E0500",
        ),
    ] {
        assert_eq!(run(&body, 10_000).err().unwrap().code, code);
    }
}

#[test]
fn emit_and_condition_operators_enforce_opaque_types_with_spans() {
    for (body, token) in [
        ("EMIT 1\n", "1"),
        ("EMIT TRUE\n", "TRUE"),
        ("DIM c AS CONDITION = 1\n", "1"),
        (
            "DIM n AS INTEGER = ASSERT_HEIGHT_ABSOLUTE(1)\n",
            "ASSERT_HEIGHT_ABSOLUTE(1)",
        ),
        ("DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nc = 1\n", "1"),
        ("DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nASSERT c\n", "c"),
        ("DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nASSERT c = c\n", "c"),
        ("DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nDIM b = c <> c\n", "c"),
        ("DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nDIM n = c + 1\n", "c"),
        ("DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nASSERT NOT c\n", "c"),
        ("DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nASSERT TRUE OR c\n", "c"),
        (
            "DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nEMIT ASSERT_HEIGHT_ABSOLUTE(c)\n",
            "c",
        ),
        ("DIM c = ASSERT_HEIGHT_ABSOLUTE(FALSE)\n", "FALSE"),
    ] {
        let text = source(body);
        let error = check("condition.bas", text.as_bytes()).unwrap_err();
        assert_eq!(error.code, "E0202", "{body}");
        let span = error.span.unwrap();
        assert_eq!(&text[span.start_byte..span.end_byte], token, "{body}");
    }
    assert_eq!(
        check("condition.bas", source("EMIT missing\n").as_bytes())
            .unwrap_err()
            .code,
        "E0200"
    );
}

#[test]
fn condition_constructors_remain_forbidden_in_constants() {
    for body in [
        "CONST c = ASSERT_HEIGHT_ABSOLUTE(1)\n",
        "CONST c AS CONDITION = ASSERT_HEIGHT_ABSOLUTE(1)\n",
        "DIM c = ASSERT_HEIGHT_ABSOLUTE(1)\nCONST saved = c\n",
        "CONST b = TRUE OR (ASSERT_HEIGHT_ABSOLUTE(-1) = ASSERT_HEIGHT_ABSOLUTE(1))\n",
    ] {
        assert_eq!(
            check("condition.bas", source(body).as_bytes())
                .unwrap_err()
                .code,
            "E0205"
        );
    }
}

#[test]
fn constructors_have_one_argument_and_preserve_expression_limits() {
    for body in [
        "EMIT ASSERT_HEIGHT_ABSOLUTE()\n",
        "DIM c = ASSERT_HEIGHT_ABSOLUTE(1, 2)\n",
        "EMIT ASSERT_HEIGHT_ABSOLUTE(1\n",
        "EMIT\n",
    ] {
        assert_eq!(
            check("condition.bas", source(body).as_bytes())
                .unwrap_err()
                .code,
            "E0100",
            "{body}"
        );
    }
    let body = "DIM c = assert_height_absolute(\n 1 + 2 ' comment\n)\nEMIT c\n";
    assert_eq!(
        run(body, clvm::DEFAULT_MAX_COST).unwrap().bytes,
        run("EMIT ASSERT_HEIGHT_ABSOLUTE(3)\n", clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes
    );
    let deep = format!(
        "DIM c = {}1{}\n",
        "ASSERT_HEIGHT_ABSOLUTE(".repeat(65),
        ")".repeat(65)
    );
    assert_eq!(
        check("condition.bas", source(&deep).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
    for (body, expected) in [
        ("EMIT []\n", "E0202"),
        ("EMIT [ASSERT_HEIGHT_ABSOLUTE(1)]\n", "E0202"),
        ("EMIT CREATE_COIN(1, 2)\n", "E0202"),
    ] {
        assert_eq!(
            check("condition.bas", source(body).as_bytes())
                .unwrap_err()
                .code,
            expected
        );
    }
}

#[test]
fn reusing_conditions_avoids_repeating_constructor_work_and_keeps_abi_guards() {
    let shared = "DIM c = ASSERT_HEIGHT_ABSOLUTE(2 + 3)\nEMIT c\nEMIT c\n";
    let duplicated = "EMIT ASSERT_HEIGHT_ABSOLUTE(2 + 3)\nEMIT ASSERT_HEIGHT_ABSOLUTE(2 + 3)\n";
    let once = run(shared, clvm::DEFAULT_MAX_COST).unwrap();
    let twice = run(duplicated, clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(once.bytes, twice.bytes);
    assert!(once.cost < twice.cost);
    let compiled = compile("condition.bas", source(shared).as_bytes()).unwrap();
    assert_eq!(
        clvm::execute(&compiled.puzzle, &[1], clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}
