//! Ordered, immutable scalar values, assertions, and height emissions.
use crate::ir::expressions::{ConstantBudget, ConstantValue};
use crate::syntax::expression::ExpressionKind;
use crate::{Diagnostic, Result, Span, syntax::ParsedContract};
use serde::Serialize;
use std::collections::BTreeMap;

pub const MAX_INTEGER_DIGITS: usize = 4096;
pub const MAX_INTEGER_VALUES: usize = 4096;

pub(crate) mod expressions;
use expressions::{constant, expression, push, require_type};

pub(crate) mod types;
pub use types::ValueType;

#[derive(Debug, Serialize)]
pub enum IntegerOperation {
    Add,
    Subtract,
    Multiply,
    Equal,
    NotEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
}

#[derive(Debug, Serialize)]
pub enum IntegerValueKind {
    Fixed {
        index: usize,
    },
    /// Validated contract input occupying an initial body-frame slot.
    Input {
        index: usize,
    },
    ListLength {
        operand: usize,
    },
    List {
        elements: Vec<usize>,
    },
    Pair {
        left: usize,
        right: usize,
    },
    PairAccess {
        operand: usize,
        first: bool,
    },
    AsPublicKey {
        operand: usize,
    },
    AsAmount {
        operand: usize,
    },
    AsPuzzleHash {
        operand: usize,
    },
    StringFromUtf8 {
        operand: usize,
    },
    UnsignedBytes {
        operand: usize,
        width: u8,
    },
    IntBytes {
        operand: usize,
    },
    IntFromBytes {
        operand: usize,
    },
    Sha256 {
        operand: usize,
    },
    ByteLength {
        operand: usize,
    },
    Concat {
        left: usize,
        right: usize,
    },
    /// A present function return state: a singleton list containing its value.
    ReturnValue {
        operand: usize,
    },
    /// Parameters occupy the first bindings of a function's private environment.
    Parameter,
    Call {
        function: usize,
        arguments: Vec<usize>,
    },
    If {
        predicate: usize,
        yes: BranchBlock,
        no: BranchBlock,
        end: usize,
    },
    Project {
        bundle: usize,
        index: usize,
    },
    PaymentCondition {
        opcode: u8,
        operands: Vec<usize>,
    },
    HeightCondition {
        operand: usize,
    },
    /// Right-hand bindings occupy the following half-open range [id + 1, end).
    /// Their IDs are branch-local; only this BOOLEAN result escapes the branch.
    ShortCircuit {
        left: usize,
        right: usize,
        end: usize,
        is_and: bool,
    },
    Not {
        operand: usize,
    },
    Assert {
        operand: usize,
    },
    Copy {
        operand: usize,
    },
    /// Canonical signed CLVM atom, including the empty atom for zero.
    Literal(Vec<u8>),
    /// Canonical serialized, bounded constant tree, quoted without runtime construction.
    TreeLiteral(Vec<u8>),
    Negate {
        operand: usize,
    },
    Binary {
        operation: IntegerOperation,
        left: usize,
        right: usize,
    },
}

#[derive(Debug, Serialize)]
pub struct IntegerValue {
    pub kind: IntegerValueKind,
    pub value_type: ValueType,
    pub span: Span,
}

#[derive(Debug, Serialize)]
pub struct HeightEmission {
    /// Value ID: expressions are evaluated once, in values-vector order.
    pub condition: usize,
    pub values_before: usize,
    pub span: Span,
    pub spread: bool,
}

#[derive(Debug, Serialize)]
pub struct BranchBlock {
    pub start: usize,
    pub end: usize,
    pub outputs: Vec<usize>,
    pub emissions: Vec<HeightEmission>,
}

#[derive(Debug, Serialize)]
pub struct Contract {
    pub fixed: Vec<crate::abi::Field>,
    pub inputs: Vec<crate::abi::Field>,
    pub functions: Vec<FunctionBody>,
    pub name: String,
    pub span: Span,
    pub values: Vec<IntegerValue>,
    pub locals: Vec<LocalBinding>,
    pub emissions: Vec<HeightEmission>,
}

#[derive(Debug, Serialize)]
pub struct FunctionBody {
    pub name: String,
    pub parameters: usize,
    pub values: Vec<IntegerValue>,
    pub result: usize,
}

type Callables = BTreeMap<String, (usize, crate::FunctionSignature)>;

