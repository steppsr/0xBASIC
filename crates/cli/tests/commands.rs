use serde_json::{Value, json};

#[test]
fn loops_round_trip_public_artifacts_and_all_inspection_stages() {
    let dir = fixture();
    let dir = dir.path();
    fs::write(dir.join("source file.bas"), "FUNCTION FirstIndex() AS INTEGER\nFOR j = 1 TO 2\nRETURN j\nNEXT j\nRETURN 0\nEND FUNCTION\nCONTRACT Demo(base AS INTEGER)\nSOLUTION count AS INTEGER\nSOLUTION flag AS BOOLEAN\nFOR i = FirstIndex() TO count\nEMIT ASSERT_HEIGHT_ABSOLUTE(base + i)\nNEXT i\nEND CONTRACT").unwrap();
    fs::write(dir.join("bindings.json"), r#"{"base":"100"}"#).unwrap();
    fs::write(dir.join("solution.json"), r#"{"count":"2","flag":false}"#).unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    let before = fs::read_dir(dir).unwrap().count();
    let ast = invoke(dir, &["explain", "source file.bas", "--stage", "ast"], 0);
    assert_eq!(
        ast["result"]["representation"]["nodes"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|n| n["kind"] == "For")
            .count(),
        2
    );
    let ir = invoke(dir, &["explain", "source file.bas", "--stage", "ir"], 0);
    assert!(
        ir["result"]["representation"]
            .to_string()
            .contains("capture_names")
    );
    let explained = invoke(
        dir,
        &[
            "explain",
            "source file.bas",
            "--stage",
            "clvm",
            "--bindings",
            "bindings.json",
        ],
        0,
    );
    assert_eq!(before, fs::read_dir(dir).unwrap().count());
    let built = invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "out",
            "--bindings",
            "bindings.json",
        ],
        0,
    );
    for role in ["template", "puzzle"] {
        assert_eq!(
            explained["result"]["representation"][role]["tree_hash"],
            built["result"][role]["tree_hash"]
        );
        assert_eq!(
            explained["result"]["representation"][role]["hex"],
            hex::encode(fs::read(dir.join(format!("out/{role}.clvm"))).unwrap())
        );
    }
    let manifest: Value =
        serde_json::from_slice(&fs::read(dir.join("out/manifest.json")).unwrap()).unwrap();
    assert_eq!(manifest["compiler"]["version"], "0.2.0-alpha.1");
    assert_eq!(manifest["language_version"], "0.2");
    let result = invoke(
        dir,
        &["run", "out/manifest.json", "--solution", "solution.json"],
        0,
    );
    let tree = &result["result"]["tree"];
    assert_eq!(tree["pair"][0]["pair"][1]["pair"][0]["atom"], "65");
    assert_eq!(
        tree["pair"][1]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "66"
    );
    let cost = result["result"]["cost"]
        .as_str()
        .unwrap()
        .parse::<u64>()
        .unwrap();
    invoke(
        dir,
        &[
            "run",
            "out/manifest.json",
            "--solution",
            "solution.json",
            "--max-cost",
            &cost.to_string(),
        ],
        0,
    );
    assert_eq!(
        invoke(
            dir,
            &[
                "run",
                "out/manifest.json",
                "--solution",
                "solution.json",
                "--max-cost",
                &(cost - 1).to_string()
            ],
            3
        )["diagnostics"][0]["code"],
        "E0501"
    );
    let saved = fs::read(dir.join("out/manifest.json")).unwrap();
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "out",
            "--bindings",
            "bindings.json",
        ],
        4,
    );
    assert_eq!(fs::read(dir.join("out/manifest.json")).unwrap(), saved);
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "template",
            "--template-only",
        ],
        0,
    );
    invoke(
        dir,
        &[
            "run",
            "template/manifest.json",
            "--solution",
            "solution.json",
        ],
        2,
    );
    fs::write(dir.join("raw.hex"), "ff80ff0280").unwrap(); // count=0, invalid unused BOOLEAN=2
    assert_eq!(
        invoke(
            dir,
            &["run", "out/manifest.json", "--solution-hex", "raw.hex"],
            3
        )["diagnostics"][0]["code"],
        "E0500"
    );
}

#[test]
fn loop_zero_step_and_keyword_migration_have_public_diagnostics() {
    let dir = fixture();
    let dir = dir.path();
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo()\nFOR i = 2 TO 1 STEP 0\nNEXT i\nEND CONTRACT",
    )
    .unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    build(dir, "zero");
    assert_eq!(
        invoke(dir, &["run", "zero/manifest.json"], 3)["diagnostics"][0]["code"],
        "E0500"
    );
    for word in ["for", "To", "STEP", "next"] {
        fs::write(
            dir.join("source file.bas"),
            format!("CONTRACT Demo()\nDIM {word} = 1\nEND CONTRACT"),
        )
        .unwrap();
        assert_eq!(
            invoke(dir, &["check", "source file.bas"], 1)["diagnostics"][0]["code"],
            "E0201"
        );
    }
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo()\nFOR i = TRUE TO 1\nNEXT i\nEND CONTRACT",
    )
    .unwrap();
    invoke(dir, &["explain", "source file.bas", "--stage", "ast"], 0);
    assert_eq!(
        invoke(dir, &["explain", "source file.bas", "--stage", "ir"], 1)["diagnostics"][0]["code"],
        "E0202"
    );
}

#[test]
fn activated_reader_rejects_previous_compiler_and_language_identities() {
    let dir = fixture();
    let dir = dir.path();
    build(dir, "out");
    let path = dir.join("out/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    for compiler in [false, true] {
        let mut old = original.clone();
        if compiler {
            old["compiler"]["version"] = json!("0.1.0-m3.8b");
        } else {
            old["language_version"] = json!("0.1");
        }
        fs::write(&path, serde_json::to_vec(&old).unwrap()).unwrap();
        assert_eq!(
            invoke(dir, &["run", "out/manifest.json"], 2)["diagnostics"][0]["code"],
            "E0400"
        );
    }
}

#[test]
fn pure_function_artifacts_build_run_and_reject_missing_returns() {
    let dir = fixture();
    let dir = dir.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m2-functions.bas"),
    )
    .unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    build(dir, "functions");
    let result = invoke(dir, &["run", "functions/manifest.json"], 0);
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "64"
    );
    assert_eq!(result["result"]["validation"], "clvm-execution-only");
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m2-early-return.bas"),
    )
    .unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    build(dir, "early-return");
    let result = invoke(dir, &["run", "early-return/manifest.json"], 0);
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "64"
    );
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m2-function-analysis.bas"),
    )
    .unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    build(dir, "branch-return");
    let result = invoke(dir, &["run", "branch-return/manifest.json"], 0);
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "64"
    );
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo()\nEND CONTRACT\nFUNCTION F() AS INTEGER\nDIM n = 1\nEND FUNCTION\n",
    )
    .unwrap();
    assert_eq!(
        invoke(dir, &["check", "source file.bas"], 1)["diagnostics"][0]["code"],
        "E0204"
    );
    invoke(dir, &["build", "source file.bas", "--out", "rejected"], 1);
    assert!(!dir.join("rejected").exists());
}

