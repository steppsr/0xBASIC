//! Canonical CLVM encoding, ABI guards, and the pinned local execution profile.
use crate::ir::{IntegerOperation, IntegerValueKind, MAX_INTEGER_VALUES};
use crate::{Diagnostic, Result, ir::Contract};
use clvmr::serde::{node_from_bytes, node_to_bytes, node_to_bytes_limit, tree_hash_from_stream};
use clvmr::{Allocator, ChiaDialect, ClvmFlags, NodePtr, SExp, run_program};
use num_bigint::{BigInt, BigUint};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::io::Cursor;
#[cfg(test)]
mod for_next;
mod utf8;

pub const FLAGS: u32 = 0x0257;
pub const DEFAULT_MAX_COST: u64 = 10_000_000;
pub const MAX_PROGRAM_BYTES: usize = 1_048_576;

fn internal(e: impl std::fmt::Display) -> Box<Diagnostic> {
    Diagnostic::new("E9000", format!("CLVM construction failed: {e}"))
}
fn list(a: &mut Allocator, nodes: &[NodePtr]) -> Result<NodePtr> {
    let mut tail = NodePtr::NIL;
    for node in nodes.iter().rev() {
        tail = a.new_pair(*node, tail).map_err(internal)?;
    }
    Ok(tail)
}
fn op(a: &mut Allocator, code: u32, args: &[NodePtr]) -> Result<NodePtr> {
    let code = a.new_small_number(code).map_err(internal)?;
    let tail = list(a, args)?;
    a.new_pair(code, tail).map_err(internal)
}
fn quote(a: &mut Allocator, value: NodePtr) -> Result<NodePtr> {
    let q = a.new_small_number(1).map_err(internal)?;
    a.new_pair(q, value).map_err(internal)
}
fn choose(a: &mut Allocator, test: NodePtr, yes: NodePtr, no: NodePtr) -> Result<NodePtr> {
    let yes = quote(a, yes)?;
    let no = quote(a, no)?;
    let branch = op(a, 3, &[test, yes, no])?;
    let env = a.new_small_number(1).map_err(internal)?;
    op(a, 2, &[branch, env])
}

pub fn generate(contract: &Contract) -> Result<Vec<u8>> {
    let mut a = Allocator::new();
    if contract.values.len() > MAX_INTEGER_VALUES
        || contract.emissions.len() > crate::syntax::MAX_EMISSIONS + 256
    {
        return Err(Diagnostic::new(
            "E0205",
            "Contract exceeds compiler resource limits",
        ));
    }
    crate::abi::validate_schemas(&contract.fixed, &contract.inputs)?;
    for index in 0..contract.fixed.len() {
        if !matches!(contract.values.get(index).map(|v| &v.kind), Some(IntegerValueKind::Fixed { index: found }) if *found == index)
        {
            return Err(internal("invalid fixed field slot"));
        }
    }
    for index in 0..contract.inputs.len() {
        if !matches!(contract.values.get(contract.fixed.len()+index).map(|v| &v.kind), Some(IntegerValueKind::Input { index: found }) if *found == index)
        {
            return Err(internal("invalid input field slot"));
        }
    }
    let functions = function_programs(&mut a, contract)?;
    let mut program = if let Some(heights) = literal_heights(contract) {
        // Preserve M1's direct encoding when every emitted height is a valid literal.
        let mut conditions = Vec::new();
        for bytes in heights {
            let code = a.new_small_number(83).map_err(internal)?;
            let height = a.new_atom(bytes).map_err(internal)?;
            conditions.push(list(&mut a, &[code, height])?);
        }
        let conditions = list(&mut a, &conditions)?;
        quote(&mut a, conditions)?
    } else {
        integer_body(&mut a, contract, &functions)?
    };
    let fail = op(&mut a, 8, &[])?;
    let nil = quote(&mut a, NodePtr::NIL)?;
    // Validate S and F only after establishing that the environment is a pair.
    if !contract.fixed.is_empty() {
        let fixed = a.new_small_number(2).map_err(internal)?;
        let solution = a.new_small_number(3).map_err(internal)?;
        let mut frame = solution;
        let mut spine = fixed;
        let mut heads = Vec::new();
        for _ in &contract.fixed {
            heads.push(op(&mut a, 5, &[spine])?);
            spine = op(&mut a, 6, &[spine])?;
        }
        for head in heads.into_iter().rev() {
            frame = op(&mut a, 4, &[head, frame])?;
        }
        let body = quote(&mut a, program)?;
        program = op(&mut a, 2, &[body, frame])?;
        program = guard_fields(&mut a, solution, &contract.inputs, program)?;
        program = guard_fields(&mut a, fixed, &contract.fixed, program)?;
    } else if !contract.inputs.is_empty() {
        let solution = a.new_small_number(3).map_err(internal)?;
        let body = quote(&mut a, program)?;
        program = op(&mut a, 2, &[body, solution])?;
        program = guard_fields(&mut a, solution, &contract.inputs, program)?;
    }
    let paths: &[u32] = if !contract.fixed.is_empty() {
        &[]
    } else if contract.inputs.is_empty() {
        &[3, 2]
    } else {
        &[2]
    };
    for &path in paths {
        let path = a.new_small_number(path).map_err(internal)?;
        let test = op(&mut a, 9, &[path, nil])?;
        program = choose(&mut a, test, program, fail)?;
    }
    let env = a.new_small_number(1).map_err(internal)?;
    let test = op(&mut a, 7, &[env])?;
    program = choose(&mut a, test, program, fail)?;
    node_to_bytes_limit(&a, program, MAX_PROGRAM_BYTES).map_err(|e| {
        Diagnostic::new(
            "E0205",
            format!("Generated program exceeds the serialization limit: {e}"),
        )
    })
}

