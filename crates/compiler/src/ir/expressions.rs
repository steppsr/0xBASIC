//! Shared scalar type rules for runtime expressions and compile-time constants.
use super::*;
use crate::syntax::{
    IntegerLiteral,
    expression::{BinaryOperator as B, Expression, UnaryOperator as U},
};
use num_bigint::BigInt;
use std::sync::Arc;

#[derive(Clone, PartialEq, Eq)]
pub(crate) enum ConstantValue {
    Number(BigInt),
    Bytes(Arc<[u8]>),
    List {
        encoded: Arc<[u8]>,
        nodes: usize,
        payload: usize,
    },
}

impl ConstantValue {
    pub(crate) fn atom(&self) -> Vec<u8> {
        match self {
            Self::Number(n) => atom(n),
            Self::Bytes(bytes) => bytes.to_vec(),
            Self::List { .. } => unreachable!("list constants are trees"),
        }
    }
    pub(crate) fn literal_kind(&self) -> IntegerValueKind {
        match self {
            Self::List { encoded, .. } => IntegerValueKind::TreeLiteral(encoded.to_vec()),
            _ => IntegerValueKind::Literal(self.atom()),
        }
    }
    fn metrics(&self) -> (usize, usize, usize) {
        let owned;
        let bytes = match self {
            Self::List {
                encoded,
                nodes,
                payload,
            } => return (*nodes, encoded.len(), *payload),
            Self::Bytes(bytes) => bytes.as_ref(),
            Self::Number(n) => {
                owned = atom(n);
                &owned
            }
        };
        let size = bytes.len();
        let prefix = if size == 1 && bytes[0] < 128 {
            0
        } else if size < 64 {
            1
        } else if size < 8192 {
            2
        } else if size < 1048576 {
            3
        } else {
            4
        };
        (
            1,
            size + prefix,
            if matches!(self, Self::Bytes(_)) {
                size
            } else {
                0
            },
        )
    }
    fn append_tree(&self, output: &mut Vec<u8>) {
        if let Self::List { encoded, .. } = self {
            output.extend_from_slice(encoded);
        } else {
            // Scalar atoms are already bounded by source and integer limits.
            let mut allocator = clvmr::Allocator::new();
            let node = allocator
                .new_atom(&self.atom())
                .expect("bounded constant atom");
            output.extend(
                clvmr::serde::node_to_bytes(&allocator, node).expect("bounded constant atom"),
            );
        }
    }
    pub(crate) fn is_zero(&self) -> bool {
        matches!(self, Self::Number(n) if *n == BigInt::from(0))
    }
    fn number(self) -> BigInt {
        match self {
            Self::Number(n) => n,
            Self::Bytes(_) | Self::List { .. } => unreachable!("numeric operands are type-checked"),
        }
    }
}

#[derive(Default)]
pub(crate) struct ConstantBudget {
    pub nodes: usize,
    pub bytes: usize,
    pub structure: usize,
    pub encoded: usize,
}

const MAX_CONSTANT_BYTE_WORK: usize = 8 * 1024 * 1024;

/// Reserved byte built-ins share exact arity/result rules in both front ends.
#[derive(Clone, Copy)]
pub(crate) enum ByteBuiltin {
    AsAmount,
    AmountValue,
    AsPuzzleHash,
    AsPublicKey,
    KeyBytes,
    HashBytes,
    ByteLength,
    Concat,
    Sha256,
    IntBytes,
    IntFromBytes,
    U32Be,
    U64Be,
    Utf8,
    StringFromUtf8,
}