// Source identifiers cannot begin with underscore. Nil means continuing;
// a singleton list means returned, even when the returned value is FALSE/zero.
const RETURN_STATE: &str = "_return_state";
fn has_return(statements: &[crate::syntax::ParsedStatement]) -> bool {
    statements.iter().any(|s| match s {
        crate::syntax::ParsedStatement::Return { .. } => true,
        crate::syntax::ParsedStatement::If(b) => has_return(&b.yes) || has_return(&b.no),
        _ => false,
    })
}

#[derive(Debug, Serialize)]
pub struct LocalBinding {
    pub name: String,
    pub mutable: bool,
    pub value: usize,
    pub span: Span,
}

struct Lowerer<'a> {
    result_type: Option<ValueType>,
    functions: &'a Callables,
    in_function: bool,
    return_state: bool,
    block_depth: usize,
    source: &'a str,
    contract: String,
    values: Vec<IntegerValue>,
    locals: Vec<LocalBinding>,
    constant_budget: ConstantBudget,
}

pub(crate) fn lower(name: &str, parsed: ParsedContract) -> Result<Contract> {
    lower_contract(name, parsed, &Callables::new())
}

fn lower_contract(name: &str, parsed: ParsedContract, functions: &Callables) -> Result<Contract> {
    let mut lowerer = Lowerer {
        functions,
        in_function: false,
        result_type: None,
        return_state: false,
        block_depth: 0,
        source: name,
        contract: parsed.name.to_ascii_lowercase(),
        values: Vec::new(),
        locals: Vec::new(),
        constant_budget: ConstantBudget::default(),
    };
    let mut names = BTreeMap::new();
    let mut fixed = Vec::new();
    let mut inputs = Vec::new();
    for (is_fixed, index, input) in parsed
        .fixed
        .into_iter()
        .enumerate()
        .map(|(i, p)| (true, i, p))
        .chain(
            parsed
                .inputs
                .into_iter()
                .enumerate()
                .map(|(i, p)| (false, i, p)),
        )
    {
        let key = input.name.to_ascii_lowercase();
        let field = crate::abi::Field::from_type(key.clone(), &input.value_type)?;
        let value = push(
            name,
            &mut lowerer.values,
            if is_fixed {
                IntegerValueKind::Fixed { index }
            } else {
                IntegerValueKind::Input { index }
            },
            input.value_type,
            input.span,
        )?;
        names.insert(key.clone(), value);
        lowerer.locals.push(LocalBinding {
            name: key.clone(),
            mutable: false,
            value,
            span: input.span,
        });
        if is_fixed {
            fixed.push(field);
        } else {
            inputs.push(field);
        }
    }
    let emissions = lowerer.block(parsed.statements, &mut names, &mut BTreeMap::new())?;
    Ok(Contract {
        fixed,
        inputs,
        functions: Vec::new(),
        name: lowerer.contract,
        span: parsed.span,
        values: lowerer.values,
        locals: lowerer.locals,
        emissions,
    })
}