fn guard_fields(
    a: &mut Allocator,
    value: NodePtr,
    fields: &[crate::abi::Field],
    mut body: NodePtr,
) -> Result<NodePtr> {
    let nil = quote(a, NodePtr::NIL)?;
    let fail = op(a, 8, &[])?;
    let mut spines = Vec::new();
    let mut spine = value;
    for _ in fields {
        spines.push(spine);
        spine = op(a, 6, &[spine])?;
    }
    let end = op(a, 9, &[spine, nil])?;
    body = choose(a, end, body, fail)?;
    for (spine, field) in spines.into_iter().zip(fields).rev() {
        let head = op(a, 5, &[spine])?;
        body = guard_value(a, head, &field.value_type, body)?;
        let pair = op(a, 7, &[spine])?;
        body = choose(a, pair, body, fail)?;
    }
    Ok(body)
}

fn guard_value(
    a: &mut Allocator,
    head: NodePtr,
    schema: &crate::abi::SchemaType,
    mut body: NodePtr,
) -> Result<NodePtr> {
    let nil = quote(a, NodePtr::NIL)?;
    let fail = op(a, 8, &[])?;
    if let crate::abi::SchemaType::List { element } = schema {
        let valid = validate_list(a, head, element)?;
        return choose(a, valid, body, fail);
    }
    if let crate::abi::SchemaType::Pair { first, rest } = schema {
        let a_head = op(a, 5, &[head])?;
        let a_rest = op(a, 6, &[head])?;
        body = guard_value(a, a_rest, rest, body)?;
        body = guard_value(a, a_head, first, body)?;
        let pair = op(a, 7, &[head])?;
        return choose(a, pair, body, fail);
    }
    match schema {
        crate::abi::SchemaType::Integer | crate::abi::SchemaType::Amount => {
            if matches!(schema, crate::abi::SchemaType::Amount) {
                let checked = checked_domain(a, head, true)?;
                let valid = op(a, 9, &[checked, head])?;
                body = choose(a, valid, body, fail)?;
            }
            let canonical = op(a, 16, &[head])?;
            let valid = op(a, 9, &[head, canonical])?;
            body = choose(a, valid, body, fail)?;
        }
        crate::abi::SchemaType::Boolean => {
            let one = a.new_small_number(1).map_err(internal)?;
            let one = quote(a, one)?;
            let is_true = op(a, 9, &[head, one])?;
            let is_false = op(a, 9, &[head, nil])?;
            let valid = choose(a, is_false, one, is_true)?;
            body = choose(a, valid, body, fail)?;
        }
        crate::abi::SchemaType::String => {
            let validated = utf8::validate(a, head)?;
            // Force validation even for unused or empty strings, without treating
            // an empty valid string as a false validation result.
            let valid = op(a, 9, &[validated, head])?;
            body = choose(a, valid, body, fail)?;
        }
        crate::abi::SchemaType::PublicKey => {
            let checked = checked_public_key(a, head)?;
            let valid = op(a, 9, &[checked, head])?;
            body = choose(a, valid, body, fail)?;
        }
        crate::abi::SchemaType::PuzzleHash => {
            let checked = checked_domain(a, head, false)?;
            let valid = op(a, 9, &[checked, head])?;
            body = choose(a, valid, body, fail)?;
        }
        crate::abi::SchemaType::Bytes => {}
        crate::abi::SchemaType::Pair { .. } | crate::abi::SchemaType::List { .. } => {
            unreachable!("handled above")
        }
    }
    let pair = op(a, 7, &[head])?;
    body = choose(a, pair, fail, body)?;
    Ok(body)
}