pub(crate) fn byte_builtin(name: &str) -> Option<(ByteBuiltin, usize, ValueType, ValueType)> {
    match name.to_ascii_uppercase().as_str() {
        "AS_PUBLICKEY" => Some((
            ByteBuiltin::AsPublicKey,
            1,
            ValueType::Bytes,
            ValueType::PublicKey,
        )),
        "KEY_BYTES" => Some((
            ByteBuiltin::KeyBytes,
            1,
            ValueType::PublicKey,
            ValueType::Bytes,
        )),
        "AS_AMOUNT" => Some((
            ByteBuiltin::AsAmount,
            1,
            ValueType::Integer,
            ValueType::Amount,
        )),
        "AMOUNT_VALUE" => Some((
            ByteBuiltin::AmountValue,
            1,
            ValueType::Amount,
            ValueType::Integer,
        )),
        "AS_PUZZLEHASH" => Some((
            ByteBuiltin::AsPuzzleHash,
            1,
            ValueType::Bytes,
            ValueType::PuzzleHash,
        )),
        "HASH_BYTES" => Some((
            ByteBuiltin::HashBytes,
            1,
            ValueType::PuzzleHash,
            ValueType::Bytes,
        )),
        "BYTE_LENGTH" => Some((
            ByteBuiltin::ByteLength,
            1,
            ValueType::Bytes,
            ValueType::Integer,
        )),
        "CONCAT" => Some((ByteBuiltin::Concat, 2, ValueType::Bytes, ValueType::Bytes)),
        "SHA256" => Some((ByteBuiltin::Sha256, 1, ValueType::Bytes, ValueType::Bytes)),
        "INT_BYTES" => Some((
            ByteBuiltin::IntBytes,
            1,
            ValueType::Integer,
            ValueType::Bytes,
        )),
        "INT_FROM_BYTES" => Some((
            ByteBuiltin::IntFromBytes,
            1,
            ValueType::Bytes,
            ValueType::Integer,
        )),
        "U32BE" => Some((ByteBuiltin::U32Be, 1, ValueType::Integer, ValueType::Bytes)),
        "U64BE" => Some((ByteBuiltin::U64Be, 1, ValueType::Integer, ValueType::Bytes)),
        "UTF8" => Some((ByteBuiltin::Utf8, 1, ValueType::String, ValueType::Bytes)),
        "STRING_FROM_UTF8" => Some((
            ByteBuiltin::StringFromUtf8,
            1,
            ValueType::Bytes,
            ValueType::String,
        )),
        _ => None,
    }
}

pub(crate) fn cons_element(expected: Option<&ValueType>) -> Option<&ValueType> {
    match expected {
        Some(ValueType::List(t)) => Some(t),
        _ => None,
    }
}
pub(crate) fn pair_component(expected: Option<&ValueType>, index: usize) -> Option<&ValueType> {
    match expected {
        Some(ValueType::Pair(a, b)) => Some(if index == 0 { a } else { b }),
        _ => None,
    }
}
pub(crate) fn pair_call(name: &str) -> Option<bool> {
    match name.to_ascii_uppercase().as_str() {
        "PAIR" => Some(true),
        "FIRST" | "REST" | "LIST_LENGTH" => Some(false),
        _ => None,
    }
}
pub(crate) fn pair_result(
    source: &str,
    name: &str,
    operands: &[ValueType],
    budget: &mut super::types::TypeBudget,
    span: Span,
) -> Result<ValueType> {
    if name.eq_ignore_ascii_case("PAIR") {
        return budget.pair(&operands[0], &operands[1], source, span);
    }
    if let ValueType::List(element) = &operands[0] {
        return Ok(if name.eq_ignore_ascii_case("FIRST") {
            (**element).clone()
        } else if name.eq_ignore_ascii_case("LIST_LENGTH") {
            ValueType::Integer
        } else {
            operands[0].clone()
        });
    }
    if let ValueType::Pair(left, right) = &operands[0] {
        if name.eq_ignore_ascii_case("LIST_LENGTH") {
            return Err(Diagnostic::at(
                "E0202",
                "LIST_LENGTH requires a LIST",
                source,
                span,
            ));
        }
        return Ok(if name.eq_ignore_ascii_case("FIRST") {
            (**left).clone()
        } else {
            (**right).clone()
        });
    }
    Err(Diagnostic::at(
        "E0202",
        "FIRST/REST require a PAIR or LIST; LIST_LENGTH requires a LIST",
        source,
        span,
    ))
}

