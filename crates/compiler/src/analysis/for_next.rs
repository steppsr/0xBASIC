//! Private semantic prototype; no loop-containing AST can reach code generation.
use super::{Analyzer, ModuleAnalysis, Scope};
use crate::syntax::{
    LocalUpdateKind, ParsedStatement, expression::Expression, for_next::ParsedFor,
};
use crate::{Diagnostic, ParameterSignature, Result, Span, ValueType};
use std::collections::BTreeSet;

/// Validated headers in source order and conservative state/effect metadata.
/// This is not executable IR: it does not implement iteration or continuations.
#[derive(Debug, serde::Serialize)]
pub(crate) struct LoopAnalysis {
    pub owner: String,
    pub counter: String,
    pub span: Span,
    pub header_expressions: Vec<Expression>,
    pub carried_locals: Vec<ParameterSignature>,
    pub emits_conditions: bool,
    pub may_return: bool,
}

// Bound type copies in the new metadata, independently of expression/type work.
fn charge_state_type(nodes: &mut usize, ty: &ValueType, source: &str, span: Span) -> Result<()> {
    if *nodes >= 65_536 {
        return Err(Diagnostic::at(
            "E0205",
            "Loop state metadata exceeds 65536 type nodes per module",
            source,
            span,
        ));
    }
    *nodes += 1;
    match ty {
        ValueType::List(element) => charge_state_type(nodes, element, source, span),
        ValueType::Pair(first, rest) => {
            charge_state_type(nodes, first, source, span)?;
            charge_state_type(nodes, rest, source, span)
        }
        _ => Ok(()),
    }
}

#[derive(Default)]
struct Effects {
    assigned: BTreeSet<String>,
    emits: bool,
    returns: bool,
}
impl Effects {
    fn visit(&mut self, statements: &[ParsedStatement]) {
        for statement in statements {
            match statement {
                ParsedStatement::Local(local)
                    if matches!(local.kind, LocalUpdateKind::Assignment) =>
                {
                    self.assigned.insert(local.name.to_ascii_lowercase());
                }
                ParsedStatement::If(branch) => {
                    self.visit(&branch.yes);
                    self.visit(&branch.no);
                }
                ParsedStatement::For(statement) => self.visit(&statement.body),
                ParsedStatement::Emit(_) => self.emits = true,
                ParsedStatement::Return { .. } => self.returns = true,
                _ => {}
            }
        }
    }
}

impl Analyzer<'_> {
    pub(super) fn for_statement(
        &mut self,
        statement: &ParsedFor,
        scope: &Scope,
        result: Option<&ValueType>,
    ) -> Result<()> {
        // The new counter is absent from header scope. Check in source order,
        // but never evaluate values or reject a literal zero step here.
        let headers = [&statement.start, &statement.end]
            .into_iter()
            .chain(statement.step.iter());
        for header in headers.clone() {
            let actual = self.expression(header, scope)?;
            super::require_type(self.source, &actual, &ValueType::Integer, header.span)?;
        }
        let mut body_scope = scope.clone();
        self.declare(
            &mut body_scope,
            &statement.counter,
            ValueType::Integer,
            false,
            statement.counter_span,
        )?;
        // A loop body has a fresh lexical scope. Outer assignment types stay
        // invariant; body-local declarations must not escape even for literals.
        self.block(&statement.body, &mut body_scope, result)?;

        let mut effects = Effects::default();
        effects.visit(&statement.body);
        let mut carried_locals = Vec::new();
        charge_state_type(
            &mut self.loop_state_nodes,
            &ValueType::Integer,
            self.source,
            statement.counter_span,
        )?;
        for name in effects.assigned {
            if let Some((ty, true)) = scope.bindings.get(&name) {
                charge_state_type(&mut self.loop_state_nodes, ty, self.source, statement.span)?;
                carried_locals.push(ParameterSignature {
                    name,
                    value_type: ty.clone(),
                });
            }
        }
        self.loops.push(LoopAnalysis {
            owner: self.current.clone(),
            counter: statement.counter.to_ascii_lowercase(),
            span: statement.span,
            header_expressions: headers.cloned().collect(),
            carried_locals,
            emits_conditions: effects.emits,
            may_return: effects.returns,
        });
        Ok(())
    }
}

