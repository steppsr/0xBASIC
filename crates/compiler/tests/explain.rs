use oxbasic_compiler::{
    COMPILER_VERSION, check, clvm,
    explain::{Stage, explain},
};
use serde_json::Value;

#[test]
fn views_preserve_template_fields_functions_and_checked_ir() {
    let source = include_bytes!("../../../examples/height-locked-payment.bas");
    let ast = explain("payment.bas", source, Stage::Ast).unwrap();
    assert_eq!(ast["compiler_version"], COMPILER_VERSION);
    assert_eq!(ast["source"]["sha256"], clvm::sha256(source));
    let r = &ast["representation"];
    assert_eq!(r["contract"]["fixed"].as_array().unwrap().len(), 4);
    assert_eq!(r["functions"].as_array().unwrap().len(), 1);
    for kind in [
        "Assert", "Emit", "Return", "Local", "Call", "Binary", "String", "Bytes", "Name",
    ] {
        assert!(
            r["nodes"]
                .as_array()
                .unwrap()
                .iter()
                .any(|n| n["kind"] == kind),
            "{kind}"
        );
    }
    let ir = explain("payment.bas", source, Stage::Ir).unwrap();
    assert_eq!(
        ir["representation"],
        serde_json::to_value(check("payment.bas", source).unwrap()).unwrap()
    );
}

#[test]
fn ast_is_parse_only_and_ir_checks_without_execution() {
    let invalid = b"CONTRACT Demo()\nEMIT unknown\nEND CONTRACT\n";
    explain("demo.bas", invalid, Stage::Ast).unwrap();
    let expected = check("demo.bas", invalid).unwrap_err();
    let actual = explain("demo.bas", invalid, Stage::Ir).unwrap_err();
    assert_eq!(actual.code, expected.code);
    assert_eq!(actual.span, expected.span);
    for stage in [Stage::Ast, Stage::Ir] {
        assert!(explain("demo.bas", b"CONTRACT", stage).is_err());
        explain(
            "demo.bas",
            b"CONTRACT Demo(n AS INTEGER)\nSOLUTION x AS BYTES\nASSERT FALSE\nEND CONTRACT\n",
            stage,
        )
        .unwrap();
    }
}

#[test]
fn source_spans_and_literal_spelling_survive_bom_crlf_and_unicode() {
    let source = "\u{feff}CONTRACT Demo()\r\n' café\r\nDIM x = &H0a + 2\r\nEND CONTRACT\r\n";
    let ast = explain("unicode.bas", source.as_bytes(), Stage::Ast).unwrap();
    let nodes = ast["representation"]["nodes"].as_array().unwrap();
    let literal = nodes.iter().find(|n| n["kind"] == "Integer").unwrap();
    assert_eq!(literal["data"]["spelling"], "&H0a");
    let span = &literal["span"];
    assert_eq!(
        &source[span["start_byte"].as_u64().unwrap() as usize
            ..span["end_byte"].as_u64().unwrap() as usize],
        "&H0a"
    );
    assert_eq!(span["line"], 3);
    let binary = nodes.iter().find(|n| n["kind"] == "Binary").unwrap();
    let operator = &binary["data"]["operator_span"];
    assert_eq!(
        &source[operator["start_byte"].as_u64().unwrap() as usize
            ..operator["end_byte"].as_u64().unwrap() as usize],
        "+"
    );
}

#[test]
fn nested_syntax_is_flat_and_json_round_trips() {
    let source = format!(
        "CONTRACT Demo()\n{}DIM x = {}1{}\n{}END CONTRACT\n",
        "IF TRUE THEN\n".repeat(30),
        "(".repeat(60),
        ")".repeat(60),
        "END IF\n".repeat(30)
    );
    for stage in [Stage::Ast, Stage::Ir] {
        let view = explain("nested.bas", source.as_bytes(), stage).unwrap();
        let bytes = serde_json::to_vec(&view).unwrap();
        assert_eq!(serde_json::from_slice::<Value>(&bytes).unwrap(), view);
    }
    let ast = explain("nested.bas", source.as_bytes(), Stage::Ast).unwrap();
    let nodes = ast["representation"]["nodes"].as_array().unwrap();
    for (id, node) in nodes.iter().enumerate() {
        let d = &node["data"];
        for key in ["expression", "initializer", "predicate"] {
            if let Some(child) = d[key].as_u64() {
                assert!((child as usize) < id);
            }
        }
        for key in ["yes", "no"] {
            if let Some(children) = d[key].as_array() {
                for child in children {
                    assert!((child.as_u64().unwrap() as usize) < id);
                }
            }
        }
    }
}