pub(crate) fn require_arity(
    source: &str,
    actual: usize,
    expected: usize,
    span: Span,
) -> Result<()> {
    if actual != expected {
        return Err(Diagnostic::at(
            "E0202",
            format!("Expected {expected} arguments, found {actual}"),
            source,
            span,
        ));
    }
    Ok(())
}

pub(crate) fn require_type(
    name: &str,
    actual: &ValueType,
    expected: &ValueType,
    span: Span,
) -> Result<()> {
    if actual != expected {
        return Err(Diagnostic::at(
            "E0202",
            format!("Expected {}, found {}", expected.label(), actual.label()),
            name,
            span,
        ));
    }
    Ok(())
}

pub(crate) fn literal(name: &str, literal: IntegerLiteral) -> Result<BigInt> {
    let digits = if literal.radix == 16 {
        &literal.spelling[2..]
    } else {
        &literal.spelling
    };
    if digits.len() > MAX_INTEGER_DIGITS {
        return Err(Diagnostic::at(
            "E0205",
            "Integer literals are limited to 4096 digits",
            name,
            literal.span,
        ));
    }
    BigInt::parse_bytes(digits.as_bytes(), literal.radix)
        .ok_or_else(|| Diagnostic::at("E0002", "Invalid integer literal", name, literal.span))
}

pub(super) fn atom(value: &BigInt) -> Vec<u8> {
    if *value == BigInt::from(0) {
        vec![]
    } else {
        value.to_signed_bytes_be()
    }
}

pub(crate) fn binary_type(
    name: &str,
    operator: B,
    left: ValueType,
    right: ValueType,
    left_span: Span,
    right_span: Span,
) -> Result<ValueType> {
    if matches!(operator, B::And | B::Or) {
        require_type(name, &left, &ValueType::Boolean, left_span)?;
        require_type(name, &right, &ValueType::Boolean, right_span)?;
        return Ok(ValueType::Boolean);
    }
    if matches!(operator, B::Equal | B::NotEqual) {
        if matches!(
            left,
            ValueType::Condition | ValueType::List(_) | ValueType::Pair(_, _)
        ) {
            return Err(Diagnostic::at(
                "E0202",
                format!("{} values do not support equality", left.label()),
                name,
                left_span,
            ));
        }
        require_type(name, &right, &left, right_span)?;
    } else {
        require_type(name, &left, &ValueType::Integer, left_span)?;
        require_type(name, &right, &ValueType::Integer, right_span)?;
    }
    Ok(if matches!(operator, B::Add | B::Subtract | B::Multiply) {
        ValueType::Integer
    } else {
        ValueType::Boolean
    })
}

pub(super) fn push(
    name: &str,
    values: &mut Vec<IntegerValue>,
    kind: IntegerValueKind,
    value_type: ValueType,
    span: Span,
) -> Result<usize> {
    if values.len() >= MAX_INTEGER_VALUES {
        return Err(Diagnostic::at(
            "E0205",
            "Contracts are limited to 4096 scalar value bindings",
            name,
            span,
        ));
    }
    let id = values.len();
    values.push(IntegerValue {
        kind,
        value_type,
        span,
    });
    Ok(id)
}

