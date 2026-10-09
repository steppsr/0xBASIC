use crate::{Diagnostic, Result, Span};

pub(crate) mod expression;

// Preserve the existing library paths while moving checked data out of syntax.
pub use crate::ir::{Contract, HeightEmission};

pub const MAX_SOURCE_BYTES: usize = 1_048_576;
pub const MAX_EMISSIONS: usize = 256;
pub const MAX_LOCALS: usize = 1024;

#[derive(Debug, Clone, serde::Serialize)]
pub(crate) struct IntegerLiteral {
    pub spelling: String,
    pub radix: u32,
    pub span: Span,
}

#[derive(Debug)]
pub(crate) struct ParsedEmission {
    pub expression: expression::Expression,
    pub span: Span,
}

#[derive(Debug)]
pub(crate) struct ParsedContract {
    pub fixed: Vec<ParsedParameter>,
    pub inputs: Vec<ParsedParameter>,
    pub name: String,
    pub span: Span,
    pub statements: Vec<ParsedStatement>,
}

pub(crate) struct ParsedModule {
    pub type_budget: crate::ir::types::TypeBudget,
    pub collection_syntax: bool,
    pub contract: ParsedContract,
    pub functions: Vec<ParsedFunction>,
}

pub(crate) struct ParsedFunction {
    pub name: String,
    pub span: Span,
    pub parameters: Vec<ParsedParameter>,
    pub result: crate::ValueType,
    pub statements: Vec<ParsedStatement>,
}

#[derive(Debug)]
pub(crate) struct ParsedParameter {
    pub name: String,
    pub span: Span,
    pub value_type: crate::ValueType,
}

/// Source order is explicit so future blocks can contain the same statements.
#[derive(Debug)]
pub(crate) enum ParsedStatement {
    Return {
        expression: expression::Expression,
        span: Span,
    },
    If(ParsedIf),
    Local(ParsedLocalUpdate),
    Assert {
        expression: expression::Expression,
        span: Span,
    },
    Emit(ParsedEmission),
}

#[derive(Debug)]
pub(crate) struct ParsedIf {
    pub predicate: expression::Expression,
    pub yes: Vec<ParsedStatement>,
    pub no: Vec<ParsedStatement>,
    pub span: Span,
}

#[derive(Default)]
struct StatementCounts {
    declarations: usize,
    assignments: usize,
    assertions: usize,
    emissions: usize,
    branches: usize,
    returns: usize,
}

#[derive(Debug)]
pub(crate) enum LocalUpdateKind {
    Declaration,
    Constant,
    Assignment,
}

#[derive(Debug)]
pub(crate) struct ParsedLocalUpdate {
    pub kind: LocalUpdateKind,
    pub name: String,
    pub span: Span,
    pub initializer: expression::Expression,
    pub annotation: Option<crate::ir::ValueType>,
}

#[derive(Debug, PartialEq, Eq)]
enum Kind {
    Bytes,
    Word(String),
    Integer(u32),
    Literal,
    Symbol(char),
    Compound(&'static str),
    Newline,
    Eof,
}

#[derive(Debug)]
struct Token {
    kind: Kind,
    span: Span,
}

struct Lexer<'a> {
    name: &'a str,
    text: &'a str,
    pos: usize,
    line: usize,
    column: usize,
    brackets: Vec<char>,
    tokens: Vec<Token>,
}

impl<'a> Lexer<'a> {
    fn span(&self, start: usize, line: usize, column: usize) -> Span {
        Span {
            start_byte: start,
            end_byte: self.pos,
            line,
            column,
        }
    }

