//! Expression syntax; lowering enforces the currently implemented types/operators.
use super::{IntegerLiteral, Kind, Parser};
use crate::{Diagnostic, Result, Span};
use serde::Serialize;

// Bound both parser recursion and resulting tree depth (including flat chains).
pub(crate) const MAX_EXPRESSION_DEPTH: usize = 64;
const MAX_EXPRESSION_NODES: usize = 1024;

#[derive(Debug, Clone, Serialize)]
pub(crate) struct Expression {
    pub kind: ExpressionKind,
    pub span: Span,
    depth: usize,
}

#[derive(Debug, Clone, Serialize)]
pub(crate) enum ExpressionKind {
    Bytes(Vec<u8>),
    String(String),
    List(Vec<Expression>),
    Call {
        name: String,
        arguments: Vec<Expression>,
    },
    HeightCondition(Box<Expression>),
    Integer(IntegerLiteral),
    Boolean(bool),
    Name(String),
    Unary {
        operator: UnaryOperator,
        operator_span: Span,
        operand: Box<Expression>,
    },
    Binary {
        operator: BinaryOperator,
        operator_span: Span,
        left: Box<Expression>,
        right: Box<Expression>,
    },
    Group(Box<Expression>),
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize)]
pub(crate) enum UnaryOperator {
    Plus,
    Minus,
    Not,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, Serialize)]
pub(crate) enum BinaryOperator {
    Or,
    And,
    Equal,
    NotEqual,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Add,
    Subtract,
    Multiply,
}

