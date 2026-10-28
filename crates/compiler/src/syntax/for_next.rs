//! Counted-loop syntax, spans and structural limits.
use super::{Kind, ParsedStatement, Parser, StatementCounts, expression::Expression};
use crate::{Diagnostic, Result, Span};

#[derive(Debug)]
pub struct ParsedFor {
    pub counter: String,
    pub counter_span: Span,
    pub for_span: Span,
    pub to_span: Span,
    pub step_span: Option<Span>,
    pub header_span: Span,
    pub next_span: Span,
    pub next_counter_span: Span,
    pub span: Span,
    pub start: Expression,
    pub end: Expression,
    // None preserves omitted syntax; semantic defaulting to 1 comes later.
    pub step: Option<Expression>,
    pub body: Vec<ParsedStatement>,
}

impl Parser<'_> {
    pub(super) fn for_statement(
        &mut self,
        counts: &mut StatementCounts,
        depth: usize,
    ) -> Result<ParsedFor> {
        if depth >= 32 || counts.loops >= 256 {
            return Err(self.error(
                "E0205",
                "FOR bodies require block depth at most 32 and at most 256 loops per body",
            ));
        }
        counts.loops += 1;
        let for_span = self.current().span;
        self.expect_word("FOR")?;
        let (counter, counter_span) = self.identifier()?;
        self.expect(Kind::Symbol('='))?;
        let start = self.expression()?;
        let to_span = self.current().span;
        self.expect_word("TO")?;
        let end = self.expression()?;
        let (step_span, step) = if self.word("STEP") {
            let span = self.current().span;
            self.pos += 1;
            (Some(span), Some(self.expression()?))
        } else {
            (None, None)
        };
        let header_span = Span {
            end_byte: step.as_ref().map_or(end.span.end_byte, |e| e.span.end_byte),
            ..for_span
        };
        self.expect(Kind::Newline)?;
        let body = self.block(counts, depth + 1)?;
        let next_start = self.current().span;
        self.expect_word("NEXT")?;
        let (next_counter, next_counter_span) = self.identifier()?;
        if !counter.eq_ignore_ascii_case(&next_counter) {
            return Err(Diagnostic::at(
                "E0100",
                "NEXT must name the innermost FOR counter",
                self.name,
                next_counter_span,
            ));
        }
        self.expect(Kind::Newline)?;
        Ok(ParsedFor {
            counter,
            counter_span,
            for_span,
            to_span,
            step_span,
            header_span,
            next_span: Span {
                end_byte: next_counter_span.end_byte,
                ..next_start
            },
            next_counter_span,
            span: Span {
                end_byte: next_counter_span.end_byte,
                ..for_span
            },
            start,
            end,
            step,
            body,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::syntax::ParsedModule;
    fn parse(source: &str) -> Result<ParsedModule> {
        crate::syntax::parse_for_next("loops.bas", source.as_bytes())
    }

    fn contract(body: &str) -> String {
        format!("CONTRACT Demo()\n{body}\nEND CONTRACT\n")
    }

    fn error(source: &str, code: &str) -> Box<Diagnostic> {
        let failure = parse(source).err().expect("must reject malformed syntax");
        assert_eq!(failure.code, code, "{source}\n{failure}");
        assert_eq!(failure.source.as_deref(), Some("loops.bas"));
        assert!(failure.span.is_some());
        failure
    }

    #[test]
    fn for_next_header_and_body_spans_preserve_original_utf8_bytes() {
        let source = "\u{feff}CONTRACT Demo()\r\n\t' é🐈\r\n\tfOr Index = (1 +\r\n 2) TO 8 STEP -2\r\n\t ASSERT TRUE\r\n\tNeXt iNdEx\r\nEND CONTRACT";
        let parsed = parse(source).unwrap();
        let ParsedStatement::For(statement) = &parsed.contract.statements[0] else {
            panic!("expected loop");
        };
        assert_eq!(statement.counter, "Index");
        for (span, text) in [
            (statement.for_span, "fOr"),
            (statement.counter_span, "Index"),
            (statement.to_span, "TO"),
            (statement.step_span.unwrap(), "STEP"),
            (statement.start.span, "(1 +\r\n 2)"),
            (statement.end.span, "8"),
            (statement.step.as_ref().unwrap().span, "-2"),
            (statement.next_span, "NeXt iNdEx"),
            (statement.next_counter_span, "iNdEx"),
        ] {
            assert_eq!(&source[span.start_byte..span.end_byte], text);
        }
        assert_eq!((statement.for_span.line, statement.for_span.column), (3, 2));
        assert_eq!(
            (
                statement.next_counter_span.line,
                statement.next_counter_span.column
            ),
            (6, 7)
        );
        assert!(
            source[statement.header_span.start_byte..statement.header_span.end_byte]
                .ends_with("STEP -2")
        );
        assert!(source[statement.span.start_byte..statement.span.end_byte].ends_with("NeXt iNdEx"));
        assert_eq!(statement.body.len(), 1);
    }

    #[test]
    fn for_next_flat_ast_keeps_optional_step_and_children_before_parent() {
        let source = contract("FOR i = 1 TO 3\n FOR j = 4 TO 1 STEP -1\n NEXT J\nNEXT I");
        let view = crate::explain::ast(parse(&source).unwrap());
        let nodes = view["nodes"].as_array().unwrap();
        let loops: Vec<_> = nodes
            .iter()
            .enumerate()
            .filter(|(_, n)| n["kind"] == "For")
            .collect();
        assert_eq!(loops.len(), 2);
        for (index, node) in &loops {
            for field in ["start", "end"] {
                assert!(node["data"][field].as_u64().unwrap() < *index as u64);
            }
            if let Some(step) = node["data"]["step"].as_u64() {
                assert!(step < *index as u64);
            }
            for child in node["data"]["body"].as_array().unwrap() {
                assert!(child.as_u64().unwrap() < *index as u64);
            }
        }
        assert!(loops[1].1["data"]["step"].is_null());
        assert!(loops[1].1["data"]["step_span"].is_null());
        assert!(!loops[0].1["data"]["step"].is_null());
    }

    #[test]
    fn for_next_accepts_functions_comments_nested_branches_and_empty_bodies() {
        let source = "FUNCTION Choose() AS INTEGER\nFOR i = 1 TO 2 REM header\nIF TRUE THEN\nFOR j = 1 TO 1\nRETURN j\nNEXT j\nELSEIF FALSE THEN\nRETURN 0\nELSE\nASSERT TRUE\nEND IF\nNEXT i\nRETURN 0\nEND FUNCTION\nCONTRACT Demo()\nFOR k = 1 TO 0\n' empty body\nNEXT k\nEND CONTRACT\n";
        let parsed = parse(source).unwrap();
        assert_eq!(parsed.functions.len(), 1);
        assert!(matches!(
            parsed.functions[0].statements[0],
            ParsedStatement::For(_)
        ));
        let ParsedStatement::For(statement) = &parsed.contract.statements[0] else {
            panic!()
        };
        assert!(statement.body.is_empty());
    }

    #[test]
    fn for_next_rejects_malformed_headers_and_closers_at_source_locations() {
        for body in [
            "FOR i AS INTEGER = 1 TO 2\nNEXT i",
            "FOR i = 1 2\nNEXT i",
            "FOR i = 1 TO 2 STEP\nNEXT i",
            "FOR i = 1 TO 2\nNEXT",
            "FOR i = 1 TO 2\nNEXT i, j",
            "FOR i = 1 TO 2\nEND FOR",
            "FOR i = 1 TO 2\nNEXT j",
            "FOR i = 1 TO 2\nFOR j = 1 TO 2\nNEXT i\nNEXT j",
            "FOR i = 1 TO 2\nIF TRUE THEN\nNEXT i\nEND IF",
            "IF TRUE THEN\nFOR i = 1 TO 2\nEND IF\nNEXT i",
            "NEXT i",
            "FOR i = 1 TO 2",
        ] {
            error(&contract(body), "E0100");
        }
        let source = contract("FOR i = 1 TO 2\nNEXT wrong");
        let diagnostic = error(&source, "E0100");
        let span = diagnostic.span.unwrap();
        assert_eq!(&source[span.start_byte..span.end_byte], "wrong");
        error("CONTRACT Demo()\nFOR i = 1 TO 2\n", "E0100");
    }

    #[test]
    fn for_next_keywords_are_reserved_for_declarations_and_references() {
        for keyword in ["FOR", "TO", "STEP", "NEXT"] {
            let source = contract(&format!("DIM {keyword} = 1\nASSERT {keyword} = 1"));
            assert!(crate::compile("legacy.bas", source.as_bytes()).is_err());
            error(&source, "E0201");
            error(
                &format!("CONTRACT Demo({keyword} AS INTEGER)\nEND CONTRACT"),
                "E0201",
            );
            error(
                &contract(&format!("FOR {keyword} = 1 TO 2\nNEXT {keyword}")),
                "E0201",
            );
            error(
                &format!(
                    "FUNCTION {keyword}() AS INTEGER\nRETURN 1\nEND FUNCTION\nCONTRACT Demo()\nEND CONTRACT"
                ),
                "E0201",
            );
            // Reserved words are not accepted as free expression names either.
            assert!(parse(&contract(&format!("ASSERT {keyword} = 1"))).is_err());
        }
    }

    fn nested(depth: usize, mixed: bool) -> String {
        let mut source = String::new();
        for i in 0..depth {
            if mixed && i % 2 == 0 {
                source.push_str("IF TRUE THEN\n");
            } else {
                source.push_str(&format!("FOR i{i} = 1 TO 1\n"));
            }
        }
        for i in (0..depth).rev() {
            if mixed && i % 2 == 0 {
                source.push_str("END IF\n");
            } else {
                source.push_str(&format!("NEXT i{i}\n"));
            }
        }
        contract(&source)
    }

    #[test]
    fn for_next_shared_block_depth_accepts_32_and_rejects_33() {
        for mixed in [false, true] {
            parse(&nested(32, mixed)).unwrap();
            error(&nested(33, mixed), "E0205");
        }
        // ELSEIF consumes depth too; it cannot reset nesting for its FOR body.
        let body = format!(
            "{}FOR i = 1 TO 1\nNEXT i\nEND IF",
            "IF TRUE THEN\n".to_owned() + &"ELSEIF FALSE THEN\n".repeat(31)
        );
        error(&contract(&body), "E0205");
    }

    #[test]
    fn for_next_count_budget_is_per_body_including_unselected_branches() {
        let loops = "FOR i = 1 TO 0\nNEXT i\n".repeat(256);
        parse(&contract(&loops)).unwrap();
        error(
            &contract(&(loops.clone() + "FOR i = 1 TO 0\nNEXT i\n")),
            "E0205",
        );
        error(
            &contract(&format!(
                "IF FALSE THEN\n{loops}FOR i = 1 TO 0\nNEXT i\nEND IF"
            )),
            "E0205",
        );
        let source = format!(
            "FUNCTION Worker() AS INTEGER\n{loops}RETURN 0\nEND FUNCTION\n{}",
            contract(&loops)
        );
        parse(&source).unwrap();
    }

    #[test]
    fn for_next_parser_defers_types_scope_and_return_semantics() {
        // Syntax-only acceptance is not a claim that these programs are well typed.
        for body in [
            "FOR i = TRUE TO 1\nNEXT i",
            "FOR i = 1 TO 2 STEP 0\nNEXT i",
            "FOR i = i TO missing\nNEXT i",
            "FOR i = 1 TO 2\ni = 3\nNEXT i",
            "FOR i = 1 TO 2\nRETURN i\nNEXT i",
        ] {
            let source = contract(body);
            parse(&source).unwrap();
            if body.contains("STEP 0") {
                crate::check("loops.bas", source.as_bytes()).unwrap();
            } else {
                assert!(crate::check("loops.bas", source.as_bytes()).is_err());
            }
        }
    }

    #[test]
    fn for_next_is_available_through_all_public_frontends() {
        let source = contract("FOR i = 1 TO 2\nNEXT i");
        assert!(crate::check("loops.bas", source.as_bytes()).is_ok());
        assert!(crate::analyze("loops.bas", source.as_bytes()).is_ok());
        assert!(crate::compile_template("loops.bas", source.as_bytes()).is_ok());
        assert!(crate::compile("loops.bas", source.as_bytes()).is_ok());
        for stage in [crate::explain::Stage::Ast, crate::explain::Stage::Ir] {
            assert!(crate::explain::explain("loops.bas", source.as_bytes(), stage).is_ok());
        }
        assert!(crate::explain::explain_clvm("loops.bas", source.as_bytes(), Some(b"{}")).is_ok());
    }
}
