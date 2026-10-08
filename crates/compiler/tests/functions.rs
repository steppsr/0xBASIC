use oxbasic_compiler::{check, clvm, compile};

fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn execute(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let program = compile("functions.bas", source(body, functions).as_bytes())?;
    clvm::execute(&program.puzzle, &[0x80], cost)
}
fn heights(body: &str, functions: &str, expected: &[u32]) {
    let reference: String = expected
        .iter()
        .map(|n| format!("EMIT ASSERT_HEIGHT_ABSOLUTE({n})\n"))
        .collect();
    assert_eq!(
        execute(body, functions, clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        execute(&reference, "", clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes
    );
}

#[test]
fn calls_forward_resolve_and_preserve_parameter_order_and_types() {
    heights(
        "EMIT Make(Sub(200, 50))\nEMIT Echo(Make(9))\nASSERT Invert(FALSE)\n",
        "FUNCTION Make(n AS INTEGER) AS CONDITION\nRETURN ASSERT_HEIGHT_ABSOLUTE(n)\nEND FUNCTION\nFUNCTION Sub(a AS INTEGER, b AS INTEGER) AS INTEGER\nRETURN a - b\nEND FUNCTION\nFUNCTION Echo(c AS CONDITION) AS CONDITION\nRETURN c\nEND FUNCTION\nFUNCTION Invert(b AS BOOLEAN) AS BOOLEAN\nRETURN NOT b\nEND FUNCTION\n",
        &[150, 9],
    );
    heights(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(Zero())\n",
        "FUNCTION Zero() AS INTEGER\nRETURN 0\nEND FUNCTION\n",
        &[0],
    );
    let compiled = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-functions.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&compiled.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        execute(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(100)\nEMIT ASSERT_HEIGHT_ABSOLUTE(0)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}

#[test]
fn private_function_scopes_merge_branches_and_preserve_caller_snapshots() {
    let functions = "FUNCTION SelectHeight(n AS INTEGER) AS INTEGER\nCONST extra = 5\nDIM value = n\nIF n < 10 THEN\nvalue = value + extra\nELSEIF n < 20 THEN\nvalue = Twice(value)\nELSE\nvalue = 0\nEND IF\nRETURN value\nEND FUNCTION\nFUNCTION Twice(n AS INTEGER) AS INTEGER\nRETURN n + n\nEND FUNCTION\n";
    heights(
        "DIM value = 7\nDIM old = SelectHeight(value)\nvalue = 15\nEMIT ASSERT_HEIGHT_ABSOLUTE(old)\nEMIT ASSERT_HEIGHT_ABSOLUTE(SelectHeight(value))\nEMIT ASSERT_HEIGHT_ABSOLUTE(SelectHeight(25))\nEMIT ASSERT_HEIGHT_ABSOLUTE(value)\n",
        functions,
        &[12, 30, 0, 15],
    );
}

#[test]
fn calls_are_eager_even_when_arguments_or_results_are_unused() {
    let functions = "FUNCTION Ignore(c AS CONDITION) AS INTEGER\nRETURN 1\nEND FUNCTION\nFUNCTION Fail() AS INTEGER\nASSERT FALSE\nRETURN 1\nEND FUNCTION\nFUNCTION BadLocal() AS INTEGER\nDIM unused = ASSERT_HEIGHT_ABSOLUTE(-1)\nRETURN 1\nEND FUNCTION\n";
    for body in [
        "DIM unused = Ignore(ASSERT_HEIGHT_ABSOLUTE(-1))\n",
        "DIM unused = Fail()\n",
        "DIM unused = BadLocal()\n",
        "DIM n = 1\nn = Fail()\nn = 2\n",
    ] {
        assert_eq!(
            execute(body, functions, clvm::DEFAULT_MAX_COST)
                .err()
                .unwrap()
                .code,
            "E0500"
        );
    }
}

#[test]
fn skipped_calls_do_not_execute_and_selected_calls_do() {
    let functions = "FUNCTION Fail() AS BOOLEAN\nASSERT FALSE\nRETURN TRUE\nEND FUNCTION\n";
    for body in [
        "ASSERT TRUE OR Fail()\n",
        "ASSERT NOT (FALSE AND Fail())\n",
        "IF FALSE THEN\nASSERT Fail()\nELSE\nASSERT TRUE\nEND IF\n",
    ] {
        heights(body, functions, &[]);
    }
    for body in [
        "ASSERT FALSE OR Fail()\n",
        "ASSERT TRUE AND Fail()\n",
        "IF TRUE THEN\nASSERT Fail()\nEND IF\n",
    ] {
        assert_eq!(
            execute(body, functions, clvm::DEFAULT_MAX_COST)
                .err()
                .unwrap()
                .code,
            "E0500"
        );
    }
}

#[test]
fn arguments_evaluate_left_to_right_before_entering_the_callee() {
    let work = vec!["9".repeat(500); 8].join(" * ");
    let functions = format!(
        "FUNCTION Expensive() AS INTEGER\nRETURN {work}\nEND FUNCTION\nFUNCTION Fail() AS INTEGER\nASSERT FALSE\nRETURN 1\nEND FUNCTION\nFUNCTION Ignore(a AS INTEGER, b AS INTEGER) AS INTEGER\nASSERT FALSE\nRETURN 1\nEND FUNCTION\n"
    );
    // A budget failure instead of ASSERT's raise reveals which argument ran first.
    assert_eq!(
        execute("DIM n = Ignore(Fail(), Expensive())\n", &functions, 10_000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_eq!(
        execute("DIM n = Ignore(Expensive(), Fail())\n", &functions, 10_000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}

#[test]
fn parameter_references_reuse_evaluated_arguments() {
    let work = vec!["99999999"; 48].join(" + ");
    let functions = format!(
        "FUNCTION Work() AS INTEGER\nRETURN {work}\nEND FUNCTION\nFUNCTION Many(n AS INTEGER) AS BOOLEAN\nRETURN n = n AND n = n AND n = n\nEND FUNCTION\n"
    );
    let one = execute(
        "DIM n = Work()\nASSERT n = n AND n = n AND n = n\n",
        &functions,
        clvm::DEFAULT_MAX_COST,
    )
    .unwrap();
    let call = execute("ASSERT Many(Work())\n", &functions, clvm::DEFAULT_MAX_COST).unwrap();
    assert!(call.cost > one.cost);
    assert!(
        call.cost - one.cost < 10_000,
        "argument work was duplicated: {} vs {}",
        call.cost,
        one.cost
    );
    assert_eq!(
        execute("ASSERT Many(Work())\n", &functions, call.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}

#[test]
fn compilation_enforces_function_semantics() {
    for (functions, code) in [
        (
            "FUNCTION F() AS INTEGER\nRETURN F()\nEND FUNCTION\n",
            "E0206",
        ),
        (
            "FUNCTION F(n AS INTEGER) AS INTEGER\nn = 1\nRETURN n\nEND FUNCTION\n",
            "E0203",
        ),
        (
            "FUNCTION F() AS INTEGER\nEMIT ASSERT_HEIGHT_ABSOLUTE(1)\nRETURN 1\nEND FUNCTION\n",
            "E0205",
        ),
        (
            "FUNCTION F() AS INTEGER\nRETURN TRUE\nEND FUNCTION\n",
            "E0202",
        ),
        (
            "FUNCTION F() AS INTEGER\nDIM n = 1\nEND FUNCTION\n",
            "E0204",
        ),
        (
            "FUNCTION F() AS INTEGER\nRETURN 1\nASSERT unknown\nEND FUNCTION\n",
            "E0200",
        ),
    ] {
        assert_eq!(
            check("invalid.bas", source("", functions).as_bytes())
                .unwrap_err()
                .code,
            code
        );
    }
}

#[test]
fn function_artifacts_are_deterministic_and_keep_empty_abi_guards() {
    let source = source(
        "EMIT H(100)\n",
        "FUNCTION H(n AS INTEGER) AS CONDITION\nRETURN ASSERT_HEIGHT_ABSOLUTE(n)\nEND FUNCTION\n",
    );
    let a = compile("a.bas", source.as_bytes()).unwrap();
    let b = compile("b.bas", source.to_ascii_lowercase().as_bytes()).unwrap();
    assert_eq!(a.puzzle, b.puzzle);
    for raw in ["01", "ff0180", "ff8080"] {
        assert_eq!(
            clvm::execute(
                &a.puzzle,
                &hex::decode(raw).unwrap(),
                clvm::DEFAULT_MAX_COST
            )
            .err()
            .unwrap()
            .code,
            "E0500"
        );
    }
}

#[test]
fn function_chains_parameters_and_generated_size_are_bounded() {
    let chain: String = (0..256)
        .map(|i| {
            let value = if i == 255 {
                "9".to_owned()
            } else {
                format!("F{}()", i + 1)
            };
            format!("FUNCTION F{i}() AS INTEGER\nRETURN {value}\nEND FUNCTION\n")
        })
        .collect();
    heights("EMIT ASSERT_HEIGHT_ABSOLUTE(F0())\n", &chain, &[9]);
    let parameters = (0..32)
        .map(|i| format!("p{i} AS INTEGER"))
        .collect::<Vec<_>>()
        .join(",");
    let arguments = (0..32).map(|i| i.to_string()).collect::<Vec<_>>().join(",");
    heights(
        &format!("EMIT ASSERT_HEIGHT_ABSOLUTE(Many({arguments}))\n"),
        &format!("FUNCTION Many({parameters}) AS INTEGER\nRETURN p31 - p0\nEND FUNCTION\n"),
        &[31],
    );
    for (count, passes) in [(600, true), (700, false)] {
        let functions: String = ["F", "G"]
            .iter()
            .map(|name| {
                format!(
                    "FUNCTION {name}() AS INTEGER\nDIM n = 0\n{}RETURN n\nEND FUNCTION\n",
                    "n = n + 1\n".repeat(count)
                )
            })
            .collect();
        let result = check("bindings.bas", source("", &functions).as_bytes());
        if passes {
            result.unwrap();
        } else {
            assert_eq!(result.unwrap_err().code, "E0205");
        }
    }
    // Traditional CLVM serialization expands repeated quoted callees. The
    // existing byte limit must stop this small, exponentially expanding DAG.
    let dag: String = (0..24)
        .map(|i| {
            let value = if i == 23 {
                "1".to_owned()
            } else {
                format!("F{}() + F{}()", i + 1, i + 1)
            };
            format!("FUNCTION F{i}() AS INTEGER\nRETURN {value}\nEND FUNCTION\n")
        })
        .collect();
    assert_eq!(
        compile("size.bas", source("DIM n = F0()\n", &dag).as_bytes())
            .err()
            .unwrap()
            .code,
        "E0205"
    );
}

#[test]
fn top_level_return_skips_checked_continuations_without_changing_program_identity() {
    for (ty, value, body) in [
        ("INTEGER", "17", "EMIT ASSERT_HEIGHT_ABSOLUTE(F())\n"),
        ("BOOLEAN", "TRUE", "ASSERT F()\n"),
        ("CONDITION", "ASSERT_HEIGHT_ABSOLUTE(100)", "EMIT F()\n"),
    ] {
        let prefix = format!("FUNCTION F() AS {ty}\nRETURN {value}\n");
        let baseline = compile(
            "base.bas",
            source(body, &format!("{prefix}END FUNCTION\n")).as_bytes(),
        )
        .unwrap();
        let tail = format!(
            "ASSERT FALSE\nDIM unused = ASSERT_HEIGHT_ABSOLUTE(-1)\nIF TRUE THEN\nRETURN {value}\nEND IF\nRETURN {value}\n"
        );
        let early = compile(
            "early.bas",
            source(body, &format!("{prefix}{tail}END FUNCTION\n")).as_bytes(),
        )
        .unwrap();
        assert_eq!(early.template, baseline.template);
        assert_eq!(early.puzzle, baseline.puzzle);
        let result = clvm::execute(&early.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
        let reference = clvm::execute(&baseline.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
        assert_eq!(result.bytes, reference.bytes);
        assert_eq!(result.cost, reference.cost);
    }
}

#[test]
fn early_return_preserves_prior_work_and_return_expression_failures() {
    heights(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(F(5))\n",
        "FUNCTION F(n AS INTEGER) AS INTEGER\nDIM x = n\nIF n > 0 THEN\nx = x + 2\nEND IF\nRETURN x\nx = 100\nASSERT FALSE\nEND FUNCTION\n",
        &[7],
    );
    for functions in [
        "FUNCTION F() AS CONDITION\nASSERT FALSE\nRETURN ASSERT_HEIGHT_ABSOLUTE(100)\nRETURN ASSERT_HEIGHT_ABSOLUTE(1)\nEND FUNCTION\n",
        "FUNCTION F() AS CONDITION\nRETURN ASSERT_HEIGHT_ABSOLUTE(-1)\nRETURN ASSERT_HEIGHT_ABSOLUTE(1)\nEND FUNCTION\n",
    ] {
        assert_eq!(
            execute("EMIT F()\n", functions, clvm::DEFAULT_MAX_COST)
                .err()
                .unwrap()
                .code,
            "E0500"
        );
    }
    let example = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-early-return.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&example.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        execute(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(100)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}

#[test]
fn abandoned_continuations_still_enforce_semantics_and_source_limits() {
    for (tail, code) in [
        ("RETURN missing\n", "E0200"),
        ("RETURN TRUE\n", "E0202"),
        ("DIM n = F()\n", "E0206"),
        ("EMIT ASSERT_HEIGHT_ABSOLUTE(1)\n", "E0205"),
        ("CONST n = F()\n", "E0205"),
        ("IF TRUE THEN\nDIM n = missing\nEND IF\n", "E0200"),
        ("DIM n =\n", "E0100"),
    ] {
        let text = source(
            "",
            &format!("FUNCTION F() AS INTEGER\nRETURN 1\n{tail}END FUNCTION\n"),
        );
        assert_eq!(
            check("unreachable.bas", text.as_bytes()).unwrap_err().code,
            code
        );
    }
    let text = source(
        "",
        &format!(
            "FUNCTION F() AS INTEGER\nRETURN 1\n{}END FUNCTION\n",
            "ASSERT TRUE\n".repeat(4097)
        ),
    );
    assert_eq!(
        check("limits.bas", text.as_bytes()).unwrap_err().code,
        "E0205"
    );
}

#[test]
fn branch_returns_propagate_through_nested_chains_and_preserve_updates() {
    let functions = "FUNCTION F(n AS INTEGER) AS INTEGER\nDIM x = n\nIF n < 10 THEN\nIF n = 0 THEN\nRETURN 0\nELSE\nx = x + 1\nEND IF\nELSEIF n < 20 THEN\nRETURN 17\nELSE\nx = 30\nEND IF\nDIM later = x + 2\nIF later > 30 THEN\nRETURN later\nEND IF\nRETURN later + 1\nASSERT FALSE\nEND FUNCTION\n";
    for (n, expected) in [(0, 0), (5, 9), (15, 17), (25, 32)] {
        heights(
            &format!("EMIT ASSERT_HEIGHT_ABSOLUTE(F({n}))\n"),
            functions,
            &[expected],
        );
    }
    heights(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(F(TRUE))\nEMIT ASSERT_HEIGHT_ABSOLUTE(F(FALSE))\n",
        "FUNCTION F(b AS BOOLEAN) AS INTEGER\nIF b THEN\nRETURN 1\nELSE\nRETURN 2\nEND IF\nEND FUNCTION\n",
        &[1, 2],
    );
}

#[test]
fn false_and_condition_returns_are_distinct_from_fallthrough() {
    heights(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(Outer(TRUE))\nEMIT ASSERT_HEIGHT_ABSOLUTE(Outer(FALSE))\n",
        "FUNCTION Outer(b AS BOOLEAN) AS INTEGER\nIF b THEN\nRETURN Inner(FALSE) + 1\nEND IF\nRETURN Inner(TRUE) + 2\nEND FUNCTION\nFUNCTION Inner(b AS BOOLEAN) AS INTEGER\nIF b THEN\nRETURN 0\nELSE\nRETURN 10\nEND IF\nEND FUNCTION\n",
        &[11, 2],
    );
    heights(
        "ASSERT NOT F(TRUE)\nASSERT F(FALSE)\nEMIT H(TRUE)\nEMIT H(FALSE)\n",
        "FUNCTION F(b AS BOOLEAN) AS BOOLEAN\nIF b THEN\nRETURN FALSE\nEND IF\nRETURN TRUE\nEND FUNCTION\nFUNCTION H(b AS BOOLEAN) AS CONDITION\nIF b THEN\nRETURN ASSERT_HEIGHT_ABSOLUTE(0)\nELSE\nRETURN ASSERT_HEIGHT_ABSOLUTE(10)\nEND IF\nASSERT FALSE\nEND FUNCTION\n",
        &[0, 10],
    );
}

#[test]
fn returned_paths_skip_failure_and_work_but_continuing_paths_do_not() {
    let work = vec!["9".repeat(500); 8].join(" * ");
    let functions = format!(
        "FUNCTION F(b AS BOOLEAN) AS INTEGER\nIF b THEN\nRETURN 1\nASSERT FALSE\nEND IF\nDIM n = {work}\nRETURN 2\nEND FUNCTION\n"
    );
    assert!(execute("EMIT ASSERT_HEIGHT_ABSOLUTE(F(TRUE))\n", &functions, 10_000).is_ok());
    assert_eq!(
        execute(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(F(FALSE))\n",
            &functions,
            10_000
        )
        .err()
        .unwrap()
        .code,
        "E0501"
    );
    let functions = "FUNCTION F(b AS BOOLEAN) AS INTEGER\nIF b THEN\nRETURN 1\nEND IF\nASSERT FALSE\nRETURN 2\nEND FUNCTION\n";
    heights("EMIT ASSERT_HEIGHT_ABSOLUTE(F(TRUE))\n", functions, &[1]);
    assert_eq!(
        execute("DIM unused = F(FALSE)\n", functions, clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    for body in [
        "ASSERT FALSE\n",
        "IF TRUE THEN\nRETURN 1\nEND IF\n",
        "IF FALSE THEN\nRETURN 2\nELSE\nASSERT FALSE\nEND IF\n",
    ] {
        let functions = format!("FUNCTION F() AS INTEGER\n{body}END FUNCTION\n");
        let result = execute("DIM n = F()\n", &functions, clvm::DEFAULT_MAX_COST);
        if body.contains("IF TRUE") {
            result.unwrap();
        } else {
            assert_eq!(result.err().unwrap().code, "E0500");
        }
    }
}

#[test]
fn branch_return_scope_and_unreachable_checks_remain_strict() {
    for (body, code) in [
        (
            "IF b THEN\nRETURN 1\nASSERT absent\nEND IF\nRETURN 2\n",
            "E0200",
        ),
        ("IF b THEN\nRETURN TRUE\nEND IF\nRETURN 2\n", "E0202"),
        ("IF b THEN\nRETURN F(b)\nEND IF\nRETURN 2\n", "E0206"),
        (
            "IF b THEN\nDIM hidden = 1\nRETURN hidden\nEND IF\nRETURN hidden\n",
            "E0200",
        ),
        ("IF b THEN\nRETURN 1\nEND IF\n", "E0204"),
    ] {
        assert_eq!(
            check(
                "bad.bas",
                source(
                    "",
                    &format!("FUNCTION F(b AS BOOLEAN) AS INTEGER\n{body}END FUNCTION\n")
                )
                .as_bytes()
            )
            .unwrap_err()
            .code,
            code
        );
    }
    heights(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(F(FALSE))\n",
        "FUNCTION F(b AS BOOLEAN) AS INTEGER\nIF b THEN\nDIM n = 1\nRETURN n\nEND IF\nDIM n = 2\nRETURN n\nEND FUNCTION\n",
        &[2],
    );
}

#[test]
fn return_continuation_lowering_has_a_bounded_depth() {
    let branch = "IF FALSE THEN\nRETURN 1\nEND IF\n";
    let functions = format!(
        "FUNCTION F() AS INTEGER\n{}RETURN 2\nEND FUNCTION\n",
        branch.repeat(63)
    );
    heights("EMIT ASSERT_HEIGHT_ABSOLUTE(F())\n", &functions, &[2]);
    let functions = format!(
        "FUNCTION F() AS INTEGER\n{}RETURN 2\nEND FUNCTION\n",
        branch.repeat(70)
    );
    let error = check("depth.bas", source("", &functions).as_bytes()).unwrap_err();
    assert_eq!(error.code, "E0205");
    assert!(error.message.contains("64"));
}