pub(super) fn expression(
    name: &str,
    expr: Expression,
    values: &mut Vec<IntegerValue>,
    names: &BTreeMap<String, usize>,
    functions: &Callables,
) -> Result<usize> {
    expression_expected(name, expr, values, names, functions, None)
}
pub(super) fn expression_expected(
    name: &str,
    expr: Expression,
    values: &mut Vec<IntegerValue>,
    names: &BTreeMap<String, usize>,
    functions: &Callables,
    expected: Option<&ValueType>,
) -> Result<usize> {
    let span = expr.span;
    let (kind, ty) = match expr.kind {
        ExpressionKind::List(elements) => {
            let context = match expected {
                Some(ValueType::List(t)) => Some(t.as_ref()),
                Some(_) => {
                    return Err(Diagnostic::at(
                        "E0202",
                        "List literal requires a LIST type",
                        name,
                        span,
                    ));
                }
                None => None,
            };
            let mut element_type = context.cloned();
            let mut operands = Vec::new();
            for element in elements {
                let span = element.span;
                let id = expression_expected(name, element, values, names, functions, context)?;
                if let Some(ty) = &element_type {
                    require_type(name, &values[id].value_type, ty, span)?;
                } else {
                    element_type = Some(values[id].value_type.clone());
                }
                operands.push(id);
            }
            let ty = element_type.ok_or_else(|| {
                Diagnostic::at(
                    "E0202",
                    "Empty list requires an expected element type",
                    name,
                    span,
                )
            })?;
            let ty = super::types::TypeBudget::default().list(&ty, name, span)?;
            (IntegerValueKind::List { elements: operands }, ty)
        }
        ExpressionKind::Bytes(bytes) => (IntegerValueKind::Literal(bytes), ValueType::Bytes),
        ExpressionKind::String(text) => (
            IntegerValueKind::Literal(text.into_bytes()),
            ValueType::String,
        ),
        ExpressionKind::Call {
            name: callee,
            arguments,
        } => {
            if callee.eq_ignore_ascii_case("CONS") {
                require_arity(name, arguments.len(), 2, span)?;
                let mut args = arguments.into_iter();
                let context = cons_element(expected);
                let head = expression_expected(
                    name,
                    args.next().unwrap(),
                    values,
                    names,
                    functions,
                    context,
                )?;
                let head_type = values[head].value_type.clone();
                if let Some(ty) = context {
                    require_type(name, &head_type, ty, span)?;
                }
                let ty = super::types::TypeBudget::default().list(&head_type, name, span)?;
                let tail_expr = args.next().unwrap();
                let tail_span = tail_expr.span;
                let tail =
                    expression_expected(name, tail_expr, values, names, functions, Some(&ty))?;
                require_type(name, &values[tail].value_type, &ty, tail_span)?;
                return push(
                    name,
                    values,
                    IntegerValueKind::Pair {
                        left: head,
                        right: tail,
                    },
                    ty,
                    span,
                );
            }
            if let Some(construct) = pair_call(&callee) {
                require_arity(name, arguments.len(), if construct { 2 } else { 1 }, span)?;
                let mut operands = Vec::new();
                for (index, argument) in arguments.into_iter().enumerate() {
                    let context = if construct {
                        pair_component(expected, index)
                    } else {
                        None
                    };
                    operands.push(expression_expected(
                        name, argument, values, names, functions, context,
                    )?);
                }
                let types: Vec<_> = operands
                    .iter()
                    .map(|id| values[*id].value_type.clone())
                    .collect();
                // Full module analysis enforces the shared cumulative budget, including unreachable source.
                // Recheck local construction before allocating during executable lowering.
                let ty = pair_result(name, &callee, &types, &mut Default::default(), span)?;
                let kind = if construct {
                    IntegerValueKind::Pair {
                        left: operands[0],
                        right: operands[1],
                    }
                } else if callee.eq_ignore_ascii_case("LIST_LENGTH") {
                    IntegerValueKind::ListLength {
                        operand: operands[0],
                    }
                } else {
                    IntegerValueKind::PairAccess {
                        operand: operands[0],
                        first: callee.eq_ignore_ascii_case("FIRST"),
                    }
                };
                return push(name, values, kind, ty, span);
            }
            if let Some((builtin, arity, argument_type, result_type)) = byte_builtin(&callee) {
                require_arity(name, arguments.len(), arity, span)?;
                let mut operands = Vec::new();
                for argument in arguments {
                    let argument_span = argument.span;
                    let operand = expression(name, argument, values, names, functions)?;
                    require_type(
                        name,
                        &values[operand].value_type,
                        &argument_type,
                        argument_span,
                    )?;
                    operands.push(operand);
                }
                let kind = match builtin {
                    ByteBuiltin::ByteLength => IntegerValueKind::ByteLength {
                        operand: operands[0],
                    },
                    ByteBuiltin::Concat => IntegerValueKind::Concat {
                        left: operands[0],
                        right: operands[1],
                    },
                    ByteBuiltin::StringFromUtf8 => IntegerValueKind::StringFromUtf8 {
                        operand: operands[0],
                    },
                    ByteBuiltin::AsPublicKey => IntegerValueKind::AsPublicKey {
                        operand: operands[0],
                    },
                    ByteBuiltin::AsAmount => IntegerValueKind::AsAmount {
                        operand: operands[0],
                    },
                    ByteBuiltin::AsPuzzleHash => IntegerValueKind::AsPuzzleHash {
                        operand: operands[0],
                    },
                    ByteBuiltin::AmountValue
                    | ByteBuiltin::HashBytes
                    | ByteBuiltin::KeyBytes
                    | ByteBuiltin::Utf8 => IntegerValueKind::Copy {
                        operand: operands[0],
                    },
                    ByteBuiltin::U32Be => IntegerValueKind::UnsignedBytes {
                        operand: operands[0],
                        width: 4,
                    },
                    ByteBuiltin::U64Be => IntegerValueKind::UnsignedBytes {
                        operand: operands[0],
                        width: 8,
                    },
                    ByteBuiltin::IntBytes => IntegerValueKind::IntBytes {
                        operand: operands[0],
                    },
                    ByteBuiltin::IntFromBytes => IntegerValueKind::IntFromBytes {
                        operand: operands[0],
                    },
                    ByteBuiltin::Sha256 => IntegerValueKind::Sha256 {
                        operand: operands[0],
                    },
                };
                return push(name, values, kind, result_type, span);
            }
            let (function, signature) =
                functions.get(&callee.to_ascii_lowercase()).ok_or_else(|| {
                    Diagnostic::at("E0200", format!("Unknown function: {callee}"), name, span)
                })?;
            if arguments.len() != signature.parameters.len() {
                return Err(Diagnostic::at(
                    "E0202",
                    "Function argument count does not match its signature",
                    name,
                    span,
                ));
            }
            let mut operands = Vec::new();
            for (argument, parameter) in arguments.into_iter().zip(&signature.parameters) {
                let argument_span = argument.span;
                let operand = expression_expected(
                    name,
                    argument,
                    values,
                    names,
                    functions,
                    Some(&parameter.value_type),
                )?;
                require_type(
                    name,
                    &values[operand].value_type,
                    &parameter.value_type,
                    argument_span,
                )?;
                operands.push(operand);
            }
            (
                IntegerValueKind::Call {
                    function: *function,
                    arguments: operands,
                },
                signature.result.clone(),
            )
        }
        ExpressionKind::HeightCondition(argument) => {
            let argument_span = argument.span;
            let operand = expression(name, *argument, values, names, functions)?;
            require_type(
                name,
                &values[operand].value_type,
                &ValueType::Integer,
                argument_span,
            )?;
            (
                IntegerValueKind::HeightCondition { operand },
                ValueType::Condition,
            )
        }
        ExpressionKind::Integer(lit) => (
            IntegerValueKind::Literal(atom(&literal(name, lit)?)),
            ValueType::Integer,
        ),
        ExpressionKind::Boolean(b) => (
            IntegerValueKind::Literal(if b { vec![1] } else { vec![] }),
            ValueType::Boolean,
        ),
        ExpressionKind::Name(id) => {
            return names
                .get(&id.to_ascii_lowercase())
                .copied()
                .ok_or_else(|| Diagnostic::at("E0200", format!("Unknown name: {id}"), name, span));
        }
        ExpressionKind::Group(inner) => {
            return expression_expected(name, *inner, values, names, functions, expected);
        }
        ExpressionKind::Unary {
            operator, operand, ..
        } => {
            let operand_span = operand.span;
            let operand = expression(name, *operand, values, names, functions)?;
            let ty = if operator == U::Not {
                ValueType::Boolean
            } else {
                ValueType::Integer
            };
            require_type(name, &values[operand].value_type, &ty, operand_span)?;
            if operator == U::Plus {
                return Ok(operand);
            }
            (
                if operator == U::Not {
                    IntegerValueKind::Not { operand }
                } else {
                    IntegerValueKind::Negate { operand }
                },
                ty,
            )
        }
        ExpressionKind::Binary {
            operator,
            left,
            right,
            ..
        } => {
            let (ls, rs) = (left.span, right.span);
            let left = expression(name, *left, values, names, functions)?;
            if matches!(operator, B::And | B::Or) {
                // Reserve the result ID before the branch so all nested bindings
                // count toward the same budget without escaping to later code.
                let id = push(
                    name,
                    values,
                    IntegerValueKind::Literal(vec![]),
                    ValueType::Boolean,
                    span,
                )?;
                let right = expression(name, *right, values, names, functions)?;
                binary_type(
                    name,
                    operator,
                    values[left].value_type.clone(),
                    values[right].value_type.clone(),
                    ls,
                    rs,
                )?;
                values[id].kind = IntegerValueKind::ShortCircuit {
                    left,
                    right,
                    end: values.len(),
                    is_and: operator == B::And,
                };
                return Ok(id);
            }
            let right = expression(name, *right, values, names, functions)?;
            let ty = binary_type(
                name,
                operator,
                values[left].value_type.clone(),
                values[right].value_type.clone(),
                ls,
                rs,
            )?;
            let operation = match operator {
                B::Add => IntegerOperation::Add,
                B::Subtract => IntegerOperation::Subtract,
                B::Multiply => IntegerOperation::Multiply,
                B::Equal => IntegerOperation::Equal,
                B::NotEqual => IntegerOperation::NotEqual,
                B::Less => IntegerOperation::Less,
                B::LessEqual => IntegerOperation::LessEqual,
                B::Greater => IntegerOperation::Greater,
                B::GreaterEqual => IntegerOperation::GreaterEqual,
                B::And | B::Or => unreachable!("rejected by type rules"),
            };
            (
                IntegerValueKind::Binary {
                    operation,
                    left,
                    right,
                },
                ty,
            )
        }
    };
    push(name, values, kind, ty, span)
}