    fn peek(&self) -> Option<char> {
        self.text[self.pos..].chars().next()
    }
    fn advance(&mut self) -> Option<char> {
        let c = self.peek()?;
        self.pos += c.len_utf8();
        self.column += 1;
        Some(c)
    }
    fn consume_while(&mut self, predicate: impl Fn(char) -> bool) {
        while self.peek().is_some_and(&predicate) {
            self.advance();
        }
    }
    fn error(&self, code: &'static str, message: &str, span: Span) -> Box<Diagnostic> {
        Diagnostic::at(code, message, self.name, span)
    }
    fn lex(mut self) -> Result<Vec<Token>> {
        while let Some(c) = self.peek() {
            let (start, line, column) = (self.pos, self.line, self.column);
            let kind = match c {
                ' ' | '\t' => {
                    self.advance();
                    continue;
                }
                '\r' | '\n' => {
                    self.advance();
                    if c == '\r' && self.advance() != Some('\n') {
                        return Err(self.error(
                            "E0001",
                            "A carriage return must be followed by a newline",
                            self.span(start, line, column),
                        ));
                    }
                    self.line += 1;
                    self.column = 1;
                    if !self.brackets.is_empty() {
                        continue;
                    }
                    Kind::Newline
                }
                '\'' => {
                    self.consume_while(|c| c != '\r' && c != '\n');
                    continue;
                }
                c if c.is_ascii_alphabetic() => {
                    self.consume_while(|c| c.is_ascii_alphanumeric() || c == '_');
                    let word = self.text[start..self.pos].to_ascii_uppercase();
                    if word == "REM" {
                        self.consume_while(|c| c != '\r' && c != '\n');
                        continue;
                    }
                    Kind::Word(word)
                }
                '0'..='9' | '&' => {
                    self.consume_while(|c| {
                        c.is_ascii_alphanumeric() || matches!(c, '&' | '_' | '.')
                    });
                    let literal = &self.text[start..self.pos];
                    let lower = literal.to_ascii_lowercase();
                    if let Some(bytes) = lower.strip_prefix("0x") {
                        if !bytes.len().is_multiple_of(2)
                            || !bytes.chars().all(|c| c.is_ascii_hexdigit())
                        {
                            return Err(self.error(
                                "E0002",
                                "Byte literals require complete pairs of hexadecimal digits",
                                self.span(start, line, column),
                            ));
                        }
                        Kind::Bytes
                    } else if let Some(digits) = lower.strip_prefix("&h") {
                        if digits.is_empty() || !digits.chars().all(|c| c.is_ascii_hexdigit()) {
                            return Err(self.error(
                                "E0002",
                                "Invalid hexadecimal integer",
                                self.span(start, line, column),
                            ));
                        }
                        Kind::Integer(16)
                    } else {
                        if !literal.chars().all(|c| c.is_ascii_digit())
                            || (literal.len() > 1 && literal.starts_with('0'))
                        {
                            return Err(self.error("E0002", "Expected a decimal integer without leading zeros or a fractional part", self.span(start, line, column)));
                        }
                        Kind::Integer(10)
                    }
                }
                '"' => {
                    self.advance();
                    loop {
                        match self.advance() {
                            Some('"') if self.peek() == Some('"') => {
                                self.advance();
                            }
                            Some('"') => break,
                            Some('\r' | '\n') | None => {
                                return Err(self.error(
                                    "E0002",
                                    "Unterminated string literal",
                                    self.span(start, line, column),
                                ));
                            }
                            _ => {}
                        }
                    }
                    Kind::Literal
                }
                '(' | '[' => {
                    self.advance();
                    self.brackets.push(c);
                    Kind::Symbol(c)
                }
                ')' | ']' => {
                    self.advance();
                    let expected = if c == ')' { '(' } else { '[' };
                    if self.brackets.pop() != Some(expected) {
                        return Err(self.error(
                            "E0100",
                            "Mismatched closing delimiter",
                            self.span(start, line, column),
                        ));
                    }
                    Kind::Symbol(c)
                }
                '<' | '>' => {
                    self.advance();
                    match (c, self.peek()) {
                        ('<', Some('=')) => {
                            self.advance();
                            Kind::Compound("<=")
                        }
                        ('>', Some('=')) => {
                            self.advance();
                            Kind::Compound(">=")
                        }
                        ('<', Some('>')) => {
                            self.advance();
                            Kind::Compound("<>")
                        }
                        _ => Kind::Symbol(c),
                    }
                }
                ',' | '+' | '-' | '*' | '=' => {
                    self.advance();
                    Kind::Symbol(c)
                }
                _ => {
                    self.advance();
                    return Err(self.error(
                        "E0001",
                        "Invalid source character",
                        self.span(start, line, column),
                    ));
                }
            };
            self.tokens.push(Token {
                kind,
                span: self.span(start, line, column),
            });
        }
        let span = self.span(self.pos, self.line, self.column);
        if !self.brackets.is_empty() {
            return Err(self.error("E0100", "Unclosed delimiter", span));
        }
        if self.tokens.last().is_some_and(|t| t.kind != Kind::Newline) {
            self.tokens.push(Token {
                kind: Kind::Newline,
                span,
            });
        }
        self.tokens.push(Token {
            kind: Kind::Eof,
            span,
        });
        Ok(self.tokens)
    }
}