// Compiler-private tail loop environment [self, remaining-list]. Each element is
// validated before advancing, and the final atom must be nil, not just false-ish.
fn validate_list(
    a: &mut Allocator,
    value: NodePtr,
    element: &crate::abi::SchemaType,
) -> Result<NodePtr> {
    let this = a.new_small_number(2).map_err(internal)?;
    let tail = a.new_small_number(5).map_err(internal)?;
    let nil = quote(a, NodePtr::NIL)?;
    let fail = op(a, 8, &[])?;
    let one = a.new_small_number(1).map_err(internal)?;
    let yes = quote(a, one)?;
    let rest = op(a, 6, &[tail])?;
    let env = op(a, 4, &[rest, nil])?;
    let env = op(a, 4, &[this, env])?;
    let step = op(a, 2, &[this, env])?;
    let head = op(a, 5, &[tail])?;
    let step = guard_value(a, head, element, step)?;
    let end = op(a, 9, &[tail, nil])?;
    let end = choose(a, end, yes, fail)?;
    let pair = op(a, 7, &[tail])?;
    let program = choose(a, pair, step, end)?;
    let program = quote(a, program)?;
    let env = op(a, 4, &[value, nil])?;
    let env = op(a, 4, &[program, env])?;
    // Bootstrap through the self slot so nested list validators are serialized
    // once, rather than duplicating an entire element validator at each level.
    let current_env = a.new_small_number(1).map_err(internal)?;
    let start = op(a, 2, &[this, current_env])?;
    let start = quote(a, start)?;
    op(a, 2, &[start, env])
}

fn literal_heights(contract: &Contract) -> Option<Vec<&[u8]>> {
    // Declarations are evaluated eagerly, including unread initializers.
    if !contract.locals.is_empty() {
        return None;
    }
    if !contract.values.iter().all(|v| {
        matches!(
            v.kind,
            IntegerValueKind::Literal(_) | IntegerValueKind::HeightCondition { .. }
        )
    }) {
        return None;
    }
    contract
        .emissions
        .iter()
        .map(|e| {
            let IntegerValueKind::HeightCondition { operand } =
                &contract.values.get(e.condition)?.kind
            else {
                return None;
            };
            let IntegerValueKind::Literal(bytes) = &contract.values.get(*operand)?.kind else {
                return None;
            };
            let value = BigInt::from_signed_bytes_be(bytes);
            (value >= BigInt::from(0) && value <= BigInt::from(u32::MAX))
                .then_some(bytes.as_slice())
        })
        .collect()
}

/// Select a previously bound value from a reverse-ordered environment stack.
fn slot_path(a: &mut Allocator, slot: usize, count: usize) -> Result<NodePtr> {
    let distance = slot
        .checked_add(1)
        .and_then(|slot| count.checked_sub(slot))
        .ok_or_else(|| internal("forward or invalid value reference"))?;
    // first(env)=2, first(rest(env))=5, then 11, 23, ... .
    let path = (BigUint::from(3u32) << distance) - BigUint::from(1u32);
    a.new_atom(&path.to_bytes_be()).map_err(internal)
}

fn value_path(a: &mut Allocator, id: usize, slots: &[usize], count: usize) -> Result<NodePtr> {
    let slot = slots
        .get(id)
        .ok_or_else(|| internal("forward or invalid integer value reference"))?;
    slot_path(a, *slot, count)
}

// Strict point_add checks canonical G1 encoding and subgroup membership even
// with empty runner flags. Equality preserves representation; infinity is not a key.
fn checked_public_key(a: &mut Allocator, value: NodePtr) -> Result<NodePtr> {
    let canonical = op(a, 29, &[value])?;
    let valid = op(a, 9, &[canonical, value])?;
    let mut infinity = [0u8; 48];
    infinity[0] = 0xc0;
    let infinity = a.new_atom(&infinity).map_err(internal)?;
    let infinity = quote(a, infinity)?;
    let is_infinity = op(a, 9, &[value, infinity])?;
    let fail = op(a, 8, &[])?;
    let checked = choose(a, is_infinity, fail, value)?;
    choose(a, valid, checked, fail)
}

fn checked_domain(a: &mut Allocator, value: NodePtr, amount: bool) -> Result<NodePtr> {
    let fail = op(a, 8, &[])?;
    if amount {
        let upper = a.new_atom(&[1, 0, 0, 0, 0, 0, 0, 0, 0]).map_err(internal)?;
        let upper = quote(a, upper)?;
        let lower = a.new_atom(&[0xff]).map_err(internal)?;
        let lower = quote(a, lower)?;
        let low_ok = op(a, 21, &[value, lower])?;
        let high_ok = op(a, 21, &[upper, value])?;
        let checked = choose(a, high_ok, value, fail)?;
        choose(a, low_ok, checked, fail)
    } else {
        let length = op(a, 13, &[value])?;
        let expected = a.new_small_number(32).map_err(internal)?;
        let expected = quote(a, expected)?;
        let valid = op(a, 9, &[length, expected])?;
        choose(a, valid, value, fail)
    }
}

