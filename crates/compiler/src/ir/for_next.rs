//! Private source-to-loop IR bridge. Functions remain gated in this slice.
use super::*;

#[derive(Debug, Serialize)]
pub struct LoopBody {
    pub headers: [usize; 3],
    pub captures: Vec<usize>,
    pub capture_names: Vec<String>,
    pub values: Vec<IntegerValue>,
    pub outputs: Vec<usize>,
    pub emissions: Vec<HeightEmission>,
}

fn count(values: &[IntegerValue]) -> usize {
    values.len()
        + values
            .iter()
            .map(|v| match &v.kind {
                IntegerValueKind::For(body) => count(&body.values),
                _ => 0,
            })
            .sum::<usize>()
}

pub(crate) fn lower(source: &str) -> Result<Contract> {
    let module = crate::syntax::parse_for_next("loops.bas", source.as_bytes())?;
    crate::analysis::analyze_module("loops.bas", &module)?;
    if !module.functions.is_empty() {
        return Err(Diagnostic::new(
            "E0205",
            "Private loop lowering does not yet support functions",
        ));
    }
    let contract = lower_contract("loops.bas", module.contract, &Callables::new())?;
    if count(&contract.values) > MAX_INTEGER_VALUES {
        return Err(Diagnostic::new(
            "E0205",
            "Loop module exceeds 4096 value bindings",
        ));
    }
    Ok(contract)
}

impl Lowerer<'_> {
    pub(super) fn for_statement(
        &mut self,
        statement: crate::syntax::for_next::ParsedFor,
        names: &mut BTreeMap<String, usize>,
        constants: &BTreeMap<String, (ConstantValue, ValueType)>,
    ) -> Result<HeightEmission> {
        let span = statement.span;
        let start = expression(
            self.source,
            statement.start,
            &mut self.values,
            names,
            self.functions,
        )?;
        let end = expression(
            self.source,
            statement.end,
            &mut self.values,
            names,
            self.functions,
        )?;
        let step = if let Some(step) = statement.step {
            expression(self.source, step, &mut self.values, names, self.functions)?
        } else {
            push(
                self.source,
                &mut self.values,
                IntegerValueKind::Literal(vec![1]),
                ValueType::Integer,
                span,
            )?
        };
        // A distinct body frame prevents folding mutable captures to entry values.
        // Capture immutable bindings too, so all reads use a stable lexical frame.
        let capture_names: Vec<_> = names.keys().cloned().collect();
        let captures: Vec<_> = names.values().copied().collect();
        fn nodes(ty: &ValueType) -> usize {
            1 + match ty {
                ValueType::List(t) => nodes(t),
                ValueType::Pair(a, b) => nodes(a) + nodes(b),
                _ => 0,
            }
        }
        let copies = captures
            .iter()
            .map(|id| 2 * nodes(&self.values[*id].value_type))
            .sum::<usize>()
            + 1;
        let total = self.loop_type_nodes.get().saturating_add(copies);
        if total > 65_536 {
            return Err(Diagnostic::at(
                "E0205",
                "Loop frame copies exceed 65536 type nodes",
                self.source,
                span,
            ));
        }
        self.loop_type_nodes.set(total);
        let mut body = Lowerer {
            loop_type_nodes: self.loop_type_nodes.clone(),
            result_type: None,
            functions: self.functions,
            in_function: false,
            return_state: false,
            block_depth: self.block_depth,
            source: self.source,
            contract: self.contract.clone(),
            values: Vec::new(),
            locals: Vec::new(),
            constant_budget: std::mem::take(&mut self.constant_budget),
        };
        let counter = push(
            self.source,
            &mut body.values,
            IntegerValueKind::Parameter,
            ValueType::Integer,
            statement.counter_span,
        )?;
        let mut body_names = BTreeMap::from([(statement.counter.to_ascii_lowercase(), counter)]);
        for (key, id) in capture_names.iter().zip(&captures) {
            let parameter = push(
                self.source,
                &mut body.values,
                IntegerValueKind::Parameter,
                self.values[*id].value_type.clone(),
                span,
            )?;
            body_names.insert(key.clone(), parameter);
        }
        let emissions = body.block(statement.body, &mut body_names, &mut constants.clone())?;
        let outputs = capture_names.iter().map(|key| body_names[key]).collect();
        self.constant_budget = body.constant_budget;
        let types: Vec<_> = captures
            .iter()
            .map(|id| self.values[*id].value_type.clone())
            .collect();
        let bundle = push(
            self.source,
            &mut self.values,
            IntegerValueKind::For(Box::new(LoopBody {
                headers: [start, end, step],
                captures,
                capture_names: capture_names.clone(),
                values: body.values,
                outputs,
                emissions,
            })),
            ValueType::Internal,
            span,
        )?;
        let conditions = push(
            self.source,
            &mut self.values,
            IntegerValueKind::Project { bundle, index: 0 },
            ValueType::Internal,
            span,
        )?;
        for (index, (key, ty)) in capture_names.into_iter().zip(types).enumerate() {
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
        if count(&self.values) > MAX_INTEGER_VALUES {
            return Err(Diagnostic::at(
                "E0205",
                "Loop module exceeds 4096 value bindings",
                self.source,
                span,
            ));
        }
        Ok(HeightEmission {
            condition: conditions,
            values_before: self.values.len(),
            span,
            spread: true,
        })
    }
}