#[test]
fn integer_expressions_build_and_height_failures_are_runtime_errors() {
    let dir = fixture();
    let dir = dir.path();
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo()\n EMIT ASSERT_HEIGHT_ABSOLUTE(2 + 3 * 4)\nEND CONTRACT\n",
    )
    .unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    build(dir, "arithmetic");
    let value = invoke(dir, &["run", "arithmetic/manifest.json"], 0);
    assert_eq!(
        value["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "0e"
    );
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo()\n EMIT ASSERT_HEIGHT_ABSOLUTE(-1)\nEND CONTRACT\n",
    )
    .unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    build(dir, "invalid-height");
    assert_eq!(
        invoke(dir, &["run", "invalid-height/manifest.json"], 3)["diagnostics"][0]["code"],
        "E0500"
    );
    build(dir, "out");
    mutate_manifest(dir, |v| v["compiler"]["version"] = json!("0.1.0-m1"));
    invoke(dir, &["run", "out/manifest.json"], 2);
}

#[test]
fn large_hex_artifacts_can_be_reloaded_at_twice_the_binary_size() {
    let dir = fixture();
    let dir = dir.path();
    let body = format!("EMIT ASSERT_HEIGHT_ABSOLUTE(&H{})\n", "F".repeat(4096)).repeat(250);
    let source = format!("CONTRACT Large()\n{body}END CONTRACT\n");
    assert!(source.len() <= 1_048_576);
    fs::write(dir.join("source file.bas"), source).unwrap();
    build(dir, "out");
    assert!(fs::metadata(dir.join("out/puzzle.hex")).unwrap().len() > 1_048_576);
    // Successful loading reaches the VM's expected height-range failure.
    assert_eq!(
        invoke(dir, &["run", "out/manifest.json"], 3)["diagnostics"][0]["code"],
        "E0500"
    );
}
use std::{fs, path::Path, process::Command};

fn invoke(dir: &Path, args: &[&str], status: i32) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_0xbasic"))
        .current_dir(dir)
        .args(args)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(
        output.status.code(),
        Some(status),
        "stdout={} stderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        output.stderr.is_empty(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(value["ok"], status == 0);
    if status != 0 {
        assert!(value["result"].is_null());
    }
    value
}
fn fixture() -> tempfile::TempDir {
    let dir = tempfile::Builder::new()
        .prefix("0xbasic tests with spaces ")
        .tempdir()
        .unwrap();
    fs::write(
        dir.path().join("source file.bas"),
        "\u{feff}CONTRACT Test()\r\n EMIT ASSERT_HEIGHT_ABSOLUTE(100)\r\nEND CONTRACT\r\n",
    )
    .unwrap();
    dir
}
fn build(dir: &Path, out: &str) {
    invoke(dir, &["build", "source file.bas", "--out", out], 0);
}
fn mutate_manifest(dir: &Path, change: impl FnOnce(&mut Value)) {
    let path = dir.join("out/manifest.json");
    let mut value: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    change(&mut value);
    fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
}

#[test]
fn check_build_run_and_reproducibility() {
    let dir = fixture();
    let dir = dir.path();
    assert_eq!(
        invoke(dir, &["check", "source file.bas"], 0)["result"]["contract"],
        "test"
    );
    build(dir, "first output");
    build(dir, "second output");
    for name in [
        "template.clvm",
        "template.hex",
        "puzzle.clvm",
        "puzzle.hex",
        "manifest.json",
    ] {
        assert_eq!(
            fs::read(dir.join("first output").join(name)).unwrap(),
            fs::read(dir.join("second output").join(name)).unwrap()
        );
    }
    let result = invoke(dir, &["run", "first output/manifest.json"], 0);
    assert_eq!(result["result"]["validation"], "clvm-execution-only");
    let cost = result["result"]["cost"].as_str().unwrap();
    invoke(
        dir,
        &["run", "first output/manifest.json", "--max-cost", cost],
        0,
    );
    invoke(
        dir,
        &["run", "first output/manifest.json", "--max-cost", "1"],
        3,
    );
    fs::write(dir.join("solution.hex"), "ff0180\n").unwrap();
    assert_eq!(
        invoke(
            dir,
            &[
                "run",
                "first output/manifest.json",
                "--solution-hex",
                "solution.hex"
            ],
            3
        )["diagnostics"][0]["code"],
        "E0500"
    );
    fs::write(dir.join("solution.hex"), "8080").unwrap();
    invoke(
        dir,
        &[
            "run",
            "first output/manifest.json",
            "--solution-hex",
            "solution.hex",
        ],
        1,
    );
}

#[test]
fn failed_build_never_publishes_or_overwrites() {
    let dir = fixture();
    let dir = dir.path();
    fs::write(
        dir.join("invalid.bas"),
        "CONTRACT Broken()\nSOLUTION x AS DOUBLE\nEND CONTRACT",
    )
    .unwrap();
    invoke(dir, &["build", "invalid.bas", "--out", "failed"], 1);
    assert!(!dir.join("failed").exists());
    build(dir, "out");
    fs::write(dir.join("out/sentinel"), "keep").unwrap();
    invoke(dir, &["build", "source file.bas", "--out", "out"], 4);
    assert_eq!(
        fs::read_to_string(dir.join("out/sentinel")).unwrap(),
        "keep"
    );
    assert!(!fs::read_dir(dir).unwrap().any(|e| {
        e.unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".0xbasic-")
    }));
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "template",
            "--template-only",
        ],
        0,
    );
    assert!(!dir.join("template/puzzle.clvm").exists());
    invoke(dir, &["run", "template/manifest.json"], 2);
}

#[test]
fn manifest_integrity_and_versions_are_enforced() {
    for (field, replacement, status) in [
        ("target_profile", json!("unknown"), 2),
        ("bindings", json!({"extra":1}), 4),
    ] {
        let dir = fixture();
        let dir = dir.path();
        build(dir, "out");
        mutate_manifest(dir, |v| v[field] = replacement);
        invoke(dir, &["run", "out/manifest.json"], status);
    }
    for bad_path in ["../puzzle.clvm", "/tmp/puzzle.clvm", "C:\\puzzle.clvm"] {
        let dir = fixture();
        let dir = dir.path();
        build(dir, "out");
        mutate_manifest(dir, |v| v["puzzle"]["binary"] = json!(bad_path));
        invoke(dir, &["run", "out/manifest.json"], 4);
    }
    let dir = fixture();
    let dir = dir.path();
    build(dir, "out");
    fs::write(dir.join("out/puzzle.clvm"), [0x80]).unwrap();
    invoke(dir, &["run", "out/manifest.json"], 4);
}