// Add a sentinel above the checked unsigned range. Its canonical atom has
// exactly width + 1 bytes; removing the leading 01 retains every output zero.
fn unsigned_bytes(a: &mut Allocator, value: NodePtr, width: u8) -> Result<NodePtr> {
    let mut upper = vec![0; usize::from(width) + 1];
    upper[0] = 1;
    let upper = a.new_atom(&upper).map_err(internal)?;
    let upper = quote(a, upper)?;
    let minus_one = a.new_atom(&[0xff]).map_err(internal)?;
    let minus_one = quote(a, minus_one)?;
    let lower_test = op(a, 21, &[value, minus_one])?;
    let upper_test = op(a, 21, &[upper, value])?;
    let padded = op(a, 16, &[upper, value])?;
    let one = a.new_small_number(1).map_err(internal)?;
    let one = quote(a, one)?;
    let encoded = op(a, 12, &[padded, one])?;
    let fail = op(a, 8, &[])?;
    let checked = choose(a, upper_test, encoded, fail)?;
    choose(a, lower_test, checked, fail)
}

// Compiler-private loop environment: [self, remaining-list, count].
fn list_length(a: &mut Allocator, value: NodePtr) -> Result<NodePtr> {
    let this = a.new_small_number(2).map_err(internal)?;
    let tail = a.new_small_number(5).map_err(internal)?;
    let count = a.new_small_number(11).map_err(internal)?;
    let one = a.new_small_number(1).map_err(internal)?;
    let one = quote(a, one)?;
    let incremented = op(a, 16, &[count, one])?;
    let rest = op(a, 6, &[tail])?;
    let nil = quote(a, NodePtr::NIL)?;
    let env = op(a, 4, &[incremented, nil])?;
    let env = op(a, 4, &[rest, env])?;
    let env = op(a, 4, &[this, env])?;
    let recurse = op(a, 2, &[this, env])?;
    let program = choose(a, tail, recurse, count)?;
    let program = quote(a, program)?;
    let env = op(a, 4, &[nil, nil])?;
    let env = op(a, 4, &[value, env])?;
    let env = op(a, 4, &[program, env])?;
    op(a, 2, &[program, env])
}

fn height_condition(a: &mut Allocator, height: NodePtr) -> Result<NodePtr> {
    let nil = quote(a, NodePtr::NIL)?;
    let code = a.new_small_number(83).map_err(internal)?;
    let code = quote(a, code)?;
    let args = op(a, 4, &[height, nil])?;
    let condition = op(a, 4, &[code, args])?;
    let minus_one = a.new_atom(&[0xff]).map_err(internal)?;
    let minus_one = quote(a, minus_one)?;
    let upper = a.new_atom(&[1, 0, 0, 0, 0]).map_err(internal)?;
    let upper = quote(a, upper)?;
    let lower_test = op(a, 21, &[height, minus_one])?;
    let upper_test = op(a, 21, &[upper, height])?;
    let fail = op(a, 8, &[])?;
    let checked = choose(a, upper_test, condition, fail)?;
    choose(a, lower_test, checked, fail)
}

// Concatenate one selected branch's proper condition list with the suffix.
// The recursive function receives (self, left, right); all source work has
// already executed before this bounded list assembly.
fn append_conditions(a: &mut Allocator, left: NodePtr, right: NodePtr) -> Result<NodePtr> {
    let self_path = a.new_small_number(2).map_err(internal)?;
    let left_path = a.new_small_number(5).map_err(internal)?;
    let right_path = a.new_small_number(11).map_err(internal)?;
    let head = op(a, 5, &[left_path])?;
    let rest = op(a, 6, &[left_path])?;
    let nil = quote(a, NodePtr::NIL)?;
    let args = op(a, 4, &[right_path, nil])?;
    let args = op(a, 4, &[rest, args])?;
    let args = op(a, 4, &[self_path, args])?;
    let recur = op(a, 2, &[self_path, args])?;
    let cons = op(a, 4, &[head, recur])?;
    let function = choose(a, left_path, cons, right_path)?;
    let function = quote(a, function)?;
    let args = op(a, 4, &[right, nil])?;
    let args = op(a, 4, &[left, args])?;
    let args = op(a, 4, &[function, args])?;
    op(a, 2, &[function, args])
}

struct BodyContext<'a> {
    values: &'a [crate::IntegerValue],
    functions: &'a [Option<NodePtr>],
}

fn functions_ready(values: &[crate::IntegerValue], programs: &[Option<NodePtr>]) -> bool {
    values.iter().all(|v| match &v.kind {
        IntegerValueKind::Call { function, .. } => {
            programs.get(*function).is_some_and(Option::is_some)
        }
        #[cfg(test)]
        IntegerValueKind::For(body) => functions_ready(&body.values, programs),
        _ => true,
    })
}

