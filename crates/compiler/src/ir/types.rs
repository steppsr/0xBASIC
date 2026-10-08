//! Recursive checked types. Source collection syntax remains gated until M2-7b2/3.
use crate::{Diagnostic, Result, Span};
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub enum ValueType {
    String,
    Bytes,
    Integer,
    Boolean,
    Condition,
    List(Box<ValueType>),
    Pair(Box<ValueType>, Box<ValueType>),
    /// Never a source type: branch bundles and return states only.
    Internal,
}
impl ValueType {
    pub(super) fn label(&self) -> String {
        match self {
            Self::List(t) => format!("LIST OF {}", t.label()),
            Self::Pair(a, b) => format!("PAIR OF ({}, {})", a.label(), b.label()),
            Self::String => "STRING".into(),
            Self::Bytes => "BYTES".into(),
            Self::Integer => "INTEGER".into(),
            Self::Boolean => "BOOLEAN".into(),
            Self::Condition => "CONDITION".into(),
            Self::Internal => "<internal>".into(),
        }
    }
}

// Prepared for the shared annotation parser and inferred constructors in later slices.
// Each constructor checks borrowed children before cloning them into a parent.
#[derive(Default, Clone)]
pub(crate) struct TypeBudget {
    nodes: usize,
}
impl TypeBudget {
    fn measure(ty: &ValueType, depth: usize, nodes: &mut usize) -> bool {
        if depth > 32 || *nodes >= 1024 {
            return false;
        }
        *nodes += 1;
        match ty {
            ValueType::List(t) => Self::measure(t, depth + 1, nodes),
            ValueType::Pair(a, b) => {
                Self::measure(a, depth + 1, nodes) && Self::measure(b, depth + 1, nodes)
            }
            ValueType::Internal => false,
            _ => true,
        }
    }
    fn charge(&mut self, children: &[&ValueType], source: &str, span: Span) -> Result<()> {
        let mut nodes = 1;
        if !children.iter().all(|t| Self::measure(t, 1, &mut nodes))
            || nodes > 65536usize.saturating_sub(self.nodes)
        {
            return Err(Diagnostic::at(
                "E0205",
                "Collection types exceed depth 32, 1024 nodes per type, or 65536 constructed nodes per module (internal types are forbidden)",
                source,
                span,
            ));
        }
        self.nodes += nodes;
        Ok(())
    }
    pub(crate) fn list(
        &mut self,
        element: &ValueType,
        source: &str,
        span: Span,
    ) -> Result<ValueType> {
        self.charge(&[element], source, span)?;
        Ok(ValueType::List(Box::new(element.clone())))
    }
    pub(crate) fn pair(
        &mut self,
        left: &ValueType,
        right: &ValueType,
        source: &str,
        span: Span,
    ) -> Result<ValueType> {
        self.charge(&[left, right], source, span)?;
        Ok(ValueType::Pair(
            Box::new(left.clone()),
            Box::new(right.clone()),
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn span() -> Span {
        Span {
            start_byte: 0,
            end_byte: 1,
            line: 1,
            column: 1,
        }
    }
    fn tree(level: usize) -> ValueType {
        if level == 0 {
            ValueType::Integer
        } else {
            ValueType::Pair(Box::new(tree(level - 1)), Box::new(tree(level - 1)))
        }
    }
    #[test]
    fn scalar_serialization_labels_and_nested_types_are_stable() {
        for (ty, json, label) in [
            (ValueType::Integer, "Integer", "INTEGER"),
            (ValueType::Boolean, "Boolean", "BOOLEAN"),
            (ValueType::Bytes, "Bytes", "BYTES"),
            (ValueType::String, "String", "STRING"),
            (ValueType::Condition, "Condition", "CONDITION"),
            (ValueType::Internal, "Internal", "<internal>"),
        ] {
            assert_eq!(serde_json::to_value(&ty).unwrap(), serde_json::json!(json));
            assert_eq!(ty.label(), label);
        }
        let mut b = TypeBudget::default();
        let list = b.list(&ValueType::Integer, "types", span()).unwrap();
        let pair = b.pair(&list, &ValueType::Bytes, "types", span()).unwrap();
        assert_eq!(pair.label(), "PAIR OF (LIST OF INTEGER, BYTES)");
        assert_eq!(pair, pair.clone());
        assert_ne!(list, b.list(&ValueType::Boolean, "types", span()).unwrap());
    }
    #[test]
    fn type_depth_boundary_is_checked_before_construction() {
        let mut b = TypeBudget::default();
        let mut ty = ValueType::Integer;
        for _ in 0..32 {
            ty = b.list(&ty, "depth", span()).unwrap();
        }
        let before = b.nodes;
        let error = b.list(&ty, "depth", span()).unwrap_err();
        assert_eq!(error.code, "E0205");
        assert_eq!(error.span.unwrap().start_byte, 0);
        assert_eq!(b.nodes, before);
    }
    #[test]
    fn per_type_nodes_and_inferred_pair_growth_are_bounded() {
        let mut b = TypeBudget::default();
        let mut ty = ValueType::Integer;
        for _ in 0..9 {
            ty = b.pair(&ty, &ty, "growth", span()).unwrap();
        }
        // 1023 nodes are accepted; parent list reaches exactly 1024.
        let full = b.list(&ty, "growth", span()).unwrap();
        assert!(b.list(&full, "growth", span()).is_err());
        assert!(b.pair(&ty, &ty, "growth", span()).is_err());
    }
    #[test]
    fn cumulative_construction_budget_accepts_exact_boundary() {
        let child = tree(9);
        let mut b = TypeBudget::default();
        for _ in 0..64 {
            b.list(&child, "budget", span()).unwrap();
        }
        assert_eq!(b.nodes, 65536);
        assert_eq!(
            b.list(&ValueType::Integer, "budget", span())
                .unwrap_err()
                .code,
            "E0205"
        );
        assert_eq!(b.nodes, 65536);
    }
    #[test]
    fn compiler_internal_types_cannot_be_collection_components() {
        let mut b = TypeBudget::default();
        let hidden = ValueType::List(Box::new(ValueType::Internal));
        assert!(b.list(&hidden, "internal", span()).is_err());
        assert!(
            b.pair(
                &ValueType::Integer,
                &ValueType::Internal,
                "internal",
                span()
            )
            .is_err()
        );
        assert_eq!(b.nodes, 0);
        // Local CONDITION containment is allowed; ABI exclusions come later.
        b.list(&ValueType::Condition, "condition", span()).unwrap();
    }
}
