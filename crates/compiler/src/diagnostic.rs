use serde::Serialize;

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
pub struct Span {
    pub start_byte: usize,
    pub end_byte: usize,
    pub line: usize,
    pub column: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct Diagnostic {
    pub code: &'static str,
    pub severity: &'static str,
    pub message: String,
    pub source: Option<String>,
    pub span: Option<Span>,
    pub notes: Vec<String>,
}

impl Diagnostic {
    pub fn new(code: &'static str, message: impl Into<String>) -> Box<Self> {
        Box::new(Self {
            code,
            severity: "error",
            message: message.into(),
            source: None,
            span: None,
            notes: vec![],
        })
    }

    pub fn at(
        code: &'static str,
        message: impl Into<String>,
        source: &str,
        span: Span,
    ) -> Box<Self> {
        let mut error = Self::new(code, message);
        error.source = Some(source.to_owned());
        error.span = Some(span);
        error
    }
}

impl std::fmt::Display for Diagnostic {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if let (Some(source), Some(span)) = (&self.source, self.span) {
            write!(f, "{source}:{}:{}: ", span.line, span.column)?;
        }
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for Diagnostic {}
