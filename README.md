# C2VerifiedRust

Workflow tools for translating C to Rust and checking candidate implementations
against explicit verification plans. The tools produce compiler/verifier
evidence, compare it with the plan, and package failures as repair input.

## Workflow

1. Prepare the C source and generate a C2Rust baseline. The
   [translation guide](c2rust_baseline/README.md) covers source collection,
   transpilation, linking, and Coreutils regression tests.
2. Inspect the baseline with `tools/triage_c2rust.py` and create a plan with
   `tools/plan_skeleton.py`. Complete the specification, trust assumptions,
   required checks, and expected outcomes using the [plan schema](plans/SCHEMA.md).
3. Produce the candidate Rust implementation and integrate it with a proof
   harness. Translation and repair execution are separate from the verifier.
4. Validate the plan, run its checks, reconcile the evidence, and use any
   diagnostics to prepare the next repair.

See [tools/README.md](tools/README.md) for individual tool commands.

## Local targets and output

This repository contains the reusable workflow tools, schema, usage
documentation, and compiler regression fixtures. Standalone demo crates,
vendor inputs for those demos, prototype plans/specifications, and generated
artifacts are excluded by [.gitignore](.gitignore).

Prepare a target in an ignored workspace such as `generated/target/`, with
its source, baseline, candidate, proof crate, and completed verification plan.
Paths in that plan must identify the actual files under evaluation. Keep the
proof-crate integration consistent with the candidate. Preserve dependency
lockfiles within the target workspace to make its dependency choices explicit.

## Run verification

The tested tool versions are Rust/Cargo 1.93.0 and Kani 0.67.0 on Linux
x86_64, with Python 3.12 or newer. The Python tools use the standard library.

The installed C2Rust fork is `0.22.1`, tested at commit
`88c112e14ee5612dbe19164ab77d7ab5eb262ab1` in the sibling `../c2rust`
checkout. This merges upstream `v0.22.1` while retaining the local transpiler
patches. Both `c2rust` and `c2rust-transpile` were built with Rust/Cargo 1.93.0
and LLVM/Clang 18.1.3. Runtime regression fixtures use
`nightly-2023-04-15` for generated Rust, matching upstream snapshot tests.
See the [build and regression instructions](compile_regress/README.md).

After preparing your target, run from the repository root:

```bash
python3 tools/plan_check.py --stage pre generated/target/plan.json
python3 tools/plan_check.py --stage ready generated/target/plan.json
python3 tools/verify_function.py \
  --plan generated/target/plan.json \
  --run-id candidate-check
```

`pre` checks the plan's schema; `ready` also checks required artifacts.
Each verification run writes a plan snapshot, per-tool evidence, combined
evidence, logs, and reconciliation under the ignored `runs/<run_id>/` directory.
Failed checks can be packaged for the next repair:

```bash
python3 tools/repair_from_diagnostics.py \
  --plan runs/candidate-check/plan.json \
  --evidence runs/candidate-check/evidence.json \
  --out runs/candidate-check/repair_prompt.md
```

## Compiler regressions

The seven C fixtures in `compile_regress/` include five stable-Rust compilation
checks and two C/Rust runtime comparisons for overflow operations and unary
integer promotion. All seven fixtures and the transpiler package's unit,
snapshot, token, and documentation tests passed for the revision above. The
installed CLI also passed both runtime fixtures. The Coreutils end-to-end
pipeline was not rerun for this update.

The harness creates generated files in temporary directories and removes them
after each fixture. Build output belongs outside this checkout or under an
ignored directory.

Known overflow limitations remain for mixed signedness and narrowing output
types; the runtime fixtures cover selected supported combinations. The upstream
lockfile also retains yanked `hermit-abi` 0.3.1 and `pest` family 2.6.0 packages.
Those dependency versions were retained for this tested merge.