struct Parser<'a> {
    type_budget: crate::ir::types::TypeBudget,
    collection_syntax: bool,
    name: &'a str,
    source: &'a str,
    tokens: Vec<Token>,
    pos: usize,
    functions: bool,
}

impl Parser<'_> {
    fn current(&self) -> &Token {
        &self.tokens[self.pos]
    }
    fn word(&self, word: &str) -> bool {
        self.current().kind == Kind::Word(word.to_owned())
    }
    fn error(&self, code: &'static str, message: &str) -> Box<Diagnostic> {
        Diagnostic::at(code, message, self.name, self.current().span)
    }
    fn unsupported(&self) -> Box<Diagnostic> {
        let mut error = self.error(
            "E0205",
            "This construct is not implemented in the current compiler subset",
        );
        error.notes.push(crate::IMPLEMENTED_SUBSET.to_owned());
        error
    }
    fn expect(&mut self, kind: Kind) -> Result<()> {
        if self.current().kind != kind {
            return Err(self.error("E0100", &format!("Expected {kind:?}")));
        }
        self.pos += 1;
        Ok(())
    }
    fn expect_word(&mut self, word: &str) -> Result<()> {
        self.expect(Kind::Word(word.to_owned()))
    }
    fn blank_lines(&mut self) {
        while self.current().kind == Kind::Newline {
            self.pos += 1;
        }
    }
    #[cfg(test)]
    fn parse(mut self) -> Result<ParsedContract> {
        self.blank_lines();
        if self.word("FUNCTION") {
            return Err(self.unsupported());
        }
        if self.current().kind == Kind::Eof {
            return Err(self.error("E0101", "Exactly one contract is required"));
        }
        let contract = self.contract(&mut StatementCounts::default())?;
        self.blank_lines();
        if self.word("CONTRACT") {
            return Err(self.error("E0101", "Only one contract per file is supported"));
        }
        if self.word("FUNCTION") {
            return Err(self.unsupported());
        }
        self.expect(Kind::Eof)?;
        Ok(contract)
    }
    fn module(mut self) -> Result<ParsedModule> {
        let mut contract = None;
        let mut functions = Vec::new();
        let mut counts = StatementCounts::default();
        self.blank_lines();
        while self.current().kind != Kind::Eof {
            if self.word("CONTRACT") {
                if contract.is_some() {
                    return Err(self.error("E0101", "Exactly one contract is required"));
                }
                contract = Some(self.contract(&mut counts)?);
            } else if self.word("FUNCTION") {
                if functions.len() >= 256 {
                    return Err(self.error("E0205", "Modules support at most 256 functions"));
                }
                functions.push(self.function(&mut counts)?);
            } else {
                return Err(self.error("E0100", "Expected CONTRACT or FUNCTION"));
            }
            self.blank_lines();
        }
        Ok(ParsedModule {
            type_budget: self.type_budget.clone(),
            collection_syntax: self.collection_syntax,
            contract: contract
                .ok_or_else(|| self.error("E0101", "Exactly one contract is required"))?,
            functions,
        })
    }
    fn identifier(&mut self) -> Result<(String, Span)> {
        let token = self.current();
        let Kind::Word(ref name) = token.kind else {
            return Err(self.error("E0100", "Expected an identifier"));
        };
        if is_reserved(name) {
            return Err(self.error("E0201", "Reserved and built-in names cannot be declared"));
        }
        let result = (
            self.source[token.span.start_byte..token.span.end_byte].to_owned(),
            token.span,
        );
        self.pos += 1;
        Ok(result)
    }
    fn annotation(&mut self) -> Result<crate::ValueType> {
        self.expect_word("AS")?;
        self.type_annotation(0)
    }
    fn type_annotation(&mut self, depth: usize) -> Result<crate::ValueType> {
        if self.word("LIST") {
            if depth >= 32 {
                return Err(self.error("E0205", "Collection type depth exceeds 32"));
            }
            let span = self.current().span;
            self.pos += 1;
            self.expect_word("OF")?;
            let element = self.type_annotation(depth + 1)?;
            return self.type_budget.list(&element, self.name, span);
        }
        if self.word("PAIR") {
            if depth >= 32 {
                return Err(self.error("E0205", "Collection type depth exceeds 32"));
            }
            let span = self.current().span;
            self.pos += 1;
            self.expect_word("OF")?;
            self.expect(Kind::Symbol('('))?;
            let left = self.type_annotation(depth + 1)?;
            self.expect(Kind::Symbol(','))?;
            let right = self.type_annotation(depth + 1)?;
            self.expect(Kind::Symbol(')'))?;
            return self.type_budget.pair(&left, &right, self.name, span);
        }
        let ty = if self.word("INTEGER") {
            crate::ValueType::Integer
        } else if self.word("BOOLEAN") {
            crate::ValueType::Boolean
        } else if self.word("CONDITION") {
            crate::ValueType::Condition
        } else if self.word("STRING") {
            crate::ValueType::String
        } else if self.word("AMOUNT") {
            crate::ValueType::Amount
        } else if self.word("PUBLICKEY") {
            crate::ValueType::PublicKey
        } else if self.word("PUZZLEHASH") {
            crate::ValueType::PuzzleHash
        } else if self.word("BYTES") {
            crate::ValueType::Bytes
        } else {
            return Err(self.unsupported());
        };
        self.pos += 1;
        Ok(ty)
    }
    fn function(&mut self, counts: &mut StatementCounts) -> Result<ParsedFunction> {
        self.expect_word("FUNCTION")?;
        let (name, span) = self.identifier()?;
        self.expect(Kind::Symbol('('))?;
        let mut parameters = Vec::new();
        if self.current().kind != Kind::Symbol(')') {
            loop {
                if parameters.len() >= 32 {
                    return Err(self.error("E0205", "Functions support at most 32 parameters"));
                }
                let (name, span) = self.identifier()?;
                let value_type = self.annotation()?;
                parameters.push(ParsedParameter {
                    name,
                    span,
                    value_type,
                });
                if self.current().kind != Kind::Symbol(',') {
                    break;
                }
                self.pos += 1;
            }
        }
        self.expect(Kind::Symbol(')'))?;
        let result = self.annotation()?;
        self.expect(Kind::Newline)?;
        let statements = self.block(counts, 0)?;
        self.expect_word("END")?;
        self.expect_word("FUNCTION")?;
        self.expect(Kind::Newline)?;
        Ok(ParsedFunction {
            name,
            span,
            parameters,
            result,
            statements,
        })
    }
    fn boundary_type(&mut self, span: Span) -> Result<crate::ValueType> {
        let value_type = self.annotation()?;
        fn forbidden(ty: &crate::ValueType) -> bool {
            use crate::ValueType::*;
            match ty {
                Condition | Internal => true,
                List(t) => forbidden(t),
                Pair(a, b) => forbidden(a) || forbidden(b),
                _ => false,
            }
        }
        if forbidden(&value_type) {
            return Err(Diagnostic::at(
                "E0205",
                "CONDITION cannot occur in a boundary schema",
                self.name,
                span,
            ));
        }
        fn supported(ty: &crate::ValueType) -> bool {
            match ty {
                crate::ValueType::Pair(a, b) => supported(a) && supported(b),
                crate::ValueType::List(element) => supported(element),
                crate::ValueType::Integer
                | crate::ValueType::Boolean
                | crate::ValueType::Amount
                | crate::ValueType::PublicKey
                | crate::ValueType::PuzzleHash
                | crate::ValueType::Bytes
                | crate::ValueType::String => true,
                _ => false,
            }
        }
        if !supported(&value_type) {
            return Err(Diagnostic::at(
                "E0205",
                "Only scalar, PAIR and LIST boundary fields are implemented in this checkpoint",
                self.name,
                span,
            ));
        }
        Ok(value_type)
    }
    fn contract(&mut self, counts: &mut StatementCounts) -> Result<ParsedContract> {
        self.expect_word("CONTRACT")?;
        let token = self.current();
        let Kind::Word(ref name) = token.kind else {
            return Err(self.error("E0100", "Expected a contract name"));
        };
        if is_reserved(name) {
            return Err(self.error("E0201", "A contract cannot use a reserved or built-in name"));
        }
        let mut contract = ParsedContract {
            fixed: vec![],
            inputs: vec![],
            name: self.source[token.span.start_byte..token.span.end_byte].to_owned(),
            span: token.span,
            statements: vec![],
        };
        self.pos += 1;
        self.expect(Kind::Symbol('('))?;
        if self.current().kind != Kind::Symbol(')') {
            loop {
                if contract.fixed.len() == 32 {
                    return Err(self.error("E0205", "At most 32 fixed fields are supported"));
                }
                let (name, span) = self.identifier()?;
                let value_type = self.boundary_type(span)?;
                contract.fixed.push(ParsedParameter {
                    name,
                    span,
                    value_type,
                });
                if self.current().kind != Kind::Symbol(',') {
                    break;
                }
                self.pos += 1;
            }
        }
        self.expect(Kind::Symbol(')'))?;
        self.expect(Kind::Newline)?;
        while self.current().kind == Kind::Newline {
            self.pos += 1;
        }
        while self.word("SOLUTION") {
            if contract.inputs.len() == 32 {
                return Err(self.error("E0205", "At most 32 SOLUTION fields are supported"));
            }
            self.pos += 1;
            let (name, span) = self.identifier()?;
            let value_type = self.boundary_type(span)?;
            self.expect(Kind::Newline)?;
            contract.inputs.push(ParsedParameter {
                name,
                span,
                value_type,
            });
            while self.current().kind == Kind::Newline {
                self.pos += 1;
            }
        }
        contract.statements = self.block(counts, 0)?;
        self.expect_word("END")?;
        self.expect_word("CONTRACT")?;
        self.expect(Kind::Newline)?;
        Ok(contract)
    }
    // ELSEIF is an IF in the preceding false branch. Only the outer caller
    // consumes END IF; all arms keep sibling scopes and lazy predicates.
    fn conditional(&mut self, counts: &mut StatementCounts, depth: usize) -> Result<ParsedIf> {
        if depth >= 32 || counts.branches >= 256 {
            return Err(self.error(
                "E0205",
                "IF/ELSEIF decisions are limited to depth 32 and 256 per contract",
            ));
        }
        counts.branches += 1;
        let start = self.current().span;
        self.pos += 1;
        let predicate = self.expression()?;
        self.expect_word("THEN")?;
        self.expect(Kind::Newline)?;
        let yes = self.block(counts, depth + 1)?;
        let no = if self.word("ELSEIF") {
            vec![ParsedStatement::If(self.conditional(counts, depth + 1)?)]
        } else if self.word("ELSE") {
            self.pos += 1;
            self.expect(Kind::Newline)?;
            self.block(counts, depth + 1)?
        } else {
            Vec::new()
        };
        let end_byte = self
            .tokens
            .get(self.pos + 1)
            .map_or(self.current().span.end_byte, |t| t.span.end_byte);
        Ok(ParsedIf {
            predicate,
            yes,
            no,
            span: Span { end_byte, ..start },
        })
    }
    fn block(
        &mut self,
        counts: &mut StatementCounts,
        depth: usize,
    ) -> Result<Vec<ParsedStatement>> {
        let mut statements = Vec::new();
        loop {
            self.blank_lines();
            if self.word("END") || self.word("ELSE") || self.word("ELSEIF") {
                break;
            }
            if self.current().kind == Kind::Eof {
                return Err(self.error("E0100", "Expected block terminator"));
            }
            if self.word("RETURN") && self.functions {
                if counts.returns >= 4096 {
                    return Err(
                        self.error("E0205", "Modules support at most 4096 RETURN statements")
                    );
                }
                counts.returns += 1;
                let span = self.current().span;
                self.pos += 1;
                let expression = self.expression()?;
                self.expect(Kind::Newline)?;
                statements.push(ParsedStatement::Return { expression, span });
                continue;
            }
            if self.word("IF") {
                let branch = self.conditional(counts, depth)?;
                self.expect_word("END")?;
                self.expect_word("IF")?;
                self.expect(Kind::Newline)?;
                statements.push(ParsedStatement::If(branch));
                continue;
            }
            if self.word("DIM") || self.word("CONST") {
                let kind = if self.word("CONST") {
                    LocalUpdateKind::Constant
                } else {
                    LocalUpdateKind::Declaration
                };
                if counts.declarations == MAX_LOCALS {
                    return Err(
                        self.error("E0205", "Contracts support at most 1024 local declarations")
                    );
                }
                self.pos += 1;
                let token = self.current();
                let Kind::Word(ref name) = token.kind else {
                    return Err(self.error("E0100", "Expected a local name"));
                };
                if is_reserved(name) {
                    return Err(
                        self.error("E0201", "A local cannot use a reserved or built-in name")
                    );
                }
                let name = self.source[token.span.start_byte..token.span.end_byte].to_owned();
                let span = token.span;
                self.pos += 1;
                let mut annotation = None;
                if self.word("AS") {
                    annotation = Some(self.annotation()?);
                }
                self.expect(Kind::Symbol('='))?;
                let initializer = self.expression()?;
                self.expect(Kind::Newline)?;
                counts.declarations += 1;
                statements.push(ParsedStatement::Local(ParsedLocalUpdate {
                    kind,
                    name,
                    span,
                    initializer,
                    annotation,
                }));
                continue;
            }
            if self.word("ASSERT") {
                if counts.assertions == 4096 {
                    return Err(self.error("E0205", "Contracts support at most 4096 assertions"));
                }
                let span = self.current().span;
                self.pos += 1;
                let initializer = self.expression()?;
                self.expect(Kind::Newline)?;
                counts.assertions += 1;
                statements.push(ParsedStatement::Assert {
                    span,
                    expression: initializer,
                });
                continue;
            }
            if let Kind::Word(ref target) = self.current().kind
                && self
                    .tokens
                    .get(self.pos + 1)
                    .is_some_and(|t| t.kind == Kind::Symbol('='))
            {
                if is_reserved(target) {
                    return Err(
                        self.error("E0203", "Assignment target must be an existing DIM local")
                    );
                }
                if counts.assignments == 4096 {
                    return Err(self.error("E0205", "Contracts support at most 4096 assignments"));
                }
                let span = self.current().span;
                let name = self.source[span.start_byte..span.end_byte].to_owned();
                self.pos += 2;
                let initializer = self.expression()?;
                self.expect(Kind::Newline)?;
                counts.assignments += 1;
                statements.push(ParsedStatement::Local(ParsedLocalUpdate {
                    kind: LocalUpdateKind::Assignment,
                    annotation: None,
                    name,
                    span,
                    initializer,
                }));
                continue;
            }
            if !self.word("EMIT") {
                return Err(self.unsupported());
            }
            if counts.emissions == MAX_EMISSIONS {
                return Err(self.error("E0205", "M1 supports at most 256 emissions per contract"));
            }
            let start = self.current().span;
            self.pos += 1;
            let expression = self.expression()?;
            let end_byte = expression.span.end_byte;
            self.expect(Kind::Newline)?;
            counts.emissions += 1;
            statements.push(ParsedStatement::Emit(ParsedEmission {
                expression,
                span: Span { end_byte, ..start },
            }));
        }
        Ok(statements)
    }
}

