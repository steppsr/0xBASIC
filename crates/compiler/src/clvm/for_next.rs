//! Private executable kernel, not yet connected to source/IR lowering.
//! Input: [start, end, step, state, body-program], all already evaluated.
//! Body input: [counter, state]. Body result: (optional-return . next-state).
//! An optional return is nil or a singleton list, including for a nil value.
use super::*;

fn path(a: &mut Allocator, n: u32) -> Result<NodePtr> {
    a.new_small_number(n).map_err(internal)
}
fn args(a: &mut Allocator, values: &[NodePtr]) -> Result<NodePtr> {
    let mut tail = quote(a, NodePtr::NIL)?;
    for value in values.iter().rev() {
        tail = op(a, 4, &[*value, tail])?;
    }
    Ok(tail)
}

fn kernel(a: &mut Allocator) -> Result<NodePtr> {
    // Transition environment: [body-result, self, counter, end, step, state, body].
    // Bind the body result once before checking its return flag or carrying state.
    let result = path(a, 2)?;
    let this = path(a, 5)?;
    let counter = path(a, 11)?;
    let end = path(a, 23)?;
    let step = path(a, 47)?;
    let body = path(a, 191)?;
    let returned = op(a, 5, &[result])?;
    let state = op(a, 6, &[result])?;
    let next = op(a, 16, &[counter, step])?;
    let env = args(a, &[this, next, end, step, state, body])?;
    let recurse = op(a, 2, &[this, env])?;
    let transition = choose(a, returned, result, recurse)?;
    let transition = quote(a, transition)?;

    // Loop environment: [self, counter, end, step, state, body].
    let counter = path(a, 5)?;
    let end = path(a, 11)?;
    let step = path(a, 23)?;
    let state = path(a, 47)?;
    let body = path(a, 95)?;
    let nil = quote(a, NodePtr::NIL)?;
    let positive = op(a, 21, &[step, nil])?;
    let past_positive = op(a, 21, &[counter, end])?;
    let past_negative = op(a, 21, &[end, counter])?;
    let finished = choose(a, positive, past_positive, past_negative)?;
    let body_env = args(a, &[counter, state])?;
    let body_result = op(a, 2, &[body, body_env])?;
    let env = path(a, 1)?;
    let transition_env = op(a, 4, &[body_result, env])?;
    let advance = op(a, 2, &[transition, transition_env])?;
    let normal = op(a, 4, &[nil, state])?;
    let loop_program = choose(a, finished, normal, advance)?;
    let loop_program = quote(a, loop_program)?;

    // Entry values are snapshots supplied by the future typed lowering layer.
    let start = path(a, 2)?;
    let end = path(a, 5)?;
    let step = path(a, 11)?;
    let state = path(a, 23)?;
    let body = path(a, 47)?;
    let env = args(a, &[loop_program, start, end, step, state, body])?;
    let run = op(a, 2, &[loop_program, env])?;
    let zero = op(a, 9, &[step, nil])?;
    let fail = op(a, 8, &[])?;
    choose(a, zero, fail, run)
}

fn integer(a: &mut Allocator, n: &BigInt) -> NodePtr {
    if n == &BigInt::from(0) {
        NodePtr::NIL
    } else {
        a.new_atom(&n.to_signed_bytes_be()).unwrap()
    }
}

// Sum fixture; optionally return at counter 3, fail at counter 4, or always fail.
fn fixture_body(a: &mut Allocator, early: bool, fail: bool) -> NodePtr {
    let counter = path(a, 2).unwrap();
    let state = path(a, 5).unwrap();
    let nil = quote(a, NodePtr::NIL).unwrap();
    let sum = op(a, 16, &[state, counter]).unwrap();
    let normal = op(a, 4, &[nil, sum]).unwrap();
    let failure = op(a, 8, &[]).unwrap();
    if fail {
        return failure;
    }
    if !early {
        return normal;
    }
    let three = integer(a, &BigInt::from(3));
    let three = quote(a, three).unwrap();
    let four = integer(a, &BigInt::from(4));
    let four = quote(a, four).unwrap();
    let stop = op(a, 9, &[counter, three]).unwrap();
    let bad = op(a, 9, &[counter, four]).unwrap();
    // Return nil, wrapped in a singleton: must still exit the loop.
    let present = args(a, &[nil]).unwrap();
    let returned = op(a, 4, &[present, sum]).unwrap();
    let normal = choose(a, bad, failure, normal).unwrap();
    choose(a, stop, returned, normal).unwrap()
}

