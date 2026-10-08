//! Runtime UTF-8 scalar validation, scanning by index without copying suffixes.
use super::*;
fn number(a: &mut Allocator, n: u32) -> Result<NodePtr> {
    let n = a.new_small_number(n).map_err(internal)?;
    quote(a, n)
}
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
fn between(a: &mut Allocator, byte: NodePtr, low: u32, high: u32) -> Result<NodePtr> {
    let low = number(a, low)?;
    let high = number(a, high)?;
    let below = op(a, 21, &[low, byte])?;
    let above = op(a, 21, &[byte, high])?;
    let either = op(a, 33, &[below, above])?;
    op(a, 32, &[either])
}
// Step environment: [byte, self, data, index, length, remaining, low, high].
fn next(a: &mut Allocator, remaining: NodePtr, low: NodePtr, high: NodePtr) -> Result<NodePtr> {
    let this = path(a, 5)?;
    let data = path(a, 11)?;
    let index = path(a, 23)?;
    let length = path(a, 47)?;
    let one = number(a, 1)?;
    let index = op(a, 16, &[index, one])?;
    let env = args(a, &[this, data, index, length, remaining, low, high])?;
    op(a, 2, &[this, env])
}
fn transition(a: &mut Allocator, remaining: u32, low: u32, high: u32) -> Result<NodePtr> {
    let remaining = number(a, remaining)?;
    let low = number(a, low)?;
    let high = number(a, high)?;
    next(a, remaining, low, high)
}
pub(super) fn validate(a: &mut Allocator, value: NodePtr) -> Result<NodePtr> {
    let fail = op(a, 8, &[])?;
    let byte = path(a, 2)?;
    let mut lead = fail;
    // Restricted second-byte ranges exclude overlong forms, surrogates and >10FFFF.
    for (low, high, remaining, next_low, next_high) in [
        (0, 127, 0, 128, 191),
        (194, 223, 1, 128, 191),
        (224, 224, 2, 160, 191),
        (225, 236, 2, 128, 191),
        (237, 237, 2, 128, 159),
        (238, 239, 2, 128, 191),
        (240, 240, 3, 144, 191),
        (241, 243, 3, 128, 191),
        (244, 244, 3, 128, 143),
    ]
    .into_iter()
    .rev()
    {
        let valid = between(a, byte, low, high)?;
        let advance = transition(a, remaining, next_low, next_high)?;
        lead = choose(a, valid, advance, lead)?;
    }
    let remaining = path(a, 95)?;
    let low = path(a, 191)?;
    let high = path(a, 383)?;
    let below = op(a, 21, &[low, byte])?;
    let above = op(a, 21, &[byte, high])?;
    let invalid = op(a, 33, &[below, above])?;
    let one = number(a, 1)?;
    let remaining_next = op(a, 17, &[remaining, one])?;
    let low = number(a, 128)?;
    let high = number(a, 191)?;
    let advance = next(a, remaining_next, low, high)?;
    let continuation = choose(a, invalid, fail, advance)?;
    let step = choose(a, remaining, continuation, lead)?;
    let step = quote(a, step)?;
    // Loop environment: [self, data, index, length, remaining, low, high].
    let data = path(a, 5)?;
    let index = path(a, 11)?;
    let length = path(a, 23)?;
    let remaining = path(a, 47)?;
    let one = number(a, 1)?;
    let end = op(a, 16, &[index, one])?;
    let byte = op(a, 12, &[data, index, end])?;
    let zero_byte = a.new_atom(&[0]).map_err(internal)?;
    let zero_byte = quote(a, zero_byte)?;
    let byte = op(a, 14, &[zero_byte, byte])?;
    let byte = op(a, 16, &[byte])?;
    let env = path(a, 1)?;
    let env = op(a, 4, &[byte, env])?;
    let step = op(a, 2, &[step, env])?;
    let finished = choose(a, remaining, fail, data)?;
    let more = op(a, 21, &[length, index])?;
    let program = choose(a, more, step, finished)?;
    let program = quote(a, program)?;
    let zero = number(a, 0)?;
    let low = number(a, 128)?;
    let high = number(a, 191)?;
    let length = op(a, 13, &[value])?;
    let env = args(a, &[program, value, zero, length, zero, low, high])?;
    op(a, 2, &[program, env])
}
