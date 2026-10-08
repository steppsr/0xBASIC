use sha2::{Digest, Sha256};
use std::{env, fs, path::Path, process::Command};

fn main() {
    let lock = Path::new("../../Cargo.lock");
    println!("cargo:rerun-if-changed={}", lock.display());
    println!("cargo:rerun-if-env-changed=RUSTC");
    let bytes = fs::read(lock).expect("Cargo.lock must exist when building");
    println!(
        "cargo:rustc-env=OXBASIC_LOCK_SHA256={}",
        hex::encode(Sha256::digest(bytes))
    );
    let output = Command::new(env::var_os("RUSTC").expect("Cargo supplies RUSTC"))
        .arg("--version")
        .output()
        .expect("read rustc version");
    assert!(output.status.success(), "rustc --version failed");
    let text = String::from_utf8(output.stdout).expect("rustc version is UTF-8");
    let version = text.split_whitespace().nth(1).expect("rustc version field");
    assert_eq!(version, "1.95.0", "Use the pinned Rust toolchain");
    println!("cargo:rustc-env=OXBASIC_RUST_VERSION={version}");
}