fn function_programs(a: &mut Allocator, contract: &Contract) -> Result<Vec<Option<NodePtr>>> {
    let total = crate::ir::value_count(&contract.values)
        + contract
            .functions
            .iter()
            .map(|f| crate::ir::value_count(&f.values))
            .sum::<usize>();
    if total > MAX_INTEGER_VALUES || contract.functions.len() > 256 {
        return Err(internal("module exceeds function/value limits"));
    }
    let mut programs = vec![None; contract.functions.len()];
    while programs.iter().any(Option::is_none) {
        let mut progress = false;
        for (id, function) in contract.functions.iter().enumerate() {
            if programs[id].is_some() {
                continue;
            }
            let ready = functions_ready(&function.values, &programs);
            if !ready {
                continue;
            }
            if function.parameters > function.values.len() || function.parameters > 32 {
                return Err(internal("invalid function parameter count"));
            }
            let slots: Vec<_> = (0..function.parameters).rev().collect();
            let body = block_program(
                a,
                &BodyContext {
                    values: &function.values,
                    functions: &programs,
                },
                function.parameters..function.values.len(),
                &[],
                &slots,
                function.parameters,
                Some(&[function.result]),
            )?;
            // The block returns (empty-emissions result). Extract the result
            // after evaluating its ordered bindings exactly once.
            let tail = op(a, 6, &[body])?;
            programs[id] = Some(op(a, 5, &[tail])?);
            progress = true;
        }
        if !progress {
            return Err(internal("cyclic or invalid function references"));
        }
    }
    Ok(programs)
}

fn integer_body(
    a: &mut Allocator,
    contract: &Contract,
    functions: &[Option<NodePtr>],
) -> Result<NodePtr> {
    block_program(
        a,
        &BodyContext {
            values: &contract.values,
            functions,
        },
        (contract.fixed.len() + contract.inputs.len())..contract.values.len(),
        &contract.emissions,
        &(0..(contract.fixed.len() + contract.inputs.len()))
            .rev()
            .collect::<Vec<_>>(),
        contract.fixed.len() + contract.inputs.len(),
        None,
    )
}

fn block_program(
    a: &mut Allocator,
    context: &BodyContext<'_>,
    range: std::ops::Range<usize>,
    emissions: &[crate::syntax::HeightEmission],
    captured: &[usize],
    count: usize,
    outputs: Option<&[usize]>,
) -> Result<NodePtr> {
    let mut bindings = Vec::new();
    let mut value_slots = captured.to_vec();
    value_slots.resize(range.start, usize::MAX);
    let mut condition_slots = Vec::new();
    let mut next = range.start;
    for emission in emissions.iter().map(Some).chain(std::iter::once(None)) {
        let boundary = emission.map_or(range.end, |e| e.values_before);
        if boundary < next || boundary > range.end {
            return Err(internal("invalid evaluation boundary"));
        }
        while next < boundary {
            let count = count + bindings.len();
            let (expression, end) = scalar_expression(a, context, next, &value_slots, count)?;
            if end > boundary {
                return Err(internal("branch crosses statement boundary"));
            }
            value_slots.resize(end, usize::MAX);
            value_slots[next] = count;
            bindings.push(expression);
            next = end;
        }
        // Constructors already validated their values in source order.
        if let Some(emission) = emission {
            let slot = value_slots
                .get(emission.condition)
                .copied()
                .ok_or_else(|| internal("invalid emitted condition"))?;
            condition_slots.push((slot, emission.spread));
        }
    }
    if next != range.end {
        return Err(internal("unused trailing integer bindings"));
    }
    let mut program = quote(a, NodePtr::NIL)?;
    for (slot, spread) in condition_slots.into_iter().rev() {
        let condition = slot_path(a, slot, count + bindings.len())?;
        program = if spread {
            append_conditions(a, condition, program)?
        } else {
            op(a, 4, &[condition, program])?
        };
    }
    if let Some(outputs) = outputs {
        let mut tail = quote(a, NodePtr::NIL)?;
        for id in outputs.iter().rev() {
            let value = value_path(a, *id, &value_slots, count + bindings.len())?;
            tail = op(a, 4, &[value, tail])?;
        }
        program = op(a, 4, &[program, tail])?;
    }
    // Each apply evaluates one binding, then its continuation. Arithmetic
    // operands are already values, so VM argument evaluation order cannot
    // reorder or repeat the source computations.
    let env = a.new_small_number(1).map_err(internal)?;
    for binding in bindings.into_iter().rev() {
        let continuation = quote(a, program)?;
        let extended = op(a, 4, &[binding, env])?;
        program = op(a, 2, &[continuation, extended])?;
    }
    Ok(program)
}