fn is_reserved(word: &str) -> bool {
    const NAMES: &str = "CONTRACT END FUNCTION AS SOLUTION INTEGER BOOLEAN BYTES STRING PUZZLEHASH PUBLICKEY AMOUNT CONDITION LIST OF PAIR DIM CONST IF THEN ELSEIF ELSE EMIT ASSERT RETURN NOT AND OR TRUE FALSE REM SHA256 CONCAT BYTE_LENGTH UTF8 STRING_FROM_UTF8 INT_BYTES INT_FROM_BYTES U64BE U32BE AS_AMOUNT AMOUNT_VALUE AS_PUZZLEHASH HASH_BYTES AS_PUBLICKEY KEY_BYTES FIRST REST CONS LIST_LENGTH CREATE_COIN ASSERT_MY_AMOUNT ASSERT_HEIGHT_ABSOLUTE AGG_SIG_ME";
    NAMES.split_whitespace().any(|name| name == word)
}

pub fn check(name: &str, source: &[u8]) -> Result<Contract> {
    crate::check(name, source)
}

#[cfg(test)]
pub(crate) fn parse(name: &str, source: &[u8]) -> Result<ParsedContract> {
    parser(name, source, false)?.parse()
}

pub(crate) fn parse_module(name: &str, source: &[u8]) -> Result<ParsedModule> {
    parser(name, source, true)?.module()
}

