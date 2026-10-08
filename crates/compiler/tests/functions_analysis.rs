use oxbasic_compiler::{ValueType, analyze, check, compile};

fn module(functions: &str) -> String {
    format!("CONTRACT Demo()\nEND CONTRACT\n{functions}")
}
fn function(body: &str) -> String {
    module(&format!(
        "FUNCTION Helper(flag AS BOOLEAN) AS INTEGER\n{body}END FUNCTION\n"
    ))
}
fn error(source: &str, code: &str) {
    let diagnostic = analyze("functions.bas", source.as_bytes()).unwrap_err();
    assert_eq!(diagnostic.code, code, "{source}\n{diagnostic:?}");
    assert!(diagnostic.span.is_some());
}

#[test]
fn signatures_forward_calls_and_all_supported_types() {
    let source = "FUNCTION Choose(n AS INTEGER, flag AS BOOLEAN) AS CONDITION\nIF flag THEN\nRETURN Second(n)\nELSE\nRETURN Second(0)\nEND IF\nEND FUNCTION\nCONTRACT Demo()\nEMIT Choose(100, TRUE)\nEND CONTRACT\nFUNCTION Second(n AS INTEGER) AS CONDITION\nRETURN ASSERT_HEIGHT_ABSOLUTE(n)\nEND FUNCTION\nFUNCTION Same(value AS CONDITION) AS CONDITION\nRETURN value\nEND FUNCTION\nFUNCTION Truth() AS BOOLEAN\nRETURN TRUE\nEND FUNCTION\n";
    let analysis = analyze("functions.bas", source.as_bytes()).unwrap();
    assert_eq!(analysis.contract, "Demo");
    assert_eq!(analysis.functions.len(), 4);
    assert_eq!(
        analysis.functions[0].parameters[0].value_type,
        ValueType::Integer
    );
    assert_eq!(
        analysis.functions[0].parameters[1].value_type,
        ValueType::Boolean
    );
    assert_eq!(analysis.functions[0].result, ValueType::Condition);
    assert_eq!(analysis.functions[3].result, ValueType::Boolean);
}

#[test]
fn declarations_are_case_insensitive_and_cannot_shadow_callables() {
    for declarations in [
        "FUNCTION Demo() AS INTEGER\nRETURN 1\nEND FUNCTION\n",
        "FUNCTION F() AS INTEGER\nRETURN 1\nEND FUNCTION\nFUNCTION f() AS BOOLEAN\nRETURN TRUE\nEND FUNCTION\n",
        "FUNCTION F(x AS INTEGER, X AS INTEGER) AS INTEGER\nRETURN x\nEND FUNCTION\n",
        "FUNCTION F(f AS INTEGER) AS INTEGER\nRETURN f\nEND FUNCTION\n",
        "FUNCTION F() AS INTEGER\nDIM demo = 1\nRETURN demo\nEND FUNCTION\n",
        "FUNCTION F(x AS INTEGER) AS INTEGER\nIF TRUE THEN\nDIM x = 2\nEND IF\nRETURN x\nEND FUNCTION\n",
    ] {
        error(&module(declarations), "E0201");
    }
    error(
        "CONTRACT Demo()\nDIM later = 1\nEND CONTRACT\nFUNCTION Later() AS INTEGER\nRETURN 1\nEND FUNCTION\n",
        "E0201",
    );
}

#[test]
fn calls_enforce_arity_types_and_known_names() {
    for (call, code) in [
        ("Missing()", "E0200"),
        ("Helper()", "E0202"),
        ("Helper(1)", "E0202"),
        ("Helper(TRUE, FALSE)", "E0202"),
    ] {
        error(
            &format!(
                "CONTRACT Demo()\nDIM n = {call}\nEND CONTRACT\nFUNCTION Helper(flag AS BOOLEAN) AS INTEGER\nRETURN 1\nEND FUNCTION\n"
            ),
            code,
        );
    }
    error(&function("RETURN flag\n"), "E0202");
    error(&function("DIM n = Demo()\nRETURN 1\n"), "E0200");
    analyze(
        "case.bas",
        function("IF FLAG THEN\nRETURN 1\nELSE\nRETURN 2\nEND IF\n").as_bytes(),
    )
    .unwrap();
}