#[test]
fn usage_and_empty_abi_are_explicit() {
    let dir = fixture();
    let dir = dir.path();
    for args in [
        vec!["explain", "source file.bas"],
        vec!["build", "source file.bas"],
        vec!["check", "source file.bas", "--future"],
        vec!["check", "source file.bas", "--json"],
        vec![
            "build",
            "source file.bas",
            "--out",
            "out",
            "--template-only",
            "--bindings",
            "x",
        ],
    ] {
        invoke(dir, &args, 2);
    }
    for value in ["null", "[]", "{\"x\":1}", "{\"x\":1,\"x\":2}"] {
        fs::write(dir.join("bindings.json"), value).unwrap();
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--out",
                "out",
                "--bindings",
                "bindings.json",
            ],
            1,
        );
        assert!(!dir.join("out").exists());
    }
    fs::write(dir.join("bindings.json"), "{}").unwrap();
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "out",
            "--bindings",
            "bindings.json",
        ],
        0,
    );
    invoke(
        dir,
        &["run", "out/manifest.json", "--solution", "bindings.json"],
        0,
    );
    for cost in ["0", "-1", "+1", "1.5", "18446744073709551616"] {
        invoke(dir, &["run", "out/manifest.json", "--max-cost", cost], 2);
    }
}

#[test]
fn duplicate_unknown_and_missing_manifest_fields_fail() {
    for variant in 0..3 {
        let dir = fixture();
        let dir = dir.path();
        build(dir, "out");
        let path = dir.join("out/manifest.json");
        if variant == 0 {
            let text =
                fs::read_to_string(&path)
                    .unwrap()
                    .replacen('{', "{\"schema_version\":1,", 1);
            fs::write(path, text).unwrap();
        } else {
            mutate_manifest(dir, |v| {
                if variant == 1 {
                    v["unknown"] = json!(1);
                } else {
                    v.as_object_mut().unwrap().remove("puzzle");
                }
            });
        }
        invoke(dir, &["run", "out/manifest.json"], 4);
    }
}

#[test]
fn concurrent_builds_publish_exactly_once() {
    let dir = fixture();
    let start = || {
        Command::new(env!("CARGO_BIN_EXE_0xbasic"))
            .current_dir(dir.path())
            .args(["build", "source file.bas", "--out", "race", "--json"])
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .unwrap()
    };
    let a = start();
    let b = start();
    let mut codes = [
        a.wait_with_output().unwrap().status.code().unwrap(),
        b.wait_with_output().unwrap().status.code().unwrap(),
    ];
    codes.sort();
    assert_eq!(codes, [0, 4]);
    invoke(dir.path(), &["run", "race/manifest.json"], 0);
}

#[cfg(unix)]
#[test]
fn artifact_symlink_cannot_escape_manifest_directory() {
    for name in ["template.clvm", "template.hex", "puzzle.clvm", "puzzle.hex"] {
        let dir = fixture();
        let dir = dir.path();
        build(dir, "out");
        // A sibling with a shared name prefix must not count as contained.
        fs::create_dir(dir.join("out-sibling")).unwrap();
        fs::rename(
            dir.join("out").join(name),
            dir.join("out-sibling").join(name),
        )
        .unwrap();
        std::os::unix::fs::symlink(format!("../out-sibling/{name}"), dir.join("out").join(name))
            .unwrap();
        let r = invoke(dir, &["run", "out/manifest.json"], 4);
        assert!(
            r["diagnostics"][0]["message"]
                .as_str()
                .unwrap()
                .contains("outside the manifest directory")
        );
    }
}

#[test]
fn largest_supported_contract_has_printable_json_output() {
    let dir = fixture();
    let dir = dir.path();
    let body = "EMIT ASSERT_HEIGHT_ABSOLUTE(4294967295)\n".repeat(256);
    fs::write(
        dir.join("source file.bas"),
        format!("CONTRACT Large()\n{body}END CONTRACT\n"),
    )
    .unwrap();
    build(dir, "out");
    let output = Command::new(env!("CARGO_BIN_EXE_0xbasic"))
        .current_dir(dir)
        .args(["run", "out/manifest.json", "--json"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    // Raw CLVM lists are nested pairs; this valid output exceeds serde_json's
    // default input nesting limit, so inspect the bounded envelope as text here.
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(text.contains("\"ok\":true"));
    assert_eq!(text.matches("00ffffffff").count(), 256);
}

#[test]
fn integer_input_artifacts_and_json_raw_solutions_enforce_boundaries() {
    let temp = fixture();
    let dir = temp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-integer-inputs.bas"),
    )
    .unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    build(dir, "inputs");
    build(dir, "repeat");
    for name in ["manifest.json", "puzzle.clvm", "template.clvm"] {
        assert_eq!(
            fs::read(dir.join("inputs").join(name)).unwrap(),
            fs::read(dir.join("repeat").join(name)).unwrap()
        );
    }
    let manifest_path = dir.join("inputs/manifest.json");
    let bytes = fs::read(&manifest_path).unwrap();
    let original: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(
        original["inputs"],
        json!([{"name":"height","type":{"kind":"INTEGER"}}])
    );
    assert_eq!(
        invoke(dir, &["run", "inputs/manifest.json"], 1)["diagnostics"][0]["code"],
        "E0300"
    );
    fs::write(dir.join("solution.json"), r#"{"HEIGHT":"7"}"#).unwrap();
    let result = invoke(
        dir,
        &["run", "inputs/manifest.json", "--solution", "solution.json"],
        0,
    );
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "07"
    );
    fs::write(dir.join("solution.json"), r#"{"height":"7","HEIGHT":"8"}"#).unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "inputs/manifest.json", "--solution", "solution.json"],
            1
        )["diagnostics"][0]["code"],
        "E0300"
    );
    for (raw, status, code) in [
        ("ff0080", 3, "E0500"),
        ("ff0102", 3, "E0500"),
        ("ff078080", 1, "E0300"),
    ] {
        fs::write(dir.join("raw.hex"), raw).unwrap();
        assert_eq!(
            invoke(
                dir,
                &["run", "inputs/manifest.json", "--solution-hex", "raw.hex"],
                status
            )["diagnostics"][0]["code"],
            code
        );
    }
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "template",
            "--template-only",
        ],
        0,
    );
    invoke(dir, &["run", "template/manifest.json"], 2);
    for fields in [
        json!([{"name":"height","type":{"kind":{"INTEGER":null}}}]),
        json!([{"name":"height","type":{"kind":"INTEGER"}},{"name":"height","type":{"kind":"INTEGER"}}]),
        json!([{"name":"HEIGHT","type":{"kind":"INTEGER"}}]),
        json!([{"name":"height","type":{"kind":"INTEGER","extra":1}}]),
    ] {
        let mut altered = original.clone();
        altered["inputs"] = fields;
        fs::write(&manifest_path, serde_json::to_vec(&altered).unwrap()).unwrap();
        invoke(dir, &["run", "inputs/manifest.json"], 4);
    }
    // Host metadata cannot authorize an ill-typed raw value for the program.
    let mut altered = original;
    altered["inputs"] = json!([]);
    fs::write(&manifest_path, serde_json::to_vec(&altered).unwrap()).unwrap();
    assert_eq!(
        invoke(dir, &["run", "inputs/manifest.json"], 3)["diagnostics"][0]["code"],
        "E0500"
    );
}