fn analyze(source: &str) -> Result<ModuleAnalysis> {
    let parsed = crate::syntax::parse_for_next("loops.bas", source.as_bytes())?;
    super::analyze_module("loops.bas", &parsed)
}
fn contract(body: &str) -> String {
    format!("CONTRACT Demo()\n{body}\nEND CONTRACT\n")
}
fn failure(source: &str, code: &str) -> Box<Diagnostic> {
    let error = analyze(source).unwrap_err();
    assert_eq!(error.code, code, "{source}\n{error}");
    assert_eq!(error.source.as_deref(), Some("loops.bas"));
    assert!(error.span.is_some());
    error
}
fn function(body: &str) -> String {
    format!(
        "FUNCTION Helper(value AS INTEGER) AS INTEGER\n{body}\nEND FUNCTION\n{}",
        contract("")
    )
}

#[test]
fn for_next_headers_require_integer_in_source_order_without_evaluation() {
    for header in [
        "TRUE TO 3",
        "1 TO 0x01",
        "1 TO 3 STEP FALSE",
        "AS_AMOUNT(1) TO 3",
    ] {
        failure(&contract(&format!("FOR i = {header}\nNEXT i")), "E0202");
    }
    let source = contract("FOR i = TRUE TO missing STEP unknown\nNEXT i");
    let error = failure(&source, "E0202");
    let span = error.span.unwrap();
    assert_eq!(&source[span.start_byte..span.end_byte], "TRUE");
    for header in ["1 TO 0 STEP 0", "1 TO U32BE(-1)"] {
        if header.contains("U32BE") {
            // Wrong result type, independently of runtime range validation.
            failure(&contract(&format!("FOR i = {header}\nNEXT i")), "E0202");
        } else {
            analyze(&contract(&format!("FOR i = {header}\nNEXT i"))).unwrap();
        }
    }
    // This conversion fails if executed, but its result type is INTEGER.
    analyze(&contract("FOR i = INT_FROM_BYTES(0x00) TO 3\nNEXT i")).unwrap();
    let source = contract("FOR i = 1 TO 3 STEP -2\nNEXT i");
    let analysis = analyze(&source).unwrap();
    let headers = &analysis.loops[0].header_expressions;
    assert_eq!(
        headers
            .iter()
            .map(|h| &source[h.span.start_byte..h.span.end_byte])
            .collect::<Vec<_>>(),
        ["1", "3", "-2"]
    );
    assert_eq!(
        analyze(&contract("FOR i = 1 TO 3\nNEXT i")).unwrap().loops[0]
            .header_expressions
            .len(),
        2
    );
}

#[test]
fn for_next_counter_scope_rejects_shadowing_and_escape() {
    for body in [
        "FOR i = i TO 1\nNEXT i",
        "FOR i = 1 TO i\nNEXT i",
        "FOR i = 1 TO 2 STEP i\nNEXT i",
        "FOR i = 1 TO 2\nNEXT i\nASSERT i = 3",
        "FOR i = 1 TO 2\nDIM local = i\nNEXT i\nASSERT local = 1",
    ] {
        failure(&contract(body), "E0200");
    }
    for body in [
        "DIM i = 0\nFOR I = 1 TO 2\nNEXT i",
        "CONST i = 0\nFOR i = 1 TO 2\nNEXT i",
        "FOR i = 1 TO 2\nDIM I = 3\nNEXT i",
        "FOR i = 1 TO 2\nFOR I = 1 TO 2\nNEXT i\nNEXT i",
        "FOR demo = 1 TO 2\nNEXT demo",
    ] {
        failure(&contract(body), "E0201");
    }
    failure(
        "CONTRACT Demo(i AS INTEGER)\nFOR i = 1 TO 2\nNEXT i\nEND CONTRACT",
        "E0201",
    );
    failure(
        "CONTRACT Demo()\nSOLUTION i AS INTEGER\nFOR i = 1 TO 2\nNEXT i\nEND CONTRACT",
        "E0201",
    );
    failure(
        &function("FOR value = 1 TO 2\nNEXT value\nRETURN 0"),
        "E0201",
    );
    failure(
        &function("FOR Helper = 1 TO 2\nNEXT Helper\nRETURN 0"),
        "E0201",
    );
    analyze(&contract(
        "FOR i = 1 TO 2\nNEXT i\nFOR I = 3 TO 4\nNEXT i\nDIM i = 9",
    ))
    .unwrap();
}

