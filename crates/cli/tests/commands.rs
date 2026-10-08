use serde_json::{Value, json};

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
        "CONTRACT Broken()\nSOLUTION x AS BOOLEAN\nEND CONTRACT",
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
    let dir = fixture();
    let dir = dir.path();
    build(dir, "out");
    // Move this test's artifact, then point its old name outside the output directory.
    std::fs::rename(dir.join("out/puzzle.clvm"), dir.join("outside.clvm")).unwrap();
    std::os::unix::fs::symlink("../outside.clvm", dir.join("out/puzzle.clvm")).unwrap();
    invoke(dir, &["run", "out/manifest.json"], 4);
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
