"""Run and audit the complete isolated SpendSim suite twice; publish only fresh evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from smoke import BASE, ROOT, WORK, preflight, require

ERRORS = {
    "premature-height": "ASSERT_HEIGHT_ABSOLUTE_FAILED",
    "missing-signature": "BAD_AGGREGATE_SIGNATURE",
    "wrong-owner": "BAD_AGGREGATE_SIGNATURE",
    "message-only-signature": "BAD_AGGREGATE_SIGNATURE",
    "wrong-network-domain": "BAD_AGGREGATE_SIGNATURE",
    "cross-coin-replay": "BAD_AGGREGATE_SIGNATURE",
    "double-spend": "DOUBLE_SPEND",
    "wrong-puzzle-reveal": "WRONG_PUZZLE_HASH",
    "wrong-coin-amount": "ASSERT_MY_AMOUNT_FAILED",
    "changed-recipient-stale-signature": "BAD_AGGREGATE_SIGNATURE",
    "malformed-solution": "GENERATOR_RUNTIME_ERROR",
    "zero-payment-amount": "GENERATOR_RUNTIME_ERROR",
}
MATRIX = ROOT / "docs/spec/m4-payment-scenarios.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(reports, profile, compiler_version):
    """Check coverage and evidence structure; scenario harnesses check actual chain state."""
    smoke, payments, mutations = reports
    require([r["validation"] for r in reports] == [
        "spendsim-environment-smoke-only", "spendsim-height-signature-checks",
        "spendsim-replay-mutation-checks"], "Wrong report kinds")
    for report in reports:
        require(report["schema_version"] == 1 and report["profile"] == profile["profile"], "Report profile mismatch")
        require(report["chia_commit"] == profile["chia_commit"], "Upstream commit mismatch")
        require(report["source_hashes"] == profile["source_hashes"], "Upstream source mismatch")
        for key in ("platform", "python", "packages", "lock_hashes"):
            require(report[key] == smoke[key], f"Mixed environments: {key}")
    require(smoke["outcome"]["resources_closed"] is True and smoke["outcome"]["blocks_farmed"] == 1,
            "Smoke incomplete")
    outcomes = payments["outcome"] + mutations["outcome"]
    expected = [case["id"] for case in json.loads(MATRIX.read_text(encoding="utf-8"))["cases"]]
    actual = [outcome["scenario"] for outcome in outcomes]
    require(len(expected) == len(set(expected)) == 15, "Invalid scenario matrix")
    require(len(actual) == len(set(actual)) and set(actual) == set(expected), "Missing, duplicate or unexpected scenario")
    require(len(payments["outcome"]) == 7 and len(mutations["outcome"]) == 8, "Wrong suite coverage")
    summary = []
    for outcome in outcomes:
        name = outcome["scenario"]
        require(outcome["resources_closed"] is True, f"{name}: resources not closed")
        is_payment = "payment_status" in outcome
        rejections = outcome["rejected_attempts"] if is_payment else outcome["rejections"]
        require(len(rejections) == (1 if name in ERRORS else 0), f"{name}: wrong rejection count")
        for rejection in rejections:
            require(rejection["error"] == ERRORS[name], f"{name}: wrong rejection reason")
            require(rejection["status"] == ("PENDING" if name == "premature-height" else "FAILED"),
                    f"{name}: wrong rejection status")
            if is_payment:
                require(rejection["input_unspent"] is True and rejection["recipient_absent"] is True
                        and rejection["children_count"] == 0 and rejection["active_mempool_empty"] is True,
                        f"{name}: rejection state missing")
            else:
                require(rejection["state_unchanged_after_farm"] is True, f"{name}: post-farm state missing")
                require(rejection["spent_before_and_after"] == (name == "double-spend")
                        and rejection["children_before_and_after"] == (1 if name == "double-spend" else 0),
                        f"{name}: wrong rejected coin state")
        if is_payment:
            require(outcome["payment_status"] == "SUCCESS" and outcome["payment_error"] is None,
                    f"{name}: no accepted positive control")
            require(outcome["input_spent_before"] is False and outcome["input_spent_after"] is True,
                    f"{name}: input not consumed")
            confirmations = [outcome]
            manifests = [outcome["manifest"]]
        else:
            confirmations = outcome["confirmations"]
            require(len(confirmations) == 1 and confirmations[0]["input_spent"] is True,
                    f"{name}: missing confirmed positive control")
            manifests = [fixture["manifest"] for fixture in outcome["fixtures"].values()]
        for confirmation in confirmations:
            require(confirmation["recipient_unspent"] is True and confirmation["exactly_one_child"] is True,
                    f"{name}: recipient evidence missing")
            require(int(confirmation["simulator_total_spend_cost"]) > 0, f"{name}: cost missing")
        for manifest in manifests:
            require(manifest["compiler"]["version"] == compiler_version, f"{name}: stale compiler")
        summary.append({"scenario": name, "rejection": ERRORS.get(name), "confirmed_payments": 1})
    return summary


def run_suite(binary, platform_name):
    reports = []
    for script, stem, options in [("smoke.py", "smoke", []),
                                  ("payment.py", "payment-checks", ["--suite", "--binary", str(binary)]),
                                  ("mutations.py", "mutations", ["--binary", str(binary)])]:
        path = WORK / f"{stem}-{platform_name}.json"
        path.unlink(missing_ok=True)
        subprocess.run([sys.executable, str(BASE / script), *options], cwd=ROOT, check=True)
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    platform_name = "windows" if sys.platform == "win32" else "linux"
    WORK.mkdir(parents=True, exist_ok=True)
    destination = WORK / f"verification-{platform_name}.json"
    # A failed preflight, subprocess, audit or rerun must not leave an old success report.
    destination.unlink(missing_ok=True)
    profile, _, _ = preflight()
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    binary = (args.binary or target / "debug" / ("0xbasic.exe" if os.name == "nt" else "0xbasic")).resolve()
    require(binary.is_file(), "Build the CLI first or pass --binary")
    compiler_version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["workspace"]["package"]["version"]
    sources = [ROOT / "Cargo.toml", ROOT / "Cargo.lock", ROOT / "rust-toolchain.toml",
               ROOT / "examples/height-locked-payment.bas", MATRIX,
               *sorted(BASE.glob("*.py")), *sorted(BASE.glob("*.lock")), BASE / "profile.json",
               *sorted((ROOT / "crates").rglob("*.rs")), *sorted((ROOT / "crates").rglob("Cargo.toml"))]
    identities = {str(path.relative_to(ROOT)).replace("\\", "/"): digest(path) for path in sources}
    binary_hash = digest(binary)
    first = run_suite(binary, platform_name)
    summary = audit(first, profile, compiler_version)
    second = run_suite(binary, platform_name)
    audit(second, profile, compiler_version)
    require(first == second, "Fresh reruns produced different evidence")
    require(digest(binary) == binary_hash and all(digest(ROOT / name) == value for name, value in identities.items()),
            "Inputs changed during verification")
    report = {"schema_version": 1, "validation": "spendsim-complete-reproducible-suite",
              "scope": "In-process SpendSim; full-node simulator and testnet validation remain separate",
              "platform": sys.platform, "compiler_version": compiler_version, "binary_sha256": binary_hash,
              "input_sha256": identities, "identical_fresh_runs": 2, "scenario_count": len(summary),
              "confirmed_payments_per_run": 15, "rejected_attempts_per_run": 12,
              "scenarios": summary, "reports": first}
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"PASS: all 15 scenarios, 12 rejections and 15 confirmed payments per run; two identical fresh runs. Report: {destination}")


if __name__ == "__main__":
    main()
