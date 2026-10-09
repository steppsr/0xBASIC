use oxbasic_compiler::{abi, analyze, check, clvm, compile, compile_template};
use serde::Deserialize;
#[derive(Deserialize)]
struct Case {
    id: String,
    hex: String,
    valid: bool,
}
fn cases() -> Vec<Case> {
    #[derive(Deserialize)]
    struct Fixture {
        cases: Vec<Case>,
    }
    serde_json::from_str::<Fixture>(include_str!("../../../docs/spec/m3-publickey-cases.json"))
        .unwrap()
        .cases
}
fn source(fixed: bool, body: &str) -> String {
    if fixed {
        format!("CONTRACT Demo(value AS PUBLICKEY)\n{body}END CONTRACT\n")
    } else {
        format!("CONTRACT Demo()\nSOLUTION value AS PUBLICKEY\n{body}END CONTRACT\n")
    }
}
fn run(body: &str) -> oxbasic_compiler::Result<clvm::Execution> {
    let p = compile(
        "key.bas",
        format!("CONTRACT Demo()\n{body}END CONTRACT\n").as_bytes(),
    )?;
    clvm::execute(&p.puzzle, &[0x80], clvm::DEFAULT_MAX_COST)
}
#[test]
fn pinned_decoder_checks_subgroup_and_requires_separate_infinity_rejection() {
    for c in cases() {
        let bytes = hex::decode(&c.hex).unwrap();
        let Ok(array) = <&[u8; 48]>::try_from(bytes.as_slice()) else {
            assert!(!c.valid);
            continue;
        };
        let key = chia_bls::PublicKey::from_bytes(array);
        assert_eq!(
            key.as_ref()
                .is_ok_and(|k| !k.is_inf() && k.to_bytes() == *array),
            c.valid,
            "{}",
            c.id
        );
        if c.id == "not-in-subgroup" {
            assert!(chia_bls::PublicKey::from_bytes_unchecked(array).is_ok());
            assert!(key.is_err());
        }
        if c.id == "infinity" {
            assert!(key.unwrap().is_inf());
        }
    }
}
#[test]
fn public_key_json_is_checked_duplicate_safe_and_normalized() {
    for fixed in [false, true] {
        let c = check("key.bas", source(fixed, "").as_bytes()).unwrap();
        let fields = if fixed { &c.fixed } else { &c.inputs };
        for case in cases() {
            let json = format!(r#"{{"VALUE":{{"hex":"{}"}}}}"#, case.hex.to_uppercase());
            let value = abi::encode_bindings(fields, json.as_bytes());
            if case.valid {
                let value = value.unwrap();
                assert_eq!(hex::encode(&value.bytes), format!("ffb0{}80", case.hex));
                let normalized = serde_json::to_vec(&value.normalized).unwrap();
                assert_eq!(
                    normalized,
                    format!(r#"{{"value":{{"hex":"{}"}}}}"#, case.hex).as_bytes()
                );
                assert_eq!(
                    abi::encode_solution(fields, &normalized).unwrap(),
                    value.bytes
                );
            } else {
                assert_eq!(value.err().unwrap().code, "E0301", "{}", case.id);
                assert_eq!(
                    abi::encode_solution(fields, json.as_bytes())
                        .unwrap_err()
                        .code,
                    "E0300"
                );
            }
        }
        let g = cases().remove(0).hex;
        for value in [
            format!(r#"{{"hex":"{g}","h\u0065x":"{g}"}}"#),
            format!(r#"{{"hex":"{g}","extra":0}}"#),
            format!(r#""{g}""#),
            "true".into(),
            "[]".into(),
        ] {
            let json = format!(r#"{{"value":{value}}}"#);
            assert!(abi::encode_solution(fields, json.as_bytes()).is_err());
        }
    }
}
#[test]
fn unused_keys_are_guarded_on_raw_fixed_solution_and_nested_routes() {
    use clvmr::{
        Allocator, ChiaDialect, ClvmFlags, run_program,
        serde::{node_from_bytes, node_to_bytes},
    };
    for fixed in [false, true] {
        for nested in [false, true] {
            let text = source(fixed, "");
            let text = if nested {
                text.replace("AS PUBLICKEY", "AS LIST OF PAIR OF (INTEGER, PUBLICKEY)")
            } else {
                text
            };
            let t = compile_template("raw.bas", text.as_bytes()).unwrap();
            for c in cases() {
                let mut a = Allocator::new();
                let atom = a.new_atom(&hex::decode(&c.hex).unwrap()).unwrap();
                let value = if nested {
                    let pair = a.new_pair(clvmr::NodePtr::NIL, atom).unwrap();
                    a.new_pair(pair, clvmr::NodePtr::NIL).unwrap()
                } else {
                    atom
                };
                let list = a.new_pair(value, clvmr::NodePtr::NIL).unwrap();
                let raw = node_to_bytes(&a, list).unwrap();
                let (p, s) = if fixed {
                    (clvm::bind_fixed(&t.template, &raw).unwrap(), vec![0x80])
                } else {
                    (t.bind(b"{}").unwrap().puzzle, raw)
                };
                assert_eq!(
                    clvm::execute(&p, &s, clvm::DEFAULT_MAX_COST).is_ok(),
                    c.valid,
                    "{}",
                    c.id
                );
                let mut a = Allocator::new();
                let p = node_from_bytes(&mut a, &p).unwrap();
                let s = node_from_bytes(&mut a, &s).unwrap();
                assert_eq!(
                    run_program(
                        &mut a,
                        &ChiaDialect::new(ClvmFlags::empty()),
                        p,
                        s,
                        clvm::DEFAULT_MAX_COST
                    )
                    .is_ok(),
                    c.valid,
                    "{}",
                    c.id
                );
            }
        }
        let t = compile_template("shape.bas", source(fixed, "").as_bytes()).unwrap();
        for raw in ["80", "ffff018080", "ff0102"] {
            let raw = hex::decode(raw).unwrap();
            let (p, s) = if fixed {
                (clvm::bind_fixed(&t.template, &raw).unwrap(), vec![0x80])
            } else {
                (t.bind(b"{}").unwrap().puzzle, raw)
            };
            assert!(clvm::execute(&p, &s, clvm::DEFAULT_MAX_COST).is_err());
        }
    }
}
#[test]
fn conversions_validate_eagerly_and_preserve_lazy_branches_and_exact_bytes() {
    for c in cases() {
        let body = format!(
            "DIM key AS PUBLICKEY = AS_PUBLICKEY(0x{})\nASSERT KEY_BYTES(key) = 0x{}\n",
            c.hex, c.hex
        );
        let r = run(&body);
        if c.valid {
            r.unwrap();
        } else {
            assert_eq!(r.err().unwrap().code, "E0500", "{}", c.id);
            assert_eq!(
                run(&format!("DIM unused = AS_PUBLICKEY(0x{})\n", c.hex))
                    .err()
                    .unwrap()
                    .code,
                "E0500"
            );
            run(&format!("IF FALSE THEN\n{body}END IF\n")).unwrap();
        }
    }
    let g = cases().remove(0).hex;
    assert_eq!(
        run(&format!(
            "DIM key = AS_PUBLICKEY(0x)\nkey = AS_PUBLICKEY(0x{g})\n"
        ))
        .err()
        .unwrap()
        .code,
        "E0500"
    );
}
#[test]
fn public_keys_have_explicit_types_and_immutable_boundaries() {
    for body in [
        "DIM k AS PUBLICKEY = 0x",
        "DIM k = AS_PUBLICKEY(1)",
        "DIM k = AS_PUBLICKEY()",
        "DIM k = AS_PUBLICKEY(0x,0x)",
        "DIM b = KEY_BYTES(0x)",
        "DIM b = KEY_BYTES()",
        "DIM b = AS_PUBLICKEY(0x) = 0x",
        "DIM b = AS_PUBLICKEY(0x) < AS_PUBLICKEY(0x)",
        "DIM b = AS_PUBLICKEY(0x) + AS_PUBLICKEY(0x)",
    ] {
        let s = format!("CONTRACT Demo()\n{body}\nEND CONTRACT\n");
        assert_eq!(check("type.bas", s.as_bytes()).unwrap_err().code, "E0202");
        assert_eq!(analyze("type.bas", s.as_bytes()).unwrap_err().code, "E0202");
    }
    assert_eq!(
        run("CONST key = AS_PUBLICKEY(0x)\n").err().unwrap().code,
        "E0205"
    );
    for fixed in [false, true] {
        for (body, code) in [
            ("value = AS_PUBLICKEY(0x)\n", "E0203"),
            ("CONST copy = value\n", "E0205"),
        ] {
            assert_eq!(
                check("immutable.bas", source(fixed, body).as_bytes())
                    .unwrap_err()
                    .code,
                code
            );
        }
    }
}
#[test]
fn key_example_functions_collections_and_cost_boundary() {
    let t = compile_template(
        "example.bas",
        include_bytes!("../../../examples/m3-publickey-boundaries.bas"),
    )
    .unwrap();
    let p = t
        .bind(include_bytes!(
            "../../../examples/m3-publickey-boundaries.bindings.json"
        ))
        .unwrap();
    let s = abi::encode_solution(
        &t.contract.inputs,
        include_bytes!("../../../examples/m3-publickey-boundaries.solution.json"),
    )
    .unwrap();
    let r = clvm::execute(&p.puzzle, &s, clvm::DEFAULT_MAX_COST).unwrap();
    assert_eq!(hex::encode(&r.bytes), "ffff53ff648080");
    clvm::execute(&p.puzzle, &s, r.cost).unwrap();
    assert_eq!(
        clvm::execute(&p.puzzle, &s, r.cost - 1).err().unwrap().code,
        "E0501"
    );
}
