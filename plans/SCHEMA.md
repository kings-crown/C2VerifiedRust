# Verification Plan Schema (v1)

A Verification Plan is a JSON document authored **before** any LLM
invocation, declaring for one C → safe-Rust translation target:

1. What is checkable (and by which mechanism)
2. What is not checkable (and why)
3. What ends up in the trust boundary
4. What outcome is expected for each checkable property

Plans are versioned alongside source. Each plan covers exactly one
function. The pipeline refuses to invoke the LLM on a target that has
no plan, and the post-verification reconciler refuses to credit
evidence that does not match the plan's expected outcomes.

## File layout

```
plans/<function>.json
```

Top-level keys are required unless explicitly marked optional.

## Fields

| Field | Type | Notes |
|---|---|---|
| `schema_version` | int | Must be `1`. |
| `function` | string | Function name (matches the C and c2rust symbol). |
| `source.c.path` | string | Path to the C source, repo-relative. |
| `source.c.line` | int | Line of the function definition. |
| `source.c.macros_expanded` | list[string] (optional) | cpp macros that expand into the function body — load-bearing for the trust list. |
| `source.c2rust_unsafe.path` | string | Path to the c2rust transpiler output, repo-relative. |
| `source.c2rust_unsafe.line` | int | Line of the `pub unsafe extern "C" fn` declaration. |
| `input_signature.kind` | enum | `scalar` \| `scalar_list` \| `bytes` \| `pointer_struct` \| `varargs` \| `globals` |
| `input_signature.rust` | string | Rust signature, e.g. `(c: libc::c_int) -> bool`. |
| `input_signature.domain` | string | The symbolic-input domain, e.g. `full_i32`, `bounded_u32_lt_64`. |
| `purity.side_effects` | enum | `none` \| `reads_globals` \| `writes_globals` \| `writes_output_buffer` \| `syscalls` \| `allocates`. |
| `purity.determinism` | enum | `total` \| `partial` \| `nondeterministic`. |
| `spec_available.source` | string | Where the specification lives (e.g. `gnulib c-ctype.h documented contract`). Use `none` if no spec exists. |
| `spec_available.format` | enum | `documented_contract` \| `iso_c` \| `none`. |
| `spec_available.excerpt` | string | The actual specification text in one or two sentences, quoted or paraphrased. |
| `checkable` | object | Map of evidence-level id → status. See "Evidence levels" below. |
| `tool_requirements` | object | Map of evidence-level id → runner configuration. Every `required` check must have a runner entry unless it is `not_feasible`. |
| `trusted` | list[string] | Non-empty. Each item is one trust assumption the verification depends on. |
| `not_checkable` | list[{reason, rationale}] | May be empty. Each item explicitly declares a property that this plan does *not* attempt to check. |
| `expected_outcomes` | object | Map of evidence-level id → expected outcome. Every `required` key in `checkable` must appear here. |
| `ceiling` | enum | `E0` \| `E1` \| `E2` \| `E3` \| `E4` \| `E5`. The highest evidence level this plan claims to reach. |
| `notes` | string (optional) | Free text. |

## Evidence levels

| Level id | Meaning | Expected-outcome shape |
|---|---|---|
| `E0_compile` | The candidate Rust compiles. | `"PASS"` \| `"FAIL"` |
| `E0_no_unsafe_marker` | The raw candidate compiles under `#![forbid(unsafe_code)]`, catching `unsafe` signatures and unsafe-adjacent attributes such as `#[no_mangle]`. | `"PASS"` \| `"FAIL"` |
| `E1_clippy` | Clippy lint pass for idiom/likely correctness issues. | `"PASS"` \| `"FAIL"` |
| `E2_test_suite` | Existing C tests pass against the translated Rust. | `"PASS"` \| `"FAIL"` |
| `E2_property_tests` | Property-based/randomized tests pass for declared generators. | `"PASS"` \| `"FAIL"` |
| `E3_miri_concrete_ub` | Miri reports no UB on concrete exercised inputs. | `"PASS"` \| `"FAIL"` |
| `E4_phase1_equivalence_to_c2rust` | Bit-equivalence to the c2rust unsafe baseline under bounded symbolic input. | `{status: SUCCESS\|FAILURE\|UNKNOWN, covers: ALL_SATISFIED\|SOME_UNSATISFIABLE\|NOT_REQUIRED}` |
| `E4_phase2_equivalence_to_spec` | Bit-equivalence to the specification (escaping the c2rust trust assumption). | same shape as Phase 1 |
| `E5_cross_tool` | Two independent verification methods agree on the outcome (e.g. Kani + Miri). | `"AGREES"` \| `"DISAGREES"` \| `"NOT_RUN"` |