fn parser<'a>(name: &'a str, source: &'a [u8], functions: bool) -> Result<Parser<'a>> {
    if source.len() > MAX_SOURCE_BYTES {
        return Err(Diagnostic::new(
            "E0205",
            "M1 source files must be no larger than 1 MiB",
        ));
    }
    let text = std::str::from_utf8(source).map_err(|e| {
        let prefix = std::str::from_utf8(&source[..e.valid_up_to()]).unwrap_or("");
        Diagnostic::at(
            "E0001",
            "Source must be valid UTF-8",
            name,
            source_span(
                prefix,
                e.valid_up_to(),
                e.valid_up_to() + e.error_len().unwrap_or(source.len() - e.valid_up_to()),
            ),
        )
    })?;
    if let Some(pos) = text.find('\0') {
        return Err(Diagnostic::at(
            "E0001",
            "NUL is not permitted in source",
            name,
            source_span(text, pos, pos + 1),
        ));
    }
    let start = if text.starts_with('\u{feff}') { 3 } else { 0 };
    let tokens = Lexer {
        name,
        text,
        pos: start,
        line: 1,
        column: 1,
        brackets: vec![],
        tokens: vec![],
    }
    .lex()?;
    let collection_syntax = tokens.iter().any(
        |t| t.kind == Kind::Symbol('[') || matches!(&t.kind, Kind::Word(w) if matches!(w.as_str(), "PAIR" | "FIRST" | "REST" | "LIST" | "CONS" | "LIST_LENGTH")),
    );
    Ok(Parser {
        type_budget: Default::default(),
        collection_syntax,
        name,
        source: text,
        tokens,
        pos: 0,
        functions,
    })
}

fn source_span(text: &str, start: usize, end: usize) -> Span {
    let prefix = text[..start].trim_start_matches('\u{feff}');
    let line = prefix.bytes().filter(|b| *b == b'\n').count() + 1;
    let column = prefix.rsplit('\n').next().unwrap_or("").chars().count() + 1;
    Span {
        start_byte: start,
        end_byte: end,
        line,
        column,
    }
}
