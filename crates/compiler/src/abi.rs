//! Host recursive boundary encoding. Runtime validation is generated independently.
use crate::{Diagnostic, Result};
use serde::{
    Deserialize, Serialize,
    de::{self, MapAccess, SeqAccess, Visitor},
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
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind")]
pub enum SchemaType {
    #[serde(rename = "LIST")]
    List { element: Box<SchemaType> },
    #[serde(rename = "PUBLICKEY")]
    PublicKey,
    #[serde(rename = "AMOUNT")]
    Amount,
    #[serde(rename = "PUZZLEHASH")]
    PuzzleHash,
    #[serde(rename = "INTEGER")]
    Integer,
    #[serde(rename = "BOOLEAN")]
    Boolean,
    #[serde(rename = "BYTES")]
    Bytes,
    #[serde(rename = "STRING")]
    String,
    #[serde(rename = "PAIR")]
    Pair {
        first: Box<SchemaType>,
        rest: Box<SchemaType>,
    },
}
impl<'de> Deserialize<'de> for SchemaType {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct SchemaVisitor;
        impl<'de> Visitor<'de> for SchemaVisitor {
            type Value = SchemaType;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("a supported boundary type schema")
            }
            fn visit_map<M: MapAccess<'de>>(
                self,
                mut map: M,
            ) -> std::result::Result<Self::Value, M::Error> {
                let (mut kind, mut first, mut rest, mut element) = (None, None, None, None);
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "kind" if kind.is_none() => kind = Some(map.next_value::<String>()?),
                        "element" if element.is_none() => {
                            element = Some(map.next_value::<Box<SchemaType>>()?)
                        }
                        "first" if first.is_none() => {
                            first = Some(map.next_value::<Box<SchemaType>>()?)
                        }
                        "rest" if rest.is_none() => {
                            rest = Some(map.next_value::<Box<SchemaType>>()?)
                        }
                        _ => return Err(de::Error::custom("Duplicate or unknown schema member")),
                    }
                }
                if kind.as_deref() == Some("LIST") {
                    if first.is_some() || rest.is_some() {
                        return Err(de::Error::custom(
                            "LIST schema cannot contain pair children",
                        ));
                    }
                    return Ok(SchemaType::List {
                        element: element.ok_or_else(|| de::Error::missing_field("element"))?,
                    });
                }
                if element.is_some() {
                    return Err(de::Error::custom("Only LIST schemas have an element"));
                }
                if kind.as_deref() == Some("PAIR") {
                    return Ok(SchemaType::Pair {
                        first: first.ok_or_else(|| de::Error::missing_field("first"))?,
                        rest: rest.ok_or_else(|| de::Error::missing_field("rest"))?,
                    });
                }
                if first.is_some() || rest.is_some() {
                    return Err(de::Error::custom("Scalar schema cannot contain children"));
                }
                match kind.as_deref() {
                    Some("PUBLICKEY") => Ok(SchemaType::PublicKey),
                    Some("AMOUNT") => Ok(SchemaType::Amount),
                    Some("PUZZLEHASH") => Ok(SchemaType::PuzzleHash),
                    Some("INTEGER") => Ok(SchemaType::Integer),
                    Some("BOOLEAN") => Ok(SchemaType::Boolean),
                    Some("BYTES") => Ok(SchemaType::Bytes),
                    Some("STRING") => Ok(SchemaType::String),
                    _ => Err(de::Error::custom("Unsupported or missing boundary kind")),
                }
            }
        }
        d.deserialize_map(SchemaVisitor)
    }
}
impl SchemaType {
    fn from_type(ty: &crate::ValueType, depth: usize, nodes: &mut usize) -> Result<Self> {
        charge_type(depth, nodes)?;
        Ok(match ty {
            crate::ValueType::PublicKey => Self::PublicKey,
            crate::ValueType::Amount => Self::Amount,
            crate::ValueType::PuzzleHash => Self::PuzzleHash,
            crate::ValueType::Integer => Self::Integer,
            crate::ValueType::Boolean => Self::Boolean,
            crate::ValueType::Bytes => Self::Bytes,
            crate::ValueType::String => Self::String,
            crate::ValueType::List(element) => Self::List {
                element: Box::new(Self::from_type(element, depth + 1, nodes)?),
            },
            crate::ValueType::Pair(a, b) => Self::Pair {
                first: Box::new(Self::from_type(a, depth + 1, nodes)?),
                rest: Box::new(Self::from_type(b, depth + 1, nodes)?),
            },
            _ => return Err(Diagnostic::new("E0205", "Unsupported boundary type")),
        })
    }
    fn measure(&self, depth: usize, nodes: &mut usize) -> Result<()> {
        charge_type(depth, nodes)?;
        if let Self::List { element } = self {
            element.measure(depth + 1, nodes)?;
        }
        if let Self::Pair { first, rest } = self {
            first.measure(depth + 1, nodes)?;
            rest.measure(depth + 1, nodes)?;
        }
        Ok(())
    }
}
fn charge_type(depth: usize, nodes: &mut usize) -> Result<()> {
    if depth > 32 || *nodes >= 1024 {
        return Err(Diagnostic::new(
            "E0300",
            "Boundary type exceeds depth 32 or 1024 nodes",
        ));
    }
    *nodes += 1;
    Ok(())
}
impl Field {
    pub(crate) fn from_type(name: String, ty: &crate::ValueType) -> Result<Self> {
        Ok(Self {
            name,
            value_type: SchemaType::from_type(ty, 0, &mut 0)?,
        })
    }
}