pub(crate) fn lower_module(name: &str, module: crate::syntax::ParsedModule) -> Result<Contract> {
    if module.functions.is_empty()
        && !module.collection_syntax
        && module.contract.inputs.is_empty()
        && module.contract.fixed.is_empty()
    {
        return lower(name, module.contract);
    }
    let analysis = crate::analysis::analyze_module(name, &module)?;
    let callables: Callables = analysis
        .functions
        .into_iter()
        .enumerate()
        .map(|(id, signature)| (signature.name.to_ascii_lowercase(), (id, signature)))
        .collect();
    let mut contract = lower_contract(name, module.contract, &callables)?;
    let mut total = contract.values.len();
    for mut function in module.functions {
        // Preserve existing encoding when there are no branch returns.
        // Full analysis has already checked abandoned continuations.
        let top_return = function.statements.iter().position(|statement| {
            matches!(statement, crate::syntax::ParsedStatement::Return { .. })
        });
        if let Some(index) = top_return {
            function.statements.truncate(index + 1);
        }
        let return_state = top_return.is_none() || function.statements.iter().any(|statement| {
            matches!(statement, crate::syntax::ParsedStatement::If(branch) if has_return(&branch.yes) || has_return(&branch.no))
        });
        let final_expression = if return_state {
            None
        } else {
            let Some(crate::syntax::ParsedStatement::Return { expression, .. }) =
                function.statements.pop()
            else {
                unreachable!("top-level return found above")
            };
            Some(expression)
        };
        let mut lowerer = Lowerer {
            functions: &callables,
            in_function: true,
            result_type: Some(function.result.clone()),
            return_state,
            block_depth: 0,
            source: name,
            contract: contract.name.clone(),
            values: Vec::new(),
            locals: Vec::new(),
            constant_budget: ConstantBudget::default(),
        };
        let mut names = BTreeMap::new();
        let parameters = function.parameters.len();
        for parameter in function.parameters {
            let id = push(
                name,
                &mut lowerer.values,
                IntegerValueKind::Parameter,
                parameter.value_type.clone(),
                parameter.span,
            )?;
            names.insert(parameter.name.to_ascii_lowercase(), id);
        }
        if return_state {
            let empty = push(
                name,
                &mut lowerer.values,
                IntegerValueKind::Literal(vec![]),
                ValueType::Internal,
                function.span,
            )?;
            names.insert(RETURN_STATE.to_owned(), empty);
        }
        lowerer.block(function.statements, &mut names, &mut BTreeMap::new())?;
        let result = if let Some(expression) = final_expression {
            expressions::expression_expected(
                name,
                expression,
                &mut lowerer.values,
                &names,
                &callables,
                Some(&function.result),
            )?
        } else {
            // Analysis proved all normal paths return; failing paths raise
            // before extraction. There is no fabricated typed result.
            push(
                name,
                &mut lowerer.values,
                IntegerValueKind::Project {
                    bundle: names[RETURN_STATE],
                    index: 0,
                },
                function.result,
                function.span,
            )?
        };
        total += lowerer.values.len();
        if total > MAX_INTEGER_VALUES {
            return Err(Diagnostic::at(
                "E0205",
                "Module exceeds 4096 value bindings across contract and functions",
                name,
                function.span,
            ));
        }
        contract.functions.push(FunctionBody {
            name: function.name.to_ascii_lowercase(),
            parameters,
            values: lowerer.values,
            result,
        });
    }
    Ok(contract)
}

