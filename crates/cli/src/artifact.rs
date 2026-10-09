use crate::{io, read, read_limited};
use oxbasic_compiler::{self as compiler, Diagnostic, Result, Template, clvm};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{fs, path::Path};

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Compiler {
    version: String,
    rust_version: String,
    cargo_lock_sha256: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Source {
    name: String,
    sha256: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Artifact {
    binary: String,
    hex: String,
    program_sha256: String,
    tree_hash: String,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema_version: u32,
    compiler: Compiler,
    language_version: String,
    abi_version: u32,
    target_profile: String,
    optimization: String,
    source: Source,
    contract: String,
    fixed_parameters: Vec<compiler::abi::Field>,
    inputs: Vec<compiler::abi::Field>,
    #[serde(deserialize_with = "required_option")]
    bindings: Option<compiler::abi::BoundaryObject>,
    template: Artifact,
    #[serde(deserialize_with = "required_option")]
    puzzle: Option<Artifact>,
}
fn required_option<'de, D: serde::Deserializer<'de>, T: Deserialize<'de>>(
    d: D,
) -> std::result::Result<Option<T>, D::Error> {
    Option::deserialize(d)
}
fn description(stem: &str, bytes: &[u8]) -> Result<Artifact> {
    Ok(Artifact {
        binary: format!("{stem}.clvm"),
        hex: format!("{stem}.hex"),
        program_sha256: clvm::sha256(bytes),
        tree_hash: clvm::tree_hash(bytes)?,
    })
}
fn write_artifact(dir: &Path, stem: &str, bytes: &[u8]) -> Result<()> {
    fs::write(dir.join(format!("{stem}.clvm")), bytes).map_err(io)?;
    fs::write(
        dir.join(format!("{stem}.hex")),
        format!("{}\n", hex::encode(bytes)),
    )
    .map_err(io)
}
pub fn build(
    name: &str,
    source: &[u8],
    compiled: &Template,
    out: &Path,
    bound: Option<&compiler::BoundProgram>,
) -> Result<Value> {
    if out.symlink_metadata().is_ok() {
        return Err(io("Output directory already exists"));
    }
    let parent = out
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let parent = parent.canonicalize().map_err(io)?;
    let filename = out
        .file_name()
        .ok_or_else(|| io("Output must name a new directory"))?;
    let destination = parent.join(filename);
    let stage = tempfile::Builder::new()
        .prefix(".0xbasic-")
        .tempdir_in(&parent)
        .map_err(io)?;
    let manifest = Manifest {
        schema_version: 1,
        compiler: Compiler {
            version: compiler::COMPILER_VERSION.into(),
            rust_version: env!("OXBASIC_RUST_VERSION").into(),
            cargo_lock_sha256: env!("OXBASIC_LOCK_SHA256").into(),
        },
        language_version: compiler::LANGUAGE_VERSION.into(),
        abi_version: compiler::ABI_VERSION,
        target_profile: compiler::TARGET_PROFILE.into(),
        optimization: "none".into(),
        source: Source {
            name: name.into(),
            sha256: clvm::sha256(source),
        },
        contract: compiled.contract.name.clone(),
        fixed_parameters: compiled.contract.fixed.clone(),
        inputs: compiled.contract.inputs.clone(),
        bindings: bound.map(|b| b.bindings.clone()),
        template: description("template", &compiled.template)?,
        puzzle: bound
            .map(|b| description("puzzle", &b.puzzle))
            .transpose()?,
    };
    write_artifact(stage.path(), "template", &compiled.template)?;
    if let Some(bound) = bound {
        write_artifact(stage.path(), "puzzle", &bound.puzzle)?;
    }
    let mut bytes = serde_json::to_vec_pretty(&manifest).map_err(io)?;
    bytes.push(b'\n');
    if bytes.len() > 1_048_576 {
        return Err(io("Manifest exceeds the 1048576-byte reader limit"));
    }
    fs::write(stage.path().join("manifest.json"), bytes).map_err(io)?;
    publish(stage.path(), &destination)?;
    Ok(json!({"manifest":"manifest.json", "template":manifest.template,"puzzle":manifest.puzzle}))
}
#[cfg(target_os = "linux")]
fn publish(stage: &Path, destination: &Path) -> Result<()> {
    rustix::fs::renameat_with(
        rustix::fs::CWD,
        stage,
        rustix::fs::CWD,
        destination,
        rustix::fs::RenameFlags::NOREPLACE,
    )
    .map_err(io)
}
#[cfg(target_os = "windows")]
fn publish(stage: &Path, destination: &Path) -> Result<()> {
    fs::rename(stage, destination).map_err(io)
}
#[cfg(not(any(target_os = "linux", target_os = "windows")))]
fn publish(_: &Path, _: &Path) -> Result<()> {
    Err(io(
        "Atomic build publishing currently supports Windows and Linux",
    ))
}

fn hash_valid(text: &str) -> bool {
    text.len() == 64
        && text
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn load_artifact(dir: &Path, entry: &Artifact, stem: &str) -> Result<Vec<u8>> {
    if entry.binary != format!("{stem}.clvm")
        || entry.hex != format!("{stem}.hex")
        || !hash_valid(&entry.program_sha256)
        || !hash_valid(&entry.tree_hash)
    {
        return Err(io("Invalid artifact path or digest"));
    }
    let mut contents = Vec::new();
    for name in [&entry.binary, &entry.hex] {
        let path = dir.join(name).canonicalize().map_err(io)?;
        if !path.starts_with(dir) {
            return Err(io("Artifact resolves outside the manifest directory"));
        }
        let limit = if name == &entry.hex {
            clvm::MAX_PROGRAM_BYTES * 2 + 1
        } else {
            clvm::MAX_PROGRAM_BYTES
        };
        contents.push(read_limited(&path, limit)?);
    }
    let bytes = contents.remove(0);
    if contents[0] != format!("{}\n", hex::encode(&bytes)).as_bytes() {
        return Err(io("Artifact binary and canonical hex file disagree"));
    }
    if clvm::sha256(&bytes) != entry.program_sha256 || clvm::tree_hash(&bytes)? != entry.tree_hash {
        return Err(io("Artifact digest mismatch"));
    }
    Ok(bytes)
}
pub struct Loaded {
    pub puzzle: Vec<u8>,
    pub inputs: Vec<compiler::abi::Field>,
}
pub fn load(path: &Path) -> Result<Loaded> {
    let bytes = read(path)?;
    // Deserialize into structs directly: duplicate and unknown fields are errors.
    let manifest: Manifest = compiler::abi::decode_json(&bytes).map_err(|e| io(e.message))?;
    if manifest.schema_version != 1
        || manifest.language_version != compiler::LANGUAGE_VERSION
        || manifest.abi_version != compiler::ABI_VERSION
        || manifest.target_profile != compiler::TARGET_PROFILE
        || manifest.optimization != "none"
        || manifest.compiler.version != compiler::COMPILER_VERSION
    {
        return Err(Diagnostic::new(
            "E0400",
            "Unsupported manifest/compiler/language/ABI/target profile",
        ));
    }
    if manifest.compiler.rust_version != env!("OXBASIC_RUST_VERSION")
        || !hash_valid(&manifest.compiler.cargo_lock_sha256)
        || !hash_valid(&manifest.source.sha256)
    {
        return Err(io("Invalid manifest provenance fields"));
    }
    let source_name = Path::new(&manifest.source.name);
    if manifest.source.name.contains(['/', '\\'])
        || source_name
            .extension()
            .and_then(|v| v.to_str())
            .is_none_or(|v| !v.eq_ignore_ascii_case("bas"))
    {
        return Err(io("Invalid source basename"));
    }
    let mut chars = manifest.contract.bytes();
    if !chars.next().is_some_and(|c| c.is_ascii_lowercase())
        || !chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == b'_')
    {
        return Err(io("Invalid normalized contract name"));
    }
    compiler::abi::validate_schemas(&manifest.fixed_parameters, &manifest.inputs)
        .map_err(|e| io(e.message))?;
    let Some(puzzle_entry) = manifest.puzzle else {
        return Err(Diagnostic::new(
            "E0400",
            "Cannot run a template-only manifest; build a bound puzzle first",
        ));
    };
    let bindings = manifest
        .bindings
        .ok_or_else(|| io("Bound manifest requires bindings"))?;
    let encoded = compiler::abi::encode_bindings(
        &manifest.fixed_parameters,
        &serde_json::to_vec(&bindings).map_err(io)?,
    )
    .map_err(|e| io(e.message))?;
    // Normalized names and values are mandatory; JSON object order is not significant on read.
    let actual: std::collections::BTreeMap<_, _> = bindings.0.into_iter().collect();
    let normalized: std::collections::BTreeMap<_, _> = encoded.normalized.0.into_iter().collect();
    if actual != normalized {
        return Err(io("Manifest bindings are not normalized"));
    }
    let dir = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."))
        .canonicalize()
        .map_err(io)?;
    let template = load_artifact(&dir, &manifest.template, "template")?;
    let puzzle = load_artifact(&dir, &puzzle_entry, "puzzle")?;
    if clvm::bind_fixed(&template, &encoded.bytes).map_err(|e| io(e.message))? != puzzle {
        return Err(io("Puzzle does not match the ABI binding of its template"));
    }
    Ok(Loaded {
        puzzle,
        inputs: manifest.inputs,
    })
}