#[test]
fn immutable_parameters_and_isolated_scopes() {
    error(&function("flag = FALSE\nRETURN 1\n"), "E0203");
    error(&function("CONST n = 1\nn = 2\nRETURN n\n"), "E0203");
    error(
        "CONTRACT Demo()\nDIM secret = 1\nEND CONTRACT\nFUNCTION F() AS INTEGER\nRETURN secret\nEND FUNCTION\n",
        "E0200",
    );
    error(
        &function("IF flag THEN\nDIM hidden = 1\nEND IF\nRETURN hidden\n"),
        "E0200",
    );
    analyze("scope.bas", function("DIM n = 0\nIF flag THEN\nDIM branch = 1\nn = branch\nELSE\nDIM branch = 2\nn = branch\nEND IF\nRETURN n\n").as_bytes()).unwrap();
}

#[test]
fn normal_paths_require_returns_and_assert_false_terminates() {
    for body in [
        "",
        "IF flag THEN\nRETURN 1\nEND IF\n",
        "ASSERT flag\n",
        "IF flag THEN\nRETURN 1\nELSEIF NOT flag THEN\nRETURN 2\nEND IF\n",
    ] {
        error(&function(body), "E0204");
    }
    for body in [
        "RETURN 1\n",
        "ASSERT FALSE\n",
        "IF flag THEN\nRETURN 1\nELSE\nASSERT FALSE\nEND IF\n",
        "CONST yes = TRUE\nIF yes THEN\nRETURN 1\nEND IF\n",
        "IF FALSE THEN\nDIM n = 1\nELSEIF TRUE THEN\nRETURN 2\nEND IF\n",
    ] {
        analyze("returns.bas", function(body).as_bytes()).unwrap();
    }
}

#[test]
fn unreachable_statements_are_still_resolved_and_typed() {
    for body in [
        "RETURN 1\nRETURN unknown\n",
        "ASSERT FALSE\nRETURN unknown\n",
        "IF FALSE THEN\nRETURN unknown\nEND IF\nRETURN 1\n",
    ] {
        error(&function(body), "E0200");
    }
    error(&function("RETURN 1\nRETURN TRUE\n"), "E0202");
    error(&function("RETURN 1\nASSERT FALSE AND Missing()\n"), "E0200");
}

#[test]
fn purity_and_constant_expression_restrictions() {
    error(
        &function("EMIT ASSERT_HEIGHT_ABSOLUTE(1)\nRETURN 1\n"),
        "E0205",
    );
    error(&function("INPUT n AS INTEGER\nRETURN 1\n"), "E0205");
    error("CONTRACT Demo()\nRETURN 1\nEND CONTRACT\n", "E0205");
    for body in [
        "CONST n = Helper(TRUE)\nRETURN n\n",
        "CONST n = flag\nRETURN 1\n",
        "CONST n = FALSE AND (Helper(TRUE) = 1)\nRETURN 1\n",
        "DIM n = 1\nCONST m = n\nRETURN m\n",
    ] {
        error(&function(body), "E0205");
    }
    analyze(
        "const.bas",
        function("CONST n = 4\nCONST m = n * 2\nRETURN m\n").as_bytes(),
    )
    .unwrap();
}

