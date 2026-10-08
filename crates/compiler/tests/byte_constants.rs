use oxbasic_compiler::{IntegerValueKind, ValueType, analyze, check, clvm, compile};

fn source(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n")
}
fn run(text: &str) -> clvm::Execution {
    let program = compile("constants.bas", text.as_bytes()).unwrap();
    clvm::execute(&program.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap()
}
fn error(text: &str, code: &str) {
    for diagnostic in [
        check("bad.bas", text.as_bytes()).unwrap_err(),
        analyze("bad.bas", text.as_bytes()).unwrap_err(),
    ] {
        assert_eq!(diagnostic.code, code, "{text}\n{diagnostic:?}");
        assert!(diagnostic.span.is_some());
    }
}

#[test]
fn constants_preserve_raw_bytes_and_immutable_dependencies() {
    let text = source(
        "CONST empty AS BYTES = 0x\nCONST tag = 0x000180ff\nCONST copy AS BYTES = (tag)\nDIM value = copy\nvalue = empty\nASSERT copy = 0x000180ff\nASSERT value = 0x\n",
    );
    let contract = check("literal.bas", text.as_bytes()).unwrap();
    assert_eq!(contract.values[0].value_type, ValueType::Bytes);
    assert!(
        matches!(&contract.values[0].kind, IntegerValueKind::Literal(bytes) if bytes.is_empty())
    );
    for id in [1, 2] {
        assert!(
            matches!(&contract.values[id].kind, IntegerValueKind::Literal(bytes) if bytes == &[0,1,128,255])
        );
    }
    assert_eq!(run(&text).bytes, [0x80]);
    run(include_str!("../../../examples/m2-byte-constants.bas"));
    let every_byte = hex::encode((0..=255).collect::<Vec<u8>>());
    run(&source(&format!(
        "CONST all = 0x{every_byte}\nCONST alias = all\nASSERT alias = 0x{every_byte}\n"
    )));
}

#[test]
fn byte_comparisons_fold_with_exact_types_and_short_circuit_rules() {
    for (left, right) in [
        ("", ""),
        ("", "00"),
        ("00", "0000"),
        ("0001", "01"),
        ("ff80", "FF80"),
    ] {
        for op in ["=", "<>"] {
            let comparison = format!("0x{left} {op} 0x{right}");
            let equal = hex::decode(left).unwrap() == hex::decode(right).unwrap();
            let expected = if equal == (op == "=") {
                "TRUE"
            } else {
                "FALSE"
            };
            run(&source(&format!(
                "CONST answer AS BOOLEAN = {comparison}\nASSERT answer = {expected}\n"
            )));
        }
    }
    run(&source(
        "CONST a = TRUE OR (0x00 = 0x)\nCONST b = FALSE AND (0x00 = 0x00)\nCONST c = NOT (0x00 = 0x)\nASSERT a AND NOT b AND c\n",
    ));
    let folded = run(&source("CONST b = 0x0001 = 0x0001\nASSERT b\n"));
    let dynamic = run(&source("DIM b = 0x0001 = 0x0001\nASSERT b\n"));
    assert!(folded.cost < dynamic.cost);
}

#[test]
fn byte_constants_keep_context_and_unreachable_checks() {
    for (body, code) in [
        ("CONST b AS INTEGER = 0x\n", "E0202"),
        ("CONST b AS BYTES = 0\n", "E0202"),
        ("CONST b = 0x\nb = 0x01\n", "E0203"),
        ("CONST b = b\n", "E0200"),
        ("CONST b = later\nCONST later = 0x\n", "E0200"),
        ("DIM b = 0x\nCONST c = TRUE OR (b = 0x)\n", "E0205"),
        ("CONST c = TRUE OR (0x = 0)\n", "E0202"),
        ("CONST c = FALSE AND (0x < 0x)\n", "E0202"),
        ("CONST c = TRUE OR (-0x = 0x)\n", "E0202"),
        ("CONST c = 0x + 0x\n", "E0202"),
    ] {
        error(&source(body), code);
    }
    error(
        "CONTRACT Demo()\nEND CONTRACT\nFUNCTION F(b AS BYTES) AS BYTES\nRETURN b\nCONST c = b\nEND FUNCTION\n",
        "E0205",
    );
    error(
        "CONTRACT Demo()\nCONST c = TRUE OR (F() = 0x)\nEND CONTRACT\nFUNCTION F() AS BYTES\nRETURN 0x\nEND FUNCTION\n",
        "E0205",
    );
}

#[test]
fn byte_predicates_support_return_path_analysis_without_mutable_folding() {
    for predicate in ["tag = 0x0001", "0x <> 0x00", "(tag) = (tag)"] {
        let text = format!(
            "CONTRACT Demo()\nASSERT F() = 0x0001\nEND CONTRACT\nFUNCTION F() AS BYTES\nCONST tag = 0x0001\nIF {predicate} THEN\nRETURN tag\nEND IF\nEND FUNCTION\n"
        );
        analyze("return.bas", text.as_bytes()).unwrap();
        run(&text);
    }
    let text = "CONTRACT Demo()\nDIM n = F()\nEND CONTRACT\nFUNCTION F() AS BYTES\nASSERT 0x00 = 0x\nEND FUNCTION\n";
    let program = compile("fail.bas", text.as_bytes()).unwrap();
    assert_eq!(
        clvm::execute(&program.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    error(
        "CONTRACT Demo()\nEND CONTRACT\nFUNCTION F() AS BYTES\nDIM tag = 0x01\nIF tag = 0x01 THEN\nRETURN tag\nEND IF\nEND FUNCTION\n",
        "E0204",
    );
}

#[test]
fn cumulative_byte_work_counts_aliases_skipped_operands_and_functions() {
    let seed = format!("CONST seed = 0x{}\n", "ff".repeat(32768));
    let aliases = |count: usize| {
        (0..count)
            .map(|i| format!("CONST c{i} = seed\n"))
            .collect::<String>()
    };
    // 256 byte-valued nodes of 32 KiB consume exactly 8 MiB.
    let boundary = source(&(seed.clone() + &aliases(255)));
    check("limit.bas", boundary.as_bytes()).unwrap();
    analyze("limit.bas", boundary.as_bytes()).unwrap();
    error(&source(&(seed.clone() + &aliases(256))), "E0205");
    let skipped: String = (0..128)
        .map(|i| format!("CONST b{i} = TRUE OR (seed = seed)\n"))
        .collect();
    error(&source(&(seed.clone() + &skipped)), "E0205");
    let function = |name: &str| {
        format!(
            "FUNCTION {name}() AS BYTES\n{seed}{}RETURN seed\nEND FUNCTION\n",
            aliases(128)
        )
    };
    error(&(source("") + &function("F") + &function("G")), "E0205");
    // Return-path probes have a separate cumulative byte budget. Exhausting
    // it makes a later predicate unknown, never an assumed successful return.
    for (count, succeeds) in [(127, true), (128, false)] {
        let text = source("")
            + &format!(
                "FUNCTION F() AS BYTES\n{seed}{}IF seed = seed THEN\nRETURN seed\nEND IF\nEND FUNCTION\n",
                "ASSERT seed = seed\n".repeat(count)
            );
        if succeeds {
            check("probes.bas", text.as_bytes()).unwrap();
        } else {
            error(&text, "E0204");
        }
    }
}