fn scalar_expression(
    a: &mut Allocator,
    context: &BodyContext<'_>,
    id: usize,
    value_slots: &[usize],
    count: usize,
) -> Result<(NodePtr, usize)> {
    let values = context.values;
    let value = values.get(id).ok_or_else(|| internal("invalid value ID"))?;
    #[cfg(test)]
    if let IntegerValueKind::For(body) = &value.kind {
        return Ok((
            for_next::lower(a, body, context, value_slots, count)?,
            id + 1,
        ));
    }
    if let IntegerValueKind::If {
        predicate,
        yes,
        no,
        end,
    } = &value.kind
    {
        if yes.start != id + 1 || yes.end != no.start || no.end != *end || *end > values.len() {
            return Err(internal("invalid IF block ranges"));
        }
        let test = value_path(a, *predicate, value_slots, count)?;
        let yes = block_program(
            a,
            context,
            yes.start..yes.end,
            &yes.emissions,
            value_slots,
            count,
            Some(&yes.outputs),
        )?;
        let no = block_program(
            a,
            context,
            no.start..no.end,
            &no.emissions,
            value_slots,
            count,
            Some(&no.outputs),
        )?;
        return Ok((choose(a, test, yes, no)?, *end));
    }
    if let IntegerValueKind::ShortCircuit {
        left,
        right,
        end,
        is_and,
    } = &value.kind
    {
        if *end <= id || *end > values.len() {
            return Err(internal("invalid branch range"));
        }
        let test = value_path(a, *left, value_slots, count)?;
        let mut slots = value_slots.to_vec();
        slots.resize(id + 1, usize::MAX);
        let mut bindings = Vec::new();
        let mut next = id + 1;
        while next < *end {
            let (binding, after) =
                scalar_expression(a, context, next, &slots, count + bindings.len())?;
            if after > *end {
                return Err(internal("nested branch escapes enclosing range"));
            }
            slots.resize(after, usize::MAX);
            slots[next] = count + bindings.len();
            bindings.push(binding);
            next = after;
        }
        let mut program = value_path(a, *right, &slots, count + bindings.len())?;
        let env = a.new_small_number(1).map_err(internal)?;
        for binding in bindings.into_iter().rev() {
            let continuation = quote(a, program)?;
            let extended = op(a, 4, &[binding, env])?;
            program = op(a, 2, &[continuation, extended])?;
        }
        let skipped = if *is_and {
            NodePtr::NIL
        } else {
            a.new_small_number(1).map_err(internal)?
        };
        let skipped = quote(a, skipped)?;
        let result = if *is_and {
            choose(a, test, program, skipped)?
        } else {
            choose(a, test, skipped, program)?
        };
        return Ok((result, *end));
    }
    let expression = match &value.kind {
        IntegerValueKind::ListLength { operand } => {
            let value = value_path(a, *operand, value_slots, count)?;
            list_length(a, value)?
        }
        IntegerValueKind::List { elements } => {
            let mut tail = quote(a, NodePtr::NIL)?;
            for id in elements.iter().rev() {
                let head = value_path(a, *id, value_slots, count)?;
                tail = op(a, 4, &[head, tail])?;
            }
            tail
        }
        IntegerValueKind::Pair { left, right } => {
            let left = value_path(a, *left, value_slots, count)?;
            let right = value_path(a, *right, value_slots, count)?;
            op(a, 4, &[left, right])?
        }
        IntegerValueKind::PairAccess { operand, first } => {
            let value = value_path(a, *operand, value_slots, count)?;
            op(a, if *first { 5 } else { 6 }, &[value])?
        }
        IntegerValueKind::UnsignedBytes { operand, width } => {
            let value = value_path(a, *operand, value_slots, count)?;
            unsigned_bytes(a, value, *width)?
        }
        IntegerValueKind::AsAmount { operand } | IntegerValueKind::AsPuzzleHash { operand } => {
            let amount = matches!(value.kind, IntegerValueKind::AsAmount { .. });
            let value = value_path(a, *operand, value_slots, count)?;
            checked_domain(a, value, amount)?
        }
        IntegerValueKind::AsPublicKey { operand } => {
            let value = value_path(a, *operand, value_slots, count)?;
            checked_public_key(a, value)?
        }
        IntegerValueKind::StringFromUtf8 { operand } => {
            let value = value_path(a, *operand, value_slots, count)?;
            utf8::validate(a, value)?
        }
        IntegerValueKind::IntBytes { operand } => {
            let value = value_path(a, *operand, value_slots, count)?;
            op(a, 16, &[value])?
        }
        IntegerValueKind::IntFromBytes { operand } => {
            let value = value_path(a, *operand, value_slots, count)?;
            // Unary addition produces the canonical signed integer atom. Require
            // byte equality so zero and redundant sign extensions cannot slip in.
            let canonical = op(a, 16, &[value])?;
            let valid = op(a, 9, &[value, canonical])?;
            let failure = op(a, 8, &[])?;
            choose(a, valid, value, failure)?
        }
        IntegerValueKind::Sha256 { operand } => {
            let value = value_path(a, *operand, value_slots, count)?;
            op(a, 11, &[value])?
        }
        IntegerValueKind::ByteLength { operand } => {
            let value = value_path(a, *operand, value_slots, count)?;
            op(a, 13, &[value])?
        }
        IntegerValueKind::Concat { left, right } => {
            let left = value_path(a, *left, value_slots, count)?;
            let right = value_path(a, *right, value_slots, count)?;
            op(a, 14, &[left, right])?
        }
        IntegerValueKind::ReturnValue { operand } => {
            let value = value_path(a, *operand, value_slots, count)?;
            let nil = quote(a, NodePtr::NIL)?;
            op(a, 4, &[value, nil])?
        }
        IntegerValueKind::Parameter
        | IntegerValueKind::Input { .. }
        | IntegerValueKind::Fixed { .. } => {
            return Err(internal("parameter outside entry"));
        }
        IntegerValueKind::Call {
            function,
            arguments,
        } => {
            let program = context
                .functions
                .get(*function)
                .and_then(|p| *p)
                .ok_or_else(|| internal("invalid function reference"))?;
            let program = quote(a, program)?;
            let mut args = quote(a, NodePtr::NIL)?;
            for argument in arguments.iter().rev() {
                let value = value_path(a, *argument, value_slots, count)?;
                args = op(a, 4, &[value, args])?;
            }
            op(a, 2, &[program, args])?
        }
        #[cfg(test)]
        IntegerValueKind::For(_) => unreachable!("handled above"),
        IntegerValueKind::If { .. } => unreachable!("handled above"),
        IntegerValueKind::Project { bundle, index } => {
            let mut tuple = value_path(a, *bundle, value_slots, count)?;
            for _ in 0..*index {
                tuple = op(a, 6, &[tuple])?;
            }
            op(a, 5, &[tuple])?
        }
        IntegerValueKind::PaymentCondition { opcode, operands } => {
            // Operands were evaluated left-to-right and already have validated
            // domain types. Construct a proper condition list; no memo argument.
            let mut tail = quote(a, NodePtr::NIL)?;
            for operand in operands.iter().rev() {
                let value = value_path(a, *operand, value_slots, count)?;
                tail = op(a, 4, &[value, tail])?;
            }
            let code = a.new_small_number(u32::from(*opcode)).map_err(internal)?;
            let code = quote(a, code)?;
            let condition = op(a, 4, &[code, tail])?;
            if *opcode == 50 {
                // Limit the application message here, including unused calls.
                // Consensus adds coin/network context later; do not append it here.
                let message = value_path(a, operands[1], value_slots, count)?;
                let length = op(a, 13, &[message])?;
                let limit = a.new_small_number(1025).map_err(internal)?;
                let limit = quote(a, limit)?;
                let valid = op(a, 21, &[limit, length])?;
                let fail = op(a, 8, &[])?;
                choose(a, valid, condition, fail)?
            } else {
                condition
            }
        }
        IntegerValueKind::HeightCondition { operand } => {
            let height = value_path(a, *operand, value_slots, count)?;
            height_condition(a, height)?
        }
        IntegerValueKind::ShortCircuit { .. } => unreachable!("handled above"),
        IntegerValueKind::Not { operand } => {
            let operand = value_path(a, *operand, value_slots, count)?;
            op(a, 32, &[operand])?
        }
        IntegerValueKind::Assert { operand } => {
            let operand = value_path(a, *operand, value_slots, count)?;
            let success = quote(a, NodePtr::NIL)?;
            let failure = op(a, 8, &[])?;
            choose(a, operand, success, failure)?
        }
        IntegerValueKind::Copy { operand } => value_path(a, *operand, value_slots, count)?,
        IntegerValueKind::TreeLiteral(bytes) => {
            let tree = node_from_bytes(a, bytes).map_err(internal)?;
            quote(a, tree)?
        }
        IntegerValueKind::Literal(bytes) => {
            let atom = a.new_atom(bytes).map_err(internal)?;
            quote(a, atom)?
        }
        IntegerValueKind::Negate { operand } => {
            let zero = quote(a, NodePtr::NIL)?;
            let value = value_path(a, *operand, value_slots, count)?;
            op(a, 17, &[zero, value])?
        }
        IntegerValueKind::Binary {
            operation,
            left,
            right,
        } => {
            let left = value_path(a, *left, value_slots, count)?;
            let right = value_path(a, *right, value_slots, count)?;
            let (opcode, left, right, invert) = match operation {
                IntegerOperation::Add => (16, left, right, false),
                IntegerOperation::Subtract => (17, left, right, false),
                IntegerOperation::Multiply => (18, left, right, false),
                IntegerOperation::Equal => (9, left, right, false),
                IntegerOperation::NotEqual => (9, left, right, true),
                IntegerOperation::Less => (21, right, left, false),
                IntegerOperation::LessEqual => (21, left, right, true),
                IntegerOperation::Greater => (21, left, right, false),
                IntegerOperation::GreaterEqual => (21, right, left, true),
            };
            let comparison = op(a, opcode, &[left, right])?;
            if invert {
                op(a, 32, &[comparison])?
            } else {
                comparison
            }
        }
    };

    Ok((expression, id + 1))
}

