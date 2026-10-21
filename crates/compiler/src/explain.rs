//! Compiler-versioned debug views without filesystem access or execution.
use crate::{Result, Span, syntax};
use serde::Serialize;
use serde_json::{Value, json};

#[derive(Clone, Copy)]
pub enum Stage {
    Ast,
    Ir,
}

/// AST parses only; IR performs the same analysis/lowering as `check`.
pub fn explain(source_name: &str, source: &[u8], stage: Stage) -> Result<Value> {
    let (label, representation) = match stage {
        Stage::Ast => ("ast", ast(syntax::parse_module(source_name, source)?)),
        Stage::Ir => (
            "ir",
            serde_json::to_value(crate::check(source_name, source)?)
                .map_err(|e| crate::Diagnostic::new("E9000", e.to_string()))?,
        ),
    };
    Ok(
        json!({"stage":label,"compiler_version":crate::COMPILER_VERSION,
        "source":{"name":source_name,"sha256":crate::clvm::sha256(source)},
        "representation":representation}),
    )
}

#[derive(Serialize)]
struct Node {
    kind: &'static str,
    span: Span,
    data: Value,
}
#[derive(Default)]
struct Ast {
    nodes: Vec<Node>,
}
impl Ast {
    fn node(&mut self, kind: &'static str, span: Span, data: Value) -> usize {
        let id = self.nodes.len();
        self.nodes.push(Node { kind, span, data });
        id
    }
    fn expression(&mut self, expression: syntax::expression::Expression) -> usize {
        use syntax::expression::ExpressionKind as E;
        let span = expression.span;
        let (kind, data) = match expression.kind {
            E::Bytes(bytes) => ("Bytes", json!({"hex":hex::encode(bytes)})),
            E::String(value) => ("String", json!({"value":value})),
            E::Integer(literal) => (
                "Integer",
                json!({"spelling":literal.spelling,"radix":literal.radix}),
            ),
            E::Boolean(value) => ("Boolean", json!({"value":value})),
            E::Name(name) => ("Name", json!({"name":name})),
            E::List(items) => {
                let items: Vec<_> = items.into_iter().map(|e| self.expression(e)).collect();
                ("List", json!({"elements":items}))
            }
            E::Call { name, arguments } => {
                let arguments: Vec<_> = arguments.into_iter().map(|e| self.expression(e)).collect();
                ("Call", json!({"name":name,"arguments":arguments}))
            }
            E::HeightCondition(inner) => {
                let argument = self.expression(*inner);
                (
                    "Call",
                    json!({"name":"ASSERT_HEIGHT_ABSOLUTE","arguments":[argument]}),
                )
            }
            E::Group(inner) => {
                let inner = self.expression(*inner);
                ("Group", json!({"expression":inner}))
            }
            E::Unary {
                operator,
                operator_span,
                operand,
            } => {
                let operand = self.expression(*operand);
                (
                    "Unary",
                    json!({"operator":operator,"operator_span":operator_span,"operand":operand}),
                )
            }
            E::Binary {
                operator,
                operator_span,
                left,
                right,
            } => {
                let left = self.expression(*left);
                let right = self.expression(*right);
                (
                    "Binary",
                    json!({"operator":operator,"operator_span":operator_span,"left":left,"right":right}),
                )
            }
        };
        self.node(kind, span, data)
    }
    fn statements(&mut self, statements: Vec<syntax::ParsedStatement>) -> Vec<usize> {
        use syntax::ParsedStatement as S;
        statements.into_iter().map(|s| match s {
            S::Return {expression,span} => {
                let expression=self.expression(expression);
                self.node("Return",span,json!({"expression":expression}))
            }
            S::Assert {expression,span} => {
                let expression=self.expression(expression);
                self.node("Assert",span,json!({"expression":expression}))
            }
            S::Emit(e) => {
                let expression=self.expression(e.expression);
                self.node("Emit",e.span,json!({"expression":expression}))
            }
            S::Local(l) => {
                let initializer=self.expression(l.initializer);
                self.node("Local",l.span,json!({"update":l.kind,"name":l.name,"annotation":l.annotation,"initializer":initializer}))
            }
            S::If(b) => {
                let predicate=self.expression(b.predicate);
                let yes=self.statements(b.yes);let no=self.statements(b.no);
                self.node("If",b.span,json!({"predicate":predicate,"yes":yes,"no":no}))
            }
        }).collect()
    }
}
fn ast(module: syntax::ParsedModule) -> Value {
    let mut view = Ast::default();
    let c = module.contract;
    let body = view.statements(c.statements);
    let contract =
        json!({"name":c.name,"span":c.span,"fixed":c.fixed,"inputs":c.inputs,"statements":body});
    let functions:Vec<_>=module.functions.into_iter().map(|f| {
        let body=view.statements(f.statements);
        json!({"name":f.name,"span":f.span,"parameters":f.parameters,"result":f.result,"statements":body})
    }).collect();
    json!({"contract":contract,"functions":functions,"nodes":view.nodes})
}

/// Compile and optionally bind using the same pipeline as build. None means template-only.
pub fn explain_clvm(source_name: &str, source: &[u8], bindings: Option<&[u8]>) -> Result<Value> {
    let compiled = crate::compile_template(source_name, source)?;
    let bound = bindings.map(|json| compiled.bind(json)).transpose()?;
    Ok(json!({
        "stage":"clvm", "compiler_version":crate::COMPILER_VERSION,
        "source":{"name":source_name,"sha256":crate::clvm::sha256(source)},
        "representation":{
            "contract":compiled.contract.name,
            "fixed_parameters":compiled.contract.fixed, "inputs":compiled.contract.inputs,
            "bindings":bound.as_ref().map(|b| &b.bindings),
            "template":program_view(&compiled.template)?,
            "puzzle":bound.as_ref().map(|b| program_view(&b.puzzle)).transpose()?
        }
    }))
}

fn program_view(bytes: &[u8]) -> Result<Value> {
    use clvmr::{Allocator, SExp, serde::node_from_bytes};
    let mut allocator = Allocator::new();
    let root = node_from_bytes(&mut allocator, bytes)
        .map_err(|e| crate::Diagnostic::new("E9000", e.to_string()))?;
    // Iterative traversal and flat references keep deeply nested CLVM printable.
    let mut pending = vec![(root, 0)];
    let mut nodes = vec![Value::Null];
    while let Some((node, index)) = pending.pop() {
        nodes[index] = match allocator.sexp(node) {
            SExp::Atom => json!({"atom":hex::encode(allocator.atom(node).as_ref())}),
            SExp::Pair(first, rest) => {
                let left = nodes.len();
                nodes.extend([Value::Null, Value::Null]);
                pending.push((rest, left + 1));
                pending.push((first, left));
                json!({"pair":[left,left + 1]})
            }
        };
    }
    Ok(
        json!({"hex":hex::encode(bytes),"program_sha256":crate::clvm::sha256(bytes),
        "tree_hash":crate::clvm::tree_hash(bytes)?,"root":0,"nodes":nodes}),
    )
}
