use oxbasic_compiler::{analyze, check};
#[test]
fn collection_operations_reject_scalar_operands() {
    for body in ["DIM n = LIST_LENGTH(1)\n", "DIM n = CONS(1,1)\n"] {
        let source = format!("CONTRACT Demo()\n{body}END CONTRACT\n");
        assert_eq!(
            check("gate.bas", source.as_bytes()).unwrap_err().code,
            "E0202",
            "{body}"
        );
        assert_eq!(
            analyze("gate.bas", source.as_bytes()).unwrap_err().code,
            "E0202",
            "{body}"
        );
    }
}