fn decode(a: &mut Allocator, bytes: &[u8], code: &'static str) -> Result<NodePtr> {
    if bytes.len() > MAX_PROGRAM_BYTES {
        return Err(Diagnostic::new(
            code,
            "Serialized CLVM exceeds the M1 1 MiB limit",
        ));
    }
    let node = node_from_bytes(a, bytes)
        .map_err(|e| Diagnostic::new(code, format!("Invalid CLVM: {e}")))?;
    let canonical = node_to_bytes(a, node).map_err(internal)?;
    if canonical != bytes {
        return Err(Diagnostic::new(
            code,
            "CLVM must use canonical traditional encoding with no trailing bytes",
        ));
    }
    Ok(node)
}

pub fn bind_empty(template: &[u8]) -> Result<Vec<u8>> {
    bind_fixed(template, &[0x80])
}
/// Bind one serialized fixed-value list. The template enforces its runtime schema.
pub fn bind_fixed(template: &[u8], fixed: &[u8]) -> Result<Vec<u8>> {
    let mut a = Allocator::new();
    let template = decode(&mut a, template, "E0600")?;
    let quoted_template = quote(&mut a, template)?;
    let fixed = decode(&mut a, fixed, "E0301")?;
    let fixed = quote(&mut a, fixed)?;
    let solution = a.new_small_number(1).map_err(internal)?;
    let env = op(&mut a, 4, &[fixed, solution])?;
    let program = op(&mut a, 2, &[quoted_template, env])?;
    node_to_bytes_limit(&a, program, MAX_PROGRAM_BYTES).map_err(|e| {
        Diagnostic::new(
            "E0600",
            format!("Bound program exceeds the serialization limit: {e}"),
        )
    })
}