#[test]
fn fixed_binding_artifacts_template_only_and_integrity_are_enforced() {
    let tmp = fixture();
    let dir = tmp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-fixed-integers.bas"),
    )
    .unwrap();
    invoke(dir, &["check", "source file.bas"], 0);
    assert_eq!(
        invoke(dir, &["build", "source file.bas", "--out", "missing"], 1)["diagnostics"][0]["code"],
        "E0301"
    );
    assert!(!dir.join("missing").exists());
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "template",
            "--template-only",
        ],
        0,
    );
    let template: Value =
        serde_json::from_slice(&fs::read(dir.join("template/manifest.json")).unwrap()).unwrap();
    assert!(template["puzzle"].is_null() && template["bindings"].is_null());
    assert!(!dir.join("template/puzzle.clvm").exists());
    invoke(dir, &["run", "template/manifest.json"], 2);
    fs::write(dir.join("bindings.json"), r#"{"BASE":"100"}"#).unwrap();
    for out in ["bound", "repeat"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--out",
                out,
                "--bindings",
                "bindings.json",
            ],
            0,
        );
    }
    for name in ["manifest.json", "template.clvm", "puzzle.clvm"] {
        assert_eq!(
            fs::read(dir.join("bound").join(name)).unwrap(),
            fs::read(dir.join("repeat").join(name)).unwrap()
        );
    }
    assert_eq!(
        fs::read(dir.join("template/template.clvm")).unwrap(),
        fs::read(dir.join("bound/template.clvm")).unwrap()
    );
    fs::write(dir.join("solution.json"), r#"{"offset":"7"}"#).unwrap();
    let result = invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        0,
    );
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "6b"
    );
    fs::write(dir.join("bindings.json"), r#"{"base":"101"}"#).unwrap();
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "changed",
            "--bindings",
            "bindings.json",
        ],
        0,
    );
    assert_ne!(
        fs::read(dir.join("bound/puzzle.clvm")).unwrap(),
        fs::read(dir.join("changed/puzzle.clvm")).unwrap()
    );
    let path = dir.join("bound/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(original["bindings"], json!({"base":"100"}));
    for bindings in [
        json!({"base":"101"}),
        json!({"BASE":"100"}),
        json!({"base":"0100"}),
        json!({}),
        Value::Null,
    ] {
        let mut m = original.clone();
        m["bindings"] = bindings;
        fs::write(&path, serde_json::to_vec(&m).unwrap()).unwrap();
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            4,
        );
    }
    let serialized = serde_json::to_string(&original).unwrap();
    let duplicated = serialized.replace(
        r#""bindings":{"base":"100"}"#,
        r#""bindings":{"base":"100","base":"100"}"#,
    );
    assert_ne!(serialized, duplicated);
    fs::write(&path, duplicated).unwrap();
    invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        4,
    );
    let mut overlap = original;
    overlap["inputs"] = json!([{"name":"base","type":{"kind":"INTEGER"}}]);
    fs::write(&path, serde_json::to_vec(&overlap).unwrap()).unwrap();
    invoke(dir, &["run", "bound/manifest.json"], 4);
    fs::write(dir.join("bindings.json"), r#"{"base":"1","BASE":"2"}"#).unwrap();
    assert_eq!(
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--out",
                "duplicate",
                "--bindings",
                "bindings.json"
            ],
            1
        )["diagnostics"][0]["code"],
        "E0301"
    );
    assert!(!dir.join("duplicate").exists());
    // A binding file can fit its own limit while provenance makes the manifest too large.
    let huge = format!(r#"{{"base":"1{}"}}"#, "0".repeat(1_048_000));
    fs::write(dir.join("bindings.json"), huge).unwrap();
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--out",
            "oversized-manifest",
            "--bindings",
            "bindings.json",
        ],
        4,
    );
    assert!(!dir.join("oversized-manifest").exists());
}

#[test]
fn scalar_boundaries_round_trip_and_reject_tampered_manifests() {
    let tmp = fixture();
    let dir = tmp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-scalar-boundaries.bas"),
    )
    .unwrap();
    fs::write(
        dir.join("bindings.json"),
        r#"{"ENABLED":true,"PREFIX":{"hex":"00Af"},"base":"100"}"#,
    )
    .unwrap();
    fs::write(
        dir.join("solution.json"),
        include_bytes!("../../../examples/m3-scalar-boundaries.solution.json"),
    )
    .unwrap();
    for out in ["bound", "repeat"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--out",
                out,
                "--bindings",
                "bindings.json",
            ],
            0,
        );
    }
    for file in ["manifest.json", "puzzle.clvm", "template.clvm"] {
        assert_eq!(
            fs::read(dir.join("bound").join(file)).unwrap(),
            fs::read(dir.join("repeat").join(file)).unwrap()
        );
    }
    let path = dir.join("bound/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(original["bindings"]["prefix"], json!({"hex":"00af"}));
    assert_eq!(original["fixed_parameters"][0]["type"]["kind"], "BOOLEAN");
    assert_eq!(original["inputs"][1]["type"]["kind"], "BYTES");
    invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        0,
    );
    for value in [
        json!({"hex":"00AF"}),
        json!({"hex":"af"}),
        json!("00af"),
        json!(false),
    ] {
        let mut altered = original.clone();
        altered["bindings"]["prefix"] = value;
        fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            4,
        );
    }
    let serialized = serde_json::to_string(&original).unwrap();
    let duplicate = serialized.replace(r#""hex":"00af""#, r#""hex":"00af","h\u0065x":"00af""#);
    assert_ne!(serialized, duplicate);
    fs::write(&path, duplicate).unwrap();
    invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        4,
    );
    // Consistent metadata cannot disable checks in the compiled template.
    let mut forged = original.clone();
    forged["inputs"][0]["type"]["kind"] = json!("BYTES");
    fs::write(&path, serde_json::to_vec(&forged).unwrap()).unwrap();
    fs::write(
        dir.join("solution.json"),
        r#"{"approved":{"hex":"02"},"payload":{"hex":""}}"#,
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            3
        )["diagnostics"][0]["code"],
        "E0500"
    );
    fs::write(&path, serialized).unwrap();
    fs::write(
        dir.join("solution.json"),
        r#"{"approved":true,"payload":{"hex":"00","hex":"01"}}"#,
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            1
        )["diagnostics"][0]["code"],
        "E0300"
    );
}