// Bound every intermediate and total visited syntax, including unused constants.
pub(crate) fn constant(
    name: &str,
    expr: Expression,
    names: &BTreeMap<String, usize>,
    constants: &BTreeMap<String, (ConstantValue, ValueType)>,
    budget: &mut ConstantBudget,
    expected: Option<&ValueType>,
) -> Result<(ConstantValue, ValueType)> {
    constant_at(name, expr, names, constants, budget, true, expected)
}

#[allow(clippy::too_many_arguments)]
fn constant_at(
    name: &str,
    expr: Expression,
    names: &BTreeMap<String, usize>,
    constants: &BTreeMap<String, (ConstantValue, ValueType)>,
    budget: &mut ConstantBudget,
    evaluate: bool,
    expected: Option<&ValueType>,
) -> Result<(ConstantValue, ValueType)> {
    let span = expr.span;
    budget.nodes += 1;
    if budget.nodes > 16384 {
        return Err(Diagnostic::at(
            "E0205",
            "Contracts support at most 16384 constant-expression nodes",
            name,
            span,
        ));
    }
    let (value, ty) = match expr.kind {
        ExpressionKind::Bytes(bytes) => (ConstantValue::Bytes(bytes.into()), ValueType::Bytes),
        ExpressionKind::String(text) => (
            ConstantValue::Bytes(text.into_bytes().into()),
            ValueType::String,
        ),
        ExpressionKind::List(elements) => {
            let context = match expected {
                Some(ValueType::List(element)) => Some(element.as_ref()),
                Some(_) => {
                    return Err(Diagnostic::at(
                        "E0202",
                        "List literal requires a LIST type",
                        name,
                        span,
                    ));
                }
                None => None,
            };
            let mut element_type = context.cloned();
            let mut children = Vec::new();
            let (mut nodes, mut size, mut payload) = (1usize, 1usize, 0usize);
            for element in elements {
                let element_span = element.span;
                let (child, ty) =
                    constant_at(name, element, names, constants, budget, evaluate, context)?;
                if let Some(expected) = &element_type {
                    require_type(name, &ty, expected, element_span)?;
                } else {
                    element_type = Some(ty);
                }
                let (child_nodes, child_size, child_payload) = child.metrics();
                nodes += 1 + child_nodes;
                size += 1 + child_size;
                payload += child_payload;
                if nodes > 65536 || size > 1048576 {
                    return Err(Diagnostic::at(
                        "E0205",
                        "Expanded constant trees are limited to 65536 nodes and 1048576 serialized bytes",
                        name,
                        span,
                    ));
                }
                children.push(child);
            }
            let element_type = element_type.ok_or_else(|| {
                Diagnostic::at(
                    "E0202",
                    "Empty list requires an expected LIST type",
                    name,
                    span,
                )
            })?;
            let ty = super::types::TypeBudget::default().list(&element_type, name, span)?;
            // Reserve the complete expansion before allocating or copying it.
            charge_structure(budget, nodes, size, name, span)?;
            let mut encoded = Vec::with_capacity(size);
            for child in children {
                encoded.push(0xff);
                child.append_tree(&mut encoded);
            }
            encoded.push(0x80);
            debug_assert_eq!(encoded.len(), size);
            return charge_bytes(
                ConstantValue::List {
                    encoded: encoded.into(),
                    nodes,
                    payload,
                },
                ty,
                budget,
                name,
                span,
            );
        }
        ExpressionKind::Call { .. } => {
            return Err(Diagnostic::at(
                "E0205",
                "CONST expressions cannot contain calls",
                name,
                span,
            ));
        }
        ExpressionKind::HeightCondition(_) => {
            return Err(Diagnostic::at(
                "E0205",
                "CONST expressions cannot call condition constructors",
                name,
                span,
            ));
        }
        ExpressionKind::Integer(lit) => (
            ConstantValue::Number(literal(name, lit)?),
            ValueType::Integer,
        ),
        ExpressionKind::Boolean(b) => (
            ConstantValue::Number(BigInt::from(u8::from(b))),
            ValueType::Boolean,
        ),
        ExpressionKind::Name(id) => {
            let key = id.to_ascii_lowercase();
            constants.get(&key).cloned().ok_or_else(|| {
                if names.contains_key(&key) {
                    Diagnostic::at(
                        "E0205",
                        "CONST expressions cannot reference mutable locals or parameters",
                        name,
                        span,
                    )
                } else {
                    Diagnostic::at("E0200", format!("Unknown name: {id}"), name, span)
                }
            })?
        }
        ExpressionKind::Group(inner) => {
            constant_at(name, *inner, names, constants, budget, evaluate, expected)?
        }
        ExpressionKind::Unary {
            operator, operand, ..
        } => {
            let operand_span = operand.span;
            let (value, ty) =
                constant_at(name, *operand, names, constants, budget, evaluate, None)?;
            let expected = if operator == U::Not {
                ValueType::Boolean
            } else {
                ValueType::Integer
            };
            require_type(name, &ty, &expected, operand_span)?;
            let value = value.number();
            (
                ConstantValue::Number(match operator {
                    U::Plus => value,
                    U::Minus => -value,
                    U::Not => BigInt::from(u8::from(value == BigInt::from(0))),
                }),
                ty,
            )
        }
        ExpressionKind::Binary {
            operator,
            left,
            right,
            ..
        } => {
            let (ls, rs) = (left.span, right.span);
            let (left, lt) = constant_at(name, *left, names, constants, budget, evaluate, None)?;
            let take_right = evaluate
                && !((operator == B::And && left.is_zero())
                    || (operator == B::Or && !left.is_zero()));
            let (right, rt) =
                constant_at(name, *right, names, constants, budget, take_right, None)?;
            let ty = binary_type(name, operator, lt, rt, ls, rs)?;
            let value = if !evaluate {
                ConstantValue::Number(BigInt::from(0))
            } else {
                match operator {
                    B::Add => ConstantValue::Number(left.number() + right.number()),
                    B::Subtract => ConstantValue::Number(left.number() - right.number()),
                    B::Multiply => ConstantValue::Number(left.number() * right.number()),
                    B::Equal => ConstantValue::Number(BigInt::from(u8::from(left == right))),
                    B::NotEqual => ConstantValue::Number(BigInt::from(u8::from(left != right))),
                    B::Less => ConstantValue::Number(BigInt::from(u8::from(
                        left.number() < right.number(),
                    ))),
                    B::LessEqual => ConstantValue::Number(BigInt::from(u8::from(
                        left.number() <= right.number(),
                    ))),
                    B::Greater => ConstantValue::Number(BigInt::from(u8::from(
                        left.number() > right.number(),
                    ))),
                    B::GreaterEqual => ConstantValue::Number(BigInt::from(u8::from(
                        left.number() >= right.number(),
                    ))),
                    B::And | B::Or => {
                        if take_right {
                            right
                        } else {
                            left
                        }
                    }
                }
            };
            (value, ty)
        }
    };
    if matches!(&value, ConstantValue::Number(n) if n.bits() > 32768) {
        return Err(Diagnostic::at(
            "E0205",
            "Constant intermediates are limited to 32768 magnitude bits",
            name,
            span,
        ));
    }
    if let ConstantValue::List { nodes, encoded, .. } = &value {
        charge_structure(budget, *nodes, encoded.len(), name, span)?;
    }
    charge_bytes(value, ty, budget, name, span)
}

