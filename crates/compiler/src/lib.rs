//! The first, deliberately small 0xBASIC compiler subset.
//! No filesystem, terminal, wallet, or network access belongs in this crate.

pub mod abi;
mod analysis;
pub mod clvm;
pub mod diagnostic;
mod ir;
pub mod syntax;

pub use analysis::{FunctionSignature, ModuleAnalysis, ParameterSignature};
pub use diagnostic::{Diagnostic, Span};
pub use ir::{Contract, IntegerOperation, IntegerValue, IntegerValueKind, LocalBinding, ValueType};

pub const LANGUAGE_VERSION: &str = "0.1";
pub const ABI_VERSION: u32 = 1;
pub const TARGET_PROFILE: &str = "chia-clvm-0.19-strict-v1";
pub const COMPILER_VERSION: &str = env!("CARGO_PKG_VERSION");
pub const IMPLEMENTED_SUBSET: &str = "m3.2: contracts with INTEGER fixed parameters and SOLUTIONs, INTEGER/BOOLEAN/BYTES/STRING/CONDITION locals and functions, INTEGER/BOOLEAN/BYTES/STRING/LIST constants, BYTE_LENGTH, CONCAT, SHA256, INT_BYTES, INT_FROM_BYTES, U32BE, U64BE, UTF8, STRING_FROM_UTF8, short-circuit logic, ASSERT, height constructors, typed EMIT, scoped IF/ELSEIF/ELSE, early and branch RETURN, typed PAIR construction and FIRST/REST, contextual LIST literals, list FIRST/REST, CONS, LIST_LENGTH; bounded list constants; domain conversions are not implemented yet";

pub type Result<T> = std::result::Result<T, Box<Diagnostic>>;

/// Analyze signatures, scopes, types, return paths and non-recursive calls.
/// This front-end API does not generate executable IR or guarantee that the
/// module belongs to the smaller subset supported by `check` and `compile`.
pub fn analyze(source_name: &str, source: &[u8]) -> Result<ModuleAnalysis> {
    analysis::analyze(source_name, source)
}

/// Parse and lower through the same checked representation used by compilation.
pub fn check(source_name: &str, source: &[u8]) -> Result<Contract> {
    ir::lower_module(source_name, syntax::parse_module(source_name, source)?)
}

pub struct Compiled {
    pub contract: Contract,
    pub template: Vec<u8>,
    pub puzzle: Vec<u8>,
}

pub struct Template {
    pub contract: Contract,
    pub template: Vec<u8>,
}
pub struct BoundProgram {
    pub puzzle: Vec<u8>,
    pub bindings: abi::IntegerObject,
}
pub fn compile_template(source_name: &str, source: &[u8]) -> Result<Template> {
    let contract = check(source_name, source)?;
    let template = clvm::generate(&contract)?;
    Ok(Template { contract, template })
}
impl Template {
    pub fn bind(&self, json: &[u8]) -> Result<BoundProgram> {
        let values = abi::encode_bindings(&self.contract.fixed, json)?;
        let puzzle = clvm::bind_fixed(&self.template, &values.bytes)?;
        Ok(BoundProgram {
            puzzle,
            bindings: values.normalized,
        })
    }
}
/// Convenience compilation with default {} bindings; nonempty fixed schemas fail E0301.
pub fn compile(source_name: &str, source: &[u8]) -> Result<Compiled> {
    let template = compile_template(source_name, source)?;
    let bound = template.bind(b"{}")?;
    Ok(Compiled {
        contract: template.contract,
        template: template.template,
        puzzle: bound.puzzle,
    })
}