#[test]
fn for_next_immutable_counter_and_constant_rules_remain_enforced() {
    failure(&contract("FOR i = 1 TO 2\ni = 8\nNEXT i"), "E0203");
    failure(
        &contract("CONST value = 0\nFOR i = 1 TO 2\nvalue = i\nNEXT i"),
        "E0203",
    );
    failure(
        &function("FOR i = 1 TO 2\nvalue = i\nNEXT i\nRETURN 0"),
        "E0203",
    );
    assert!(analyze(&contract("FOR i = 1 TO 2\nCONST cached = i\nNEXT i")).is_err());
    analyze(&contract(
        "CONST stop = 4\nFOR i = 1 TO stop\nCONST cached = stop\nASSERT i <= cached\nNEXT i",
    ))
    .unwrap();
}

#[test]
fn for_next_carried_state_preserves_all_supported_types_and_excludes_body_locals() {
    let source = "CONTRACT Demo(key AS PUBLICKEY, hash AS PUZZLEHASH)\nDIM number = 0\nDIM flag = FALSE\nDIM byteValue = 0x00\nDIM text = \"x\"\nDIM amountValue = AS_AMOUNT(0)\nDIM recipient = hash\nDIM owner = key\nDIM values AS LIST OF INTEGER = []\nDIM pairValue = PAIR(0, FALSE)\nDIM conditionValue = ASSERT_HEIGHT_ABSOLUTE(0)\nDIM unchanged = 0\nFOR i = 1 TO 2\nDIM temporary = i\nnumber = temporary\nflag = TRUE\nbyteValue = 0x01\ntext = \"y\"\namountValue = AS_AMOUNT(i)\nrecipient = hash\nowner = key\nvalues = CONS(i, values)\npairValue = PAIR(i, flag)\nconditionValue = ASSERT_HEIGHT_ABSOLUTE(i)\nNEXT i\nEND CONTRACT";
    let analysis = analyze(source).unwrap();
    let plan = &analysis.loops[0];
    assert_eq!(plan.owner, "demo");
    assert_eq!(plan.counter, "i");
    assert_eq!(
        plan.carried_locals
            .iter()
            .map(|p| p.name.as_str())
            .collect::<Vec<_>>(),
        [
            "amountvalue",
            "bytevalue",
            "conditionvalue",
            "flag",
            "number",
            "owner",
            "pairvalue",
            "recipient",
            "text",
            "values"
        ]
    );
    assert_eq!(plan.carried_locals[0].value_type, ValueType::Amount);
    assert_eq!(
        plan.carried_locals[6].value_type,
        ValueType::Pair(Box::new(ValueType::Integer), Box::new(ValueType::Boolean))
    );
    assert_eq!(
        plan.carried_locals[9].value_type,
        ValueType::List(Box::new(ValueType::Integer))
    );
    assert!(!plan.emits_conditions && !plan.may_return);
    assert!(source[plan.span.start_byte..plan.span.end_byte].starts_with("FOR i"));
    failure(
        &contract("DIM value = 1\nFOR i = 1 TO 0\nvalue = TRUE\nNEXT i"),
        "E0202",
    );
}

#[test]
fn for_next_nested_and_conditional_updates_record_only_visible_outer_locals() {
    let source = contract(
        "DIM finish = 3\nDIM stride = 1\nDIM total = 0\nFOR i = 1 TO finish STEP stride\nDIM temporary = i\nFOR j = i TO finish\nIF j = 1 THEN\ntotal = total + temporary\nELSE\nstride = 2\nEND IF\ntemporary = j\nEMIT ASSERT_HEIGHT_ABSOLUTE(j)\nNEXT j\nfinish = 0\nNEXT i",
    );
    let analysis = analyze(&source).unwrap();
    assert_eq!(analysis.loops.len(), 2);
    let inner = &analysis.loops[0];
    let outer = &analysis.loops[1];
    assert_eq!(
        inner
            .carried_locals
            .iter()
            .map(|p| p.name.as_str())
            .collect::<Vec<_>>(),
        ["stride", "temporary", "total"]
    );
    assert_eq!(
        outer
            .carried_locals
            .iter()
            .map(|p| p.name.as_str())
            .collect::<Vec<_>>(),
        ["finish", "stride", "total"]
    );
    assert!(inner.emits_conditions && outer.emits_conditions);
    assert_eq!(
        outer
            .header_expressions
            .iter()
            .map(|e| &source[e.span.start_byte..e.span.end_byte])
            .collect::<Vec<_>>(),
        ["1", "finish", "stride"]
    );
    // Header metadata retains expressions, not folded values of mutable locals.
    assert!(
        matches!(&outer.header_expressions[1].kind, crate::syntax::expression::ExpressionKind::Name(name) if name == "finish")
    );
}