fn run(
    start: BigInt,
    end: BigInt,
    step: i64,
    initial: i64,
    early: bool,
    fail: bool,
    limit: u64,
) -> Result<Execution> {
    let mut a = Allocator::new();
    let program = kernel(&mut a).unwrap();
    let body = fixture_body(&mut a, early, fail);
    let start = integer(&mut a, &start);
    let end = integer(&mut a, &end);
    let step = integer(&mut a, &BigInt::from(step));
    let initial = integer(&mut a, &BigInt::from(initial));
    let env = list(&mut a, &[start, end, step, initial, body]).unwrap();
    execute(
        &node_to_bytes(&a, program).unwrap(),
        &node_to_bytes(&a, env).unwrap(),
        limit,
    )
}

fn result(execution: &Execution) -> (bool, BigInt) {
    let mut a = Allocator::new();
    let node = node_from_bytes(&mut a, &execution.bytes).unwrap();
    let SExp::Pair(returned, state) = a.sexp(node) else {
        panic!("expected state pair")
    };
    (
        returned != NodePtr::NIL,
        BigInt::from_signed_bytes_be(a.atom(state).as_ref()),
    )
}

#[test]
fn for_next_kernel_signed_ranges_match_independent_host_model() {
    for start in -4..=4 {
        for end in -4..=4 {
            for step in [-3, -1, 1, 2] {
                let mut expected = 17;
                let mut i = start;
                while if step > 0 { i <= end } else { i >= end } {
                    expected += i;
                    i += step;
                }
                let actual = run(
                    start.into(),
                    end.into(),
                    step,
                    17,
                    false,
                    false,
                    DEFAULT_MAX_COST,
                )
                .unwrap();
                assert_eq!(
                    result(&actual),
                    (false, expected.into()),
                    "{start} {end} {step}"
                );
            }
        }
    }
}

#[test]
fn for_next_kernel_zero_step_and_skipped_failure() {
    for (start, end) in [(1, 3), (3, 1), (2, 2)] {
        assert_eq!(
            run(
                start.into(),
                end.into(),
                0,
                0,
                false,
                false,
                DEFAULT_MAX_COST
            )
            .err()
            .unwrap()
            .code,
            "E0500"
        );
    }
    let skipped = run(3.into(), 1.into(), 1, 17, false, true, DEFAULT_MAX_COST).unwrap();
    assert_eq!(result(&skipped), (false, 17.into()));
    assert_eq!(
        run(1.into(), 1.into(), 1, 17, false, true, DEFAULT_MAX_COST)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
}

#[test]
fn for_next_kernel_return_nil_stops_before_later_failure() {
    let actual = run(1.into(), 9.into(), 1, 0, true, false, DEFAULT_MAX_COST).unwrap();
    assert_eq!(result(&actual), (true, 6.into()));
}

#[test]
fn for_next_kernel_large_integers_and_cost_boundary() {
    let start = BigInt::from(1) << 130usize;
    let end = &start + BigInt::from(4);
    let expected = &start * BigInt::from(3) + BigInt::from(6);
    let actual = run(
        start.clone(),
        end.clone(),
        2,
        0,
        false,
        false,
        DEFAULT_MAX_COST,
    )
    .unwrap();
    assert_eq!(result(&actual), (false, expected));
    assert_eq!(
        run(start.clone(), end.clone(), 2, 0, false, false, actual.cost)
            .unwrap()
            .bytes,
        actual.bytes
    );
    assert_eq!(
        run(start, end, 2, 0, false, false, actual.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    let huge = BigInt::from(1) << 200usize;
    assert_eq!(
        run(0.into(), huge, 1, 0, false, false, 100_000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}

#[test]
fn for_next_kernel_reuses_body_for_long_range() {
    let actual = run(1.into(), 10_000.into(), 1, 0, false, false, 1_000_000_000).unwrap();
    assert_eq!(result(&actual), (false, 50_005_000.into()));
    // No numeric range is supplied to construction; the same program handles all inputs.
    let mut a = Allocator::new();
    let program = kernel(&mut a).unwrap();
    let bytes = node_to_bytes(&a, program).unwrap();
    assert!(bytes.len() < 1024);
    eprintln!(
        "FOR kernel: {} bytes; 10000 iterations cost {}",
        bytes.len(),
        actual.cost
    );
}