pub fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

pub fn tree_hash(bytes: &[u8]) -> Result<String> {
    decode(&mut Allocator::new(), bytes, "E0600")?;
    tree_hash_from_stream(&mut Cursor::new(bytes))
        .map(hex::encode)
        .map_err(internal)
}

pub struct Execution {
    pub cost: u64,
    pub bytes: Vec<u8>,
    pub tree: Value,
}

pub fn execute(program: &[u8], solution: &[u8], max_cost: u64) -> Result<Execution> {
    if max_cost == 0 {
        return Err(Diagnostic::new("E0501", "Maximum cost must be positive"));
    }
    let mut a = Allocator::new();
    let program = decode(&mut a, program, "E0600")?;
    let env = decode(&mut a, solution, "E0300")?;
    let dialect = ChiaDialect::new(ClvmFlags::from_bits_retain(FLAGS));
    let reduction = run_program(&mut a, &dialect, program, env, max_cost).map_err(|e| {
        let code = if matches!(e, clvmr::error::EvalErr::CostExceeded) {
            "E0501"
        } else {
            "E0500"
        };
        Diagnostic::new(code, format!("CLVM execution failed: {e}"))
    })?;
    let bytes = node_to_bytes_limit(&a, reduction.1, MAX_PROGRAM_BYTES)
        .map_err(|e| Diagnostic::new("E0500", format!("Result serialization limit: {e}")))?;
    let tree = raw_tree(&a, reduction.1, 0, &mut 8192)?;
    Ok(Execution {
        cost: reduction.0,
        bytes,
        tree,
    })
}

fn raw_tree(a: &Allocator, node: NodePtr, depth: usize, budget: &mut usize) -> Result<Value> {
    // Bounded recursion also limits downstream JSON serialization depth.
    if depth > 512 || *budget == 0 {
        return Err(Diagnostic::new(
            "E0500",
            "Result exceeds M1's 512-level or 8192-node display limit",
        ));
    }
    *budget -= 1;
    match a.sexp(node) {
        SExp::Atom => Ok(json!({"atom": hex::encode(a.atom(node).as_ref())})),
        SExp::Pair(first, rest) => Ok(
            json!({"pair": [raw_tree(a, first, depth + 1, budget)?, raw_tree(a, rest, depth + 1, budget)?]}),
        ),
    }
}
