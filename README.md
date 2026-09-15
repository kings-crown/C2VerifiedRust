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

The five C fixtures in `compile_regress/` cover integer width, promotion,
narrowing, and varargs compilation cases. Follow the
[regression instructions](compile_regress/README.md) to generate Rust and
compile it with the patched C2Rust tool. Generated regression Rust is ignored.
These tests check compilation only.
