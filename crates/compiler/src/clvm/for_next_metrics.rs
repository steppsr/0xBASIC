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