#[test]
fn all_call_edges_participate_in_cycle_detection() {
    error(&function("RETURN Helper(flag)\n"), "E0206");
    error(&function("RETURN 1\nDIM n = Helper(TRUE)\n"), "E0206");
    error(
        &function("IF FALSE THEN\nRETURN Helper(flag)\nEND IF\nRETURN 1\n"),
        "E0206",
    );
    error(
        &module(
            "FUNCTION F() AS INTEGER\nRETURN G()\nEND FUNCTION\nFUNCTION G() AS INTEGER\nRETURN F()\nEND FUNCTION\n",
        ),
        "E0206",
    );
    error(
        &module("FUNCTION F() AS BOOLEAN\nRETURN FALSE AND F()\nEND FUNCTION\n"),
        "E0206",
    );
    analyze("dag.bas", module("FUNCTION F() AS INTEGER\nRETURN G() + G()\nEND FUNCTION\nFUNCTION G() AS INTEGER\nRETURN 1\nEND FUNCTION\n").as_bytes()).unwrap();
}

#[test]
fn module_syntax_and_resource_limits_are_explicit() {
    error("FUNCTION F() AS INTEGER\nRETURN 1\nEND FUNCTION\n", "E0101");
    error(
        "CONTRACT Demo()\nEND CONTRACT\nCONTRACT Other()\nEND CONTRACT\n",
        "E0101",
    );
    error(
        &module("FUNCTION F(n) AS INTEGER\nRETURN n\nEND FUNCTION\n"),
        "E0100",
    );
    error(&module("FUNCTION F()\nRETURN 1\nEND FUNCTION\n"), "E0100");
    let functions: String = (0..256)
        .map(|i| format!("FUNCTION F{i}() AS INTEGER\nRETURN 1\nEND FUNCTION\n"))
        .collect();
    analyze("limit.bas", module(&functions).as_bytes()).unwrap();
    error(
        &module(&format!(
            "{functions}FUNCTION Extra() AS INTEGER\nRETURN 1\nEND FUNCTION\n"
        )),
        "E0205",
    );
    let parameters = (0..33)
        .map(|i| format!("p{i} AS INTEGER"))
        .collect::<Vec<_>>()
        .join(", ");
    error(
        &module(&format!(
            "FUNCTION F({parameters}) AS INTEGER\nRETURN 1\nEND FUNCTION\n"
        )),
        "E0205",
    );
    error(
        &function(&format!("RETURN Helper({})\n", vec!["TRUE"; 33].join(","))),
        "E0205",
    );
}

#[test]
fn branch_return_example_is_analyzed_and_compiled() {
    let source = include_bytes!("../../../examples/m2-function-analysis.bas");
    analyze("example.bas", source).unwrap();
    check("example.bas", source).unwrap();
    compile("example.bas", source).unwrap();
}

#[test]
fn analysis_work_and_statement_limits_are_shared_across_the_module() {
    let predicate = vec!["TRUE"; 32].join(" AND ");
    let assertion = format!("ASSERT {predicate}\n");
    analyze(
        "bounded.bas",
        function(&format!("{}RETURN 1\n", assertion.repeat(1040))).as_bytes(),
    )
    .unwrap();
    error(
        &function(&format!("{}RETURN 1\n", assertion.repeat(1041))),
        "E0205",
    );
    let branch = "IF FALSE THEN\nEND IF\n";
    let functions = format!(
        "FUNCTION F() AS INTEGER\n{}RETURN 1\nEND FUNCTION\nFUNCTION G() AS INTEGER\n{}RETURN 1\nEND FUNCTION\n",
        branch.repeat(128),
        branch.repeat(128)
    );
    analyze("branches.bas", module(&functions).as_bytes()).unwrap();
    error(
        &format!("CONTRACT Demo()\n{branch}END CONTRACT\n{functions}"),
        "E0205",
    );
    let chain: String = (0..256)
        .map(|i| {
            let value = if i == 255 {
                "1".to_owned()
            } else {
                format!("F{}()", i + 1)
            };
            format!("FUNCTION F{i}() AS INTEGER\nRETURN {value}\nEND FUNCTION\n")
        })
        .collect();
    analyze("chain.bas", module(&chain).as_bytes()).unwrap();
}
