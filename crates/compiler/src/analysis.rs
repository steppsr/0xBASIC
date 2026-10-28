//! Semantic analysis for functions before their executable backend is available.
use crate::ir::expressions::{ConstantBudget, ConstantValue};
use crate::ir::expressions::{binary_type, constant, literal, require_type};
use crate::syntax::expression::{Expression, ExpressionKind as E, UnaryOperator};
use crate::syntax::{self, LocalUpdateKind, ParsedStatement};
use crate::{Diagnostic, Result, Span, ValueType};
use std::collections::{BTreeMap, BTreeSet};

mod for_next;

#[derive(Debug, serde::Serialize)]
pub struct ModuleAnalysis {
    pub contract: String,
    pub functions: Vec<FunctionSignature>,
    #[cfg(test)]
    #[serde(skip)]
    pub(crate) loops: Vec<for_next::LoopAnalysis>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct FunctionSignature {
    pub name: String,
    pub parameters: Vec<ParameterSignature>,
    pub result: ValueType,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct ParameterSignature {
    pub name: String,
    pub value_type: ValueType,
}

#[derive(Clone, Default)]
struct Scope {
    bindings: BTreeMap<String, (ValueType, bool)>,
    constants: BTreeMap<String, (ConstantValue, ValueType)>,
}

impl Scope {
    fn names(&self) -> BTreeMap<String, usize> {
        self.bindings.keys().map(|key| (key.clone(), 0)).collect()
    }
}

struct Analyzer<'a> {
    type_budget: crate::ir::types::TypeBudget,
    source: &'a str,
    signatures: BTreeMap<String, FunctionSignature>,
    callables: BTreeSet<String>,
    edges: BTreeMap<String, Vec<(String, Span)>>,
    current: String,
    nodes: usize,
    constant_budget: ConstantBudget,
    probe_bytes: usize,
    probe_structure: usize,
    probe_encoded: usize,
    loops: Vec<for_next::LoopAnalysis>,
    loop_state_nodes: usize,
}

impl Analyzer<'_> {
    fn error(&self, code: &'static str, message: &str, span: Span) -> Box<Diagnostic> {
        Diagnostic::at(code, message, self.source, span)
    }
    fn declare(
        &self,
        scope: &mut Scope,
        name: &str,
        ty: ValueType,
        mutable: bool,
        span: Span,
    ) -> Result<()> {
        let key = name.to_ascii_lowercase();
        if self.callables.contains(&key) || scope.bindings.contains_key(&key) {
            return Err(self.error(
                "E0201",
                "Declaration duplicates or shadows a visible name",
                span,
            ));
        }
        scope.bindings.insert(key, (ty, mutable));
        Ok(())
    }
    fn expression(&mut self, expr: &Expression, scope: &Scope) -> Result<ValueType> {
        self.expression_expected(expr, scope, None)
    }
    fn expression_expected(
        &mut self,
        expr: &Expression,
        scope: &Scope,
        expected: Option<&ValueType>,
    ) -> Result<ValueType> {
        self.nodes += 1;
        if self.nodes > 65_536 {
            return Err(self.error(
                "E0205",
                "Analysis exceeds 65536 expression nodes",
                expr.span,
            ));
        }
        Ok(match &expr.kind {
            E::List(elements) => {
                let context = match expected {
                    Some(ValueType::List(t)) => Some(t.as_ref()),
                    Some(_) => {
                        return Err(self.error(
                            "E0202",
                            "List literal requires a LIST type",
                            expr.span,
                        ));
                    }
                    None => None,
                };
                let mut element_type = context.cloned();
                for element in elements {
                    let ty = self.expression_expected(element, scope, context)?;
                    if let Some(expected) = &element_type {
                        require_type(self.source, &ty, expected, element.span)?;
                    } else {
                        element_type = Some(ty);
                    }
                }
                let ty = element_type.ok_or_else(|| {
                    self.error(
                        "E0202",
                        "Empty list requires an expected element type",
                        expr.span,
                    )
                })?;
                self.type_budget.list(&ty, self.source, expr.span)?
            }
            E::Bytes(_) => ValueType::Bytes,
            E::String(_) => ValueType::String,
            E::Integer(value) => {
                literal(self.source, value.clone())?;
                ValueType::Integer
            }
            E::Boolean(_) => ValueType::Boolean,
            E::Name(name) => scope
                .bindings
                .get(&name.to_ascii_lowercase())
                .ok_or_else(|| self.error("E0200", "Unknown name", expr.span))?
                .0
                .clone(),
            E::Group(inner) => self.expression_expected(inner, scope, expected)?,
            E::HeightCondition(inner) => {
                let ty = self.expression(inner, scope)?;
                require_type(self.source, &ty, &ValueType::Integer, inner.span)?;
                ValueType::Condition
            }
            E::Unary {
                operator, operand, ..
            } => {
                let expected = if *operator == UnaryOperator::Not {
                    ValueType::Boolean
                } else {
                    ValueType::Integer
                };
                let ty = self.expression(operand, scope)?;
                require_type(self.source, &ty, &expected, operand.span)?;
                expected
            }
            E::Binary {
                operator,
                left,
                right,
                ..
            } => {
                let lhs = self.expression(left, scope)?;
                let rhs = self.expression(right, scope)?;
                binary_type(self.source, *operator, lhs, rhs, left.span, right.span)?
            }
            E::Call { name, arguments } => {
                if let Some((_, parameters)) = crate::ir::expressions::payment_builtin(name) {
                    crate::ir::expressions::require_arity(
                        self.source,
                        arguments.len(),
                        parameters.len(),
                        expr.span,
                    )?;
                    for (argument, expected) in arguments.iter().zip(&parameters) {
                        let ty = self.expression(argument, scope)?;
                        require_type(self.source, &ty, expected, argument.span)?;
                    }
                    return Ok(ValueType::Condition);
                }
                if name.eq_ignore_ascii_case("CONS") {
                    crate::ir::expressions::require_arity(
                        self.source,
                        arguments.len(),
                        2,
                        expr.span,
                    )?;
                    let context = crate::ir::expressions::cons_element(expected);
                    let head = self.expression_expected(&arguments[0], scope, context)?;
                    if let Some(ty) = context {
                        require_type(self.source, &head, ty, arguments[0].span)?;
                    }
                    let ty = self.type_budget.list(&head, self.source, expr.span)?;
                    let tail = self.expression_expected(&arguments[1], scope, Some(&ty))?;
                    require_type(self.source, &tail, &ty, arguments[1].span)?;
                    return Ok(ty);
                }
                if let Some(construct) = crate::ir::expressions::pair_call(name) {
                    crate::ir::expressions::require_arity(
                        self.source,
                        arguments.len(),
                        if construct { 2 } else { 1 },
                        expr.span,
                    )?;
                    let mut types = Vec::new();
                    for (index, argument) in arguments.iter().enumerate() {
                        let context = if construct {
                            crate::ir::expressions::pair_component(expected, index)
                        } else {
                            None
                        };
                        types.push(self.expression_expected(argument, scope, context)?);
                    }
                    return crate::ir::expressions::pair_result(
                        self.source,
                        name,
                        &types,
                        &mut self.type_budget,
                        expr.span,
                    );
                }
                if let Some((_, arity, argument_type, result_type)) =
                    crate::ir::expressions::byte_builtin(name)
                {
                    crate::ir::expressions::require_arity(
                        self.source,
                        arguments.len(),
                        arity,
                        expr.span,
                    )?;
                    for argument in arguments {
                        let ty = self.expression(argument, scope)?;
                        require_type(self.source, &ty, &argument_type, argument.span)?;
                    }
                    return Ok(result_type);
                }
                let key = name.to_ascii_lowercase();
                let signature = self
                    .signatures
                    .get(&key)
                    .cloned()
                    .ok_or_else(|| self.error("E0200", "Unknown function", expr.span))?;
                if arguments.len() != signature.parameters.len() {
                    return Err(self.error(
                        "E0202",
                        "Function argument count does not match its signature",
                        expr.span,
                    ));
                }
                self.edges
                    .entry(self.current.clone())
                    .or_default()
                    .push((key, expr.span));
                for (argument, parameter) in arguments.iter().zip(&signature.parameters) {
                    let ty =
                        self.expression_expected(argument, scope, Some(&parameter.value_type))?;
                    require_type(self.source, &ty, &parameter.value_type, argument.span)?;
                }
                signature.result.clone()
            }
        })
    }
    fn known_boolean(&mut self, expr: &Expression, scope: &Scope) -> Option<bool> {
        let mut budget = ConstantBudget {
            nodes: 0,
            bytes: self.probe_bytes,
            structure: self.probe_structure,
            encoded: self.probe_encoded,
        };
        let result = constant(
            self.source,
            expr.clone(),
            &scope.names(),
            &scope.constants,
            &mut budget,
            None,
        );
        self.probe_bytes = budget.bytes;
        self.probe_structure = budget.structure;
        self.probe_encoded = budget.encoded;
        result
            .ok()
            .filter(|(_, ty)| *ty == ValueType::Boolean)
            .map(|(v, _)| !v.is_zero())
    }
    // A false result means no normal path reaches the end of this block.
    // Continue checking source after terminal statements for semantic errors.
    fn block(
        &mut self,
        statements: &[ParsedStatement],
        scope: &mut Scope,
        result: Option<&ValueType>,
    ) -> Result<bool> {
        let mut falls_through = true;
        for statement in statements {
            let next = match statement {
                ParsedStatement::For(statement) => {
                    self.for_statement(statement, scope, result)?;
                    // Even literal ranges may execute zero times for return analysis.
                    true
                }
                ParsedStatement::Return { expression, span } => {
                    let expected = result.ok_or_else(|| {
                        self.error("E0205", "RETURN is forbidden in contracts", *span)
                    })?;
                    let ty = self.expression_expected(expression, scope, Some(expected))?;
                    require_type(self.source, &ty, expected, expression.span)?;
                    false
                }
                ParsedStatement::Emit(emission) => {
                    if result.is_some() {
                        return Err(self.error(
                            "E0205",
                            "EMIT is forbidden in functions",
                            emission.span,
                        ));
                    }
                    let ty = self.expression(&emission.expression, scope)?;
                    require_type(self.source, &ty, &ValueType::Condition, emission.span)?;
                    true
                }
                ParsedStatement::Assert { expression, .. } => {
                    let ty = self.expression(expression, scope)?;
                    require_type(self.source, &ty, &ValueType::Boolean, expression.span)?;
                    self.known_boolean(expression, scope) != Some(false)
                }
                ParsedStatement::If(branch) => {
                    let ty = self.expression(&branch.predicate, scope)?;
                    require_type(self.source, &ty, &ValueType::Boolean, branch.predicate.span)?;
                    let yes = self.block(&branch.yes, &mut scope.clone(), result)?;
                    let no = self.block(&branch.no, &mut scope.clone(), result)?;
                    match self.known_boolean(&branch.predicate, scope) {
                        Some(true) => yes,
                        Some(false) => no,
                        None => yes || no,
                    }
                }
                ParsedStatement::Local(local) => {
                    let key = local.name.to_ascii_lowercase();
                    let context = local.annotation.as_ref().or_else(|| {
                        if matches!(local.kind, LocalUpdateKind::Assignment) {
                            scope.bindings.get(&key).map(|(ty, _)| ty)
                        } else {
                            None
                        }
                    });
                    let ty = self.expression_expected(&local.initializer, scope, context)?;
                    if let Some(annotation) = &local.annotation {
                        require_type(self.source, &ty, annotation, local.span)?;
                    }
                    match local.kind {
                        LocalUpdateKind::Assignment => {
                            let (expected, mutable) =
                                scope.bindings.get(&key).ok_or_else(|| {
                                    self.error(
                                        "E0203",
                                        "Assignment requires an existing DIM local",
                                        local.span,
                                    )
                                })?;
                            if !mutable {
                                return Err(self.error(
                                    "E0203",
                                    "Parameters and constants are immutable",
                                    local.span,
                                ));
                            }
                            require_type(self.source, &ty, expected, local.span)?;
                        }
                        LocalUpdateKind::Declaration => {
                            self.declare(scope, &local.name, ty, true, local.span)?
                        }
                        LocalUpdateKind::Constant => {
                            let value = constant(
                                self.source,
                                local.initializer.clone(),
                                &scope.names(),
                                &scope.constants,
                                &mut self.constant_budget,
                                local.annotation.as_ref(),
                            )?;
                            self.declare(scope, &local.name, ty, false, local.span)?;
                            scope.constants.insert(key, value);
                        }
                    }
                    true
                }
            };
            falls_through &= next;
        }
        Ok(falls_through)
    }
    fn visit(&self, name: &str, colors: &mut BTreeMap<String, u8>) -> Result<()> {
        colors.insert(name.to_owned(), 1);
        if let Some(edges) = self.edges.get(name) {
            for (target, span) in edges {
                match colors.get(target).copied().unwrap_or(0) {
                    1 => return Err(self.error("E0206", "Recursive function call cycle", *span)),
                    0 => self.visit(target, colors)?,
                    _ => {}
                }
            }
        }
        colors.insert(name.to_owned(), 2);
        Ok(())
    }
}

