use oxbasic_compiler::{abi, clvm, compile_template};
use serde_json::Value;

#[test]
fn all_original_source_cases_are_active() {
    let cases: Value =
        serde_json::from_str(include_str!("../../../docs/spec/source-cases.json")).unwrap();
    let vectors: Value =
        serde_json::from_str(include_str!("../../../docs/spec/vectors.json")).unwrap();
    assert_eq!(cases["cases"].as_array().unwrap().len(), 29);
    for case in cases["cases"].as_array().unwrap() {
        let source = case["source"]
            .as_str()
            .unwrap_or(include_str!("../../../examples/height-locked-payment.bas"));
        let template = compile_template("case.bas", source.as_bytes());
        if !case["accept"].as_bool().unwrap() {
            assert_eq!(
                template.err().unwrap().code,
                case["diagnostic"],
                "{}",
                case["id"]
            );
            continue;
        }
        let template = template.unwrap();
        let bindings: &[u8] = if case["id"] == "full-payment" {
            include_bytes!("../../../examples/height-locked-payment.bindings.json")
        } else {
            b"{}"
        };
        let bound = template.bind(bindings).unwrap();
        let solution = abi::encode_solution(
            &template.contract.inputs,
            &serde_json::to_vec(case.get("solution").unwrap_or(&serde_json::json!({}))).unwrap(),
        )
        .unwrap();
        let result = clvm::execute(&bound.puzzle, &solution, clvm::DEFAULT_MAX_COST).unwrap();
        if case["id"] == "full-payment" {
            assert_eq!(
                hex::encode(&result.bytes),
                vectors["payment"]["conditions_serialized_hex"]
            );
        } else {
            let expected = case["expected_conditions"].as_array().unwrap();
            let mut a = clvmr::Allocator::new();
            let mut tail = clvmr::NodePtr::NIL;
            for condition in expected.iter().rev() {
                let mut row = clvmr::NodePtr::NIL;
                for item in condition.as_array().unwrap().iter().rev() {
                    let atom = a.new_small_number(item.as_u64().unwrap() as u32).unwrap();
                    row = a.new_pair(atom, row).unwrap();
                }
                tail = a.new_pair(row, tail).unwrap();
            }
            assert_eq!(
                result.bytes,
                clvmr::serde::node_to_bytes(&a, tail).unwrap(),
                "{}",
                case["id"]
            );
        }
        clvm::execute(&bound.puzzle, &solution, result.cost).unwrap();
        assert_eq!(
            clvm::execute(&bound.puzzle, &solution, result.cost - 1)
                .err()
                .unwrap()
                .code,
            "E0501"
        );
    }
}

#[test]
fn original_boundary_vectors_guard_fixed_and_solution_even_when_unused() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../docs/spec/vectors.json")).unwrap();
    for case in vectors["boundary_cases"].as_array().unwrap() {
        for fixed in [false, true] {
            let fields: Vec<_> = case["schema"]
                .as_array()
                .unwrap()
                .iter()
                .enumerate()
                .map(|(i, t)| format!("field{i} AS {}", t.as_str().unwrap()))
                .collect();
            let source = if fixed {
                format!("CONTRACT Demo({})\nEND CONTRACT\n", fields.join(","))
            } else {
                format!(
                    "CONTRACT Demo()\n{}END CONTRACT\n",
                    fields
                        .iter()
                        .map(|f| format!("SOLUTION {f}\n"))
                        .collect::<String>()
                )
            };
            let template = compile_template("boundary.bas", source.as_bytes()).unwrap();
            let raw = hex::decode(case["serialized_solution_hex"].as_str().unwrap()).unwrap();
            let (puzzle, solution) = if fixed {
                (
                    clvm::bind_fixed(&template.template, &raw).unwrap(),
                    vec![0x80],
                )
            } else {
                (template.bind(b"{}").unwrap().puzzle, raw)
            };
            let result = clvm::execute(&puzzle, &solution, clvm::DEFAULT_MAX_COST);
            if case["valid"].as_bool().unwrap() {
                assert_eq!(result.unwrap().bytes, vec![0x80]);
            } else {
                assert_eq!(
                    result.err().unwrap().code,
                    "E0500",
                    "{} fixed={fixed}",
                    case["name"]
                );
            }
        }
    }
}