#[test]
fn clvm_views_match_compilation_and_flat_tree_hashes() {
    use oxbasic_compiler::{compile_template, explain::explain_clvm};
    let source = include_bytes!("../../../examples/height-locked-payment.bas");
    let bindings = include_bytes!("../../../examples/height-locked-payment.bindings.json");
    let template = compile_template("payment.bas", source).unwrap();
    let bound = template.bind(bindings).unwrap();
    let view = explain_clvm("payment.bas", source, Some(bindings)).unwrap();
    let r = &view["representation"];
    for (name, bytes) in [("template", &template.template), ("puzzle", &bound.puzzle)] {
        let p = &r[name];
        assert_eq!(p["hex"], hex::encode(bytes));
        assert_eq!(p["program_sha256"], clvm::sha256(bytes));
        assert_eq!(p["tree_hash"], clvm::tree_hash(bytes).unwrap());
        let nodes = p["nodes"].as_array().unwrap();
        let mut hashes = vec![String::new(); nodes.len()];
        for (id, node) in nodes.iter().enumerate().rev() {
            let digest = if let Some(atom) = node["atom"].as_str() {
                let mut data = vec![1];
                data.extend(hex::decode(atom).unwrap());
                clvm::sha256(&data)
            } else {
                let pair = node["pair"].as_array().unwrap();
                let mut data = vec![2];
                for child in pair {
                    let child = child.as_u64().unwrap() as usize;
                    assert!(child > id);
                    data.extend(hex::decode(&hashes[child]).unwrap());
                }
                clvm::sha256(&data)
            };
            hashes[id] = digest;
        }
        assert_eq!(hashes[0], p["tree_hash"]);
    }
    assert_eq!(r["bindings"], serde_json::to_value(bound.bindings).unwrap());
    let unbound = explain_clvm("payment.bas", source, None).unwrap();
    assert_eq!(unbound["representation"]["template"], r["template"]);
    assert!(unbound["representation"]["puzzle"].is_null());
    assert!(unbound["representation"]["bindings"].is_null());
}

#[test]
fn clvm_view_enforces_binding_rules_without_executing() {
    use oxbasic_compiler::explain::explain_clvm;
    let source = b"CONTRACT Demo(n AS INTEGER)\nASSERT FALSE\nEND CONTRACT\n";
    for bad in [b"{}".as_slice(), b"{\"n\":1}", b"{\"n\":\"1\",\"N\":\"2\"}"] {
        assert_eq!(
            explain_clvm("demo.bas", source, Some(bad))
                .unwrap_err()
                .code,
            "E0301"
        );
    }
    explain_clvm("demo.bas", source, Some(b"{\"N\":\"1\"}")).unwrap();
    explain_clvm("demo.bas", source, None).unwrap();
    let empty = explain_clvm(
        "empty.bas",
        b"CONTRACT Empty()\nEND CONTRACT\n",
        Some(b"{}"),
    )
    .unwrap();
    assert_ne!(
        empty["representation"]["template"]["hex"],
        empty["representation"]["puzzle"]["hex"]
    );
}

#[test]
fn large_clvm_view_round_trips_without_recursive_json() {
    let source = format!(
        "CONTRACT Demo()\n{}END CONTRACT\n",
        "EMIT ASSERT_HEIGHT_ABSOLUTE(100)\n".repeat(256)
    );
    let view = oxbasic_compiler::explain::explain_clvm("large.bas", source.as_bytes(), Some(b"{}"))
        .unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&serde_json::to_vec(&view).unwrap()).unwrap(),
        view
    );
}
