use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};

fn invoke(dir: &Path, args: &[&str], status: i32) -> Value {
    let output = Command::new(env!("CARGO_BIN_EXE_0xbasic"))
        .current_dir(dir)
        .args(args)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(status), "{output:?}");
    assert!(output.stderr.is_empty(), "{output:?}");
    assert!(output.stdout.ends_with(b"\n"));
    let envelope: Value = serde_json::from_slice(&output.stdout).unwrap();
    let keys: Vec<_> = envelope
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(
        keys,
        ["command", "diagnostics", "ok", "result", "schema_version"]
    );
    assert_eq!(envelope["schema_version"], 1);
    assert_eq!(envelope["command"], args[0]);
    assert_eq!(envelope["ok"], status == 0);
    if status == 0 {
        assert_eq!(envelope["diagnostics"], json!([]));
        assert!(!envelope["result"].is_null());
    } else {
        assert!(envelope["result"].is_null());
        assert_eq!(envelope["diagnostics"].as_array().unwrap().len(), 1);
        let diagnostic = &envelope["diagnostics"][0];
        let keys: Vec<_> = diagnostic
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();
        assert_eq!(
            keys,
            ["code", "message", "notes", "severity", "source", "span"]
        );
        assert_eq!(diagnostic["severity"], "error");
        assert!(!diagnostic["message"].as_str().unwrap().is_empty());
        assert!(
            diagnostic["notes"]
                .as_array()
                .unwrap()
                .iter()
                .all(Value::is_string)
        );
    }
    envelope
}

#[test]
fn diagnostic_contract_unicode_spans_and_human_streams() {
    let dir = tempfile::tempdir().unwrap();
    fs::create_dir(dir.path().join("nested")).unwrap();
    let source = "\u{feff}CONTRACT Demo()\r\n\tDIM x = (\"é🐈\" = missing)\r\nEND CONTRACT\r\n";
    fs::write(dir.path().join("nested/source é.bas"), source).unwrap();
    let args = ["check", "nested/source é.bas"];
    let envelope = invoke(dir.path(), &args, 1);
    let diagnostic = &envelope["diagnostics"][0];
    assert_eq!(diagnostic["code"], "E0200");
    assert_eq!(diagnostic["source"], "source é.bas");
    let start = source.find("missing").unwrap();
    assert_eq!(
        diagnostic["span"],
        json!({
            "start_byte": start, "end_byte": start + 7, "line": 2, "column": 18
        })
    );
    let human = Command::new(env!("CARGO_BIN_EXE_0xbasic"))
        .current_dir(dir.path())
        .args(args)
        .output()
        .unwrap();
    assert_eq!(human.status.code(), Some(1));
    assert!(human.stdout.is_empty());
    assert_eq!(
        String::from_utf8(human.stderr).unwrap(),
        format!(
            "source é.bas:2:18: E0200: {}\n",
            diagnostic["message"].as_str().unwrap()
        )
    );
}

#[test]
fn diagnostic_contract_exit_categories_and_absent_locations() {
    let dir = tempfile::tempdir().unwrap();
    fs::write(
        dir.path().join("source.bas"),
        "CONTRACT Demo()\nEMIT ASSERT_HEIGHT_ABSOLUTE(-1)\nEND CONTRACT\n",
    )
    .unwrap();
    invoke(dir.path(), &["check", "source.bas"], 0);
    invoke(dir.path(), &["build", "source.bas", "--out", "artifact"], 0);
    fs::write(
        dir.path().join("fixed.bas"),
        "CONTRACT Fixed(n AS INTEGER)\nEND CONTRACT\n",
    )
    .unwrap();
    let cases: &[(&[&str], i32, &str)] = &[
        (&["check", "source.bas", "--unknown"], 2, "E0400"),
        (&["check", "absent.bas"], 4, "E0600"),
        (
            &["build", "fixed.bas", "--out", "missing-binding"],
            1,
            "E0301",
        ),
        (&["run", "artifact/manifest.json"], 3, "E0500"),
        (
            &["run", "artifact/manifest.json", "--max-cost", "1"],
            3,
            "E0501",
        ),
    ];
    for (args, status, code) in cases {
        let result = invoke(dir.path(), args, *status);
        assert_eq!(result["diagnostics"][0]["code"], *code);
    }
    assert!(!dir.path().join("missing-binding").exists());
    let usage = invoke(dir.path(), &["check", "source.bas", "--unknown"], 2);
    assert!(usage["diagnostics"][0]["source"].is_null());
    assert!(usage["diagnostics"][0]["span"].is_null());
    let human = Command::new(env!("CARGO_BIN_EXE_0xbasic"))
        .current_dir(dir.path())
        .args(["check", "source.bas", "--unknown"])
        .output()
        .unwrap();
    assert_eq!(human.status.code(), Some(2));
    assert!(human.stdout.is_empty());
    assert_eq!(
        String::from_utf8(human.stderr).unwrap(),
        format!(
            "E0400: {}\n",
            usage["diagnostics"][0]["message"].as_str().unwrap()
        )
    );
}

#[test]
fn diagnostic_contract_version_and_success_streams() {
    let output = Command::new(env!("CARGO_BIN_EXE_0xbasic"))
        .arg("--version")
        .output()
        .unwrap();
    assert!(output.status.success());
    assert!(output.stderr.is_empty());
    let version: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        version,
        json!({"compiler": env!("CARGO_PKG_VERSION"), "language": "0.2",
        "abi": 1, "target_profile": "chia-clvm-0.19-strict-v1"})
    );
    let dir = tempfile::tempdir().unwrap();
    fs::write(
        dir.path().join("source.bas"),
        "CONTRACT Demo()\nEND CONTRACT\n",
    )
    .unwrap();
    let envelope = invoke(dir.path(), &["check", "source.bas"], 0);
    let human = Command::new(env!("CARGO_BIN_EXE_0xbasic"))
        .current_dir(dir.path())
        .args(["check", "source.bas"])
        .output()
        .unwrap();
    assert!(human.status.success());
    assert!(human.stderr.is_empty());
    assert_eq!(
        serde_json::from_slice::<Value>(&human.stdout).unwrap(),
        envelope["result"]
    );
}