impl Parser<'_> {
    pub(super) fn expression(&mut self) -> Result<Expression> {
        self.expression_at(1, 0, &mut 0)
    }

    fn expression_limit(&self) -> Box<Diagnostic> {
        self.error(
            "E0205",
            "Expression exceeds the 64-level or 1024-node parser limit",
        )
    }

    fn expression_node(
        &self,
        kind: ExpressionKind,
        span: Span,
        depth: usize,
        nodes: &mut usize,
    ) -> Result<Expression> {
        if depth > MAX_EXPRESSION_DEPTH || *nodes >= MAX_EXPRESSION_NODES {
            return Err(self.expression_limit());
        }
        *nodes += 1;
        Ok(Expression { kind, span, depth })
    }

    fn expression_at(
        &mut self,
        minimum: u8,
        recursion: usize,
        nodes: &mut usize,
    ) -> Result<Expression> {
        if recursion >= MAX_EXPRESSION_DEPTH {
            return Err(self.expression_limit());
        }
        let start = self.current().span;
        let mut left = match &self.current().kind {
            Kind::Symbol('[') => {
                self.pos += 1;
                let mut elements = Vec::new();
                if self.current().kind != Kind::Symbol(']') {
                    loop {
                        elements.push(self.expression_at(1, recursion + 1, nodes)?);
                        if self.current().kind != Kind::Symbol(',') {
                            break;
                        }
                        self.pos += 1;
                    }
                }
                let span = Span {
                    end_byte: self.current().span.end_byte,
                    ..start
                };
                self.expect(Kind::Symbol(']'))?;
                let depth = elements.iter().map(|e| e.depth).max().unwrap_or(0) + 1;
                self.expression_node(ExpressionKind::List(elements), span, depth, nodes)?
            }
            Kind::Literal => {
                let text =
                    self.source[start.start_byte + 1..start.end_byte - 1].replace("\"\"", "\"");
                self.pos += 1;
                self.expression_node(ExpressionKind::String(text), start, 1, nodes)?
            }
            Kind::Bytes => {
                let bytes = hex::decode(&self.source[start.start_byte + 2..start.end_byte])
                    .map_err(|_| self.error("E0002", "Invalid byte literal"))?;
                self.pos += 1;
                self.expression_node(ExpressionKind::Bytes(bytes), start, 1, nodes)?
            }
            Kind::Integer(radix) => {
                let literal = IntegerLiteral {
                    spelling: self.source[start.start_byte..start.end_byte].to_owned(),
                    radix: *radix,
                    span: start,
                };
                self.pos += 1;
                self.expression_node(ExpressionKind::Integer(literal), start, 1, nodes)?
            }
            Kind::Word(word) if word == "TRUE" || word == "FALSE" => {
                let value = word == "TRUE";
                self.pos += 1;
                self.expression_node(ExpressionKind::Boolean(value), start, 1, nodes)?
            }
            Kind::Symbol('+' | '-') => {
                let operator = if self.current().kind == Kind::Symbol('+') {
                    UnaryOperator::Plus
                } else {
                    UnaryOperator::Minus
                };
                self.pos += 1;
                let operand = self.expression_at(7, recursion + 1, nodes)?;
                let depth = operand.depth + 1;
                let span = Span {
                    end_byte: operand.span.end_byte,
                    ..start
                };
                self.expression_node(
                    ExpressionKind::Unary {
                        operator,
                        operator_span: start,
                        operand: Box::new(operand),
                    },
                    span,
                    depth,
                    nodes,
                )?
            }
            Kind::Word(word) if word == "NOT" && minimum <= 3 => {
                self.pos += 1;
                let operand = self.expression_at(3, recursion + 1, nodes)?;
                let depth = operand.depth + 1;
                let span = Span {
                    end_byte: operand.span.end_byte,
                    ..start
                };
                self.expression_node(
                    ExpressionKind::Unary {
                        operator: UnaryOperator::Not,
                        operator_span: start,
                        operand: Box::new(operand),
                    },
                    span,
                    depth,
                    nodes,
                )?
            }
            Kind::Symbol('(') => {
                self.pos += 1;
                let inner = self.expression_at(1, recursion + 1, nodes)?;
                let span = Span {
                    end_byte: self.current().span.end_byte,
                    ..start
                };
                self.expect(Kind::Symbol(')'))?;
                let depth = inner.depth + 1;
                self.expression_node(ExpressionKind::Group(Box::new(inner)), span, depth, nodes)?
            }
            Kind::Word(word) if matches!(word.as_str(), "AND" | "OR" | "NOT") => {
                return Err(self.error("E0100", "Expected an expression operand"));
            }
            Kind::Word(word) if word == "ASSERT_HEIGHT_ABSOLUTE" => {
                self.pos += 1;
                self.expect(Kind::Symbol('('))?;
                let argument = self.expression_at(1, recursion + 1, nodes)?;
                let span = Span {
                    end_byte: self.current().span.end_byte,
                    ..start
                };
                self.expect(Kind::Symbol(')'))?;
                let depth = argument.depth + 1;
                self.expression_node(
                    ExpressionKind::HeightCondition(Box::new(argument)),
                    span,
                    depth,
                    nodes,
                )?
            }
            Kind::Word(word)
                if !super::is_reserved(word)
                    || matches!(
                        word.as_str(),
                        "CONCAT"
                            | "BYTE_LENGTH"
                            | "SHA256"
                            | "INT_BYTES"
                            | "INT_FROM_BYTES"
                            | "U32BE"
                            | "U64BE"
                            | "UTF8"
                            | "STRING_FROM_UTF8"
                            | "AS_AMOUNT"
                            | "AMOUNT_VALUE"
                            | "AS_PUZZLEHASH"
                            | "HASH_BYTES"
                            | "AS_PUBLICKEY"
                            | "KEY_BYTES"
                            | "PAIR"
                            | "FIRST"
                            | "REST"
                            | "CONS"
                            | "LIST_LENGTH"
                    ) =>
            {
                let name = self.source[start.start_byte..start.end_byte].to_owned();
                self.pos += 1;
                if self.current().kind == Kind::Symbol('(') {
                    if !self.functions {
                        return Err(self.unsupported());
                    }
                    self.pos += 1;
                    let mut arguments = Vec::new();
                    if self.current().kind != Kind::Symbol(')') {
                        loop {
                            if arguments.len() >= 32 {
                                return Err(
                                    self.error("E0205", "Calls support at most 32 arguments")
                                );
                            }
                            arguments.push(self.expression_at(1, recursion + 1, nodes)?);
                            if self.current().kind != Kind::Symbol(',') {
                                break;
                            }
                            self.pos += 1;
                        }
                    }
                    let span = Span {
                        end_byte: self.current().span.end_byte,
                        ..start
                    };
                    self.expect(Kind::Symbol(')'))?;
                    let depth = arguments.iter().map(|a| a.depth).max().unwrap_or(0) + 1;
                    self.expression_node(
                        ExpressionKind::Call { name, arguments },
                        span,
                        depth,
                        nodes,
                    )?
                } else {
                    if super::is_reserved(&name.to_ascii_uppercase()) {
                        return Err(self.error("E0100", "Built-in calls require parentheses"));
                    }
                    self.expression_node(ExpressionKind::Name(name), start, 1, nodes)?
                }
            }
            Kind::Word(_) => return Err(self.unsupported()),
            _ => return Err(self.error("E0100", "Expected an expression operand")),
        };
        let mut compared = false;
        while let Some((operator, precedence)) = self.binary_operator() {
            if precedence < minimum {
                break;
            }
            if precedence == 4 && compared {
                return Err(self.error("E0100", "Chained comparisons require explicit parentheses"));
            }
            compared |= precedence == 4;
            let operator_span = self.current().span;
            self.pos += 1;
            let right = self.expression_at(precedence + 1, recursion + 1, nodes)?;
            let span = Span {
                end_byte: right.span.end_byte,
                ..left.span
            };
            let depth = left.depth.max(right.depth) + 1;
            left = self.expression_node(
                ExpressionKind::Binary {
                    operator,
                    operator_span,
                    left: Box::new(left),
                    right: Box::new(right),
                },
                span,
                depth,
                nodes,
            )?;
        }
        Ok(left)
    }

    fn binary_operator(&self) -> Option<(BinaryOperator, u8)> {
        use BinaryOperator::*;
        Some(match &self.current().kind {
            Kind::Word(word) if word == "OR" => (Or, 1),
            Kind::Word(word) if word == "AND" => (And, 2),
            Kind::Symbol('=') => (Equal, 4),
            Kind::Compound("<>") => (NotEqual, 4),
            Kind::Symbol('<') => (Less, 4),
            Kind::Compound("<=") => (LessEqual, 4),
            Kind::Symbol('>') => (Greater, 4),
            Kind::Compound(">=") => (GreaterEqual, 4),
            Kind::Symbol('+') => (Add, 5),
            Kind::Symbol('-') => (Subtract, 5),
            Kind::Symbol('*') => (Multiply, 6),
            _ => return None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(text: &str) -> Result<Expression> {
        let source = format!("CONTRACT Demo()\n EMIT {text}\nEND CONTRACT\n");
        let super::super::ParsedStatement::Emit(emission) =
            crate::syntax::parse("expression.bas", source.as_bytes())?
                .statements
                .remove(0)
        else {
            panic!("Expected emission");
        };
        Ok(emission.expression)
    }

    fn shape(expr: &Expression) -> String {
        match &expr.kind {
            ExpressionKind::Call { name, .. } => format!("(call {name})"),
            ExpressionKind::HeightCondition(inner) => format!("(height {})", shape(inner)),
            ExpressionKind::Integer(value) => value.spelling.clone(),
            ExpressionKind::Boolean(value) => value.to_string(),
            ExpressionKind::List(elements) => format!(
                "[{}]",
                elements.iter().map(shape).collect::<Vec<_>>().join(",")
            ),
            ExpressionKind::String(text) => format!("{text:?}"),
            ExpressionKind::Bytes(bytes) => format!("0x{}", hex::encode(bytes)),
            ExpressionKind::Name(name) => name.clone(),
            ExpressionKind::Group(inner) => format!("(group {})", shape(inner)),
            ExpressionKind::Unary {
                operator, operand, ..
            } => format!("({operator:?} {})", shape(operand)),
            ExpressionKind::Binary {
                operator,
                left,
                right,
                ..
            } => format!("({operator:?} {} {})", shape(left), shape(right)),
        }
    }

    #[test]
    fn arithmetic_precedence_associativity_and_grouping() {
        for (text, expected) in [
            ("2 + 3 * 4", "(Add 2 (Multiply 3 4))"),
            ("20 - 5 - 2", "(Subtract (Subtract 20 5) 2)"),
            ("2 * 3 * 4", "(Multiply (Multiply 2 3) 4)"),
            (
                "-(2 + 3) * +4",
                "(Multiply (Minus (group (Add 2 3))) (Plus 4))",
            ),
            ("--+1", "(Minus (Minus (Plus 1)))"),
            (
                "&h00FF + 18446744073709551616",
                "(Add &h00FF 18446744073709551616)",
            ),
        ] {
            assert_eq!(shape(&parse(text).unwrap()), expected, "{text}");
        }
    }

    #[test]
    fn not_comparison_and_boolean_precedence_match_the_grammar() {
        for (text, expected) in [
            (
                "NOT 2 + 3 * 4 <> 14 AND TRUE",
                "(And (Not (NotEqual (Add 2 (Multiply 3 4)) 14)) true)",
            ),
            (
                "TRUE OR FALSE AND NOT FALSE",
                "(Or true (And false (Not false)))",
            ),
            ("NOT NOT 1 = 1", "(Not (Not (Equal 1 1)))"),
            ("(1 < 2) = TRUE", "(Equal (group (Less 1 2)) true)"),
            ("1 < (2 = 3)", "(Less 1 (group (Equal 2 3)))"),
            (
                "1 < 2 AND 3 < 4 OR 5 > 6",
                "(Or (And (Less 1 2) (Less 3 4)) (Greater 5 6))",
            ),
        ] {
            assert_eq!(shape(&parse(text).unwrap()), expected, "{text}");
        }
        // Syntactically valid does not imply well typed; typing is a later slice.
    }

    #[test]
    fn all_comparisons_require_contiguous_compound_tokens() {
        for (text, expected) in [
            ("1=2", "(Equal 1 2)"),
            ("1<>2", "(NotEqual 1 2)"),
            ("1<2", "(Less 1 2)"),
            ("1<=2", "(LessEqual 1 2)"),
            ("1>2", "(Greater 1 2)"),
            ("1>=2", "(GreaterEqual 1 2)"),
        ] {
            assert_eq!(shape(&parse(text).unwrap()), expected);
        }
        for text in [
            "1 < = 2",
            "1 > = 2",
            "1 < > 2",
            "1 <\n= 2",
            "1 < ' split\n> 2",
        ] {
            assert_eq!(parse(text).unwrap_err().code, "E0100", "{text}");
        }
    }

    #[test]
    fn malformed_operands_and_chained_comparisons_are_rejected() {
        for text in [
            "",
            "()",
            "1 +",
            "* 1",
            "NOT",
            "1 AND",
            "1 2",
            "1 < 2 < 3",
            "1 = 2 <> 3",
            "1 >= 2 <= 3",
            "1 + NOT TRUE",
            "-NOT TRUE",
            "TRUE = NOT FALSE",
        ] {
            let error = parse(text).unwrap_err();
            assert_eq!(error.code, "E0100", "{text}");
            assert_eq!(error.source.as_deref(), Some("expression.bas"));
            assert!(error.span.is_some());
        }
    }

    #[test]
    fn spans_refer_to_original_bom_crlf_source() {
        let source = "\u{feff}CONTRACT Demo()\r\n EMIT ASSERT_HEIGHT_ABSOLUTE((\r\n &h0A ' keep comment\r\n <= 20))\r\nEND CONTRACT\r\n";
        let parsed = crate::syntax::parse("spans.bas", source.as_bytes()).unwrap();
        let super::super::ParsedStatement::Emit(emission) = &parsed.statements[0] else {
            panic!("Expected emission");
        };
        let ExpressionKind::HeightCondition(expression) = &emission.expression.kind else {
            panic!("Expected constructor");
        };
        let ExpressionKind::Group(inner) = &expression.kind else {
            panic!("Expected group");
        };
        let ExpressionKind::Binary {
            operator_span,
            left,
            right,
            ..
        } = &inner.kind
        else {
            panic!("Expected comparison");
        };
        assert_eq!(
            &source[expression.span.start_byte..expression.span.end_byte],
            "(\r\n &h0A ' keep comment\r\n <= 20)"
        );
        assert_eq!(
            &source[operator_span.start_byte..operator_span.end_byte],
            "<="
        );
        assert_eq!((operator_span.line, operator_span.column), (4, 2));
        assert_eq!(&source[left.span.start_byte..left.span.end_byte], "&h0A");
        assert_eq!(&source[right.span.start_byte..right.span.end_byte], "20");
    }

    #[test]
    fn nested_and_flat_expressions_have_bounded_depth() {
        for depth in [1, 16, 63] {
            assert!(parse(&format!("{}1{}", "(".repeat(depth), ")".repeat(depth))).is_ok());
        }
        for text in [
            format!("{}1{}", "(".repeat(64), ")".repeat(64)),
            format!("{}1", "-".repeat(64)),
            vec!["1"; 65].join(" + "),
            format!("{}TRUE", "NOT ".repeat(64)),
        ] {
            assert_eq!(parse(&text).unwrap_err().code, "E0205");
        }
        assert!(parse(&vec!["1"; 64].join(" + ")).is_ok());
    }

    fn balanced(level: usize) -> String {
        if level == 0 {
            "1".into()
        } else {
            let child = balanced(level - 1);
            format!("({child}+{child})")
        }
    }

    #[test]
    fn shallow_but_wide_expressions_have_a_node_budget() {
        assert!(parse(&balanced(8)).is_ok());
        let error = parse(&balanced(9)).unwrap_err();
        assert_eq!(error.code, "E0205");
        assert!(error.message.contains("1024-node"));
    }
}