fn execute(body: &str) -> Result<crate::clvm::Execution> {
    let source = format!("CONTRACT Demo()\n{body}\nEND CONTRACT");
    let contract = lower(&source)?;
    let program = crate::clvm::generate(&contract)?;
    crate::clvm::execute(&program, &[0xff, 0x80, 0x80], 100_000_000)
}

fn heights(execution: &crate::clvm::Execution) -> Vec<i64> {
    use clvmr::{Allocator, NodePtr, SExp};
    let mut a = Allocator::new();
    let mut tree = clvmr::serde::node_from_bytes(&mut a, &execution.bytes).unwrap();
    let mut result = Vec::new();
    while tree != NodePtr::NIL {
        let SExp::Pair(condition, rest) = a.sexp(tree) else {
            panic!("conditions list")
        };
        let SExp::Pair(opcode, args) = a.sexp(condition) else {
            panic!("condition")
        };
        assert_eq!(a.atom(opcode).as_ref(), &[83]);
        let SExp::Pair(value, nil) = a.sexp(args) else {
            panic!("height argument")
        };
        assert_eq!(nil, NodePtr::NIL);
        result.push(
            num_bigint::BigInt::from_signed_bytes_be(a.atom(value).as_ref())
                .to_string()
                .parse()
                .unwrap(),
        );
        tree = rest;
    }
    result
}

#[test]
fn for_next_source_snapshots_carried_state_and_body_locals() {
    let actual = execute("DIM finish = 3\nDIM stride = 1\nDIM total = 0\nFOR i = 1 TO finish STEP stride\nDIM temporary = i\ntotal = total + temporary\nfinish = 0\nstride = 0\nNEXT i\nASSERT total = 6\nASSERT finish = 0\nASSERT stride = 0\nEMIT ASSERT_HEIGHT_ABSOLUTE(total)").unwrap();
    assert_eq!(heights(&actual), [6]);
    let skipped = execute("DIM total = 17\nFOR i = 3 TO 1\ntotal = 0\nASSERT FALSE\nNEXT i\nEMIT ASSERT_HEIGHT_ABSOLUTE(total)").unwrap();
    assert_eq!(heights(&skipped), [17]);
}

#[test]
fn for_next_source_nested_branches_and_ordered_emissions() {
    let actual = execute("DIM total = 0\nEMIT ASSERT_HEIGHT_ABSOLUTE(99)\nFOR i = 1 TO 3\nDIM stop = i\nFOR j = 1 TO stop\nIF j = 2 THEN\ntotal = total + 10\nELSE\ntotal = total + 1\nEND IF\nEMIT ASSERT_HEIGHT_ABSOLUTE(i * 10 + j)\nNEXT j\nNEXT i\nEMIT ASSERT_HEIGHT_ABSOLUTE(total)").unwrap();
    assert_eq!(heights(&actual), [99, 11, 21, 22, 31, 32, 33, 24]);
    let descending =
        execute("FOR i = 5 TO 1 STEP -2\nEMIT ASSERT_HEIGHT_ABSOLUTE(i)\nNEXT i").unwrap();
    assert_eq!(heights(&descending), [5, 3, 1]);
    let repeated = execute("FOR i = 1 TO 300\nEMIT ASSERT_HEIGHT_ABSOLUTE(i)\nNEXT i").unwrap();
    assert_eq!(heights(&repeated), (1..=300).collect::<Vec<_>>());
}