fn charge_structure(
    budget: &mut ConstantBudget,
    nodes: usize,
    size: usize,
    name: &str,
    span: Span,
) -> Result<()> {
    if nodes > 1048576usize.saturating_sub(budget.structure)
        || size > MAX_CONSTANT_BYTE_WORK.saturating_sub(budget.encoded)
    {
        budget.structure = 1048576;
        budget.encoded = MAX_CONSTANT_BYTE_WORK;
        return Err(Diagnostic::at(
            "E0205",
            "Constant structural work exceeds 1048576 nodes or 8388608 serialized bytes",
            name,
            span,
        ));
    }
    budget.structure += nodes;
    budget.encoded += size;
    Ok(())
}

fn charge_bytes(
    value: ConstantValue,
    ty: ValueType,
    budget: &mut ConstantBudget,
    name: &str,
    span: Span,
) -> Result<(ConstantValue, ValueType)> {
    let bytes = match &value {
        ConstantValue::Bytes(bytes) => bytes.len(),
        ConstantValue::List { payload, .. } => *payload,
        ConstantValue::Number(_) => 0,
    };
    if bytes > MAX_CONSTANT_BYTE_WORK.saturating_sub(budget.bytes) {
        budget.bytes = MAX_CONSTANT_BYTE_WORK;
        return Err(Diagnostic::at(
            "E0205",
            "Constant byte work exceeds 8388608 bytes",
            name,
            span,
        ));
    }
    budget.bytes += bytes;
    Ok((value, ty))
}