#[test]
fn string_artifacts_preserve_unicode_and_reject_forged_boundary_metadata() {
    let tmp = fixture();
    let dir = tmp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-string-boundaries.bas"),
    )
    .unwrap();
    fs::write(
        dir.join("bindings.json"),
        include_bytes!("../../../examples/m3-string-boundaries.bindings.json"),
    )
    .unwrap();
    fs::write(
        dir.join("solution.json"),
        include_bytes!("../../../examples/m3-string-boundaries.solution.json"),
    )
    .unwrap();
    for out in ["bound", "repeat"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                out,
            ],
            0,
        );
    }
    for file in ["manifest.json", "template.clvm", "puzzle.clvm"] {
        assert_eq!(
            fs::read(dir.join("bound").join(file)).unwrap(),
            fs::read(dir.join("repeat").join(file)).unwrap()
        );
    }
    let result = invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        0,
    );
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "6b"
    );
    let path = dir.join("bound/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(original["bindings"]["prefix"], "é");
    assert_eq!(original["inputs"][0]["type"]["kind"], "STRING");
    let mut altered = original.clone();
    altered["bindings"]["prefix"] = json!("e\u{301}");
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        4,
    );
    altered = original.clone();
    altered["inputs"][0]["type"]["kind"] = json!("BYTES");
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    fs::write(dir.join("solution.json"), r#"{"message":{"hex":"eda080"}}"#).unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            3
        )["diagnostics"][0]["code"],
        "E0500"
    );
    let serialized = serde_json::to_string(&original).unwrap();
    let invalid = serialized.replace("é", r#"\ud800"#);
    assert_ne!(invalid, serialized);
    fs::write(&path, invalid).unwrap();
    invoke(dir, &["run", "bound/manifest.json"], 4);
    fs::write(&path, serialized).unwrap();
    fs::write(dir.join("solution.json"), r#"{"message":"\ud800"}"#).unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            1
        )["diagnostics"][0]["code"],
        "E0300"
    );
    fs::write(
        dir.join("bindings.json"),
        r#"{"prefix":"\udc00","base":"100"}"#,
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                "invalid"
            ],
            1
        )["diagnostics"][0]["code"],
        "E0301"
    );
    assert!(!dir.join("invalid").exists());
}

#[test]
fn pair_artifacts_round_trip_and_recursive_metadata_cannot_disable_guards() {
    let tmp = fixture();
    let dir = tmp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-pair-boundaries.bas"),
    )
    .unwrap();
    fs::write(
        dir.join("bindings.json"),
        include_bytes!("../../../examples/m3-pair-boundaries.bindings.json"),
    )
    .unwrap();
    fs::write(
        dir.join("solution.json"),
        include_bytes!("../../../examples/m3-pair-boundaries.solution.json"),
    )
    .unwrap();
    for out in ["bound", "repeat"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                out,
            ],
            0,
        );
    }
    for file in ["manifest.json", "template.clvm", "puzzle.clvm"] {
        assert_eq!(
            fs::read(dir.join("bound").join(file)).unwrap(),
            fs::read(dir.join("repeat").join(file)).unwrap()
        );
    }
    let path = dir.join("bound/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(
        original["fixed_parameters"][0]["type"],
        json!({"kind":"PAIR","first":{"kind":"INTEGER"},"rest":{"kind":"BOOLEAN"}})
    );
    let result = invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        0,
    );
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "68"
    );
    let mut altered = original.clone();
    altered["bindings"]["config"]["rest"] = json!(false);
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        4,
    );
    altered = original.clone();
    altered["inputs"][0]["type"]["first"] = json!({"kind":"BYTES"});
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    fs::write(
        dir.join("solution.json"),
        r#"{"payload":{"first":{"hex":"ff"},"rest":{"hex":""}}}"#,
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            3
        )["diagnostics"][0]["code"],
        "E0500"
    );
    let serialized = serde_json::to_string(&original).unwrap();
    let duplicate = serialized.replace(r#""first":"100""#, r#""first":"100","f\u0069rst":"100""#);
    assert_ne!(duplicate, serialized);
    fs::write(&path, duplicate).unwrap();
    invoke(dir, &["run", "bound/manifest.json"], 4);
    let bad_schema = serialized.replace(r#""kind":"INTEGER""#, r#""kind":"INTEGER","first":null"#);
    assert_ne!(bad_schema, serialized);
    fs::write(&path, bad_schema).unwrap();
    invoke(dir, &["run", "bound/manifest.json"], 4);
    let mut schema = json!({"kind":"INTEGER"});
    for _ in 0..33 {
        schema = json!({"kind":"PAIR","first":{"kind":"INTEGER"},"rest":schema});
    }
    altered = original.clone();
    altered["inputs"][0]["type"] = schema;
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    invoke(dir, &["run", "bound/manifest.json"], 4);
    fs::write(&path, serialized).unwrap();
    fs::write(
        dir.join("bindings.json"),
        r#"{"config":{"first":"100","rest":true,"rest":false}}"#,
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                "invalid"
            ],
            1
        )["diagnostics"][0]["code"],
        "E0301"
    );
    assert!(!dir.join("invalid").exists());
}

#[test]
fn list_artifacts_round_trip_and_forged_element_schemas_cannot_disable_guards() {
    let tmp = fixture();
    let dir = tmp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-list-boundaries.bas"),
    )
    .unwrap();
    fs::write(
        dir.join("bindings.json"),
        include_bytes!("../../../examples/m3-list-boundaries.bindings.json"),
    )
    .unwrap();
    fs::write(
        dir.join("solution.json"),
        include_bytes!("../../../examples/m3-list-boundaries.solution.json"),
    )
    .unwrap();
    for out in ["bound", "repeat"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                out,
            ],
            0,
        );
    }
    for file in ["manifest.json", "template.clvm", "puzzle.clvm"] {
        assert_eq!(
            fs::read(dir.join("bound").join(file)).unwrap(),
            fs::read(dir.join("repeat").join(file)).unwrap()
        );
    }
    let path = dir.join("bound/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    assert_eq!(original["fixed_parameters"][0]["type"]["kind"], "LIST");
    assert_eq!(original["inputs"][0]["type"]["element"]["kind"], "PAIR");
    let result = invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        0,
    );
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "68"
    );
    let mut altered = original.clone();
    altered["bindings"]["config"][0]["first"] = json!("101");
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    invoke(
        dir,
        &["run", "bound/manifest.json", "--solution", "solution.json"],
        4,
    );
    altered = original.clone();
    altered["inputs"][0]["type"]["element"]["first"] = json!({"kind":"BYTES"});
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    fs::write(
        dir.join("solution.json"),
        r#"{"items":[{"first":{"hex":"ff"},"rest":{"hex":""}}]}"#,
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            3
        )["diagnostics"][0]["code"],
        "E0500"
    );
    altered = original.clone();
    altered["inputs"][0]["type"]["element"] = Value::Null;
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    invoke(dir, &["run", "bound/manifest.json"], 4);
    let serialized = serde_json::to_string(&original).unwrap();
    let duplicate = serialized.replace(r#""first":"100""#, r#""first":"100","f\u0069rst":"100""#);
    assert_ne!(duplicate, serialized);
    fs::write(&path, duplicate).unwrap();
    invoke(dir, &["run", "bound/manifest.json"], 4);
    fs::write(&path, serialized).unwrap();
    fs::write(
        dir.join("solution.json"),
        r#"{"items":[{"first":"","rest":{"hex":"","hex":"00"}}]}"#,
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "bound/manifest.json", "--solution", "solution.json"],
            1
        )["diagnostics"][0]["code"],
        "E0300"
    );
    fs::write(
        dir.join("bindings.json"),
        r#"{"config":[{"first":"100","rest":true},{"first":"0","rest":1}]}"#,
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                "invalid"
            ],
            1
        )["diagnostics"][0]["code"],
        "E0301"
    );
    assert!(!dir.join("invalid").exists());
}