#[test]
fn for_next_source_state_types_and_constants() {
    let actual = execute("CONST stop = 2\nDIM flag = FALSE\nDIM text = \"a\"\nDIM byteValue = 0x01\nDIM amountValue = AS_AMOUNT(0)\nDIM values AS LIST OF INTEGER = []\nDIM pairValue = PAIR(0, FALSE)\nDIM conditionValue = ASSERT_HEIGHT_ABSOLUTE(0)\nFOR i = 1 TO stop\nCONST cached = stop\nASSERT cached = 2\nflag = NOT flag\ntext = STRING_FROM_UTF8(CONCAT(UTF8(text), 0x62))\nbyteValue = CONCAT(byteValue, 0x02)\namountValue = AS_AMOUNT(i)\nvalues = CONS(i, values)\npairValue = PAIR(i, flag)\nconditionValue = ASSERT_HEIGHT_ABSOLUTE(i)\nNEXT i\nASSERT NOT flag\nASSERT text = \"abb\"\nASSERT byteValue = 0x010202\nASSERT AMOUNT_VALUE(amountValue) = 2\nASSERT LIST_LENGTH(values) = 2\nASSERT FIRST(values) = 2\nASSERT FIRST(pairValue) = 2\nASSERT NOT REST(pairValue)\nEMIT conditionValue").unwrap();
    assert_eq!(heights(&actual), [2]);
    let fixtures: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../docs/spec/m3-publickey-cases.json"
    ))
    .unwrap();
    let key = fixtures["cases"][0]["hex"].as_str().unwrap();
    let other = fixtures["cases"][1]["hex"].as_str().unwrap();
    execute(&format!("DIM owner = AS_PUBLICKEY(0x{key})\nDIM recipient = AS_PUZZLEHASH(SHA256(0x00))\nFOR i = 1 TO 2\nowner = AS_PUBLICKEY(0x{other})\nrecipient = AS_PUZZLEHASH(SHA256(INT_BYTES(i)))\nNEXT i\nASSERT KEY_BYTES(owner) = 0x{other}\nASSERT HASH_BYTES(recipient) = SHA256(0x02)")).unwrap();
}

#[test]
fn for_next_source_failure_timing_and_unselected_loops() {
    for body in [
        "FOR i = 1 TO 0 STEP 0\nNEXT i",
        "FOR i = 2 TO 1 STEP INT_FROM_BYTES(0x00)\nNEXT i",
        "FOR i = 1 TO 1\nDIM unused = AS_AMOUNT(-1)\nNEXT i",
    ] {
        assert_eq!(execute(body).err().unwrap().code, "E0500");
    }
    execute("IF FALSE THEN\nFOR i = 1 TO 2 STEP 0\nNEXT i\nEND IF\nFOR j = 2 TO 1\nDIM unused = AS_AMOUNT(-1)\nNEXT j").unwrap();
    // Header failures remain runtime failures even when no body value is needed.
    let error = execute(
        "FOR i = INT_FROM_BYTES(0x00) TO BYTE_LENGTH(UTF8(STRING_FROM_UTF8(0xff)))\nNEXT i",
    )
    .err()
    .unwrap();
    assert_eq!(error.code, "E0500");
    // A costly earlier header must exhaust a low budget before the later
    // failing conversion can raise. Reversed evaluation would raise E0500.
    let costly = format!("BYTE_LENGTH(SHA256(0x{}))", "00".repeat(10_000));
    for header in [
        format!("{costly} TO INT_FROM_BYTES(0x00)"),
        format!("0 TO {costly} STEP INT_FROM_BYTES(0x00)"),
    ] {
        let source = format!("CONTRACT Demo()\nFOR i = {header}\nNEXT i\nEND CONTRACT");
        let program = crate::clvm::generate(&lower(&source).unwrap()).unwrap();
        assert_eq!(
            crate::clvm::execute(&program, &[0xff, 0x80, 0x80], 10_000)
                .err()
                .unwrap()
                .code,
            "E0501"
        );
        assert_eq!(
            crate::clvm::execute(&program, &[0xff, 0x80, 0x80], 1_000_000)
                .err()
                .unwrap()
                .code,
            "E0500"
        );
    }
}