impl Lowerer<'_> {
    fn conditional(
        &mut self,
        branch: crate::syntax::ParsedIf,
        names: &mut BTreeMap<String, usize>,
        constants: &BTreeMap<String, (ConstantValue, ValueType)>,
    ) -> Result<HeightEmission> {
        let span = branch.span;
        let predicate_span = branch.predicate.span;
        let predicate = expression(
            self.source,
            branch.predicate,
            &mut self.values,
            names,
            self.functions,
        )?;
        require_type(
            self.source,
            &self.values[predicate].value_type,
            &ValueType::Boolean,
            predicate_span,
        )?;
        self.conditional_body(predicate, branch.yes, branch.no, span, names, constants)
    }

    fn conditional_body(
        &mut self,
        predicate: usize,
        yes: Vec<crate::syntax::ParsedStatement>,
        no: Vec<crate::syntax::ParsedStatement>,
        span: Span,
        names: &mut BTreeMap<String, usize>,
        constants: &BTreeMap<String, (ConstantValue, ValueType)>,
    ) -> Result<HeightEmission> {
        let bundle = push(
            self.source,
            &mut self.values,
            IntegerValueKind::Literal(vec![]),
            ValueType::Internal,
            span,
        )?;
        let mut yes_names = names.clone();
        let yes_start = self.values.len();
        let yes_emissions = self.block(yes, &mut yes_names, &mut constants.clone())?;
        let yes_end = self.values.len();
        let mut no_names = names.clone();
        let no_emissions = self.block(no, &mut no_names, &mut constants.clone())?;
        let end = self.values.len();
        // Stable name order; unchanged outer bindings keep their incoming IDs.
        let changed: Vec<_> = names
            .iter()
            .filter(|(key, id)| yes_names[*key] != **id || no_names[*key] != **id)
            .map(|(key, id)| (key.clone(), self.values[*id].value_type.clone()))
            .collect();
        let yes_outputs = changed.iter().map(|(key, _)| yes_names[key]).collect();
        let no_outputs = changed.iter().map(|(key, _)| no_names[key]).collect();
        self.values[bundle].kind = IntegerValueKind::If {
            predicate,
            yes: BranchBlock {
                start: yes_start,
                end: yes_end,
                outputs: yes_outputs,
                emissions: yes_emissions,
            },
            no: BranchBlock {
                start: yes_end,
                end,
                outputs: no_outputs,
                emissions: no_emissions,
            },
            end,
        };
        let conditions = push(
            self.source,
            &mut self.values,
            IntegerValueKind::Project { bundle, index: 0 },
            ValueType::Internal,
            span,
        )?;
        for (index, (key, ty)) in changed.into_iter().enumerate() {
            let value = push(
                self.source,
                &mut self.values,
                IntegerValueKind::Project {
                    bundle,
                    index: index + 1,
                },
                ty,
                span,
            )?;
            names.insert(key, value);
        }
        Ok(HeightEmission {
            condition: conditions,
            values_before: self.values.len(),
            span,
            spread: true,
        })
    }
    fn block(
        &mut self,
        statements: Vec<crate::syntax::ParsedStatement>,
        names: &mut BTreeMap<String, usize>,
        constants: &mut BTreeMap<String, (ConstantValue, ValueType)>,
    ) -> Result<Vec<HeightEmission>> {
        if self.return_state && self.block_depth >= 64 {
            return Err(Diagnostic::new(
                "E0205",
                "Return-aware lowering exceeds 64 nested blocks and continuations",
            ));
        }
        self.block_depth += 1;
        let result = self.block_inner(statements, names, constants);
        self.block_depth -= 1;
        result
    }
    fn block_inner(
        &mut self,
        statements: Vec<crate::syntax::ParsedStatement>,
        names: &mut BTreeMap<String, usize>,
        constants: &mut BTreeMap<String, (ConstantValue, ValueType)>,
    ) -> Result<Vec<HeightEmission>> {
        let name = self.source;
        let mut emissions = Vec::new();
        let mut statements = statements.into_iter();
        while let Some(statement) = statements.next() {
            match statement {
                crate::syntax::ParsedStatement::Return {
                    expression: result,
                    span,
                } => {
                    if self.return_state {
                        let operand = expressions::expression_expected(
                            name,
                            result,
                            &mut self.values,
                            names,
                            self.functions,
                            self.result_type.as_ref(),
                        )?;
                        let state = push(
                            name,
                            &mut self.values,
                            IntegerValueKind::ReturnValue { operand },
                            ValueType::Internal,
                            span,
                        )?;
                        names.insert(RETURN_STATE.to_owned(), state);
                        break;
                    }
                    return Err(Diagnostic::at(
                        "E0205",
                        if self.in_function {
                            "Compilation supports top-level function RETURN; branch returns are not implemented yet"
                        } else {
                            "RETURN is forbidden in contracts"
                        },
                        name,
                        span,
                    ));
                }
                crate::syntax::ParsedStatement::If(branch) => {
                    let may_return =
                        self.return_state && (has_return(&branch.yes) || has_return(&branch.no));
                    let span = branch.span;
                    emissions.push(self.conditional(branch, names, constants)?);
                    if may_return {
                        let remaining: Vec<_> = statements.collect();
                        if !remaining.is_empty() {
                            let predicate = push(
                                name,
                                &mut self.values,
                                IntegerValueKind::Not {
                                    operand: names[RETURN_STATE],
                                },
                                ValueType::Boolean,
                                span,
                            )?;
                            emissions.push(self.conditional_body(
                                predicate,
                                remaining,
                                Vec::new(),
                                span,
                                names,
                                constants,
                            )?);
                        }
                        break;
                    }
                }
                crate::syntax::ParsedStatement::Assert {
                    expression: predicate,
                    span,
                } => {
                    let operand_span = predicate.span;
                    let operand =
                        expression(name, predicate, &mut self.values, names, self.functions)?;
                    require_type(
                        name,
                        &self.values[operand].value_type,
                        &ValueType::Boolean,
                        operand_span,
                    )?;
                    push(
                        name,
                        &mut self.values,
                        IntegerValueKind::Assert { operand },
                        ValueType::Boolean,
                        span,
                    )?;
                }
                crate::syntax::ParsedStatement::Local(declaration) => {
                    let key = declaration.name.to_ascii_lowercase();
                    let assigning =
                        matches!(declaration.kind, crate::syntax::LocalUpdateKind::Assignment);
                    let is_constant =
                        matches!(declaration.kind, crate::syntax::LocalUpdateKind::Constant);
                    if assigning {
                        if constants.contains_key(&key) {
                            return Err(Diagnostic::at(
                                "E0203",
                                "Cannot assign to a CONST",
                                name,
                                declaration.span,
                            ));
                        }
                        if key == self.contract {
                            return Err(Diagnostic::at(
                                "E0203",
                                "A contract name is not an assignable local",
                                name,
                                declaration.span,
                            ));
                        }
                        if !names.contains_key(&key) {
                            return Err(Diagnostic::at(
                                "E0200",
                                format!("Unknown assignment target: {}", declaration.name),
                                name,
                                declaration.span,
                            ));
                        }
                    } else if names.contains_key(&key) || key == self.contract {
                        return Err(Diagnostic::at(
                            "E0201",
                            format!("Duplicate or shadowed name: {}", declaration.name),
                            name,
                            declaration.span,
                        ));
                    }
                    // Publish the name only after its initializer has been checked.
                    let initializer_span = declaration.initializer.span;
                    let context = declaration.annotation.clone().or_else(|| {
                        if assigning {
                            names
                                .get(&key)
                                .map(|id| self.values[*id].value_type.clone())
                        } else {
                            None
                        }
                    });
                    let mut value = if is_constant {
                        let span = declaration.initializer.span;
                        let (evaluated, value_type) = constant(
                            name,
                            declaration.initializer,
                            names,
                            constants,
                            &mut self.constant_budget,
                            context.as_ref(),
                        )?;
                        let kind = evaluated.literal_kind();
                        constants.insert(key.clone(), (evaluated, value_type.clone()));
                        push(name, &mut self.values, kind, value_type, span)?
                    } else {
                        expressions::expression_expected(
                            name,
                            declaration.initializer,
                            &mut self.values,
                            names,
                            self.functions,
                            context.as_ref(),
                        )?
                    };
                    let value_type = self.values[value].value_type.clone();
                    if let Some(expected) = declaration.annotation {
                        require_type(name, &value_type, &expected, initializer_span)?;
                    }
                    if assigning {
                        require_type(
                            name,
                            &value_type,
                            &self.values[names[&key]].value_type,
                            initializer_span,
                        )?;
                        let operand = value;
                        value = push(
                            name,
                            &mut self.values,
                            IntegerValueKind::Copy { operand },
                            value_type,
                            declaration.span,
                        )?;
                    }
                    names.insert(key.clone(), value);
                    if !assigning {
                        self.locals.push(LocalBinding {
                            name: key,
                            mutable: !is_constant,
                            value,
                            span: declaration.span,
                        });
                    }
                }
                crate::syntax::ParsedStatement::Emit(emission) => {
                    let span = emission.expression.span;
                    let condition = expression(
                        name,
                        emission.expression,
                        &mut self.values,
                        names,
                        self.functions,
                    )?;
                    require_type(
                        name,
                        &self.values[condition].value_type,
                        &ValueType::Condition,
                        span,
                    )?;
                    emissions.push(HeightEmission {
                        spread: false,
                        condition,
                        values_before: self.values.len(),
                        span: emission.span,
                    });
                }
            }
        }
        Ok(emissions)
    }
}
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn syntax_preserves_spelling_and_spans_before_lowering() {
        let source = "\u{feff}CONTRACT MixedCase()\r\n EMIT ASSERT_HEIGHT_ABSOLUTE(&h00aF)\r\n EMIT ASSERT_HEIGHT_ABSOLUTE(17)\r\nEND CONTRACT\r\n";
        let parsed = crate::syntax::parse("source.bas", source.as_bytes()).unwrap();
        assert_eq!(parsed.name, "MixedCase");
        let crate::syntax::ParsedStatement::Emit(first) = &parsed.statements[0] else {
            panic!("Expected emission");
        };
        let ExpressionKind::HeightCondition(argument) = &first.expression.kind else {
            panic!("Expected constructor syntax");
        };
        let ExpressionKind::Integer(literal) = &argument.kind else {
            panic!("Expected integer syntax");
        };
        assert_eq!(literal.spelling, "&h00aF");
        assert_eq!(literal.radix, 16);
        assert_eq!(
            &source[argument.span.start_byte..argument.span.end_byte],
            "&h00aF"
        );
        assert_eq!((argument.span.line, argument.span.column), (2, 30));
        let emission_span = first.span;
        let checked = lower("source.bas", parsed).unwrap();
        assert_eq!(checked.name, "mixedcase");
        assert_eq!(checked.emissions[0].span, emission_span);
        assert!(
            matches!(&checked.values[0].kind, IntegerValueKind::Literal(bytes) if bytes == &[0, 175])
        );
    }

    #[test]
    fn lowering_keeps_out_of_range_integers_for_runtime_validation() {
        let checked = crate::check(
            "large.bas",
            b"CONTRACT Demo()\n EMIT ASSERT_HEIGHT_ABSOLUTE(4294967296)\nEND CONTRACT\n",
        )
        .unwrap();
        assert!(
            matches!(&checked.values[0].kind, IntegerValueKind::Literal(bytes) if bytes == &[1, 0, 0, 0, 0])
        );
    }
}