pub(crate) fn analyze(source: &str, bytes: &[u8]) -> Result<ModuleAnalysis> {
    let module = syntax::parse_module(source, bytes)?;
    analyze_module(source, &module)
}

pub(crate) fn analyze_module(
    source: &str,
    module: &syntax::ParsedModule,
) -> Result<ModuleAnalysis> {
    let mut analyzer = Analyzer {
        type_budget: module.type_budget.clone(),
        source,
        signatures: BTreeMap::new(),
        callables: BTreeSet::from([module.contract.name.to_ascii_lowercase()]),
        edges: BTreeMap::new(),
        current: module.contract.name.to_ascii_lowercase(),
        nodes: 0,
        constant_budget: ConstantBudget::default(),
        probe_bytes: 0,
        probe_structure: 0,
        probe_encoded: 0,
        loops: Vec::new(),
        loop_state_nodes: 0,
    };
    let mut functions = Vec::new();
    for function in &module.functions {
        let key = function.name.to_ascii_lowercase();
        if !analyzer.callables.insert(key.clone()) {
            return Err(analyzer.error("E0201", "Duplicate module declaration", function.span));
        }
        let signature = FunctionSignature {
            name: function.name.clone(),
            parameters: function
                .parameters
                .iter()
                .map(|p| ParameterSignature {
                    name: p.name.clone(),
                    value_type: p.value_type.clone(),
                })
                .collect(),
            result: function.result.clone(),
        };
        analyzer.signatures.insert(key, signature.clone());
        functions.push(signature);
    }
    let mut contract_scope = Scope::default();
    for input in module.contract.fixed.iter().chain(&module.contract.inputs) {
        analyzer.declare(
            &mut contract_scope,
            &input.name,
            input.value_type.clone(),
            false,
            input.span,
        )?;
    }
    analyzer.block(&module.contract.statements, &mut contract_scope, None)?;
    for function in &module.functions {
        analyzer.current = function.name.to_ascii_lowercase();
        let mut scope = Scope::default();
        for parameter in &function.parameters {
            analyzer.declare(
                &mut scope,
                &parameter.name,
                parameter.value_type.clone(),
                false,
                parameter.span,
            )?;
        }
        if analyzer.block(&function.statements, &mut scope, Some(&function.result))? {
            return Err(analyzer.error(
                "E0204",
                "Function may finish without returning a value",
                function.span,
            ));
        }
    }
    let mut colors = BTreeMap::new();
    for name in analyzer.signatures.keys() {
        if !colors.contains_key(name) {
            analyzer.visit(name, &mut colors)?;
        }
    }
    Ok(ModuleAnalysis {
        contract: module.contract.name.clone(),
        functions,
        #[cfg(test)]
        loops: analyzer.loops,
    })
}