#[cfg(test)]
mod constant_tree_tests {
    use super::*;
    #[test]
    fn exact_structural_limits_and_atom_size_prefixes() {
        let span = Span {
            start_byte: 0,
            end_byte: 1,
            line: 1,
            column: 1,
        };
        let mut budget = ConstantBudget::default();
        charge_structure(&mut budget, 1048576, 8388608, "test", span).unwrap();
        assert_eq!(
            charge_structure(&mut budget, 1, 0, "test", span)
                .unwrap_err()
                .code,
            "E0205"
        );
        let mut budget = ConstantBudget::default();
        charge_structure(&mut budget, 0, 8388608, "test", span).unwrap();
        assert!(charge_structure(&mut budget, 0, 1, "test", span).is_err());
        for size in [0, 1, 63, 64, 8191, 8192, 1048575, 1048576] {
            let value = ConstantValue::Bytes(vec![0xff; size].into());
            let mut encoded = Vec::new();
            value.append_tree(&mut encoded);
            assert_eq!(value.metrics(), (1, encoded.len(), size));
        }
        for byte in [0, 127, 128, 255] {
            let value = ConstantValue::Bytes(vec![byte].into());
            let mut encoded = Vec::new();
            value.append_tree(&mut encoded);
            assert_eq!(value.metrics().1, encoded.len());
        }
    }
}