#[test]
fn domain_artifacts_normalize_bindings_and_enforce_solution_schemas() {
    let temp = fixture();
    let dir = temp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-domain-boundaries.bas"),
    )
    .unwrap();
    fs::write(
        dir.join("bindings.json"),
        include_bytes!("../../../examples/m3-domain-boundaries.bindings.json"),
    )
    .unwrap();
    fs::write(
        dir.join("solution.json"),
        include_bytes!("../../../examples/m3-domain-boundaries.solution.json"),
    )
    .unwrap();
    for out in ["domain-a", "domain-b"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                out,
            ],
            0,
        );
    }
    assert_eq!(
        fs::read(dir.join("domain-a/puzzle.clvm")).unwrap(),
        fs::read(dir.join("domain-b/puzzle.clvm")).unwrap()
    );
    let path = dir.join("domain-a/manifest.json");
    let original = fs::read(&path).unwrap();
    let mut manifest: Value = serde_json::from_slice(&original).unwrap();
    assert_eq!(
        manifest["fixed_parameters"][0]["type"]["kind"],
        "PUZZLEHASH"
    );
    assert_eq!(manifest["fixed_parameters"][1]["type"]["kind"], "AMOUNT");
    assert_eq!(
        manifest["bindings"]["recipient"]["hex"],
        format!("{}af", "00".repeat(31))
    );
    let result = invoke(
        dir,
        &[
            "run",
            "domain-a/manifest.json",
            "--solution",
            "solution.json",
        ],
        0,
    );
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "64"
    );
    manifest["inputs"][0]["type"]["rest"]["element"]["extra"] = json!(true);
    fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    invoke(
        dir,
        &[
            "run",
            "domain-a/manifest.json",
            "--solution",
            "solution.json",
        ],
        4,
    );
    fs::write(&path, original).unwrap();
    let mut solution: Value = serde_json::from_slice(include_bytes!(
        "../../../examples/m3-domain-boundaries.solution.json"
    ))
    .unwrap();
    solution["request"]["rest"][1] = json!("-1");
    fs::write(
        dir.join("solution.json"),
        serde_json::to_vec(&solution).unwrap(),
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &[
                "run",
                "domain-a/manifest.json",
                "--solution",
                "solution.json"
            ],
            1
        )["diagnostics"][0]["code"],
        "E0300"
    );
}

#[test]
fn public_key_manifests_are_normalized_and_forged_schemas_cannot_bypass_guards() {
    let temp = fixture();
    let dir = temp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-publickey-boundaries.bas"),
    )
    .unwrap();
    fs::write(
        dir.join("bindings.json"),
        include_bytes!("../../../examples/m3-publickey-boundaries.bindings.json"),
    )
    .unwrap();
    fs::write(
        dir.join("solution.json"),
        include_bytes!("../../../examples/m3-publickey-boundaries.solution.json"),
    )
    .unwrap();
    for out in ["key-a", "key-b"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                out,
            ],
            0,
        );
    }
    assert_eq!(
        fs::read(dir.join("key-a/puzzle.clvm")).unwrap(),
        fs::read(dir.join("key-b/puzzle.clvm")).unwrap()
    );
    let path = dir.join("key-a/manifest.json");
    let original = fs::read(&path).unwrap();
    let mut manifest: Value = serde_json::from_slice(&original).unwrap();
    assert_eq!(manifest["fixed_parameters"][0]["type"]["kind"], "PUBLICKEY");
    let normalized = manifest["bindings"]["owner"]["hex"].as_str().unwrap();
    assert_eq!(normalized, normalized.to_lowercase());
    let result = invoke(
        dir,
        &["run", "key-a/manifest.json", "--solution", "solution.json"],
        0,
    );
    assert_eq!(
        result["result"]["tree"]["pair"][0]["pair"][1]["pair"][0]["atom"],
        "64"
    );
    manifest["inputs"][0]["type"]["element"]["first"] = json!({"kind":"BYTES"});
    fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    let mut solution: Value = serde_json::from_slice(include_bytes!(
        "../../../examples/m3-publickey-boundaries.solution.json"
    ))
    .unwrap();
    solution["candidates"][0]["first"]["hex"] = json!(format!("c0{}", "00".repeat(47)));
    fs::write(
        dir.join("solution.json"),
        serde_json::to_vec(&solution).unwrap(),
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "key-a/manifest.json", "--solution", "solution.json"],
            3
        )["diagnostics"][0]["code"],
        "E0500"
    );
    fs::write(&path, &original).unwrap();
    assert_eq!(
        invoke(
            dir,
            &["run", "key-a/manifest.json", "--solution", "solution.json"],
            1
        )["diagnostics"][0]["code"],
        "E0300"
    );
    manifest = serde_json::from_slice(&original).unwrap();
    manifest["fixed_parameters"][0]["type"]["element"] = json!({"kind":"BYTES"});
    fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
    invoke(dir, &["run", "key-a/manifest.json"], 4);
}

#[test]
fn payment_artifacts_build_reproducibly_and_run_without_spend_validation() {
    let temp = fixture();
    let dir = temp.path();
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/m3-payment-conditions.bas"),
    )
    .unwrap();
    fs::write(
        dir.join("bindings.json"),
        include_bytes!("../../../examples/m3-payment-conditions.bindings.json"),
    )
    .unwrap();
    for out in ["pay-a", "pay-b"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                out,
            ],
            0,
        );
    }
    assert_eq!(
        fs::read(dir.join("pay-a/puzzle.clvm")).unwrap(),
        fs::read(dir.join("pay-b/puzzle.clvm")).unwrap()
    );
    let result = invoke(dir, &["run", "pay-a/manifest.json"], 0);
    assert_eq!(result["result"]["validation"], "clvm-execution-only");
    let tree = &result["result"]["tree"];
    assert_eq!(tree["pair"][0]["pair"][0]["atom"], "49");
    assert_eq!(tree["pair"][1]["pair"][0]["pair"][0]["atom"], "53");
    let coin = &tree["pair"][1]["pair"][1]["pair"][0];
    assert_eq!(coin["pair"][0]["atom"], "33");
    assert_eq!(coin["pair"][1]["pair"][1]["pair"][1]["atom"], "");
    fs::write(
        dir.join("bindings.json"),
        format!(
            r#"{{"recipient":{{"hex":"{}"}},"paymentAmount":"-1","earliestHeight":"100"}}"#,
            "00".repeat(32)
        ),
    )
    .unwrap();
    assert_eq!(
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                "bad-payment"
            ],
            1
        )["diagnostics"][0]["code"],
        "E0301"
    );
    assert!(!dir.join("bad-payment").exists());
}