/// Bound JSON nesting before serde recursion, counting containers outside strings.
/// Serde still checks syntax, duplicate members and its own recursion limit.
pub fn decode_json<T: serde::de::DeserializeOwned>(json: &[u8]) -> Result<T> {
    if json.len() > 1048576 {
        return Err(Diagnostic::new(
            "E0300",
            "Boundary JSON exceeds 1048576 bytes",
        ));
    }
    let (mut depth, mut quoted, mut escaped) = (0usize, false, false);
    for &b in json {
        if quoted {
            if escaped {
                escaped = false;
            } else if b == b'\\' {
                escaped = true;
            } else if b == b'"' {
                quoted = false;
            }
        } else {
            match b {
                b'"' => quoted = true,
                b'{' | b'[' => {
                    depth += 1;
                    if depth > 96 {
                        return Err(Diagnostic::new(
                            "E0300",
                            "JSON nesting exceeds 96 containers",
                        ));
                    }
                }
                b'}' | b']' => depth = depth.saturating_sub(1),
                _ => {}
            }
        }
    }
    serde_json::from_slice(json).map_err(|e| Diagnostic::new("E0300", e.to_string()))
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
        field.value_type.measure(0, &mut 0)?;
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
pub struct BoundaryObject(pub Vec<(String, BoundaryValue)>);

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HexValue {
    pub hex: String,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum BoundaryValue {
    List(Vec<BoundaryValue>),
    Pair {
        first: Box<BoundaryValue>,
        rest: Box<BoundaryValue>,
    },
    Text(String),
    Boolean(bool),
    Bytes(HexValue),
}
impl<'de> Deserialize<'de> for BoundaryValue {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct ValueVisitor;
        impl<'de> Visitor<'de> for ValueVisitor {
            type Value = BoundaryValue;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("a string, boolean, hex/pair object, or array")
            }
            fn visit_str<E: de::Error>(self, v: &str) -> std::result::Result<Self::Value, E> {
                Ok(BoundaryValue::Text(v.to_owned()))
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> std::result::Result<Self::Value, E> {
                Ok(BoundaryValue::Boolean(v))
            }
            fn visit_seq<S: SeqAccess<'de>>(
                self,
                mut seq: S,
            ) -> std::result::Result<Self::Value, S::Error> {
                let mut values = Vec::new();
                while let Some(value) = seq.next_element::<BoundaryValue>()? {
                    if values.len() >= 32767 {
                        return Err(de::Error::custom("Array exceeds boundary tree node budget"));
                    }
                    values.push(value);
                }
                Ok(BoundaryValue::List(values))
            }
            fn visit_map<M: MapAccess<'de>>(
                self,
                mut map: M,
            ) -> std::result::Result<Self::Value, M::Error> {
                let (mut hex, mut first, mut rest) = (None, None, None);
                while let Some(key) = map.next_key::<String>()? {
                    match key.as_str() {
                        "hex" if hex.is_none() && first.is_none() && rest.is_none() => {
                            hex = Some(map.next_value::<String>()?)
                        }
                        "first" if first.is_none() && hex.is_none() => {
                            first = Some(map.next_value::<Box<BoundaryValue>>()?)
                        }
                        "rest" if rest.is_none() && hex.is_none() => {
                            rest = Some(map.next_value::<Box<BoundaryValue>>()?)
                        }
                        _ => {
                            return Err(de::Error::custom(
                                "Duplicate, mixed or unknown boundary value member",
                            ));
                        }
                    }
                }
                if let Some(hex) = hex {
                    return Ok(BoundaryValue::Bytes(HexValue { hex }));
                }
                Ok(BoundaryValue::Pair {
                    first: first.ok_or_else(|| de::Error::missing_field("first"))?,
                    rest: rest.ok_or_else(|| de::Error::missing_field("rest"))?,
                })
            }
        }
        d.deserialize_any(ValueVisitor)
    }
}
impl Serialize for BoundaryObject {
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
    pub normalized: BoundaryObject,
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
impl<'de> Deserialize<'de> for BoundaryObject {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct ObjectVisitor;
        impl<'de> Visitor<'de> for ObjectVisitor {
            type Value = BoundaryObject;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("an object of typed boundary values")
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
                    // Recursive visitors retain duplicate-member detection at every pair level.
                    values.push((key, map.next_value::<BoundaryValue>()?));
                }
                Ok(BoundaryObject(values))
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
    let BoundaryObject(values) = decode_json(json)?;
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
    let mut nodes = fields.len() + 1; // outer proper-list spine and nil tail
    for field in fields {
        let value = values
            .remove(&field.name)
            .ok_or_else(|| invalid(format!("Missing field: {}", field.name)))?;
        let (node, value) = encode_value(
            &mut allocator,
            &field.value_type,
            value,
            &field.name,
            &mut nodes,
        )?;
        normalized.push((field.name.clone(), value));
        atoms.push(node);
    }
    let mut tail = clvmr::NodePtr::NIL;
    for atom in atoms.into_iter().rev() {
        tail = allocator
            .new_pair(atom, tail)
            .map_err(|e| invalid(e.to_string()))?;
    }
    // encode_value charges all pair/atom nodes before allocation.
    let bytes = clvmr::serde::node_to_bytes_limit(&allocator, tail, 1048576)
        .map_err(|e| invalid(e.to_string()))?;
    Ok(EncodedBindings {
        bytes,
        normalized: BoundaryObject(normalized),
    })
}

fn encode_value(
    allocator: &mut clvmr::Allocator,
    schema: &SchemaType,
    value: BoundaryValue,
    name: &str,
    nodes: &mut usize,
) -> Result<(clvmr::NodePtr, BoundaryValue)> {
    let invalid = |message| Diagnostic::new("E0300", message);
    if *nodes >= 65536 {
        return Err(invalid(
            "Boundary value exceeds 65536 tree nodes".to_owned(),
        ));
    }
    *nodes += 1;
    let (bytes, value) = match (schema, value) {
        (SchemaType::Integer | SchemaType::Amount, BoundaryValue::Text(text)) => {
            let digits = text.strip_prefix('-').unwrap_or(&text);
            if text != "0"
                && (digits.is_empty()
                    || digits.starts_with('0')
                    || !digits.bytes().all(|b| b.is_ascii_digit()))
            {
                return Err(invalid(format!(
                    "Field {} requires a canonical decimal string",
                    name
                )));
            }
            let n = num_bigint::BigInt::parse_bytes(text.as_bytes(), 10)
                .ok_or_else(|| invalid("Invalid INTEGER".to_owned()))?;
            if matches!(schema, SchemaType::Amount) && (n < 0.into() || n > u64::MAX.into()) {
                return Err(invalid("AMOUNT must be in 0..2^64-1".to_owned()));
            }
            let bytes = if n == num_bigint::BigInt::from(0) {
                vec![]
            } else {
                n.to_signed_bytes_be()
            };
            (bytes, BoundaryValue::Text(text))
        }
        (SchemaType::String, BoundaryValue::Text(text)) => {
            // serde's String decoder rejects invalid UTF-8 and unpaired surrogates.
            // Preserve scalar sequences exactly, including NUL and normalization form.
            (text.as_bytes().to_vec(), BoundaryValue::Text(text))
        }
        (SchemaType::Boolean, BoundaryValue::Boolean(v)) => {
            (if v { vec![1] } else { vec![] }, BoundaryValue::Boolean(v))
        }
        (
            SchemaType::Bytes | SchemaType::PuzzleHash | SchemaType::PublicKey,
            BoundaryValue::Bytes(v),
        ) => {
            let bytes = hex::decode(&v.hex).map_err(|_| {
                invalid(format!(
                    "Field {} requires even-length hex without a prefix",
                    name
                ))
            })?;
            if matches!(schema, SchemaType::PuzzleHash) && bytes.len() != 32 {
                return Err(invalid("PUZZLEHASH requires exactly 32 bytes".to_owned()));
            }
            if matches!(schema, SchemaType::PublicKey) {
                let array: &[u8; 48] = bytes
                    .as_slice()
                    .try_into()
                    .map_err(|_| invalid("PUBLICKEY requires exactly 48 bytes".to_owned()))?;
                let key = chia_bls::PublicKey::from_bytes(array).map_err(|_| {
                    invalid("PUBLICKEY requires a canonical subgroup-valid key".to_owned())
                })?;
                if key.is_inf() || key.to_bytes() != *array {
                    return Err(invalid(
                        "PUBLICKEY must be canonical and non-infinity".to_owned(),
                    ));
                }
            }
            let normalized = BoundaryValue::Bytes(HexValue {
                hex: hex::encode(&bytes),
            });
            (bytes, normalized)
        }
        (SchemaType::List { element }, BoundaryValue::List(values)) => {
            // The entry charge accounts for the nil tail. Flat spines use loops;
            // recursion only follows the already bounded element schema.
            let mut encoded = Vec::new();
            let mut normalized = Vec::new();
            for value in values {
                if *nodes >= 65536 {
                    return Err(invalid(
                        "Boundary value exceeds 65536 tree nodes".to_owned(),
                    ));
                }
                *nodes += 1; // list cons cell, charged before allocation
                let (node, normalized_value) =
                    encode_value(allocator, element, value, name, nodes)?;
                encoded.push(node);
                normalized.push(normalized_value);
            }
            let mut tail = clvmr::NodePtr::NIL;
            for node in encoded.into_iter().rev() {
                tail = allocator
                    .new_pair(node, tail)
                    .map_err(|e| invalid(e.to_string()))?;
            }
            return Ok((tail, BoundaryValue::List(normalized)));
        }
        (SchemaType::Pair { first, rest }, BoundaryValue::Pair { first: a, rest: b }) => {
            let (a, na) = encode_value(allocator, first, *a, name, nodes)?;
            let (b, nb) = encode_value(allocator, rest, *b, name, nodes)?;
            let pair = allocator
                .new_pair(a, b)
                .map_err(|e| invalid(e.to_string()))?;
            return Ok((
                pair,
                BoundaryValue::Pair {
                    first: Box::new(na),
                    rest: Box::new(nb),
                },
            ));
        }
        _ => {
            return Err(invalid(format!(
                "Field {} has the wrong JSON value type",
                name
            )));
        }
    };
    let node = allocator
        .new_atom(&bytes)
        .map_err(|e| invalid(e.to_string()))?;
    Ok((node, value))
}
