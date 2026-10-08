use oxbasic_compiler::{analyze, check, clvm, compile};
fn source(body: &str, functions: &str) -> String {
    format!("CONTRACT Demo()\n{body}END CONTRACT\n{functions}")
}
fn run(body: &str, functions: &str, cost: u64) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile("utf8.bas", source(body, functions).as_bytes())?;
    clvm::execute(&p.puzzle, &[0x80], cost)
}
fn compare(data: &[u8]) {
    let body = format!(
        "DIM s AS STRING = STRING_FROM_UTF8(0x{})\nASSERT UTF8(s) = 0x{}\n",
        hex::encode(data),
        hex::encode(data)
    );
    let result = run(&body, "", clvm::DEFAULT_MAX_COST);
    if std::str::from_utf8(data).is_ok() {
        result.unwrap();
    } else {
        assert_eq!(result.err().unwrap().code, "E0500", "{}", hex::encode(data));
    }
}
#[test]
fn valid_scalar_boundaries_empty_nul_and_noncharacters_preserve_bytes() {
    for data in [
        "",
        "00",
        "7f",
        "c280",
        "dfbf",
        "e0a080",
        "ed9fbf",
        "ee8080",
        "efbfbf",
        "f0908080",
        "f48fbfbf",
        "efbbbf",
        "61cc81",
        "c3a9",
        "48656c6c6f00f09fa680",
    ] {
        compare(&hex::decode(data).unwrap());
    }
    run("ASSERT STRING_FROM_UTF8(0xc3a9) <> STRING_FROM_UTF8(0x65cc81)\nASSERT STRING_FROM_UTF8(0x) = \"\"\n","",clvm::DEFAULT_MAX_COST).unwrap();
}
#[test]
fn malformed_and_truncated_sequences_fail_even_when_unused() {
    for data in [
        "80", "bf", "c0af", "c180", "c2", "c241", "e08080", "e09fbf", "eda080", "edbfbf", "e180",
        "e18041", "f0808080", "f08fbfbf", "f4908080", "f5808080", "fe", "ff", "f18080", "f1808041",
        "61c280ff",
    ] {
        let body = format!("DIM unused = STRING_FROM_UTF8(0x{data})\nunused = \"\"\n");
        check("bad.bas", source(&body, "").as_bytes()).unwrap();
        assert_eq!(
            run(&body, "", clvm::DEFAULT_MAX_COST).err().unwrap().code,
            "E0500",
            "{data}"
        );
    }
}
#[test]
fn byte_classes_and_second_byte_boundaries_match_rust_utf8() {
    for b in 0..=255 {
        compare(&[b]);
    }
    for lead in [
        0xc0, 0xc2, 0xdf, 0xe0, 0xe1, 0xec, 0xed, 0xee, 0xef, 0xf0, 0xf1, 0xf3, 0xf4, 0xf5,
    ] {
        for second in [0, 0x7f, 0x80, 0x8f, 0x90, 0x9f, 0xa0, 0xbf, 0xc0, 0xff] {
            let mut data = vec![lead, second];
            if lead >= 0xe0 {
                data.push(0x80);
            }
            if lead >= 0xf0 {
                data.push(0x80);
            }
            compare(&data);
        }
    }
    // Deterministic arbitrary short sequences compared with an independent decoder.
    let mut seed = 1234567u32;
    for n in 0..128 {
        let mut bytes = Vec::new();
        for _ in 0..n % 9 {
            seed = seed.wrapping_mul(1664525).wrapping_add(1013904223);
            bytes.push((seed >> 24) as u8);
        }
        compare(&bytes);
    }
}
#[test]
fn strict_signature_constants_and_unreachable_types_remain_checked() {
    for (body, code) in [
        ("DIM s = STRING_FROM_UTF8()\n", "E0202"),
        ("DIM s = STRING_FROM_UTF8(0x,0x)\n", "E0202"),
        ("DIM s = STRING_FROM_UTF8(\"a\")\n", "E0202"),
        ("DIM s = STRING_FROM_UTF8(1)\n", "E0202"),
        ("DIM b AS BYTES = STRING_FROM_UTF8(0x)\n", "E0202"),
        ("DIM s = STRING_FROM_UTF8\n", "E0100"),
        ("DIM STRING_FROM_UTF8 = 0\n", "E0201"),
        ("CONST s = STRING_FROM_UTF8(0x)\n", "E0205"),
        (
            "CONST b = TRUE OR (STRING_FROM_UTF8(0xff) = \"\")\n",
            "E0205",
        ),
        (
            "IF FALSE THEN\nDIM s = STRING_FROM_UTF8(TRUE)\nEND IF\n",
            "E0202",
        ),
    ] {
        let text = source(body, "");
        assert_eq!(check("bad.bas", text.as_bytes()).unwrap_err().code, code);
        assert_eq!(analyze("bad.bas", text.as_bytes()).unwrap_err().code, code);
    }
}
#[test]
fn eager_once_lazy_flow_and_function_returns_are_preserved() {
    let functions = "FUNCTION Data() AS BYTES\nRETURN CONCAT(0xc2,0x80)\nEND FUNCTION\nFUNCTION Decode(b AS BYTES) AS STRING\nIF TRUE THEN\nRETURN STRING_FROM_UTF8(b)\nEND IF\nEND FUNCTION\n";
    run("DIM s = Decode(Data())\nIF TRUE THEN\ns = Decode(0x00)\nEND IF\nASSERT UTF8(s) = 0x00\nASSERT TRUE OR (Decode(0xff) = \"\")\nIF FALSE THEN\nDIM bad = Decode(0xff)\nEND IF\n",functions,clvm::DEFAULT_MAX_COST).unwrap();
    let direct = compile(
        "direct.bas",
        source("DIM s = STRING_FROM_UTF8(Data())\n", functions).as_bytes(),
    )
    .unwrap();
    let named = compile(
        "named.bas",
        source("DIM b = Data()\nDIM s = STRING_FROM_UTF8(b)\n", functions).as_bytes(),
    )
    .unwrap();
    assert_eq!(direct.puzzle, named.puzzle);
    let expensive = format!(
        "FUNCTION Work() AS BYTES\nDIM b = 0x{}\nRETURN CONCAT(b,b)\nEND FUNCTION\n",
        "ff".repeat(32768)
    );
    assert_eq!(
        run(
            "DIM b = CONCAT(UTF8(STRING_FROM_UTF8(0xff)),Work())\n",
            &expensive,
            100000
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    assert_eq!(
        run(
            "DIM b = CONCAT(Work(),UTF8(STRING_FROM_UTF8(0xff)))\n",
            &expensive,
            100000
        )
        .err()
        .unwrap()
        .code,
        "E0501"
    );
}
#[test]
fn validation_cost_is_bounded_and_example_executes() {
    let body = format!("DIM s = STRING_FROM_UTF8(0x{})\n", "61".repeat(64));
    let result = run(&body, "", clvm::DEFAULT_MAX_COST).unwrap();
    let mut costs = vec![result.cost];
    for size in [128, 256] {
        let body = format!("DIM s = STRING_FROM_UTF8(0x{})\n", "61".repeat(size));
        costs.push(run(&body, "", clvm::DEFAULT_MAX_COST).unwrap().cost);
    }
    // Per-byte work is bounded; doubling length does not copy growing suffixes.
    assert!(costs[2] - costs[1] < 3 * (costs[1] - costs[0]));
    println!("ASCII validation costs for 64/128/256 bytes: {costs:?}");

    run(&body, "", result.cost).unwrap();
    assert_eq!(run(&body, "", result.cost - 1).err().unwrap().code, "E0501");
    let long = format!("DIM s = STRING_FROM_UTF8(0x{})\n", "61".repeat(4096));
    assert_eq!(run(&long, "", 100000).err().unwrap().code, "E0501");
    let p = compile(
        "example.bas",
        include_bytes!("../../../examples/m2-utf8-validation.bas"),
    )
    .unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
            .unwrap()
            .bytes,
        run(
            "EMIT ASSERT_HEIGHT_ABSOLUTE(10)\n",
            "",
            clvm::DEFAULT_MAX_COST
        )
        .unwrap()
        .bytes
    );
}