#[test]
fn signature_cli_preserves_messages_and_reports_execution_only() {
    let temp = fixture();
    let dir = temp.path();
    let vectors: Value =
        serde_json::from_slice(include_bytes!("../../../docs/spec/vectors.json")).unwrap();
    let key = vectors["payment"]["owner_hex"].as_str().unwrap();
    fs::write(dir.join("source file.bas"),"CONTRACT Demo(owner AS PUBLICKEY)\nSOLUTION message AS BYTES\nDIM pending = AGG_SIG_ME(owner,message)\nEMIT pending\nEND CONTRACT\n").unwrap();
    fs::write(
        dir.join("bindings.json"),
        format!(r#"{{"owner":{{"hex":"{key}"}}}}"#),
    )
    .unwrap();
    for out in ["sig-a", "sig-b"] {
        invoke(
            dir,
            &[
                "build",
                "source file.bas",
                "--bindings",
                "bindings.json",
                "--out",
                out,
            ],
            0,
        );
    }
    assert_eq!(
        fs::read(dir.join("sig-a/puzzle.clvm")).unwrap(),
        fs::read(dir.join("sig-b/puzzle.clvm")).unwrap()
    );
    for n in [1024, 1025] {
        let message = "00".repeat(n);
        fs::write(
            dir.join("solution.json"),
            format!(r#"{{"message":{{"hex":"{message}"}}}}"#),
        )
        .unwrap();
        fs::write(
            dir.join("raw.hex"),
            format!("ffc4{:02x}{message}80", n - 1024),
        )
        .unwrap();
        for (flag, file) in [
            ("--solution", "solution.json"),
            ("--solution-hex", "raw.hex"),
        ] {
            let r = invoke(
                dir,
                &["run", "sig-a/manifest.json", flag, file],
                if n == 1024 { 0 } else { 3 },
            );
            if n == 1024 {
                assert_eq!(r["result"]["validation"], "clvm-execution-only");
                let condition = &r["result"]["tree"]["pair"][0];
                assert_eq!(condition["pair"][0]["atom"], "32");
                assert_eq!(condition["pair"][1]["pair"][0]["atom"], key);
                assert_eq!(condition["pair"][1]["pair"][1]["pair"][0]["atom"], message);
            } else {
                assert_eq!(r["diagnostics"][0]["code"], "E0500");
            }
        }
    }
    fs::write(
        dir.join("source file.bas"),
        include_bytes!("../../../examples/height-locked-payment.bas"),
    )
    .unwrap();
    fs::write(
        dir.join("bindings.json"),
        include_bytes!("../../../examples/height-locked-payment.bindings.json"),
    )
    .unwrap();
    invoke(
        dir,
        &[
            "build",
            "source file.bas",
            "--bindings",
            "bindings.json",
            "--out",
            "full-payment",
        ],
        0,
    );
    let r = invoke(dir, &["run", "full-payment/manifest.json"], 0);
    assert_eq!(r["result"]["validation"], "clvm-execution-only");
}

#[test]
fn explain_is_repeatable_read_only_and_has_no_binding_requirement() {
    let dir = fixture();
    let dir = dir.path();
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo(n AS INTEGER)\nSOLUTION x AS BYTES\nASSERT FALSE\nEND CONTRACT\n",
    )
    .unwrap();
    let before: Vec<_> = fs::read_dir(dir)
        .unwrap()
        .map(|p| p.unwrap().file_name())
        .collect();
    for stage in ["ast", "ir"] {
        let args = ["explain", "source file.bas", "--stage", stage];
        let result = invoke(dir, &args, 0);
        assert_eq!(result, invoke(dir, &args, 0));
        assert_eq!(result["command"], "explain");
        assert_eq!(result["result"]["stage"], stage);
        assert_eq!(result["result"]["source"]["name"], "source file.bas");
        assert_eq!(
            result["result"]["compiler_version"],
            env!("CARGO_PKG_VERSION")
        );
    }
    let after: Vec<_> = fs::read_dir(dir)
        .unwrap()
        .map(|p| p.unwrap().file_name())
        .collect();
    assert_eq!(before, after);
}

#[test]
fn explain_rejects_invalid_options_and_distinguishes_parse_and_check() {
    let dir = fixture();
    let dir = dir.path();
    for args in [
        vec!["explain", "absent.bas"],
        vec!["explain", "absent.bas", "--stage", "CLVM"],
        vec!["explain", "absent.bas", "--stage", "unknown"],
        vec!["explain", "absent.bas", "--stage", "ast", "--stage", "ir"],
        vec![
            "explain",
            "absent.bas",
            "--stage",
            "ast",
            "--bindings",
            "absent.json",
        ],
        vec!["explain", "absent.bas", "--stage", "ir", "--template-only"],
        vec!["explain", "absent.bas", "--stage", "ir", "--out", "output"],
    ] {
        assert_eq!(invoke(dir, &args, 2)["diagnostics"][0]["code"], "E0400");
    }
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo()\nEMIT unknown\nEND CONTRACT\n",
    )
    .unwrap();
    invoke(dir, &["explain", "source file.bas", "--stage", "ast"], 0);
    let checked = invoke(dir, &["check", "source file.bas"], 1);
    let explained = invoke(dir, &["explain", "source file.bas", "--stage", "ir"], 1);
    assert_eq!(checked["diagnostics"], explained["diagnostics"]);
}

#[test]
fn clvm_explain_matches_build_artifacts_and_is_read_only() {
    let dir = fixture();
    let dir = dir.path();
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo(n AS INTEGER)\nASSERT FALSE\nEND CONTRACT\n",
    )
    .unwrap();
    fs::write(dir.join("bindings.json"), "{\"N\":\"7\"}").unwrap();
    for template_only in [false, true] {
        let flags = if template_only {
            vec!["--template-only"]
        } else {
            vec!["--bindings", "bindings.json"]
        };
        let mut args = vec!["explain", "source file.bas", "--stage", "clvm"];
        args.extend(&flags);
        let before = fs::read_dir(dir).unwrap().count();
        let result = invoke(dir, &args, 0);
        assert_eq!(result, invoke(dir, &args, 0));
        assert_eq!(before, fs::read_dir(dir).unwrap().count());
        let out = if template_only { "unbound" } else { "bound" };
        let mut args = vec!["build", "source file.bas", "--out", out];
        args.extend(&flags);
        let built = invoke(dir, &args, 0);
        let r = &result["result"]["representation"];
        for name in ["template", "puzzle"] {
            if template_only && name == "puzzle" {
                assert!(r[name].is_null());
                continue;
            }
            assert_eq!(r[name]["tree_hash"], built["result"][name]["tree_hash"]);
            assert_eq!(
                r[name]["program_sha256"],
                built["result"][name]["program_sha256"]
            );
            assert_eq!(
                r[name]["hex"],
                hex::encode(fs::read(dir.join(out).join(format!("{name}.clvm"))).unwrap())
            );
        }
    }
}

#[test]
fn clvm_explain_reports_binding_and_usage_errors() {
    let dir = fixture();
    let dir = dir.path();
    fs::write(
        dir.join("source file.bas"),
        "CONTRACT Demo(n AS INTEGER)\nEND CONTRACT\n",
    )
    .unwrap();
    assert_eq!(
        invoke(dir, &["explain", "source file.bas", "--stage", "clvm"], 1)["diagnostics"][0]["code"],
        "E0301"
    );
    invoke(
        dir,
        &[
            "explain",
            "source file.bas",
            "--stage",
            "clvm",
            "--bindings",
            "missing.json",
        ],
        4,
    );
    for flags in [
        vec!["--bindings", "missing.json", "--template-only"],
        vec!["--solution", "missing.json"],
        vec!["--out", "output"],
    ] {
        let mut args = vec!["explain", "absent.bas", "--stage", "clvm"];
        args.extend(flags);
        invoke(dir, &args, 2);
    }
}

