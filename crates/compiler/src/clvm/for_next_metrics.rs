//! Pinned VM counters for private loop resource tests; no public runner changes.
use super::*;

fn measure(source: &str) -> (u64, clvmr::run_program::Counters, Vec<u8>) {
    let contract = crate::ir::for_next::lower(source).unwrap();
    let program = generate(&contract).unwrap();
    let mut a = Allocator::new();
    let program = node_from_bytes(&mut a, &program).unwrap();
    let env = a.new_pair(NodePtr::NIL, NodePtr::NIL).unwrap();
    let dialect = ChiaDialect::new(ClvmFlags::from_bits_retain(FLAGS));
    let (counters, result) = clvmr::run_program::run_program_with_counters(
        &mut a,
        &dialect,
        program,
        env,
        1_000_000_000,
    );
    let result = result.unwrap();
    (result.0, counters, node_to_bytes(&a, result.1).unwrap())
}

fn expected_heights(n: u32) -> Vec<u8> {
    let mut a = Allocator::new();
    let opcode = a.new_small_number(83).unwrap();
    let mut result = NodePtr::NIL;
    for i in (1..=n).rev() {
        let i = a.new_small_number(i).unwrap();
        let condition = list(&mut a, &[opcode, i]).unwrap();
        result = a.new_pair(condition, result).unwrap();
    }
    node_to_bytes(&a, result).unwrap()
}

#[test]
fn for_next_emission_cost_and_vm_counters() {
    let mut previous: Option<(u64, u32)> = None;
    for n in [32, 64, 128, 256] {
        let source = format!(
            "CONTRACT Demo()\nFOR i = 1 TO {n}\nEMIT ASSERT_HEIGHT_ABSOLUTE(i)\nNEXT i\nEND CONTRACT"
        );
        let (cost, counters, bytes) = measure(&source);
        assert_eq!(bytes, expected_heights(n));
        if let Some((cost_before, pairs_before)) = previous {
            assert!(
                cost * 10 < cost_before * 22,
                "cost must scale approximately linearly"
            );
            assert!(counters.max_pair_count * 10 < pairs_before * 22);
        }
        assert!(counters.val_stack_usage <= 40);
        assert!(counters.env_stack_usage <= 16);
        assert!(counters.op_stack_usage <= 40);
        previous = Some((cost, counters.max_pair_count));
        eprintln!("EMIT n={n} cost={cost} counters={counters:?}");
    }
}

#[test]
fn for_next_nonemitting_vm_stack_is_stable_over_sampled_ranges() {
    let mut baseline = None;
    for n in [32, 256, 1024] {
        let source = format!(
            "CONTRACT Demo()\nDIM total = 0\nFOR i = 1 TO {n}\ntotal = total + i\nNEXT i\nASSERT total = {}\nEND CONTRACT",
            n * (n + 1) / 2
        );
        let (cost, counters, bytes) = measure(&source);
        assert_eq!(bytes, [0x80]);
        let stacks = (
            counters.val_stack_usage,
            counters.env_stack_usage,
            counters.op_stack_usage,
        );
        assert_eq!(*baseline.get_or_insert(stacks), stacks);
        eprintln!("SUM n={n} cost={cost} counters={counters:?}");
    }
}

#[test]
fn for_next_mixed_nesting_executes_with_measured_resources() {
    for depth in [1, 4, 8] {
        let mut source = "CONTRACT Demo()\nDIM total = 0\n".to_owned();
        for i in 0..depth {
            source.push_str(&format!(
                "FOR counter{i} = 1 TO 2\nIF counter{i} > 0 THEN\n"
            ));
        }
        source.push_str("total = total + 1\n");
        for i in (0..depth).rev() {
            source.push_str(&format!("END IF\nNEXT counter{i}\n"));
        }
        source.push_str(&format!("ASSERT total = {}\nEND CONTRACT", 1 << depth));
        let (cost, counters, bytes) = measure(&source);
        assert_eq!(bytes, [0x80]);
        assert!(counters.val_stack_usage < 512);
        assert!(counters.env_stack_usage < 512);
        assert!(counters.op_stack_usage < 512);
        eprintln!("NEST depth={depth} cost={cost} counters={counters:?}");
    }
}

fn deep_source(depth: usize, mixed: bool, returning: bool) -> String {
    let mut source = if returning {
        "FUNCTION Find() AS INTEGER\n".to_owned()
    } else {
        "CONTRACT Demo()\nDIM total = 0\n".to_owned()
    };
    for i in 0..depth {
        if mixed && i % 2 == 1 {
            source.push_str("IF TRUE THEN\n");
        } else {
            source.push_str(&format!("FOR counter{i} = 1 TO 1\n"));
        }
    }
    source.push_str(if returning {
        "RETURN 7\n"
    } else {
        "total = total + 1\n"
    });
    for i in (0..depth).rev() {
        if mixed && i % 2 == 1 {
            source.push_str("END IF\n");
        } else {
            source.push_str(&format!("NEXT counter{i}\n"));
        }
        if returning {
            source.push_str("ASSERT FALSE\n");
        }
    }
    source.push_str(if returning {
        "RETURN 0\nEND FUNCTION\nCONTRACT Demo()\nASSERT Find() = 7\nEND CONTRACT"
    } else {
        "ASSERT total = 1\nEND CONTRACT"
    });
    source
}

