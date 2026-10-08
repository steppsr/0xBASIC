use oxbasic_compiler::{analyze, check, clvm, compile};

fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn execute(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let program = compile("operations.bas", source(body, functions).as_bytes())?;
    clvm::execute(&program.puzzle, &[0x80], cost)
}
fn passes(body: &str) {
    execute(body, "", clvm::DEFAULT_MAX_COST).unwrap();
}

#[test]
fn exact_byte_operations_preserve_empty_zero_prefixed_and_high_bytes() {
    for (left, right) in [
        ("", ""),
        ("", "00"),
        ("00", ""),
        ("0001", "80ff"),
        ("ff", "00"),
    ] {
        let joined = format!("{left}{right}");
        passes(&format!(
            "ASSERT CONCAT(0x{left}, 0x{right}) = 0x{joined}\nASSERT BYTE_LENGTH(CONCAT(0x{left}, 0x{right})) = {}\n",
            joined.len() / 2
        ));
    }
    let all = hex::encode((0..=255).collect::<Vec<u8>>());
    passes(&format!(
        "DIM b = cOnCaT(0x{all}, 0x{all})\nASSERT b = 0x{all}{all}\nASSERT byte_length(b) = 512\n"
    ));
    let program = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-byte-operations.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&program.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        execute(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(4)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}

#[test]
fn arity_types_parentheses_and_constant_restrictions_are_shared() {
    for (body, code) in [
        ("DIM n = BYTE_LENGTH()\n", "E0202"),
        ("DIM n = BYTE_LENGTH(0x, 0x)\n", "E0202"),
        ("DIM n = CONCAT(0x)\n", "E0202"),
        ("DIM n = CONCAT(0x,0x,0x)\n", "E0202"),
        ("DIM n = CONCAT()\n", "E0202"),
        ("DIM n = CONCAT(0x,1)\n", "E0202"),
        ("DIM n = BYTE_LENGTH(FALSE)\n", "E0202"),
        ("ASSERT BYTE_LENGTH(0x)\n", "E0202"),
        ("DIM n = BYTE_LENGTH\n", "E0100"),
        ("DIM n = CONCAT(0x,)\n", "E0100"),
        ("CONST n = BYTE_LENGTH(0x)\n", "E0205"),
        ("CONST n = CONCAT(0x,0x)\n", "E0205"),
        ("CONST b = TRUE OR (BYTE_LENGTH(0x) = 0)\n", "E0205"),
        ("DIM CONCAT = 0x\n", "E0201"),
    ] {
        let text = source(body, "");
        assert_eq!(
            check("bad.bas", text.as_bytes()).unwrap_err().code,
            code,
            "{body}"
        );
        assert_eq!(
            analyze("bad.bas", text.as_bytes()).unwrap_err().code,
            code,
            "{body}"
        );
    }
}

#[test]
fn operations_execute_arguments_once_in_source_order_even_when_unused() {
    let functions = format!(
        "FUNCTION Fail() AS BYTES\nASSERT FALSE\nRETURN 0x\nEND FUNCTION\nFUNCTION Work() AS BYTES\nDIM b = 0x{}\nRETURN CONCAT(b,b)\nEND FUNCTION\n",
        "ff".repeat(8192)
    );
    assert_eq!(
        execute("DIM b = CONCAT(Fail(),Work())\n", &functions, 20_000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    assert_eq!(
        execute("DIM b = CONCAT(Work(),Fail())\n", &functions, 20_000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    assert_eq!(
        execute(
            "DIM n = BYTE_LENGTH(Fail())\n",
            &functions,
            clvm::DEFAULT_MAX_COST
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    let direct = compile(
        "direct.bas",
        source("DIM n = BYTE_LENGTH(Work())\n", &functions).as_bytes(),
    )
    .unwrap();
    let named = compile(
        "named.bas",
        source("DIM b = Work()\nDIM n = BYTE_LENGTH(b)\n", &functions).as_bytes(),
    )
    .unwrap();
    assert_eq!(direct.puzzle, named.puzzle);
    clvm::execute(&direct.puzzle, &[0x80], clvm::DEFAULT_MAX_COST).unwrap();
}

#[test]
fn calls_work_in_branches_and_returns_with_normal_lazy_evaluation() {
    let functions = "FUNCTION Join(b AS BOOLEAN) AS BYTES\nIF b THEN\nRETURN CONCAT(0x00,0xff)\nEND IF\nRETURN CONCAT(0x,0x80)\nEND FUNCTION\nFUNCTION Fail() AS BYTES\nASSERT FALSE\nRETURN 0x\nEND FUNCTION\n";
    execute("ASSERT Join(TRUE) = 0x00ff\nASSERT Join(FALSE) = 0x80\nASSERT TRUE OR (BYTE_LENGTH(Fail()) = 0)\nIF FALSE THEN\nDIM b = CONCAT(Fail(),0x)\nEND IF\n",functions,clvm::DEFAULT_MAX_COST).unwrap();
    passes(
        "CONST start = 0x00\nDIM b = start\nIF TRUE THEN\nb = CONCAT(b,0xff)\nEND IF\nASSERT b = 0x00ff\n",
    );
}

#[test]
fn runtime_growth_obeys_execution_cost_without_a_new_source_value_cap() {
    let body = format!(
        "DIM b = 0x01\n{}ASSERT BYTE_LENGTH(b) = 4096\n",
        "b = CONCAT(b,b)\n".repeat(12)
    );
    let result = execute(&body, "", clvm::DEFAULT_MAX_COST).unwrap();
    execute(&body, "", result.cost).unwrap();
    assert_eq!(
        execute(&body, "", result.cost - 1).err().unwrap().code,
        "E0501"
    );
    let growth = format!("DIM b = 0x01\n{}RETURN b\n", "b = CONCAT(b,b)\n".repeat(24));
    let functions = format!("FUNCTION Grow() AS BYTES\n{growth}END FUNCTION\n");
    assert_eq!(
        execute("DIM b = Grow()\n", &functions, clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    execute(
        "IF FALSE THEN\nDIM b = Grow()\nEND IF\n",
        &functions,
        10_000,
    )
    .unwrap();
}