Each `checkable` value is one of:

- `"required"` — the gate must run and the outcome must match `expected_outcomes`.
- `"optional"` — the gate may run; if it does, the outcome must match.
- `"not_feasible"` — the gate cannot run on this target (e.g. Kani Phase 1 on FFI varargs); rationale belongs in `not_checkable`.

## Tool requirements

`tool_requirements` makes the Verification Plan executable without making
`plan_check.py` run the tools. It declares which runner must produce evidence
for each required check.

Supported runner shapes:

```json
{
  "E0_compile": {
    "runner": "cargo_build",
    "crate": "generated/target/proof"
  },
  "E0_no_unsafe_marker": {
    "runner": "rustc_forbid_unsafe",
    "raw_candidate": "generated/target/candidate/target_function_safe.rs"
  },
  "E1_clippy": {
    "runner": "clippy",
    "crate": "generated/target/proof",
    "deny_warnings": true
  },
  "E3_miri_concrete_ub": {
    "runner": "miri",
    "crate": "generated/target/proof",
    "test_filter": "target_function"
  },
  "E4_phase1_equivalence_to_c2rust": {
    "runner": "kani",
    "crate": "generated/target/proof",
    "harness": "proofs::equiv_target_function",
    "harness_file": "generated/target/proof/src/proofs.rs",
    "kani_args": ["--default-unwind", "8"],
    "input_domain": "full_i32",
    "expected_cover_count": 9
  },
  "E4_phase2_equivalence_to_spec": {
    "runner": "kani",
    "crate": "generated/target/proof",
    "harness": "proofs::spec_target_function",
    "harness_file": "generated/target/proof/src/proofs.rs",
    "spec": "generated/target/spec.md"
  },
  "E5_cross_tool": {
    "runner": "evidence_fusion",
    "inputs": [
      "target_function.E4_phase2_equivalence_to_spec",
      "target_function.E3_miri_concrete_ub"
    ]
  }
}
```

## Validation rules (enforced by `tools/plan_check.py`)

1. `schema_version == 1`.
2. Every required top-level field is present.
3. Every key in `checkable` is one of the evidence-level ids above.
4. Every key marked `required` in `checkable` appears in `expected_outcomes`.
5. `trusted` has at least one entry. (A plan with no trust assumptions is dishonest.)
6. Each `not_checkable` entry has both `reason` and `rationale`.
7. `ceiling` is at least as high as the highest `required` key. (`E5_cross_tool` ceiling requires E5 in checkable; an `E4`-level required check forces ceiling ≥ `E4`.)
8. `input_signature.domain == "full_i32"` is only valid when `input_signature.kind == "scalar"` and the rust signature parameter is `c_int`.
9. Every `required` check has a matching `tool_requirements` entry with a supported `runner`.
10. `plan_check.py --stage ready` additionally verifies that referenced crates, raw candidates, harness files, and spec files exist.

## Reconciliation rules (enforced by `tools/reconcile.py`)

For each `(plan, evidence_record)` pair, the reconciler compares each
key in `expected_outcomes` against the corresponding actual outcome
recorded by the verification pipeline. Possible verdicts per key:

- `consistent` — actual matches expected.
- `divergent` — actual differs from expected; the plan must be updated, the translation must be repaired, or the trust list extended.
- `unverified` — the gate did not run; only acceptable for `optional` checks.

A plan is **honored** only if every `required` key has a `consistent`
verdict. Anything else is a finding.
