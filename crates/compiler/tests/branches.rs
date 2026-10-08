use oxbasic_compiler::{check, clvm, compile};

fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn run(body: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let compiled = compile("branch.bas", source(body).as_bytes())?;
    clvm::execute(&compiled.puzzle, &[0x80], cost)
}
fn expect_heights(body: &str, heights: &[u32]) {
    let reference: String = heights
        .iter()
        .map(|n| format!("EMIT ASSERT_HEIGHT_ABSOLUTE({n})\n"))
        .collect();
    assert_eq!(
        run(body, clvm::DEFAULT_MAX_COST).unwrap().bytes,
        run(&reference, clvm::DEFAULT_MAX_COST).unwrap().bytes,
        "{body}"
    );
}

#[test]
fn only_selected_branch_executes_and_outer_updates_merge() {
    for (predicate, expected) in [("TRUE", 20), ("FALSE", 30)] {
        let body = format!(
            "DIM h = 10\nIF {predicate} THEN\nh = 20\nELSE\nh = 30\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n"
        );
        expect_heights(&body, &[expected]);
    }
    expect_heights(
        "DIM h = 10\nIF FALSE THEN\nh = 99\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nIF TRUE THEN\nh = h + 5\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n",
        &[10, 15],
    );
    expect_heights(
        "IF FALSE THEN\nASSERT FALSE\nDIM c = ASSERT_HEIGHT_ABSOLUTE(-1)\nELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(1)\nEND IF\n",
        &[1],
    );
    assert_eq!(
        run(
            "IF TRUE THEN\nDIM unused = ASSERT_HEIGHT_ABSOLUTE(-1)\nEND IF\n",
            clvm::DEFAULT_MAX_COST
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
}

#[test]
fn nested_emissions_keep_source_order_and_empty_branches_emit_nothing() {
    let body = "EMIT ASSERT_HEIGHT_ABSOLUTE(1)\nIF TRUE THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(2)\nIF FALSE THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(99)\nELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(3)\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(4)\nELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(98)\nEND IF\nIF TRUE THEN\nELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(97)\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(5)\n";
    expect_heights(body, &[1, 2, 3, 4, 5]);
    expect_heights(
        "IF FALSE THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(1)\nEND IF\nIF TRUE THEN\nEND IF\n",
        &[],
    );
    expect_heights(
        "IF FALSE THEN\nELSE\nIF TRUE THEN\nELSE\nEND IF\nEND IF\n",
        &[],
    );
}

#[test]
fn updates_preserve_types_captures_and_nested_outer_state() {
    let body = "DIM height = 10\nDIM condition = ASSERT_HEIGHT_ABSOLUTE(1)\nDIM enabled = TRUE\nDIM saved = condition\nIF enabled THEN\nDIM extra = 5\nIF TRUE THEN\nheight = height + extra\ncondition = ASSERT_HEIGHT_ABSOLUTE(height)\nenabled = FALSE\nEND IF\nELSE\nheight = 99\nEND IF\nASSERT NOT enabled\nEMIT condition\nEMIT saved\nEMIT ASSERT_HEIGHT_ABSOLUTE(height)\n";
    // 'condition' is reserved, so use an ordinary local name.
    expect_heights(&body.replace("condition", "pending"), &[15, 1, 15]);
    expect_heights(
        "DIM a = 1\nDIM z = 2\nIF FALSE THEN\na = 3\nELSE\nz = 4\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(a)\nEMIT ASSERT_HEIGHT_ABSOLUTE(z)\n",
        &[1, 4],
    );
    expect_heights(
        "DIM h = 1\nIF TRUE THEN\nDIM temporary = 2\nIF TRUE THEN\ntemporary = 3\nEND IF\nh = temporary\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n",
        &[3],
    );
}

#[test]
fn sibling_scopes_are_independent_and_outer_shadowing_is_rejected() {
    for predicate in ["TRUE", "FALSE"] {
        let body = format!(
            "CONST base = 10\nIF {predicate} THEN\nCONST local = base + 1\nDIM other = local\nEMIT ASSERT_HEIGHT_ABSOLUTE(other)\nELSE\nCONST local = base + 2\nDIM other = local\nEMIT ASSERT_HEIGHT_ABSOLUTE(other)\nEND IF\nDIM local = 13\nEMIT ASSERT_HEIGHT_ABSOLUTE(local)\n"
        );
        expect_heights(&body, &[if predicate == "TRUE" { 11 } else { 12 }, 13]);
    }
    for (body, code) in [
        ("DIM h = 1\nIF FALSE THEN\nDIM H = 2\nEND IF\n", "E0201"),
        (
            "IF TRUE THEN\nDIM hidden = 1\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(hidden)\n",
            "E0200",
        ),
        (
            "IF TRUE THEN\nDIM hidden = 1\nELSE\nASSERT hidden = 1\nEND IF\n",
            "E0200",
        ),
        (
            "CONST fixed = 1\nIF TRUE THEN\nfixed = 2\nEND IF\n",
            "E0203",
        ),
        (
            "IF TRUE THEN\nCONST scoped = 1\nEND IF\nCONST x = scoped\n",
            "E0200",
        ),
        ("IF TRUE THEN\nDIM Demo = 1\nEND IF\n", "E0201"),
    ] {
        assert_eq!(
            check("scope.bas", source(body).as_bytes())
                .unwrap_err()
                .code,
            code,
            "{body}"
        );
    }
}

#[test]
fn both_branches_are_checked_with_source_spans_and_strict_predicates() {
    for (body, code, token) in [
        ("IF 1 THEN\nEND IF\n", "E0202", "1"),
        (
            "IF TRUE THEN\nELSE\nASSERT missing\nEND IF\n",
            "E0200",
            "missing",
        ),
        (
            "DIM h = 1\nIF FALSE THEN\nh = TRUE\nEND IF\n",
            "E0202",
            "TRUE",
        ),
        ("IF FALSE THEN\nEMIT 1\nEND IF\n", "E0202", "1"),
        (
            "ASSERT FALSE\nIF TRUE THEN\nASSERT missing\nEND IF\n",
            "E0200",
            "missing",
        ),
    ] {
        let text = source(body);
        let error = check("branch.bas", text.as_bytes()).unwrap_err();
        assert_eq!(error.code, code);
        let span = error.span.unwrap();
        assert_eq!(&text[span.start_byte..span.end_byte], token);
    }
}

#[test]
fn skipped_work_has_no_runtime_cost_and_predicate_is_eager() {
    let huge = "9".repeat(500);
    let work = [huge.as_str(); 8].join(" * ");
    for body in [
        format!("IF FALSE THEN\nDIM unused = {work}\nEND IF\n"),
        format!("IF TRUE THEN\nELSE\nDIM unused = {work}\nEND IF\n"),
    ] {
        assert_eq!(run(&body, 10_000).unwrap().bytes, [0x80]);
    }
    for body in [
        format!("IF TRUE THEN\nDIM unused = {work}\nEND IF\n"),
        format!("IF {work} > 0 THEN\nEND IF\n"),
        format!("IF TRUE THEN\nDIM unused = {work}\nASSERT FALSE\nEND IF\n"),
    ] {
        assert_eq!(run(&body, 10_000).err().unwrap().code, "E0501");
    }
    assert_eq!(
        run(
            &format!("IF TRUE THEN\nASSERT FALSE\nDIM unused = {work}\nEND IF\n"),
            10_000
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    expect_heights(
        "IF FALSE AND (2 > 1) THEN\nASSERT FALSE\nELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(2)\nEND IF\n",
        &[2],
    );
}

#[test]
fn malformed_blocks_and_misplaced_else_if_are_rejected() {
    for body in [
        "IF TRUE\nEND IF\n",
        "IF TRUE THEN ASSERT TRUE\nEND IF\n",
        "IF TRUE THEN\n",
        "ELSE\n",
        "END IF\n",
        "IF TRUE THEN\nELSE\nELSE\nEND IF\n",
        "IF TRUE THEN\nEND CONTRACT\n",
    ] {
        assert_eq!(
            check("syntax.bas", source(body).as_bytes())
                .unwrap_err()
                .code,
            "E0100",
            "{body}"
        );
    }
    assert_eq!(
        check(
            "future.bas",
            source("IF TRUE THEN\nELSE\nELSEIF FALSE THEN\nEND IF\n").as_bytes()
        )
        .unwrap_err()
        .code,
        "E0100"
    );
}

#[test]
fn limits_count_both_branches_and_nested_blocks() {
    let nested = |n| format!("{}{}", "IF TRUE THEN\n".repeat(n), "END IF\n".repeat(n));
    expect_heights(&nested(32), &[]);
    assert_eq!(
        check("limits.bas", source(&nested(33)).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
    let branches = "IF TRUE THEN\nEND IF\n".repeat(256);
    assert!(check("limits.bas", source(&branches).as_bytes()).is_ok());
    assert_eq!(
        check(
            "limits.bas",
            source(&(branches + "IF TRUE THEN\nEND IF\n")).as_bytes()
        )
        .unwrap_err()
        .code,
        "E0205"
    );
    let emits = "EMIT ASSERT_HEIGHT_ABSOLUTE(1)\n".repeat(128);
    expect_heights(
        &format!("IF TRUE THEN\n{emits}ELSE\n{emits}END IF\n"),
        &[1; 128],
    );
    let body = format!("IF FALSE THEN\n{emits}{emits}EMIT ASSERT_HEIGHT_ABSOLUTE(1)\nEND IF\n");
    assert_eq!(
        check("limits.bas", source(&body).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
    let mut locals = String::new();
    for n in 0..513 {
        locals.push_str(&format!("DIM v{n} = 1\n"));
    }
    let body = format!("IF TRUE THEN\n{locals}ELSE\n{locals}END IF\n");
    assert_eq!(
        check("limits.bas", source(&body).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
}

#[test]
fn elseif_selects_first_match_and_preserves_updates_and_emission_order() {
    for a in [false, true] {
        for b in [false, true] {
            for c in [false, true] {
                let selected = if a {
                    1
                } else if b {
                    2
                } else if c {
                    3
                } else {
                    4
                };
                let body = format!(
                    "DIM h = 0\nEMIT ASSERT_HEIGHT_ABSOLUTE(9)\nIF {} THEN\nDIM local = 1\nh = local\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nELSEIF {} THEN\nDIM local = 2\nh = local\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nELSEIF {} THEN\nDIM local = 3\nh = local\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nELSE\nDIM local = 4\nh = local\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n",
                    a.to_string().to_uppercase(),
                    b.to_string().to_uppercase(),
                    c.to_string().to_uppercase()
                );
                expect_heights(&body, &[9, selected, selected]);
            }
        }
    }
    expect_heights(
        "DIM h = 7\nIF FALSE THEN\nh = 1\nELSEIF FALSE THEN\nh = 2\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(h)\n",
        &[7],
    );
    expect_heights(
        "IF TRUE THEN\nELSEIF TRUE THEN\nASSERT FALSE\nEND IF\n",
        &[],
    );
    expect_heights(
        "IF FALSE THEN\nELSEIF TRUE THEN\nIF FALSE THEN\nASSERT FALSE\nELSEIF TRUE THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(2)\nEND IF\nELSE\nASSERT FALSE\nEND IF\n",
        &[2],
    );
}

#[test]
fn elseif_skips_later_predicate_work_but_evaluates_reached_predicates() {
    let big = "9".repeat(500);
    let work = [big.as_str(); 8].join(" * ");
    for body in [
        format!("IF TRUE THEN\nELSEIF {work} > 0 THEN\nASSERT FALSE\nEND IF\n"),
        format!("IF FALSE THEN\nELSEIF TRUE THEN\nELSEIF {work} > 0 THEN\nASSERT FALSE\nEND IF\n"),
    ] {
        assert_eq!(run(&body, 10_000).unwrap().bytes, [0x80]);
    }
    for body in [
        format!("IF FALSE THEN\nELSEIF {work} > 0 THEN\nEND IF\n"),
        format!("IF FALSE THEN\nELSEIF FALSE THEN\nELSEIF {work} > 0 THEN\nEND IF\n"),
    ] {
        assert_eq!(run(&body, 10_000).err().unwrap().code, "E0501");
    }
    assert_eq!(
        run(
            "IF FALSE THEN\nELSEIF TRUE THEN\nASSERT FALSE\nELSEIF TRUE THEN\nEND IF\n",
            clvm::DEFAULT_MAX_COST
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
}

#[test]
fn elseif_checks_all_predicates_and_keeps_arm_scopes_separate() {
    for (body, code, token) in [
        ("IF TRUE THEN\nELSEIF 1 THEN\nEND IF\n", "E0202", "1"),
        (
            "IF TRUE THEN\nELSEIF missing THEN\nEND IF\n",
            "E0200",
            "missing",
        ),
        (
            "IF TRUE THEN\nDIM hidden = 1\nELSEIF hidden = 1 THEN\nEND IF\n",
            "E0200",
            "hidden",
        ),
        (
            "IF FALSE THEN\nELSEIF TRUE THEN\nDIM hidden = 1\nEND IF\nASSERT hidden = 1\n",
            "E0200",
            "hidden",
        ),
        (
            "DIM h = 1\nIF TRUE THEN\nELSEIF FALSE THEN\nDIM H = 2\nEND IF\n",
            "E0201",
            "H",
        ),
        (
            "DIM h = 1\nIF TRUE THEN\nELSEIF FALSE THEN\nh = TRUE\nEND IF\n",
            "E0202",
            "TRUE",
        ),
    ] {
        let text = source(body);
        let error = check("elseif.bas", text.as_bytes()).unwrap_err();
        assert_eq!(error.code, code);
        let span = error.span.unwrap();
        assert_eq!(&text[span.start_byte..span.end_byte], token);
    }
}

#[test]
fn elseif_requires_multiline_then_and_precedes_else() {
    for body in [
        "ELSEIF TRUE THEN\n",
        "IF FALSE THEN\nELSEIF TRUE\nEND IF\n",
        "IF FALSE THEN\nELSEIF THEN\nEND IF\n",
        "IF FALSE THEN\nELSEIF TRUE THEN ASSERT TRUE\nEND IF\n",
        "IF FALSE THEN\nELSE\nELSEIF TRUE THEN\nEND IF\n",
    ] {
        assert!(
            check("syntax.bas", source(body).as_bytes()).is_err(),
            "{body}"
        );
    }
    expect_heights(
        "if false then\nelseif (1 < 2 ' predicate comment\n) then\nEMIT ASSERT_HEIGHT_ABSOLUTE(3)\nend if\n",
        &[3],
    );
}

#[test]
fn elseif_decisions_share_depth_and_contract_budgets() {
    let chain = |n: usize| {
        format!(
            "IF FALSE THEN\n{}ELSE\nEMIT ASSERT_HEIGHT_ABSOLUTE(1)\nEND IF\n",
            "ELSEIF FALSE THEN\n".repeat(n - 1)
        )
    };
    expect_heights(&chain(32), &[1]);
    assert_eq!(
        check("limits.bas", source(&chain(33)).as_bytes())
            .unwrap_err()
            .code,
        "E0205"
    );
    assert!(check("limits.bas", source(&chain(32).repeat(8)).as_bytes()).is_ok());
    assert_eq!(
        check(
            "limits.bas",
            source(&(chain(32).repeat(8) + "IF TRUE THEN\nEND IF\n")).as_bytes()
        )
        .unwrap_err()
        .code,
        "E0205"
    );
}
