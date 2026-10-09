use oxbasic_compiler::{check, clvm, compile};

#[test]
fn ordered_statement_refactor_preserves_all_existing_example_programs() {
    // Captured with m2.4c before changing the parser/lowerer, not regenerated
    // from the implementation under test. Preserve program identity and cost.
    let baseline: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/m2-4c-examples.json")).unwrap();
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let cases = baseline["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 9);
    for case in cases {
        let name = case["source"].as_str().unwrap();
        let source = std::fs::read(root.join(name)).unwrap();
        assert_eq!(
            clvm::sha256(&source),
            case["source_sha256"],
            "source changed: {name}"
        );
        let compiled = compile(name, &source).unwrap();
        assert_eq!(
            clvm::sha256(&compiled.template),
            case["template_sha256"],
            "{name}"
        );
        assert_eq!(
            clvm::sha256(&compiled.puzzle),
            case["puzzle_sha256"],
            "{name}"
        );
        assert_eq!(
            clvm::tree_hash(&compiled.puzzle).unwrap(),
            case["tree_hash"],
            "{name}"
        );
        let execution = clvm::execute(&compiled.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
        assert_eq!(execution.cost.to_string(), case["cost"], "{name}");
        assert_eq!(execution.tree, case["tree"], "{name}");
    }
}

#[test]
fn interleaved_statements_report_the_first_semantic_failure_in_source_order() {
    for (body, expected_code, token) in [
        ("ASSERT missing\nDIM bad = absent\n", "E0200", "missing"),
        ("EMIT missing\nCONST bad = absent\n", "E0200", "missing"),
        (
            "DIM n = 1\nASSERT TRUE\nEMIT ASSERT_HEIGHT_ABSOLUTE(n)\nn = FALSE\nASSERT absent\n",
            "E0202",
            "FALSE",
        ),
        (
            "CONST n = 1\nEMIT ASSERT_HEIGHT_ABSOLUTE(n)\nASSERT FALSE\nDIM bad = absent\n",
            "E0200",
            "absent",
        ),
    ] {
        let source = format!("CONTRACT Ordered()\n{body}END CONTRACT\n");
        let error = check("ordered.bas", source.as_bytes()).unwrap_err();
        assert_eq!(error.code, expected_code);
        let span = error.span.unwrap();
        assert_eq!(&source[span.start_byte..span.end_byte], token);
    }
}

#[test]
fn unknown_functions_are_rejected_by_check_and_compile() {
    for expression in ["Helper(1)", "NOT Helper(1)"] {
        let source =
            format!("CONTRACT Demo()\n EMIT ASSERT_HEIGHT_ABSOLUTE({expression})\nEND CONTRACT\n");
        for error in [
            check("future.bas", source.as_bytes()).unwrap_err(),
            compile("future.bas", source.as_bytes()).err().unwrap(),
        ] {
            assert_eq!(error.code, "E0200", "{expression}");
            assert_eq!(error.span.unwrap().line, 2);
        }
    }
}

#[test]
fn independently_assembled_golden_matches() {
    let golden: serde_json::Value =
        serde_json::from_str(include_str!("fixtures/m1-height.json")).unwrap();
    let c = compile(
        "reference.bas",
        golden["source"].as_str().unwrap().as_bytes(),
    )
    .unwrap();
    assert_eq!(hex::encode(&c.template), golden["template_hex"]);
    assert_eq!(hex::encode(&c.puzzle), golden["puzzle_hex"]);
    assert_eq!(
        clvm::tree_hash(&c.template).unwrap(),
        golden["template_tree_hash"]
    );
    assert_eq!(
        clvm::tree_hash(&c.puzzle).unwrap(),
        golden["puzzle_tree_hash"]
    );
    let execution = clvm::execute(&c.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(hex::encode(execution.bytes), golden["result_hex"]);
    assert_eq!(execution.cost.to_string(), golden["cost"]);
}

fn compiled(body: &str) -> oxbasic_compiler::Compiled {
    compile(
        "fixture.bas",
        format!("CONTRACT Fixture()\n{body}END CONTRACT\n").as_bytes(),
    )
    .unwrap()
}

#[test]
fn empty_and_ordered_conditions_execute() {
    let empty = compiled("");
    assert_ne!(empty.template, empty.puzzle);
    assert_eq!(
        clvm::execute(&empty.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        [0x80]
    );
    let heights = compiled(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(128)\nEMIT ASSERT_HEIGHT_ABSOLUTE(0)\nEMIT ASSERT_HEIGHT_ABSOLUTE(&HFFFFFFFF)\n",
    );
    let output = clvm::execute(&heights.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    // Independently hand-encoded proper list ((83 128) (83 0) (83 4294967295)).
    assert_eq!(
        hex::encode(output.bytes),
        "ffff53ff82008080ffff53ff8080ffff53ff8500ffffffff8080"
    );
    assert!(output.cost > 0);
    assert_eq!(
        clvm::execute(&heights.puzzle, &[0x80], output.cost)
            .unwrap()
            .cost,
        output.cost
    );
    assert_eq!(
        clvm::execute(&heights.puzzle, &[0x80], output.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}

#[test]
fn raw_solutions_cannot_bypass_boundary_guards() {
    let c = compiled("");
    for raw in ["01", "ff0180", "ff8001", "ff8080"] {
        assert_eq!(
            clvm::execute(
                &c.puzzle,
                &hex::decode(raw).unwrap(),
                clvm::DEFAULT_MAX_COST
            )
            .err()
            .unwrap()
            .code,
            "E0500",
            "{raw}"
        );
    }
    for raw in ["80", "ff0180", "ff80ff0180"] {
        assert!(
            clvm::execute(
                &c.template,
                &hex::decode(raw).unwrap(),
                clvm::DEFAULT_MAX_COST
            )
            .is_err()
        );
    }
    assert_eq!(
        clvm::execute(
            &c.template,
            &hex::decode("ff8080").unwrap(),
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes,
        [0x80]
    );
    for raw in ["", "8080", "8100", "ff80"] {
        assert_eq!(
            clvm::execute(
                &c.puzzle,
                &hex::decode(raw).unwrap(),
                clvm::DEFAULT_MAX_COST
            )
            .err()
            .unwrap()
            .code,
            "E0300"
        );
    }
}

#[test]
fn formatting_does_not_change_program_identity() {
    let plain = compiled("EMIT ASSERT_HEIGHT_ABSOLUTE(10)\n");
    let formatted = compile("with spaces.bas", "\u{feff}rem a comment\r\ncontract fixture(\r\n) ' header\r\n\tEmIt assert_height_absolute(\r\n&H0A)\r\nend contract".as_bytes()).unwrap();
    assert_eq!(plain.template, formatted.template);
    assert_eq!(plain.puzzle, formatted.puzzle);
    assert_eq!(clvm::bind_empty(&plain.template).unwrap(), plain.puzzle);
    assert_eq!(clvm::tree_hash(&plain.puzzle).unwrap().len(), 64);
    assert_ne!(
        clvm::tree_hash(&plain.puzzle).unwrap(),
        clvm::sha256(&plain.puzzle)
    );
}

#[test]
fn unsupported_and_invalid_source_is_rejected_with_locations() {
    for body in [
        "SOLUTION x AS DOUBLE\n",
        "ELSEIF TRUE THEN\n",
        "EMIT CREATE_COIN(0x, 1)\n",
        "EMIT ASSERT_HEIGHT_ABSOLUTE(TRUE)\n",
        "EMIT ASSERT_HEIGHT_ABSOLUTE(1 < 2)\n",
    ] {
        let err = compile(
            "bad.bas",
            format!("CONTRACT Demo()\n{body}END CONTRACT\n").as_bytes(),
        )
        .err()
        .unwrap();
        assert_eq!(err.source.as_deref(), Some("bad.bas"));
        assert_eq!(err.span.unwrap().line, 2);
    }
    for text in [
        "",
        "CONTRACT Demo()",
        "CONTRACT Demo()\nEND CONTRACT\nCONTRACT Other()\nEND CONTRACT",
        "CONTRACT Demo()\nEMIT ASSERT_HEIGHT_ABSOLUTE(01)\nEND CONTRACT",
        "CONTRACT Demo()\nEND CONTRACT garbage",
    ] {
        assert!(check("bad.bas", text.as_bytes()).is_err());
    }
    let mut bytes = "\u{feff}' π\r\n".as_bytes().to_vec();
    bytes.push(0xff);
    let span = check("encoding.bas", &bytes).err().unwrap().span.unwrap();
    assert_eq!(
        (span.start_byte, span.line, span.column),
        (bytes.len() - 1, 2, 1)
    );
}

#[test]
fn resource_limits_are_explicit() {
    let body = "EMIT ASSERT_HEIGHT_ABSOLUTE(1)\n".repeat(256);
    let c = compiled(&body);
    assert!(clvm::execute(&c.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).is_ok());
    assert!(
        check(
            "large.bas",
            format!("CONTRACT Demo()\n{body}EMIT ASSERT_HEIGHT_ABSOLUTE(1)\nEND CONTRACT")
                .as_bytes()
        )
        .is_err()
    );
    assert!(check("large.bas", &vec![b' '; 1_048_577]).is_err());
}

#[test]
fn check_and_compile_share_lowering_and_legacy_api_paths() {
    for literal in ["0", "&h00FF", "4294967295", "4294967296"] {
        let source =
            format!("CONTRACT Mixed()\n EMIT ASSERT_HEIGHT_ABSOLUTE({literal})\nEND CONTRACT\n");
        let checked = check("same.bas", source.as_bytes());
        let compiled = compile("same.bas", source.as_bytes());
        match (checked, compiled) {
            (Ok(checked), Ok(compiled)) => {
                assert_eq!(
                    serde_json::to_value(&checked).unwrap(),
                    serde_json::to_value(&compiled.contract).unwrap()
                );
                let legacy: oxbasic_compiler::syntax::Contract =
                    oxbasic_compiler::syntax::check("same.bas", source.as_bytes()).unwrap();
                assert_eq!(clvm::generate(&legacy).unwrap(), compiled.template);
            }
            (Err(checked), Err(compiled)) => assert_eq!(
                serde_json::to_value(checked).unwrap(),
                serde_json::to_value(compiled).unwrap()
            ),
            _ => panic!("check and compile disagree for {literal}"),
        }
    }
}

#[test]
fn integer_arithmetic_executes_without_machine_width_truncation() {
    for (expression, expected) in [
        ("2 + 3 * 4", 14u32),
        ("(2 + 3) * 4", 20),
        ("20 - 5 - 2", 13),
        ("-(-128)", 128),
        ("-128 + 129", 1),
        ("+(&hFFFFFFFF)", u32::MAX),
        ("1 - 1", 0),
        ("-0", 0),
        ("18446744073709551616 - 18446744073709551615", 1),
        (
            "(18446744073709551616 * 18446744073709551616) - 340282366920938463463374607431768211455",
            1,
        ),
        ("&HFFFFFFFF + 1 - 1", u32::MAX),
    ] {
        let actual = compiled(&format!("EMIT ASSERT_HEIGHT_ABSOLUTE({expression})\n"));
        let reference = compiled(&format!("EMIT ASSERT_HEIGHT_ABSOLUTE({expected})\n"));
        let actual = clvm::execute(&actual.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
        let reference = clvm::execute(&reference.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
        assert_eq!(actual.bytes, reference.bytes, "{expression}");
    }
}

#[test]
fn invalid_heights_compile_but_fail_when_executed() {
    for expression in [
        "-1",
        "4294967296",
        "&H100000000",
        "1 - 2",
        "&HFFFFFFFF + 1",
        "18446744073709551616 * 2",
    ] {
        let source =
            format!("CONTRACT Demo()\n EMIT ASSERT_HEIGHT_ABSOLUTE({expression})\nEND CONTRACT\n");
        check("range.bas", source.as_bytes()).unwrap();
        let c = compile("range.bas", source.as_bytes()).unwrap();
        assert_eq!(
            clvm::execute(&c.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
                .err()
                .unwrap()
                .code,
            "E0500",
            "{expression}"
        );
    }
}

#[test]
fn dynamic_emissions_preserve_order_cost_and_boundary_checks() {
    let c = compiled(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(2 + 3)\nEMIT ASSERT_HEIGHT_ABSOLUTE(7)\nEMIT ASSERT_HEIGHT_ABSOLUTE(12 - 3)\n",
    );
    let reference = compiled(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(5)\nEMIT ASSERT_HEIGHT_ABSOLUTE(7)\nEMIT ASSERT_HEIGHT_ABSOLUTE(9)\n",
    );
    let run = clvm::execute(&c.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(
        run.bytes,
        clvm::execute(&reference.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes
    );
    assert_eq!(
        clvm::execute(&c.puzzle, &[0x80], run.cost).unwrap().cost,
        run.cost
    );
    assert_eq!(
        clvm::execute(&c.puzzle, &[0x80], run.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    assert_eq!(
        clvm::execute(&c.puzzle, &[1], clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_ne!(
        c.puzzle, reference.puzzle,
        "Arithmetic must execute, not be folded into the literal fixture"
    );
}

#[test]
fn boolean_operands_and_integer_resource_limits_have_source_diagnostics() {
    for expression in ["TRUE", "1 + FALSE", "-TRUE", "(FALSE) * 2"] {
        let source =
            format!("CONTRACT Demo()\n EMIT ASSERT_HEIGHT_ABSOLUTE({expression})\nEND CONTRACT\n");
        let error = check("types.bas", source.as_bytes()).unwrap_err();
        assert_eq!(error.code, "E0202");
        assert_eq!(error.span.unwrap().line, 2);
    }
    let source = format!(
        "CONTRACT Demo()\n EMIT ASSERT_HEIGHT_ABSOLUTE({})\nEND CONTRACT\n",
        "9".repeat(4097)
    );
    assert_eq!(
        check("limits.bas", source.as_bytes()).unwrap_err().code,
        "E0205"
    );
    let body = format!("EMIT ASSERT_HEIGHT_ABSOLUTE({})\n", vec!["1"; 64].join("+")).repeat(33);
    assert_eq!(
        check(
            "limits.bas",
            format!("CONTRACT Demo()\n{body}END CONTRACT\n").as_bytes()
        )
        .unwrap_err()
        .code,
        "E0205"
    );
}

#[test]
fn a_failing_emission_stops_before_later_expensive_arithmetic() {
    let huge = "9".repeat(500);
    let expensive = [huge.as_str(); 8].join(" * ");
    let first_failure = compiled(&format!(
        "EMIT ASSERT_HEIGHT_ABSOLUTE(-1)\nEMIT ASSERT_HEIGHT_ABSOLUTE({expensive})\n"
    ));
    let expensive_first = compiled(&format!(
        "EMIT ASSERT_HEIGHT_ABSOLUTE({expensive})\nEMIT ASSERT_HEIGHT_ABSOLUTE(-1)\n"
    ));
    assert_eq!(
        clvm::execute(&first_failure.puzzle, &[0x80], 10_000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_eq!(
        clvm::execute(&expensive_first.puzzle, &[0x80], 10_000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}