#[test]
fn for_next_source_dynamic_boundaries_cost_and_public_gate() {
    let source = "CONTRACT Demo()\nSOLUTION stop AS INTEGER\nSOLUTION unused AS BOOLEAN\nFOR i = 1 TO stop\nEMIT ASSERT_HEIGHT_ABSOLUTE(i)\nNEXT i\nEND CONTRACT";
    let contract = lower(source).unwrap();
    let program = crate::clvm::generate(&contract).unwrap();
    // Environment (nil . (3 nil)); guards run before loop entry.
    let env = [0xff, 0x80, 0xff, 3, 0xff, 0x80, 0x80];
    let actual = crate::clvm::execute(&program, &env, 10_000_000).unwrap();
    assert_eq!(heights(&actual), [1, 2, 3]);
    assert_eq!(
        crate::clvm::execute(&program, &env, actual.cost)
            .unwrap()
            .bytes,
        actual.bytes
    );
    assert_eq!(
        crate::clvm::execute(&program, &env, actual.cost - 1)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
    assert_eq!(
        crate::clvm::execute(&program, &[0xff, 0x80, 0x80], 10_000_000)
            .err()
            .unwrap()
            .code,
        "E0500"
    );
    // Even when stop=0 skips the loop, unused BOOLEAN input 2 is invalid.
    assert_eq!(
        crate::clvm::execute(
            &program,
            &[0xff, 0x80, 0xff, 0x80, 0xff, 2, 0x80],
            10_000_000
        )
        .err()
        .unwrap()
        .code,
        "E0500"
    );
    assert!(crate::check("loops.bas", source.as_bytes()).is_err());
    let parsed = crate::syntax::parse_for_next("loops.bas", source.as_bytes()).unwrap();
    assert_eq!(
        crate::ir::lower_module("loops.bas", parsed)
            .unwrap_err()
            .code,
        "E0205"
    );
    assert_eq!(lower("FUNCTION Helper() AS INTEGER\nRETURN 1\nEND FUNCTION\nCONTRACT Demo()\nFOR i = 1 TO 2\nNEXT i\nEND CONTRACT").unwrap_err().code, "E0205");
}

#[test]
fn for_next_source_ir_is_deterministic_and_numeric_range_is_not_unrolled() {
    let a = lower("CONTRACT Demo()\nFOR i = 1 TO 3\nNEXT i\nEND CONTRACT").unwrap();
    let b =
        lower("CONTRACT Demo()\nFOR i = 1 TO 999999999999999999999999999999\nNEXT i\nEND CONTRACT")
            .unwrap();
    assert_eq!(a.values.len(), b.values.len());
    let a_bytes = crate::clvm::generate(&a).unwrap();
    assert_eq!(a_bytes, crate::clvm::generate(&a).unwrap());
    assert!(crate::clvm::generate(&b).unwrap().len() < a_bytes.len() + 32);
    let json = serde_json::to_string(&a).unwrap();
    assert!(json.contains("capture_names"));
    let loop_body = a
        .values
        .iter()
        .find_map(|value| match &value.kind {
            IntegerValueKind::For(body) => Some(body),
            _ => None,
        })
        .unwrap();
    assert!(loop_body.headers[0] < loop_body.headers[1]);
    assert!(loop_body.headers[1] < loop_body.headers[2]);
    let huge = crate::clvm::generate(&b).unwrap();
    assert_eq!(
        crate::clvm::execute(&huge, &[0xff, 0x80, 0x80], 100_000)
            .err()
            .unwrap()
            .code,
        "E0501"
    );
}

#[test]
fn for_next_source_frame_type_copy_budget_is_shared() {
    let mut ty = "INTEGER".to_owned();
    let mut value = "0".to_owned();
    for _ in 0..9 {
        ty = format!("PAIR OF ({ty}, {ty})");
        value = format!("PAIR({value}, {value})");
    }
    // Each loop copies 1023 type nodes twice, plus the counter: 2047 nodes.
    let source = |n| {
        format!(
            "CONTRACT Demo()\nDIM state AS {ty} = {value}\n{}END CONTRACT",
            "FOR i = 1 TO 0\nstate = state\nNEXT i\n".repeat(n)
        )
    };
    lower(&source(32)).unwrap();
    let error = lower(&source(33)).unwrap_err();
    assert_eq!(error.code, "E0205");
    assert!(error.message.contains("frame copies"));
}

#[test]
fn for_next_source_value_budget_includes_isolated_bodies() {
    let body = (0..20)
        .map(|i| format!("ASSERT i + {i} > 0\n"))
        .collect::<String>();
    let source = format!(
        "CONTRACT Demo()\n{}END CONTRACT",
        format!("FOR i = 1 TO 1\n{body}NEXT i\n").repeat(80)
    );
    let error = lower(&source).unwrap_err();
    assert_eq!(error.code, "E0205");
    assert!(error.message.contains("4096 value"), "{error:?}");
}