// Run maximum-depth construction on the normal Rust test-thread stack in a
// subprocess, so any stack abort is reported as a failed parent test.
#[test]
fn for_next_depth_worker() {
    if std::env::var_os("OXBASIC_PRIVATE_DEPTH_WORKER").is_none() {
        return;
    }
    for mixed in [false, true] {
        for returning in [false, true] {
            let source = deep_source(32, mixed, returning);
            let (cost, counters, bytes) = measure(&source);
            assert_eq!(bytes, [0x80]);
            eprintln!("DEPTH32 mixed={mixed} return={returning} cost={cost} counters={counters:?}");
            let error = crate::ir::for_next::lower(&deep_source(33, mixed, returning)).unwrap_err();
            assert_eq!(error.code, "E0205");
        }
    }
}

#[test]
fn for_next_maximum_depth_in_subprocess() {
    let output = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "clvm::for_next_metrics::for_next_depth_worker",
            "--nocapture",
        ])
        .env("OXBASIC_PRIVATE_DEPTH_WORKER", "1")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    eprintln!("{}", String::from_utf8_lossy(&output.stderr));
}

#[test]
fn for_next_deterministic_golden_programs() {
    let cases: Vec<serde_json::Value> =
        serde_json::from_str(include_str!("for_next_golden.json")).unwrap();
    for case in cases {
        let source = case["source"].as_str().unwrap();
        let program = generate(&crate::ir::for_next::lower(source).unwrap()).unwrap();
        let crlf =
            generate(&crate::ir::for_next::lower(&source.replace('\n', "\r\n")).unwrap()).unwrap();
        assert_eq!(program, crlf);
        let env = hex::decode(case["env_hex"].as_str().unwrap()).unwrap();
        let execution = execute(&program, &env, DEFAULT_MAX_COST).unwrap();
        let mut a = Allocator::new();
        let opcode = a.new_small_number(83).unwrap();
        let mut expected = NodePtr::NIL;
        for height in case["heights"].as_array().unwrap().iter().rev() {
            let height = a.new_small_number(height.as_u64().unwrap() as u32).unwrap();
            let condition = list(&mut a, &[opcode, height]).unwrap();
            expected = a.new_pair(condition, expected).unwrap();
        }
        assert_eq!(execution.bytes, node_to_bytes(&a, expected).unwrap());
        assert_eq!(
            execute(&program, &env, execution.cost).unwrap().bytes,
            execution.bytes
        );
        assert_eq!(
            execute(&program, &env, execution.cost - 1)
                .err()
                .unwrap()
                .code,
            "E0501"
        );
        assert_eq!(
            case["program_bytes"].as_u64().unwrap(),
            program.len() as u64,
            "{}",
            case["name"]
        );
        assert_eq!(
            case["sha256"].as_str().unwrap(),
            sha256(&program),
            "{}",
            case["name"]
        );
        assert_eq!(
            case["tree_hash"].as_str().unwrap(),
            tree_hash(&program).unwrap(),
            "{}",
            case["name"]
        );
        assert_eq!(
            case["cost"].as_u64().unwrap(),
            execution.cost,
            "{}",
            case["name"]
        );
        assert_eq!(
            case["result_hex"].as_str().unwrap(),
            hex::encode(execution.bytes),
            "{}",
            case["name"]
        );
    }
}

#[test]
fn for_next_statement_budget_and_failure_after_emission() {
    let source = |n| {
        format!(
            "CONTRACT Demo()\n{}END CONTRACT",
            "FOR i = 1 TO 0\nASSERT FALSE\nNEXT i\n".repeat(n)
        )
    };
    assert_eq!(measure(&source(256)).2, [0x80]);
    assert_eq!(
        crate::ir::for_next::lower(&source(257)).unwrap_err().code,
        "E0205"
    );
    let contract = crate::ir::for_next::lower("CONTRACT Demo()\nFOR i = 1 TO 3\nEMIT ASSERT_HEIGHT_ABSOLUTE(i)\nIF i = 2 THEN\nASSERT FALSE\nEND IF\nNEXT i\nEND CONTRACT").unwrap();
    let program = generate(&contract).unwrap();
    assert_eq!(
        execute(&program, &[0xff, 0x80, 0x80], DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}
