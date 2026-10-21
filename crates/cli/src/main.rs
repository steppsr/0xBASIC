mod artifact;

use oxbasic_compiler::{self as compiler, Diagnostic, Result, clvm};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

struct Args {
    command: String,
    path: PathBuf,
    options: BTreeMap<String, String>,
}
impl Args {
    fn parse(args: &[String]) -> Result<Self> {
        let command = args
            .first()
            .ok_or_else(|| usage("Expected check, build, run, or explain"))?
            .clone();
        let allowed: &[&str] = match command.as_str() {
            "check" => &[],
            "explain" => &["--stage", "--bindings", "--template-only"],
            "build" => &["--out", "--bindings", "--template-only"],
            "run" => &["--solution", "--solution-hex", "--max-cost"],
            _ => {
                return Err(usage(
                    "Implemented commands: check, build, run, explain (ast/ir/clvm)",
                ));
            }
        };
        let mut path = None;
        let mut options = BTreeMap::new();
        let mut iter = args[1..].iter();
        while let Some(arg) = iter.next() {
            if arg.starts_with('-') {
                if arg != "--json" && !allowed.contains(&arg.as_str()) {
                    return Err(usage(format!("Unsupported option: {arg}")));
                }
                let value = if matches!(arg.as_str(), "--json" | "--template-only") {
                    String::new()
                } else {
                    iter.next()
                        .filter(|s| !s.starts_with("--"))
                        .ok_or_else(|| usage(format!("Missing value for {arg}")))?
                        .clone()
                };
                if options.insert(arg.clone(), value).is_some() {
                    return Err(usage(format!("Duplicate option: {arg}")));
                }
            } else if path.replace(PathBuf::from(arg)).is_some() {
                return Err(usage("Expected exactly one input path"));
            }
        }
        let path = path.ok_or_else(|| usage("Missing input path"))?;
        if command == "build" && !options.contains_key("--out") {
            return Err(usage("build requires --out DIRECTORY"));
        }
        for (left, right) in [
            ("--bindings", "--template-only"),
            ("--solution", "--solution-hex"),
        ] {
            if options.contains_key(left) && options.contains_key(right) {
                return Err(usage(format!("{left} and {right} are mutually exclusive")));
            }
        }
        if command == "explain" {
            match options.get("--stage").map(String::as_str) {
                Some("ast" | "ir") => {
                    if options.contains_key("--bindings") || options.contains_key("--template-only")
                    {
                        return Err(usage("AST/IR views reject binding flags"));
                    }
                }
                Some("clvm") => {}
                _ => return Err(usage("explain requires --stage ast|ir|clvm")),
            }
        }
        Ok(Self {
            command,
            path,
            options,
        })
    }
}
fn usage(message: impl Into<String>) -> Box<Diagnostic> {
    Diagnostic::new("E0400", message)
}
pub(crate) fn io(e: impl std::fmt::Display) -> Box<Diagnostic> {
    Diagnostic::new("E0600", e.to_string())
}
pub(crate) fn read(path: &Path) -> Result<Vec<u8>> {
    read_limited(path, 1_048_576)
}
pub(crate) fn read_limited(path: &Path, limit: usize) -> Result<Vec<u8>> {
    use std::io::Read;
    let file = std::fs::File::open(path).map_err(io)?;
    let mut data = Vec::new();
    file.take(limit as u64 + 1)
        .read_to_end(&mut data)
        .map_err(io)?;
    if data.len() > limit {
        return Err(io(format!("File exceeds the {limit}-byte limit")));
    }
    Ok(data)
}
fn source(path: &Path) -> Result<(String, Vec<u8>)> {
    if path
        .extension()
        .and_then(|v| v.to_str())
        .is_none_or(|s| !s.eq_ignore_ascii_case("bas"))
    {
        return Err(usage("Source must be a .bas file"));
    }
    let name = path
        .file_name()
        .and_then(|v| v.to_str())
        .ok_or_else(|| usage("Source basename must be UTF-8"))?
        .to_owned();
    Ok((name, read(path)?))
}
fn binding_json(args: &Args) -> Result<Option<Vec<u8>>> {
    if args.options.contains_key("--template-only") {
        return Ok(None);
    }
    Ok(Some(if let Some(path) = args.options.get("--bindings") {
        read(Path::new(path))?
    } else {
        b"{}".to_vec()
    }))
}
fn perform(args: Args) -> Result<Value> {
    match args.command.as_str() {
        "explain" => {
            let (name, bytes) = source(&args.path)?;
            if args.options["--stage"] == "clvm" {
                let bindings = binding_json(&args)?;
                return compiler::explain::explain_clvm(&name, &bytes, bindings.as_deref());
            }
            let stage = if args.options["--stage"] == "ast" {
                compiler::explain::Stage::Ast
            } else {
                compiler::explain::Stage::Ir
            };
            compiler::explain::explain(&name, &bytes, stage)
        }
        "check" => {
            let (name, bytes) = source(&args.path)?;
            let contract = compiler::check(&name, &bytes)?;
            Ok(json!({"contract":contract.name}))
        }
        "build" => {
            let (name, bytes) = source(&args.path)?;
            let compiled = compiler::compile_template(&name, &bytes)?;
            let bindings = binding_json(&args)?;
            let bound = bindings
                .as_deref()
                .map(|json| compiled.bind(json))
                .transpose()?;
            artifact::build(
                &name,
                &bytes,
                &compiled,
                Path::new(&args.options["--out"]),
                bound.as_ref(),
            )
        }
        "run" => {
            let loaded = artifact::load(&args.path)?;
            let solution = if let Some(path) = args.options.get("--solution-hex") {
                let bytes = read(Path::new(path))?;
                let text = std::str::from_utf8(&bytes)
                    .map_err(|e| Diagnostic::new("E0300", e.to_string()))?;
                hex::decode(text.trim_matches(|c: char| c.is_ascii_whitespace()))
                    .map_err(|e| Diagnostic::new("E0300", e.to_string()))?
            } else {
                let bytes = if let Some(path) = args.options.get("--solution") {
                    read(Path::new(path))?
                } else {
                    b"{}".to_vec()
                };
                compiler::abi::encode_solution(&loaded.inputs, &bytes)?
            };
            let cost = if let Some(text) = args.options.get("--max-cost") {
                if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
                    return Err(usage("--max-cost must be a positive decimal u64"));
                }
                text.parse::<u64>()
                    .ok()
                    .filter(|n| *n > 0)
                    .ok_or_else(|| usage("--max-cost must be a positive decimal u64"))?
            } else {
                clvm::DEFAULT_MAX_COST
            };
            let execution = clvm::execute(&loaded.puzzle, &solution, cost)?;
            Ok(
                json!({"validation":"clvm-execution-only", "cost":execution.cost.to_string(), "tree":execution.tree}),
            )
        }
        _ => Err(usage("Unsupported command")),
    }
}
fn main() {
    let raw: Vec<_> = std::env::args_os().skip(1).collect();
    let json_mode = raw.iter().any(|s| s == "--json");
    let command = raw
        .first()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_owned();
    let args: std::result::Result<Vec<_>, _> = raw.into_iter().map(|v| v.into_string()).collect();
    let result = args.map_err(|_| usage("Command arguments must be valid Unicode")).and_then(|args| {
        if args.len() == 1 && args[0] == "--help" {
            return Ok(json!({"usage":["0xbasic explain SOURCE --stage ast|ir|clvm [--bindings FILE | --template-only] [--json]", "0xbasic check SOURCE [--json]", "0xbasic build SOURCE --out DIRECTORY [--bindings FILE | --template-only] [--json]", "0xbasic run MANIFEST [--solution FILE | --solution-hex FILE] [--max-cost N] [--json]"],"implemented":compiler::IMPLEMENTED_SUBSET}));
        }
        if args.len() == 1 && args[0] == "--version" {
            return Ok(json!({"compiler":compiler::COMPILER_VERSION,"language":compiler::LANGUAGE_VERSION,"abi":compiler::ABI_VERSION,"target_profile":compiler::TARGET_PROFILE}));
        }
        perform(Args::parse(&args)?)
    });
    let status = match &result {
        Ok(_) => 0,
        Err(e) => match e.code {
            "E0400" => 2,
            "E0500" | "E0501" => 3,
            "E0600" => 4,
            "E9000" => 70,
            _ => 1,
        },
    };
    if json_mode {
        let envelope = match result {
            Ok(value) => {
                json!({"schema_version":1,"command":command,"ok":true,"diagnostics":[],"result":value})
            }
            Err(e) => {
                json!({"schema_version":1,"command":command,"ok":false,"diagnostics":[e],"result":null})
            }
        };
        println!("{envelope}");
    } else {
        match result {
            Ok(v) => println!("{v}"),
            Err(e) => {
                eprintln!("{e}");
                for note in e.notes {
                    eprintln!("  {note}");
                }
            }
        }
    }
    std::process::exit(status);
}
