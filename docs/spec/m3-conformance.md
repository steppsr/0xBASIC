# M3 integration conformance

M3-9a activates all 29 original cases in [source-cases.json](source-cases.json) through `tools/verify_m3_conformance.py` and compiler integration tests. No source cases are deferred in this suite. The historical M2 scope and its five deferrals remain unchanged because they document the earlier milestone.

The CLI verifier checks expected rejection codes, successful condition trees, deterministic repeated artifacts, explain/build byte and hash agreement, and exact successful-cost boundaries. Fixed bindings and solution data are supplied when required. The full-payment case uses the example's bindings and original payment condition expectations; it proves local compilation/execution only. Signature authorization, coin lifecycle, network signing context and consensus spend acceptance remain M4 work.

## Coverage ledger

| Original vector or case group | Executable evidence |
| --- | --- |
| All 29 original source cases | `m3_conformance.rs`: all_original_source_cases_are_active; `verify_m3_conformance.py` |
| All 10 raw boundary cases | `m3_conformance.rs`: original_boundary_vectors_guard_fixed_and_solution_even_when_unused; both F and S paths |
| BOOLEAN, UTF-8, invalid PUBLICKEY and noncanonical INTEGER atoms | `m3_conformance.rs`: original_scalar_atom_and_serialization_vectors_remain_enforced; both F and S paths |
| Canonical INTEGER encodings | `integer_inputs.rs`: original_integer_vectors_match_host_and_generated_validation |
| Traditional serialization hashes | `m3_conformance.rs`: original_scalar_atom_and_serialization_vectors_remain_enforced |
| Curry binding convention | `fixed_integers.rs`; original binding vector |
| Payment condition bytes | `signature_conditions.rs`; `verify_m3_signatures.py --with-upstream` |
| Combined maximum 32 fixed and 32 solution fields | `m3_conformance.rs`: combined_maximum_field_counts_preserve_slots_and_validate_last_fields; final-field corruption tested in both paths |
| Signing message, synthetic coin and signature reference | M0 reference-vector checks only; compiled spend/lifecycle proof deferred to M4 |

These checks do not replace the per-feature recursive-type, resource-limit and malformed-metadata tests. M3-9b adds the artifact audit below; M3 is closed after the user confirmed all 275 Linux tests. Compiler remains `0.1.0-m3.8b`: M3-9a changes tests and documentation, not executable language behavior or artifact formats.

## M3-9b artifact audit

The CLI integration suite now covers:

- Every manifest/compiler/language/ABI/profile/optimization version gate and malformed provenance fields.
- All four artifact path roles, including traversal, absolute paths, aliases, alternate-stream spelling and wrong-role filenames.
- Duplicate, missing and unknown nested compiler/source/artifact metadata fields.
- Canonical binary/hex agreement, missing newline, uppercase hex, leading/trailing data and digest mismatches.
- Correlated artifact-byte/digest changes that still fail template-to-puzzle rebinding.
- Relocated artifact directories and the intentional distinction between descriptive provenance and authenticated source.
- Linux symlink escape rejection for all four artifacts, including a sibling directory sharing the output-directory name prefix.

Existing tests retain coverage of recursive schema metadata, normalized bindings, generated guards despite forged input schemas, oversized files, failed publication, concurrent no-overwrite publication, and reproducibility. See `crates/cli/tests/commands.rs`. Windows cannot execute the Unix symlink test; Linux confirmation is required.

No runtime change was needed in this audit. The tests establish static artifact consistency and path containment, not resistance to concurrent filesystem mutation or proof that arbitrary replacement CLVM implements claimed source. The [CLI trust boundary](cli-v1.md) documents these limits. Compiler remains `0.1.0-m3.8b`; the next milestone is M4 design for simulator-backed payment authorization and lifecycle validation.