#[test]
fn for_next_returns_are_typed_and_loops_never_prove_definite_return() {
    for header in ["1 TO 1", "1 TO 0", "1 TO 2 STEP 0"] {
        failure(
            &function(&format!("FOR i = {header}\nRETURN i\nNEXT i")),
            "E0204",
        );
    }
    let source = function(
        "FOR i = 1 TO value\nFOR j = 1 TO i\nIF j > 0 THEN\nRETURN j\nEND IF\nNEXT j\nNEXT i\nRETURN 0",
    );
    let analysis = analyze(&source).unwrap();
    assert!(
        analysis
            .loops
            .iter()
            .all(|l| l.may_return && l.owner == "helper")
    );
    failure(
        &function("FOR i = 1 TO 2\nRETURN FALSE\nNEXT i\nRETURN 0"),
        "E0202",
    );
    failure(&contract("FOR i = 1 TO 0\nRETURN i\nNEXT i"), "E0205");
    failure(
        &function("FOR i = 1 TO 0\nEMIT ASSERT_HEIGHT_ABSOLUTE(i)\nNEXT i\nRETURN 0"),
        "E0205",
    );
}

#[test]
fn for_next_checks_unreachable_bodies_and_keeps_function_cycle_detection() {
    failure(
        &function("RETURN 0\nFOR i = 1 TO 0\nASSERT missing\nNEXT i"),
        "E0200",
    );
    failure(
        &contract("IF FALSE THEN\nFOR i = TRUE TO 0\nNEXT i\nEND IF"),
        "E0202",
    );
    failure(
        &function("FOR i = Helper(value) TO 0\nNEXT i\nRETURN 0"),
        "E0206",
    );
    failure(
        &function("RETURN 0\nFOR i = 1 TO 0\nDIM result = Helper(value)\nNEXT i"),
        "E0206",
    );
    let source = "FUNCTION Bound() AS INTEGER\nRETURN 2\nEND FUNCTION\nCONTRACT Demo()\nFOR i = 1 TO Bound()\nNEXT i\nEND CONTRACT";
    analyze(source).unwrap();
}

#[test]
fn for_next_backend_rejects_valid_and_unreachable_loop_programs() {
    for source in [
        contract("FOR i = 1 TO 0\nNEXT i"),
        contract("IF FALSE THEN\nFOR i = 1 TO 0\nNEXT i\nEND IF"),
        function("RETURN 0\nFOR i = 1 TO 2\nNEXT i"),
    ] {
        analyze(&source).unwrap();
        let parsed = crate::syntax::parse_for_next("loops.bas", source.as_bytes()).unwrap();
        let error = crate::ir::lower_module("loops.bas", parsed).unwrap_err();
        assert_eq!(error.code, "E0205");
        assert_eq!(error.message, "FOR/NEXT lowering is not implemented");
    }
}

#[test]
fn for_next_state_metadata_budget_checks_exact_boundary_before_type_copy() {
    let span = Span {
        start_byte: 0,
        end_byte: 1,
        line: 1,
        column: 1,
    };
    let ty = ValueType::Pair(
        Box::new(ValueType::Integer),
        Box::new(ValueType::List(Box::new(ValueType::Boolean))),
    );
    let mut nodes = 65_532;
    charge_state_type(&mut nodes, &ty, "budget.bas", span).unwrap();
    assert_eq!(nodes, 65_536);
    assert_eq!(
        charge_state_type(&mut nodes, &ValueType::Integer, "budget.bas", span)
            .unwrap_err()
            .code,
        "E0205"
    );
    // Module integration: each loop carries the same 1023-node pair type.
    let mut ty = "INTEGER".to_owned();
    let mut value = "0".to_owned();
    for _ in 0..9 {
        ty = format!("PAIR OF ({ty}, {ty})");
        value = format!("PAIR({value}, {value})");
    }
    let loops = "FOR i = 1 TO 0\nstate = state\nNEXT i\n";
    let source = |count| {
        contract(&format!(
            "DIM state AS {ty} = {value}\n{}",
            loops.repeat(count)
        ))
    };
    analyze(&source(64)).unwrap();
    failure(&source(65), "E0205");
}
