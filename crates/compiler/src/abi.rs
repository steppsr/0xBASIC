//! Host INTEGER solution encoding. Runtime validation is generated independently.
use crate::{Diagnostic, Result};
use serde::{
    Deserialize, Serialize,
    de::{self, MapAccess, Visitor},
};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Field {
    pub name: String,
    #[serde(rename = "type")]
    pub value_type: SchemaType,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SchemaType {
    pub kind: IntegerKind,
}
#[derive(Debug, Clone, Serialize)]
pub enum IntegerKind {
    #[serde(rename = "INTEGER")]
    Integer,
}
impl<'de> Deserialize<'de> for IntegerKind {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        let kind = String::deserialize(d)?;
        if kind == "INTEGER" {
            Ok(Self::Integer)
        } else {
            Err(de::Error::custom(
                "Only INTEGER boundary schemas are implemented",
            ))
        }
    }
}
impl Field {
    pub(crate) fn integer(name: String) -> Self {
        Self {
            name,
            value_type: SchemaType {
                kind: IntegerKind::Integer,
            },
        }
    }
}
pub fn validate_fields(fields: &[Field]) -> Result<()> {
    let mut names = BTreeSet::new();
    if fields.len() > 32 {
        return Err(Diagnostic::new(
            "E0300",
            "At most 32 boundary fields are supported",
        ));
    }
    for field in fields {
        let mut chars = field.name.bytes();
        if !chars.next().is_some_and(|c| c.is_ascii_lowercase())
            || !chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_')
            || !names.insert(&field.name)
        {
            return Err(Diagnostic::new(
                "E0300",
                "Invalid or duplicate normalized boundary field name",
            ));
        }
    }
    Ok(())
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IntegerObject(pub Vec<(String, String)>);
impl Serialize for IntegerObject {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        use serde::ser::SerializeMap;
        let mut map = s.serialize_map(Some(self.0.len()))?;
        for (key, value) in &self.0 {
            map.serialize_entry(key, value)?;
        }
        map.end()
    }
}
pub struct EncodedBindings {
    pub bytes: Vec<u8>,
    pub normalized: IntegerObject,
}
pub fn validate_schemas(fixed: &[Field], inputs: &[Field]) -> Result<()> {
    validate_fields(fixed)?;
    validate_fields(inputs)?;
    if fixed
        .iter()
        .any(|f| inputs.iter().any(|i| i.name == f.name))
    {
        return Err(Diagnostic::new("E0300", "Fixed and input names overlap"));
    }
    Ok(())
}
impl<'de> Deserialize<'de> for IntegerObject {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct ObjectVisitor;
        impl<'de> Visitor<'de> for ObjectVisitor {
            type Value = IntegerObject;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("an object of INTEGER decimal strings")
            }
            fn visit_map<M: MapAccess<'de>>(
                self,
                mut map: M,
            ) -> std::result::Result<Self::Value, M::Error> {
                let mut values = Vec::new();
                let mut names = BTreeSet::new();
                while let Some(key) = map.next_key::<String>()? {
                    if !names.insert(key.to_ascii_lowercase()) {
                        return Err(de::Error::custom(
                            "Duplicate or case-colliding boundary key",
                        ));
                    }
                    if values.len() == 32 {
                        return Err(de::Error::custom(
                            "At most 32 boundary fields are supported",
                        ));
                    }
                    // A string is required immediately; nested arrays/objects cannot consume unbounded recursion.
                    values.push((key, map.next_value::<String>()?));
                }
                Ok(IntegerObject(values))
            }
        }
        d.deserialize_map(ObjectVisitor)
    }
}
pub fn encode_solution(fields: &[Field], json: &[u8]) -> Result<Vec<u8>> {
    Ok(encode_fields(fields, json)?.bytes)
}
pub fn encode_bindings(fields: &[Field], json: &[u8]) -> Result<EncodedBindings> {
    encode_fields(fields, json).map_err(|mut e| {
        e.code = "E0301";
        e
    })
}
fn encode_fields(fields: &[Field], json: &[u8]) -> Result<EncodedBindings> {
    validate_fields(fields)?;
    let invalid = |message| Diagnostic::new("E0300", message);
    if json.len() > 1048576 {
        return Err(invalid("Boundary JSON exceeds 1048576 bytes".to_owned()));
    }
    let IntegerObject(values) = serde_json::from_slice(json).map_err(|e| invalid(e.to_string()))?;
    let mut values: BTreeMap<_, _> = values
        .into_iter()
        .map(|(k, v)| (k.to_ascii_lowercase(), v))
        .collect();
    let mut normalized = Vec::new();
    if values.len() != fields.len() {
        return Err(invalid("Missing or extra boundary fields".to_owned()));
    }
    let mut allocator = clvmr::Allocator::new();
    let mut atoms = Vec::new();
    for field in fields {
        let text = values
            .remove(&field.name)
            .ok_or_else(|| invalid(format!("Missing field: {}", field.name)))?;
        normalized.push((field.name.clone(), text.clone()));
        let digits = text.strip_prefix('-').unwrap_or(&text);
        if text != "0"
            && (digits.is_empty()
                || digits.starts_with('0')
                || !digits.bytes().all(|b| b.is_ascii_digit()))
        {
            return Err(invalid(format!(
                "Field {} requires a canonical decimal string",
                field.name
            )));
        }
        let n = num_bigint::BigInt::parse_bytes(text.as_bytes(), 10)
            .ok_or_else(|| invalid("Invalid INTEGER".to_owned()))?;
        let bytes = if n == num_bigint::BigInt::from(0) {
            vec![]
        } else {
            n.to_signed_bytes_be()
        };
        atoms.push(
            allocator
                .new_atom(&bytes)
                .map_err(|e| invalid(e.to_string()))?,
        );
    }
    let mut tail = clvmr::NodePtr::NIL;
    for atom in atoms.into_iter().rev() {
        tail = allocator
            .new_pair(atom, tail)
            .map_err(|e| invalid(e.to_string()))?;
    }
    // INTEGER-only schemas have at most 65 tree nodes, below the general host limit.
    let bytes = clvmr::serde::node_to_bytes_limit(&allocator, tail, 1048576)
        .map_err(|e| invalid(e.to_string()))?;
    Ok(EncodedBindings {
        bytes,
        normalized: IntegerObject(normalized),
    })
}