#[test]
fn combined_maximum_field_counts_preserve_slots_and_validate_last_fields() {
    let fixed = (0..32)
        .map(|i| format!("f{i} AS INTEGER"))
        .collect::<Vec<_>>()
        .join(",");
    let inputs = (0..32)
        .map(|i| format!("SOLUTION s{i} AS INTEGER\n"))
        .collect::<String>();
    let source = format!(
        "CONTRACT Demo({fixed})\n{inputs}DIM n = f31 + s31\nIF n > 0 THEN\nEMIT ASSERT_HEIGHT_ABSOLUTE(n)\nEND IF\nEND CONTRACT\n"
    );
    let t = compile_template("maximum.bas", source.as_bytes()).unwrap();
    let f: serde_json::Map<_, _> = (0..32)
        .map(|i| (format!("f{i}"), Value::String(i.to_string())))
        .collect();
    let s: serde_json::Map<_, _> = (0..32)
        .map(|i| (format!("s{i}"), Value::String(i.to_string())))
        .collect();
    let bound = t.bind(&serde_json::to_vec(&f).unwrap()).unwrap();
    let solution =
        abi::encode_solution(&t.contract.inputs, &serde_json::to_vec(&s).unwrap()).unwrap();
    let result = clvm::execute(&bound.puzzle, &solution, clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(hex::encode(result.bytes), "ffff53ff3e8080");
    let mut invalid_fixed =
        abi::encode_bindings(&t.contract.fixed, &serde_json::to_vec(&f).unwrap())
            .unwrap()
            .bytes;
    let len = invalid_fixed.len();
    invalid_fixed[len - 2] = 0;
    let invalid_puzzle = clvm::bind_fixed(&t.template, &invalid_fixed).unwrap();
    assert_eq!(
        clvm::execute(&invalid_puzzle, &solution, clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    let mut invalid = solution;
    // Last INTEGER atom becomes noncanonical zero; serialization remains valid.
    let len = invalid.len();
    invalid[len - 2] = 0;
    assert_eq!(
        clvm::execute(&bound.puzzle, &invalid, clvm::DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}

#[test]
fn original_scalar_atom_and_serialization_vectors_remain_enforced() {
    let vectors: Value =
        serde_json::from_str(include_str!("../../../docs/spec/vectors.json")).unwrap();
    for (key, ty, valid) in [
        ("valid_boolean_atoms", "BOOLEAN", true),
        ("invalid_boolean_atoms", "BOOLEAN", false),
        ("valid_utf8_atoms", "STRING", true),
        ("invalid_utf8_atoms", "STRING", false),
        ("invalid_public_key_atoms", "PUBLICKEY", false),
        ("noncanonical_integer_atoms", "INTEGER", false),
    ] {
        for fixed in [false, true] {
            let source = if fixed {
                format!("CONTRACT Demo(v AS {ty})\nEND CONTRACT\n")
            } else {
                format!("CONTRACT Demo()\nSOLUTION v AS {ty}\nEND CONTRACT\n")
            };
            let t = compile_template("atoms.bas", source.as_bytes()).unwrap();
            for atom in vectors[key].as_array().unwrap() {
                let mut a = clvmr::Allocator::new();
                let atom = a
                    .new_atom(&hex::decode(atom.as_str().unwrap()).unwrap())
                    .unwrap();
                let list = a.new_pair(atom, clvmr::NodePtr::NIL).unwrap();
                let raw = clvmr::serde::node_to_bytes(&a, list).unwrap();
                let (puzzle, solution) = if fixed {
                    (clvm::bind_fixed(&t.template, &raw).unwrap(), vec![0x80])
                } else {
                    (t.bind(b"{}").unwrap().puzzle, raw)
                };
                let result = clvm::execute(&puzzle, &solution, clvm::DEFAULT_MAX_COST);
                if valid {
                    assert_eq!(result.unwrap().bytes, vec![0x80]);
                } else {
                    assert_eq!(result.err().unwrap().code, "E0500", "{key} fixed={fixed}");
                }
            }
        }
    }
    for vector in vectors["serialization"].as_array().unwrap() {
        assert_eq!(
            clvm::tree_hash(&hex::decode(vector["serialized_hex"].as_str().unwrap()).unwrap())
                .unwrap(),
            vector["tree_hash"]
        );
    }
}
