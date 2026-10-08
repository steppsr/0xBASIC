use oxbasic_compiler::{check, clvm, compile};

fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn run(body: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let compiled = compile("short.bas", source(body).as_bytes())?;
    clvm::execute(&compiled.puzzle, &[0x80], cost)
}
fn passes(body: &str) {
    assert_eq!(run(body, clvm::DEFAULT_MAX_COST).unwrap().bytes, [0x80]);
}

#[test]
fn truth_tables_precedence_and_nested_results_are_canonical() {
    for (a, ab) in [("TRUE", true), ("FALSE", false)] {
        for (b, bb) in [("TRUE", true), ("FALSE", false)] {
            for (op, expected) in [("AND", ab && bb), ("OR", ab || bb)] {
                for kind in ["DIM", "CONST"] {
                    let expected = if expected { "TRUE" } else { "FALSE" };
                    passes(&format!(
                        "{kind} result = {a} {op} {b}\nASSERT result = {expected}\n"
                    ));
                }
            }
        }
    }
    passes(
        "ASSERT TRUE OR FALSE AND FALSE\nASSERT NOT (FALSE OR TRUE AND FALSE)\nASSERT (TRUE OR FALSE) AND (FALSE OR TRUE)\nASSERT (TRUE AND (FALSE OR TRUE)) = TRUE\nASSERT FALSE OR FALSE OR TRUE\n",
    );
    passes(
        "CONST a = TRUE OR FALSE AND FALSE\nCONST b = NOT (FALSE OR TRUE AND FALSE)\nASSERT a AND b\n",
    );
}

#[test]
fn skipped_right_work_is_not_executed_but_selected_and_prior_work_is() {
    let huge = "9".repeat(500);
    let expensive = [huge.as_str(); 8].join(" * ");
    for (left, op) in [("FALSE", "AND"), ("TRUE", "OR")] {
        let body = format!("DIM b = {left} {op} ({expensive} > 0)\nASSERT b = {left}\n");
        assert_eq!(run(&body, 10_000).unwrap().bytes, [0x80]);
    }
    for body in [
        format!("DIM b = TRUE AND ({expensive} > 0)\n"),
        format!("DIM b = FALSE OR ({expensive} > 0)\n"),
        format!("DIM b = ({expensive} > 0) OR TRUE\n"),
        format!("DIM expensive = {expensive} > 0\nDIM b = FALSE AND expensive\n"),
        format!("ASSERT FALSE OR (TRUE AND ({expensive} > 0))\n"),
    ] {
        assert_eq!(run(&body, 10_000).err().unwrap().code, "E0501");
    }
    let body = format!("ASSERT TRUE OR (FALSE OR ({expensive} > 0))\n");
    assert_eq!(run(&body, 10_000).unwrap().bytes, [0x80]);
}

#[test]
fn branch_local_bindings_do_not_corrupt_captures_or_later_statements() {
    let body = "DIM h = 10\nDIM yes = TRUE\nDIM no = FALSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nDIM selected = yes AND (no OR (h + 5 = 15))\nDIM captured = selected OR no\nASSERT selected\nselected = no OR (yes AND (h = 10))\nh = h + 5\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nASSERT selected AND captured\nASSERT (no OR yes) AND (yes OR no)\nASSERT yes AND yes\nASSERT no OR yes\nASSERT (no AND yes) = FALSE\n";
    let expected = run(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(10)\nEMIT ASSERT_HEIGHT_ABSOLUTE(15)\n",
        clvm::DEFAULT_MAX_COST,
    )
    .unwrap();
    assert_eq!(
        run(body, clvm::DEFAULT_MAX_COST).unwrap().bytes,
        expected.bytes
    );
    assert_eq!(
        run("ASSERT FALSE AND TRUE\n", clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}

#[test]
fn skipped_operands_still_require_valid_names_types_and_constant_dependencies() {
    for (body, code) in [
        ("ASSERT TRUE OR missing\n", "E0200"),
        ("DIM b = FALSE AND 1\n", "E0202"),
        ("ASSERT 0 OR TRUE\n", "E0202"),
        ("CONST b = TRUE OR 0\n", "E0202"),
        ("DIM a = TRUE\nCONST b = TRUE OR a\n", "E0205"),
        ("CONST b = FALSE AND missing\n", "E0200"),
        ("CONST b = TRUE OR Helper(1)\n", "E0205"),
        ("ASSERT FALSE\nDIM b = TRUE OR 1\n", "E0202"),
    ] {
        assert_eq!(
            check("short.bas", source(body).as_bytes())
                .unwrap_err()
                .code,
            code,
            "{body}"
        );
    }
}

#[test]
fn constants_skip_evaluation_but_preserve_syntax_and_work_limits() {
    let large = format!("&H8{}", "0".repeat(4095));
    let computation = format!("({large} * {large} * 4 > 0)");
    passes(&format!("CONST b = TRUE OR {computation}\nASSERT b\n"));
    passes(&format!(
        "CONST b = FALSE AND {computation}\nASSERT NOT b\n"
    ));
    let error = check(
        "short.bas",
        source(&format!("CONST b = FALSE OR {computation}\n")).as_bytes(),
    )
    .unwrap_err();
    assert!(error.message.contains("32768"));
    let bad_literal = format!("CONST b = TRUE OR ({} > 0)\n", "9".repeat(4097));
    assert!(
        check("short.bas", source(&bad_literal).as_bytes())
            .unwrap_err()
            .message
            .contains("4096 digits")
    );
    let rhs = ["TRUE"; 32].join(" OR ");
    let mut body = String::new();
    for n in 0..260 {
        body.push_str(&format!("CONST b{n} = TRUE OR ({rhs})\n"));
    }
    assert!(
        check("short.bas", source(&body).as_bytes())
            .unwrap_err()
            .message
            .contains("16384")
    );
}

#[test]
fn branch_values_count_toward_the_global_binding_limit() {
    let mut body = String::new();
    for n in 0..400 {
        body.push_str(&format!("DIM b{n} = TRUE OR (1 + 2 + 3 + 4 > 0)\n"));
    }
    assert_eq!(
        check("short.bas", source(&body).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
}