#[test]
fn artifact_metadata_matrix_rejects_invalid_versions_and_provenance() {
    let dir = fixture();
    let dir = dir.path();
    build(dir, "out");
    let path = dir.join("out/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    for (pointer, value, status) in [
        ("/schema_version", json!(2), 2),
        ("/language_version", json!("future"), 2),
        ("/abi_version", json!(2), 2),
        ("/target_profile", json!("future"), 2),
        ("/optimization", json!("aggressive"), 2),
        ("/compiler/version", json!("future"), 2),
        ("/compiler/rust_version", json!("0.0.0"), 4),
        ("/compiler/cargo_lock_sha256", json!("bad"), 4),
        ("/source/sha256", json!("G".repeat(64)), 4),
        ("/source/name", json!("../source.bas"), 4),
        ("/source/name", json!("..\\source.bas"), 4),
        ("/source/name", json!("source.txt"), 4),
        ("/contract", json!("Uppercase"), 4),
        ("/contract", json!("bad-name"), 4),
        ("/template/program_sha256", json!("0".repeat(64)), 4),
        ("/puzzle/tree_hash", json!("0".repeat(64)), 4),
    ] {
        let mut changed = original.clone();
        *changed.pointer_mut(pointer).unwrap() = value;
        fs::write(&path, serde_json::to_vec(&changed).unwrap()).unwrap();
        let result = invoke(dir, &["run", "out/manifest.json"], status);
        assert_eq!(
            result["diagnostics"][0]["code"],
            if status == 2 { "E0400" } else { "E0600" },
            "{pointer}"
        );
    }
    fs::write(&path, serde_json::to_vec(&original).unwrap()).unwrap();
    invoke(dir, &["run", "out/manifest.json"], 0);
}

#[test]
fn every_artifact_path_rejects_aliases_traversal_and_absolute_names() {
    let dir = fixture();
    let dir = dir.path();
    build(dir, "out");
    let path = dir.join("out/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    for role in ["template", "puzzle"] {
        for field in ["binary", "hex"] {
            for bad in [
                "../outside.clvm",
                "..\\outside.clvm",
                "/tmp/outside.clvm",
                "C:\\outside.clvm",
                "\\\\server\\share\\outside.clvm",
                "./puzzle.clvm",
                "puzzle.clvm:stream",
                "other.clvm",
                "",
            ] {
                let mut changed = original.clone();
                changed[role][field] = json!(bad);
                fs::write(&path, serde_json::to_vec(&changed).unwrap()).unwrap();
                assert_eq!(
                    invoke(dir, &["run", "out/manifest.json"], 4)["diagnostics"][0]["code"],
                    "E0600"
                );
            }
        }
    }
}

#[test]
fn matching_file_digests_cannot_hide_template_puzzle_binding_mismatch() {
    let dir = fixture();
    let dir = dir.path();
    build(dir, "out");
    let path = dir.join("out/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    for role in ["template", "puzzle"] {
        let binary_path = dir.join(format!("out/{role}.clvm"));
        let hex_path = dir.join(format!("out/{role}.hex"));
        let binary = fs::read(&binary_path).unwrap();
        let text = fs::read(&hex_path).unwrap();
        let mut changed = original.clone();
        // Canonical nil with internally consistent bytes, hex and both hashes.
        fs::write(&binary_path, [0x80]).unwrap();
        fs::write(&hex_path, "80\n").unwrap();
        changed[role]["program_sha256"] = json!(oxbasic_compiler::clvm::sha256(&[0x80]));
        changed[role]["tree_hash"] = json!(oxbasic_compiler::clvm::tree_hash(&[0x80]).unwrap());
        fs::write(&path, serde_json::to_vec(&changed).unwrap()).unwrap();
        let r = invoke(dir, &["run", "out/manifest.json"], 4);
        assert!(
            r["diagnostics"][0]["message"]
                .as_str()
                .unwrap()
                .contains("ABI binding")
        );
        fs::write(binary_path, binary).unwrap();
        fs::write(hex_path, text).unwrap();
    }
    fs::write(&path, serde_json::to_vec(&original).unwrap()).unwrap();
    invoke(dir, &["run", "out/manifest.json"], 0);
}

#[test]
fn nested_artifact_metadata_requires_exact_fields_and_canonical_hex_files() {
    let dir = fixture();
    let dir = dir.path();
    build(dir, "out");
    let path = dir.join("out/manifest.json");
    let original: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    for (object, field) in [
        ("compiler", "version"),
        ("source", "name"),
        ("template", "hex"),
        ("puzzle", "tree_hash"),
    ] {
        for variant in 0..3 {
            let mut changed = original.clone();
            let text = if variant == 0 {
                let value = serde_json::to_string(&changed[object][field]).unwrap();
                let object_text = serde_json::to_string(&changed[object]).unwrap();
                serde_json::to_string(&changed).unwrap().replace(
                    &object_text,
                    &object_text.replacen('{', &format!("{{\"{field}\":{value},"), 1),
                )
            } else {
                if variant == 1 {
                    changed[object].as_object_mut().unwrap().remove(field);
                } else {
                    changed[object]["unknown"] = json!(true);
                }
                serde_json::to_string(&changed).unwrap()
            };
            fs::write(&path, text).unwrap();
            assert_eq!(
                invoke(dir, &["run", "out/manifest.json"], 4)["diagnostics"][0]["code"],
                "E0600"
            );
        }
    }
    fs::write(&path, serde_json::to_vec(&original).unwrap()).unwrap();
    for role in ["template", "puzzle"] {
        let hex_path = dir.join(format!("out/{role}.hex"));
        let text = fs::read_to_string(&hex_path).unwrap();
        for bad in [
            text.trim().to_owned(),
            text.to_uppercase(),
            format!(" {text}"),
            format!("{text}00"),
        ] {
            fs::write(&hex_path, bad).unwrap();
            invoke(dir, &["run", "out/manifest.json"], 4);
        }
        fs::write(hex_path, text).unwrap();
    }
}

#[test]
fn relocated_artifacts_run_without_source_and_provenance_is_not_authentication() {
    let dir = fixture();
    let dir = dir.path();
    build(dir, "out");
    let expected = invoke(dir, &["run", "out/manifest.json"], 0);
    let relocated = dir.join("relocated bundle");
    fs::create_dir(&relocated).unwrap();
    for name in [
        "template.clvm",
        "template.hex",
        "puzzle.clvm",
        "puzzle.hex",
        "manifest.json",
    ] {
        fs::copy(dir.join("out").join(name), relocated.join(name)).unwrap();
    }
    let path = relocated.join("manifest.json");
    let mut m: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    // Validly shaped descriptive provenance is not verified against external source or lock files.
    m["source"]["name"] = json!("not-present.bas");
    m["source"]["sha256"] = json!("0".repeat(64));
    m["compiler"]["cargo_lock_sha256"] = json!("1".repeat(64));
    fs::write(path, serde_json::to_vec(&m).unwrap()).unwrap();
    assert_eq!(
        invoke(dir, &["run", "relocated bundle/manifest.json"], 0),
        expected
    );
}
